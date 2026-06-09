"""
Phase 2 — Profile↔Grant fit / match engine.

DESIGN PRINCIPLE (anti-hallucination):
  The overall fit score is computed DETERMINISTICALLY from comparable features.
  The LLM is used ONLY to phrase the qualitative explanation; it never invents
  or overrides the numeric score. If the LLM is unavailable the engine still
  produces a score plus rule-based strengths/weaknesses.

SCORING FORMULA
  Six dimensions, each normalized to [0, 1], combined as a weighted average:

      fit_score = Σ (weight_d * score_d) / Σ (weight_d)

  Only dimensions that are *applicable* (i.e. the profile provides the signal
  needed to judge them) contribute to the denominator, so a sparse profile is
  not penalised for fields it never specified.

  Dimensions & weights (see SCORING_WEIGHTS):
    - industry  (0.20): token overlap between profile.industry/keywords and the
                        grant's industry/category/title.
    - region    (0.15): geo compatibility. "Global"/"International" grants match
                        any profile; otherwise normalized whole-phrase equality
                        on region/country (alias-mapped, NOT substring — so
                        "United States" never matches "United Kingdom").
    - budget    (0.20): does the funding the profile seeks fall inside the
                        grant's [budget_min, budget_max] window.
    - deadline  (0.10): is the grant still open (deadline in the future / absent).
    - stage     (0.10): startup-stage eligibility overlap.
    - semantic  (0.25): cosine similarity of profile text vs grant embedding
                        (pgvector). When embeddings are unavailable this
                        dimension is dropped (weight removed from denominator).

  probability_pct = round(fit_score * 100). It is a *relative* fit indicator,
  not a calibrated statistical probability — documented as such.
"""
import logging
import re
from typing import Optional, TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

if TYPE_CHECKING:  # pragma: no cover - typing only
    from openai import AsyncOpenAI

from core.config import get_settings
from models.grant import Grant
from models.profile import CompanyProfile
from services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)
settings = get_settings()

# Dimension weights for the deterministic weighted-average fit score.
SCORING_WEIGHTS: dict[str, float] = {
    "industry": 0.20,
    "region": 0.15,
    "budget": 0.20,
    "deadline": 0.10,
    "stage": 0.10,
    "semantic": 0.25,
}

# Geo buckets that mean "anyone, anywhere is eligible".
_GLOBAL_REGIONS = {"global", "international", "worldwide", "any", "all"}

_STOP = {
    "and", "or", "the", "for", "with", "of", "in", "to", "a", "an", "on",
    "tech", "technology", "company", "startup", "solutions", "services",
}


def _tokens(s: Optional[str]) -> set[str]:
    if not s:
        return set()
    words = re.findall(r"[a-z0-9]{3,}", s.lower())
    return {w for w in words if w not in _STOP}


# Canonicalise common geo synonyms so equality comparison is reliable. Matching
# is done on whole normalized phrases (not substrings) to avoid false positives
# like "United States" ⊂ "United Kingdom" or "South America" ⊂ "North America".
_GEO_ALIASES = {
    "us": "united states", "usa": "united states", "u.s.": "united states",
    "u.s.a.": "united states", "united states of america": "united states",
    "america": "united states", "uk": "united kingdom", "u.k.": "united kingdom",
    "britain": "united kingdom", "great britain": "united kingdom",
    "england": "united kingdom", "eu": "europe", "european union": "europe",
    "uae": "united arab emirates", "korea": "south korea",
}


def _norm_geo(s: Optional[str]) -> Optional[str]:
    """Normalize a single geo phrase (lowercase, collapse spaces, alias-map)."""
    if not s:
        return None
    norm = re.sub(r"\s+", " ", s.strip().lower())
    return _GEO_ALIASES.get(norm, norm)


