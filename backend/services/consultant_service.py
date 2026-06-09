"""
Phase 5 — AI consultant (grant Q&A + recommendations + completeness/fit check).

Three capabilities, all GROUNDED and anti-hallucination by construction:

1. ASK  — answer a question about a grant's terms/conditions/eligibility using
          ONLY the grant's stored data (+ optionally the user's package and
          retrieved knowledge-base precedent). Mirrors RAGService's strict
          grounding contract.

2. RECOMMEND — improvement recommendations for an application package: derived
          deterministically from the readiness checklist (Phase-4
          ``calendar_service``) + the deterministic profile↔grant fit
          (Phase-2 ``MatchingService``), then optionally phrased by the LLM
          (which is forbidden from inventing new facts or changing the numbers).

3. CHECK_COMPLETENESS — check a Phase-3 ``ApplicationPackage`` (a document set)
          for completeness and fit against the grant's requirements: which
          required sections are missing/TODO, weak/thin spots, and eligibility
          gaps from the structured fit breakdown.

ANTI-HALLUCINATION DESIGN (consistent with rag_service / matching_service /
document_service):
- The LLM answers ONLY from the supplied grounded context (grant data, the
  user's package, retrieved KB cases). A strict system prompt forbids invention,
  requires "not found in the provided data" when context is missing, and asks for
  source attribution.
- The context fed to the model is built by deterministic, pure functions below so
  it is fully unit-testable without any network call.
- If the LLM/key is unavailable, every capability degrades to a deterministic,
  grounded textual answer — it NEVER crashes.

LLM transport: NVIDIA NIM via Chat Completions DIRECTLY (OpenAI-compatible,
``settings.nvidia_*``) — the same path used across the repo. Webwright/Responses
API is intentionally NOT used (Phase 0 finding).

SECURITY: any package read goes through ``DocumentService.get_owned(id, user_id)``
and any KB retrieval through the user-scoped ``KnowledgeService`` — the consultant
never reads another user's data. Secrets come from settings only.
"""
from __future__ import annotations

import logging
import re
from typing import Optional, TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:  # pragma: no cover - typing only
    from openai import AsyncOpenAI

from core.config import get_settings
from models.grant import Grant
from services import calendar_service as cal
from services.document_service import build_grant_context

logger = logging.getLogger(__name__)
settings = get_settings()

CONSULTANT_TIMEOUT_SECONDS = 60

# Strict anti-hallucination system prompt (mirrors RAG_SYSTEM_PROMPT style).
CONSULTANT_SYSTEM_PROMPT = (
    "You are an AI grant consultant for Ansar Consulting. You advise employees on "
    "grant applications.\n\n"
    "STRICT RULES — NEVER VIOLATE:\n"
    "1. Answer ONLY using the GROUNDED CONTEXT provided below (the grant data, the "
    "applicant's document package, and retrieved past-application cases). Treat it "
    "as the single source of truth.\n"
    "2. NEVER invent grant terms, deadlines, funding amounts, eligibility rules, "
    "facts about the applicant, or details of past cases. Do not use outside "
    "knowledge.\n"
    "3. If the answer is not present in the provided context, say exactly: \"This "
    "information was not found in the provided data.\" Do not guess.\n"
    "4. When you state a fact, attribute it to its source (the grant, the "
    "applicant's package, or a named past case).\n"
    "5. Do not change any score, percentage, count or status given in the context "
    "— those were computed deterministically. You may explain them, not override "
    "them.\n"
    "6. Be concise, concrete and professional."
)


# ── Knowledge-base context (pure / testable) ─────────────────────────────────

def build_kb_context(cases: list[dict]) -> str:
    """Render retrieved knowledge-base cases as grounded context. Pure."""
    if not cases:
        return "No past applications or cases were found in the knowledge base."
    lines: list[str] = []
    for i, c in enumerate(cases[:5], 1):
        lines.append(f"\n{'-' * 32}")
        lines.append(f"PAST CASE #{i} [{c.get('kind', 'entry')}]")
        if c.get("title"):
            lines.append(f"Title: {c['title']}")
        if c.get("funder"):
            lines.append(f"Funder: {c['funder']}")
        if c.get("outcome"):
            lines.append(f"Outcome: {c['outcome']}")
        content = (c.get("content") or "").strip()
        if content:
            lines.append(f"Notes: {content[:800]}")
    return "\n".join(lines)


def build_package_context(package: Optional[dict]) -> str:
    """Render an application package (title + sections) as grounded context. Pure.

    ``package`` is a plain dict {"title", "sections": [{key,title,content}]} so
    this stays DB-free and testable; the route resolves the owned package first.
    """
    if not package:
        return "No application package was provided."
    lines = [f"Application package: {package.get('title', '(untitled)')}"]
    for s in package.get("sections", []) or []:
        title = s.get("title") or s.get("key") or "Section"
        content = (s.get("content") or "").strip()
        snippet = content[:600] if content else "(empty)"
        lines.append(f"\n## {title}\n{snippet}")
    return "\n".join(lines)


# ── Completeness / fit (deterministic, pure) ─────────────────────────────────

# A thin-but-present section is flagged as weak below this character count.
WEAK_SECTION_CHARS = 200


def assess_completeness(
    *,
    package_title: str,
    package_status: str,
    sections: list[dict],
    required_keys: Optional[list[str]] = None,
    fit: Optional[dict] = None,
) -> dict:
    """Deterministic completeness + fit assessment of a document set. PURE.

    Reuses Phase-4 ``calendar_service.evaluate_sections`` to classify each
    section drafted/TODO/missing, then derives:
      - missing/TODO/weak section lists,
      - any REQUIRED sections entirely absent from the package,
      - eligibility gaps pulled from the deterministic fit breakdown (if given),
      - an overall readiness percentage + stage.

    ``required_keys`` (e.g. the grant's expected section keys, or the default
    template keys) lets the check flag sections that should exist but were never
    generated. ``fit`` is the MatchingService.compute_fit() dict (optional).
    """
    statuses = cal.evaluate_sections(sections)
    present_keys = {s.key for s in statuses if s.key}
    total = len(statuses)
    drafted = sum(1 for s in statuses if s.drafted)

    missing_sections = [
        {"key": s.key, "title": s.title}
        for s in statuses
        if not s.drafted and not s.has_todo
    ]
    todo_sections = [
        {"key": s.key, "title": s.title}
        for s in statuses
        if s.has_todo
    ]
    weak_sections = [
        {"key": s.key, "title": s.title, "char_count": s.char_count}
        for s in statuses
        if s.drafted and s.char_count < WEAK_SECTION_CHARS
    ]

    # Required sections that are not present in the package at all.
    absent_required = []
    if required_keys:
        for key in required_keys:
            if key not in present_keys:
                absent_required.append(key)

    # Eligibility / fit gaps from the deterministic breakdown.
    eligibility_gaps: list[str] = []
    fit_pct: Optional[int] = None
    if fit:
        fit_pct = fit.get("probability_pct")
        for w in fit.get("weaknesses", []) or []:
            eligibility_gaps.append(w)

    pct = round(100 * drafted / total) if total else 0
    stage = cal.prep_stage(total, drafted)

    issues_found = bool(
        missing_sections or todo_sections or absent_required or eligibility_gaps
    )

    return {
        "package_title": package_title,
        "package_status": package_status,
        "section_count": total,
        "drafted_count": drafted,
        "percent_complete": pct,
        "stage": stage,
        "complete": (not issues_found) and total > 0,
        "missing_sections": missing_sections,
        "todo_sections": todo_sections,
        "weak_sections": weak_sections,
        "absent_required_sections": absent_required,
        "eligibility_gaps": eligibility_gaps,
        "fit_percent": fit_pct,
    }


def build_recommendations(assessment: dict) -> list[str]:
    """Deterministic, grounded improvement recommendations from an assessment.

    These are produced WITHOUT the LLM (so advice exists offline) and are exactly
    what the LLM is later asked to phrase — keeping the explanation grounded.
    """
    recs: list[str] = []
    for k in assessment.get("absent_required_sections", []) or []:
        recs.append(f"Add the required '{k}' section — it is missing from the package.")
    for s in assessment.get("missing_sections", []) or []:
        title = s.get("title") or s.get("key") or "section"
        recs.append(f"Draft the empty section '{title}'.")
    for s in assessment.get("todo_sections", []) or []:
        title = s.get("title") or s.get("key") or "section"
        recs.append(f"Resolve the open [TODO] placeholders in '{title}'.")
    for s in assessment.get("weak_sections", []) or []:
        title = s.get("title") or s.get("key") or "section"
        recs.append(
            f"Expand the thin section '{title}' "
            f"({s.get('char_count', 0)} chars) with more detail."
        )
    for gap in assessment.get("eligibility_gaps", []) or []:
        recs.append(f"Address eligibility/fit gap: {gap}")
    if not recs:
        if assessment.get("section_count", 0) == 0:
            recs.append(
                "The package has no sections — generate the application before review."
            )
        else:
            recs.append(
                "No structural gaps detected. Proofread for clarity and ensure "
                "every claim is supported by evidence before submission."
            )
    return recs