class MatchingService:
    """Computes explainable profile↔grant fit scores."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.embedding_service = EmbeddingService(db)
        self._llm: Optional["AsyncOpenAI"] = None
        if settings.nvidia_api_key:
            # Imported lazily so the deterministic scoring engine remains
            # importable in minimal/offline environments without `openai`.
            from openai import AsyncOpenAI

            self._llm = AsyncOpenAI(
                base_url=settings.nvidia_base_url,
                api_key=settings.nvidia_api_key,
            )

    # ── Per-dimension deterministic scorers ───────────────────────────────
    # Each returns (score in [0,1], applicable: bool). applicable=False means
    # the profile lacked the signal to judge this dimension, so it is excluded
    # from the weighted average rather than counted as a zero.

    @staticmethod
    def score_industry(profile: CompanyProfile, grant: Grant) -> tuple[float, bool]:
        prof = _tokens(profile.industry) | _tokens(profile.keywords)
        if not prof:
            return 0.0, False
        grant_toks = (
            _tokens(grant.industry) | _tokens(grant.category) | _tokens(grant.title)
        )
        if not grant_toks:
            return 0.0, True
        overlap = prof & grant_toks
        # Overlap coefficient (Szymkiewicz–Simpson): size of the intersection
        # over the SMALLER vocabulary. Using the smaller side avoids penalising a
        # profile that lists many keywords — if the grant's domain terms are all
        # covered by the profile (or vice-versa) that is a strong match, even
        # when one side's vocabulary is much larger.
        score = len(overlap) / max(1, min(len(prof), len(grant_toks)))
        return min(1.0, score), True

    @staticmethod
    def score_region(profile: CompanyProfile, grant: Grant) -> tuple[float, bool]:
        prof_geos = {g for g in (_norm_geo(profile.region), _norm_geo(profile.country)) if g}
        if not prof_geos:
            return 0.0, False
        grant_region = _norm_geo(grant.region)
        grant_country = _norm_geo(grant.country)
        if not grant_region and not grant_country:
            # Unknown grant geo — neutral, slightly positive (not a hard block).
            return 0.6, True
        if grant_region in _GLOBAL_REGIONS or grant_country in _GLOBAL_REGIONS:
            return 1.0, True
        grant_geos = {g for g in (grant_region, grant_country) if g}
        # Whole-phrase equality only (after alias normalization). We deliberately
        # do NOT do substring/token matching: "united states" must not match
        # "united kingdom", nor "south america" match "north america".
        if prof_geos & grant_geos:
            return 1.0, True
        return 0.0, True

    @staticmethod
    def score_budget(profile: CompanyProfile, grant: Grant) -> tuple[float, bool]:
        sought = profile.funding_amount_sought
        if sought is None:
            return 0.0, False
        sought = float(sought)
        lo = float(grant.budget_min) if grant.budget_min is not None else None
        hi = float(grant.budget_max) if grant.budget_max is not None else None
        if lo is None and hi is None:
            return 0.5, True  # grant budget unknown — neutral
        # If both sides declare a currency and they differ, raw amounts are not
        # directly comparable — don't award a confident score on the numbers
        # alone (a 100k KZT ask must not look like a perfect fit for a 100k USD
        # grant). Treat as neutral-applicable. (A real FX conversion is a future
        # improvement; for now we refuse to over-claim.)
        pcur = (profile.currency or "").strip().upper()
        gcur = (grant.currency or "").strip().upper()
        if pcur and gcur and pcur != gcur:
            return 0.5, True
        # Inside the window → perfect.
        if (lo is None or sought >= lo) and (hi is None or sought <= hi):
            return 1.0, True
        # Outside the window → decay by how far out of range, relative to the
        # nearest bound. Closer asks score higher.
        if hi is not None and sought > hi and hi > 0:
            ratio = hi / sought  # < 1
            return max(0.0, min(1.0, ratio)), True
        if lo is not None and sought < lo and lo > 0:
            ratio = sought / lo  # < 1
            return max(0.0, min(1.0, ratio)), True
        return 0.0, True

    @staticmethod
    def score_deadline(profile: CompanyProfile, grant: Grant) -> tuple[float, bool]:
        # Deadline applicability does not depend on the profile — every profile
        # cares whether the grant is still open.
        from datetime import date as _date
        if grant.deadline is None:
            return 0.8, True  # rolling / unknown — assume open but slight discount
        today = _date.today()
        if grant.deadline >= today:
            return 1.0, True
        return 0.0, True  # already closed

    @staticmethod
    def score_stage(profile: CompanyProfile, grant: Grant) -> tuple[float, bool]:
        prof = _tokens(profile.stage)
        if not prof:
            return 0.0, False
        grant_stage = _tokens(grant.startup_stage)
        if not grant_stage:
            return 0.7, True  # grant doesn't restrict stage — mostly compatible
        return (1.0 if prof & grant_stage else 0.0), True

    async def score_semantic(
        self, profile: CompanyProfile, grant: Grant
    ) -> tuple[float, bool]:
        """Cosine similarity of profile text vs the grant's stored embedding.

        Reuses embedding_service (NVIDIA NIM) + pgvector. Returns applicable=
        False when no embedding exists or the embedding API is unavailable, so
        the semantic dimension is simply dropped from the weighted average.
        """
        try:
            query_emb = await self.embedding_service.generate_embedding(
                profile.profile_text(), input_type="query"
            )
        except Exception as e:
            # Embedding API failure (timeout / rate-limit / bad key) must NOT fail
            # the whole fit computation — just drop the semantic dimension.
            logger.warning(f"embedding generation failed for fit scoring: {e}")
            return 0.0, False
        if not query_emb:
            return 0.0, False
        vec_str = f"[{','.join(str(round(x, 8)) for x in query_emb)}]"
        try:
            result = await self.db.execute(
                text(
                    """
                    SELECT 1 - (ge.embedding <=> CAST(:emb AS vector)) AS similarity
                    FROM grant_embeddings ge
                    WHERE ge.grant_id = :gid AND ge.embedding IS NOT NULL
                    ORDER BY ge.embedding <=> CAST(:emb AS vector)
                    LIMIT 1
                    """
                ),
                {"emb": vec_str, "gid": grant.id},
            )
            row = result.first()
        except Exception as e:
            logger.warning(f"semantic score query failed for grant {grant.id}: {e}")
            return 0.0, False
        if row is None or row.similarity is None:
            return 0.0, False
        # Cosine similarity is in [-1, 1]; clamp to [0, 1].
        return max(0.0, min(1.0, float(row.similarity))), True

    # ── Aggregation ───────────────────────────────────────────────────────

    async def compute_fit(self, profile: CompanyProfile, grant: Grant) -> dict:
        """Compute the deterministic fit score + feature breakdown for one grant."""
        industry, ind_ok = self.score_industry(profile, grant)
        region, reg_ok = self.score_region(profile, grant)
        budget, bud_ok = self.score_budget(profile, grant)
        deadline, dl_ok = self.score_deadline(profile, grant)
        stage, stg_ok = self.score_stage(profile, grant)
        semantic, sem_ok = await self.score_semantic(profile, grant)

        dims = {
            "industry": (industry, ind_ok),
            "region": (region, reg_ok),
            "budget": (budget, bud_ok),
            "deadline": (deadline, dl_ok),
            "stage": (stage, stg_ok),
            "semantic": (semantic, sem_ok),
        }

        num = 0.0
        denom = 0.0
        applied_weights: dict[str, float] = {}
        for name, (val, ok) in dims.items():
            if not ok:
                continue
            w = SCORING_WEIGHTS[name]
            num += w * val
            denom += w
            applied_weights[name] = w

        fit_score = round(num / denom, 4) if denom > 0 else 0.0

        breakdown = {
            "industry": round(industry, 4),
            "region": round(region, 4),
            "budget": round(budget, 4),
            "deadline": round(deadline, 4),
            "stage": round(stage, 4),
            "semantic": round(semantic, 4),
            "weights": applied_weights,
        }

        strengths, weaknesses = self._rule_based_reasons(dims, grant)

        return {
            "grant_id": grant.id,
            "grant_title": grant.title,
            "fit_score": fit_score,
            "probability_pct": int(round(fit_score * 100)),
            "breakdown": breakdown,
            "strengths": strengths,
            "weaknesses": weaknesses,
        }

    @staticmethod
    def _rule_based_reasons(
        dims: dict[str, tuple[float, bool]], grant: Grant
    ) -> tuple[list[str], list[str]]:
        """Deterministic strengths/weaknesses derived from the dimension scores.

        These are always produced (no LLM needed) and are what the LLM is later
        asked to phrase — so the explanation stays grounded in real features.
        """
        labels = {
            "industry": "industry / sector alignment",
            "region": "geographic eligibility",
            "budget": "funding amount fit",
            "deadline": "application window (deadline)",
            "stage": "company-stage eligibility",
            "semantic": "overall thematic relevance",
        }
        strengths: list[str] = []
        weaknesses: list[str] = []
        for name, (val, ok) in dims.items():
            if not ok:
                continue
            label = labels[name]
            if val >= 0.75:
                strengths.append(f"Strong {label} ({int(val * 100)}%).")
            elif val <= 0.34:
                weaknesses.append(f"Weak {label} ({int(val * 100)}%).")
        if not strengths:
            strengths.append("No strongly matching dimension; treat as a stretch fit.")
        if not weaknesses:
            weaknesses.append("No major eligibility gaps detected from structured fields.")
        return strengths, weaknesses

    # ── LLM explanation (grounded in computed features) ───────────────────

    async def explain_fit(
        self, profile: CompanyProfile, grant: Grant, fit: dict
    ) -> str:
        """Ask the LLM to phrase an explanation. It is GIVEN the computed score
        and strengths/weaknesses and instructed NOT to change them. Falls back
        to a deterministic sentence if the LLM is unavailable."""
        fallback = (
            f"Estimated fit {fit['probability_pct']}%. "
            f"Strengths: {' '.join(fit['strengths'])} "
            f"Weaknesses: {' '.join(fit['weaknesses'])}"
        )
        if not self._llm:
            return fallback
        try:
            prompt = (
                "You are a grant-fit analyst. The fit score and the lists of "
                "strengths/weaknesses below were computed deterministically from "
                "structured data. Do NOT change the score or invent new facts. "
                "Write 2-3 sentences explaining the fit, using ONLY the provided "
                "strengths/weaknesses.\n\n"
                f"Company: {profile.name} | Industry: {profile.industry} | "
                f"Stage: {profile.stage} | Region: {profile.region}\n"
                f"Grant: {grant.title} | Industry: {grant.industry} | "
                f"Region: {grant.region}\n"
                f"Computed fit score: {fit['probability_pct']}%\n"
                f"Strengths: {fit['strengths']}\n"
                f"Weaknesses: {fit['weaknesses']}\n\n"
                "Explanation:"
            )
            resp = await self._llm.chat.completions.create(
                model=settings.nvidia_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=220,
                timeout=40,
            )
            text_out = (resp.choices[0].message.content or "").strip()
            if not text_out:
                return fallback
            # Grounding guard: the numeric score is authoritative. If the model
            # states a different percentage than the deterministic one, it has
            # contradicted the computed score — discard it for the fallback.
            stated = {int(m) for m in re.findall(r"(\d{1,3})\s*%", text_out)}
            if any(p != fit["probability_pct"] for p in stated):
                logger.warning(
                    "explain_fit output stated %s%% vs computed %s%% — using "
                    "deterministic fallback", stated, fit["probability_pct"],
                )
                return fallback
            return text_out
        except Exception as e:
            logger.warning(f"explain_fit LLM call failed: {e}")
            return fallback

    async def analyze_pair(
        self, profile: CompanyProfile, grant: Grant, with_llm: bool = True
    ) -> dict:
        """Full single-pair analysis: deterministic score + explanation."""
        fit = await self.compute_fit(profile, grant)
        fit["explanation"] = (
            await self.explain_fit(profile, grant, fit)
            if with_llm
            else (
                f"Estimated fit {fit['probability_pct']}%. "
                f"{' '.join(fit['strengths'])} {' '.join(fit['weaknesses'])}"
            )
        )
        return fit

    async def rank_for_profile(
        self,
        profile: CompanyProfile,
        grants: list[Grant],
        limit: int = 10,
        with_llm: bool = True,
    ) -> list[dict]:
        """Score every candidate grant deterministically, sort by fit, then
        generate LLM explanations only for the top `limit` (keeps cost bounded).
        """
        scored: list[dict] = []
        for grant in grants:
            scored.append(await self.compute_fit(profile, grant))
        scored.sort(key=lambda x: x["fit_score"], reverse=True)
        top = scored[:limit]

        grant_map = {g.id: g for g in grants}
        for fit in top:
            grant = grant_map.get(fit["grant_id"])
            if with_llm and grant is not None:
                fit["explanation"] = await self.explain_fit(profile, grant, fit)
            else:
                fit["explanation"] = (
                    f"Estimated fit {fit['probability_pct']}%. "
                    f"{' '.join(fit['strengths'])} {' '.join(fit['weaknesses'])}"
                )
        return top