class ConsultantService:
    """Grounded grant consultant. LLM phrases; deterministic logic decides."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._llm: Optional["AsyncOpenAI"] = None
        if settings.nvidia_api_key:
            # Lazy import keeps the service importable in minimal/offline envs.
            from openai import AsyncOpenAI

            self._llm = AsyncOpenAI(
                base_url=settings.nvidia_base_url,
                api_key=settings.nvidia_api_key,
            )

    @property
    def llm_available(self) -> bool:
        return self._llm is not None

    # ── Prompt construction (pure / testable) ───────────────────────────────

    @staticmethod
    def _build_grounded_context(
        *,
        grant_ctx: Optional[str] = None,
        package_ctx: Optional[str] = None,
        kb_ctx: Optional[str] = None,
        extra: Optional[str] = None,
    ) -> str:
        blocks: list[str] = []
        if grant_ctx:
            blocks.append(f"=== GRANT DATA ===\n{grant_ctx}")
        if package_ctx:
            blocks.append(f"=== APPLICANT DOCUMENT PACKAGE ===\n{package_ctx}")
        if kb_ctx:
            blocks.append(f"=== PAST CASES (KNOWLEDGE BASE) ===\n{kb_ctx}")
        if extra:
            blocks.append(f"=== ADDITIONAL CONTEXT ===\n{extra[:4000]}")
        if not blocks:
            return "(no grounded context available)"
        return "\n\n".join(blocks)

    @classmethod
    def _ask_messages(cls, question: str, context: str) -> list[dict]:
        """Pure — builds the chat messages for a Q&A call. No network."""
        return [
            {"role": "system", "content": CONSULTANT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"GROUNDED CONTEXT:\n{context}\n\n"
                    f"{'=' * 32}\n"
                    f"QUESTION: {question}\n\n"
                    "Answer using ONLY the grounded context above. If the answer is "
                    "not present, say it was not found in the provided data."
                ),
            },
        ]

    # ── LLM helper (grounded; never crashes) ────────────────────────────────

    async def _complete(self, messages: list[dict], max_tokens: int) -> Optional[str]:
        """Run a grounded chat completion. Returns None on any failure/no-LLM."""
        if not self._llm:
            return None
        try:
            resp = await self._llm.chat.completions.create(
                model=settings.nvidia_model,
                messages=messages,
                temperature=0.2,
                max_tokens=max_tokens,
                timeout=CONSULTANT_TIMEOUT_SECONDS,
            )
            content = (resp.choices[0].message.content or "").strip()
            return content or None
        except Exception as e:  # network/timeout/rate-limit must not crash
            logger.warning("consultant LLM call failed: %s", e)
            return None

    # ── 1. Q&A on grant terms ───────────────────────────────────────────────

    async def ask(
        self,
        *,
        question: str,
        grant: Optional[Grant] = None,
        package: Optional[dict] = None,
        cases: Optional[list[dict]] = None,
        extra: Optional[str] = None,
    ) -> dict:
        """Answer a grounded question about a grant (+ optional package/cases).

        Returns {"answer", "grounded", "llm_used", "sources"}. Deterministic
        fallback when the LLM is unavailable: returns the grounded context with a
        clear notice rather than fabricating an answer.
        """
        grant_ctx = build_grant_context(grant) if grant is not None else None
        package_ctx = build_package_context(package) if package else None
        kb_ctx = build_kb_context(cases) if cases else None
        context = self._build_grounded_context(
            grant_ctx=grant_ctx, package_ctx=package_ctx, kb_ctx=kb_ctx, extra=extra
        )
        grounded = bool(grant_ctx or package_ctx or kb_ctx or extra)

        sources: list[str] = []
        if grant is not None:
            sources.append(f"grant:{grant.id}")
            if grant.source_url:
                sources.append(grant.source_url)
        if package:
            sources.append("applicant_package")
        if cases:
            sources.extend(f"case:{c['id']}" for c in cases if c.get("id"))

        if not grounded:
            return {
                "answer": "This information was not found in the provided data.",
                "grounded": False,
                "llm_used": False,
                "sources": sources,
            }

        answer = await self._complete(
            self._ask_messages(question, context), max_tokens=800
        )
        if answer is None:
            # Deterministic, non-fabricating fallback.
            answer = (
                "AI answering is currently unavailable, so here is the verified "
                "context relevant to your question — please review it directly:\n\n"
                f"{context}"
            )
            return {
                "answer": answer,
                "grounded": True,
                "llm_used": False,
                "sources": sources,
            }
        return {
            "answer": answer,
            "grounded": True,
            "llm_used": True,
            "sources": sources,
        }

    # ── 2 + 3. Completeness/fit check + recommendations ─────────────────────

    async def review_package(
        self,
        *,
        package: dict,
        grant: Optional[Grant] = None,
        fit: Optional[dict] = None,
        required_keys: Optional[list[str]] = None,
        cases: Optional[list[dict]] = None,
        with_llm: bool = True,
    ) -> dict:
        """Completeness/fit check + improvement recommendations for a package.

        The assessment + recommendations are computed DETERMINISTICALLY (so they
        exist without the LLM). The LLM, if available, only phrases a short
        narrative summary grounded in those findings — it cannot change them.
        """
        assessment = assess_completeness(
            package_title=package.get("title", "(untitled)"),
            package_status=package.get("status", "unknown"),
            sections=package.get("sections", []) or [],
            required_keys=required_keys,
            fit=fit,
        )
        recommendations = build_recommendations(assessment)

        summary = self._deterministic_summary(assessment, recommendations)
        llm_used = False
        if with_llm and self._llm is not None:
            narrative = await self._summarize_review(
                assessment, recommendations, grant, cases
            )
            if narrative is not None and self._narrative_numbers_grounded(
                narrative, assessment
            ):
                summary = narrative
                llm_used = True

        return {
            "assessment": assessment,
            "recommendations": recommendations,
            "summary": summary,
            "llm_used": llm_used,
        }

    @staticmethod
    def _deterministic_summary(assessment: dict, recommendations: list[str]) -> str:
        parts = [
            f"Package '{assessment['package_title']}' is "
            f"{assessment['percent_complete']}% complete "
            f"(stage: {assessment['stage']}).",
        ]
        if assessment.get("fit_percent") is not None:
            parts.append(f"Estimated fit to the grant: {assessment['fit_percent']}%.")
        if assessment["complete"]:
            parts.append("No structural gaps were detected.")
        else:
            parts.append(f"{len(recommendations)} item(s) need attention:")
            parts.extend(f"- {r}" for r in recommendations)
        return " ".join(parts[:2]) + ("\n" + "\n".join(parts[2:]) if len(parts) > 2 else "")

    @staticmethod
    def _narrative_numbers_grounded(narrative: str, assessment: dict) -> bool:
        """Reject LLM summaries that contradict deterministic assessment."""
        if not ConsultantService._narrative_readiness_grounded(narrative, assessment):
            return False

        allowed = {int(assessment["percent_complete"])}
        fit_percent = assessment.get("fit_percent")
        if fit_percent is not None:
            allowed.add(int(fit_percent))

        stated = {int(m) for m in re.findall(r"(\d{1,3})\s*%", narrative)}
        bad = stated - allowed
        if bad:
            logger.warning(
                "review summary stated %s%% outside deterministic percentages %s%%; "
                "using deterministic fallback",
                bad,
                allowed,
            )
            return False
        return True

    @staticmethod
    def _narrative_readiness_grounded(narrative: str, assessment: dict) -> bool:
        """Reject LLM readiness claims that contradict deterministic assessment."""
        if assessment.get("complete") is True and assessment.get("stage") == "ready":
            return True

        # Conservative deny-list for qualitative readiness/completeness drift.
        blocked_phrases = (
            "ready to submit",
            "no missing",
            "no gaps",
            "fully complete",
            "is complete",
            "nothing missing",
            "all sections complete",
        )
        lowered = narrative.lower()
        for phrase in blocked_phrases:
            if phrase in lowered:
                logger.warning(
                    "review summary stated readiness/completeness despite "
                    "deterministic assessment complete=%s stage=%s; using "
                    "deterministic fallback",
                    assessment.get("complete"),
                    assessment.get("stage"),
                )
                return False
        return True

    async def _summarize_review(
        self,
        assessment: dict,
        recommendations: list[str],
        grant: Optional[Grant],
        cases: Optional[list[dict]],
    ) -> Optional[str]:
        grant_ctx = build_grant_context(grant) if grant is not None else None
        kb_ctx = build_kb_context(cases) if cases else None
        findings = (
            f"COMPLETENESS/FIT ASSESSMENT (computed deterministically — do not "
            f"change any number or status):\n"
            f"- percent_complete: {assessment['percent_complete']}%\n"
            f"- stage: {assessment['stage']}\n"
            f"- fit_percent: {assessment.get('fit_percent')}\n"
            f"- missing sections: {[s['title'] for s in assessment['missing_sections']]}\n"
            f"- TODO sections: {[s['title'] for s in assessment['todo_sections']]}\n"
            f"- weak sections: {[s['title'] for s in assessment['weak_sections']]}\n"
            f"- absent required sections: {assessment['absent_required_sections']}\n"
            f"- eligibility gaps: {assessment['eligibility_gaps']}\n"
            f"- recommendations: {recommendations}\n"
        )
        context = self._build_grounded_context(grant_ctx=grant_ctx, kb_ctx=kb_ctx)
        messages = [
            {"role": "system", "content": CONSULTANT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"GROUNDED CONTEXT:\n{context}\n\n{findings}\n"
                    "Write a short (3-5 sentence) review for the applicant that "
                    "summarises completeness and fit and prioritises the "
                    "recommendations above. Use ONLY the findings and context "
                    "provided; do NOT invent new gaps or change any number."
                ),
            },
        ]
        return await self._complete(messages, max_tokens=400)
