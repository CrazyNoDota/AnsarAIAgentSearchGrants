import re
import logging
from collections import Counter
from typing import Optional

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.grant import Grant
from models.grant_feature import GrantFeature
from core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Common English stop words to exclude from keyword analysis
STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can", "this",
    "that", "these", "those", "it", "its", "we", "our", "you", "your",
    "they", "their", "he", "she", "his", "her", "not", "no", "new", "all",
    "also", "more", "other", "some", "any", "such", "than", "then", "so",
    "up", "out", "if", "about", "into", "through", "during", "before",
    "after", "between", "each", "both", "few", "most", "other",
}


def _make_llm_client() -> Optional[AsyncOpenAI]:
    """
    Returns an async OpenAI-compatible client.
    Prefers NVIDIA API (Qwen3-480B), falls back to OpenAI.
    Returns None if neither is configured.
    """
    if settings.use_nvidia_ai:
        return AsyncOpenAI(
            base_url=settings.nvidia_base_url,
            api_key=settings.nvidia_api_key,
        )
    if settings.use_openai:
        return AsyncOpenAI(api_key=settings.openai_api_key)
    return None


def _get_model_name() -> str:
    if settings.use_nvidia_ai:
        return settings.nvidia_model
    return "gpt-4o-mini"


def tokenize(text: str) -> list[str]:
    """Extract meaningful keywords from text."""
    if not text:
        return []
    words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())
    return [w for w in words if w not in STOP_WORDS]


class AIService:
    # Hard cap on how long we wait for the LLM. Vercel function maxDuration
    # for /api/index is 90s, so keep this well below it.
    LLM_TIMEOUT_SECONDS = 40
    # Cap on candidates sent to the LLM — keeps prompt size and latency bounded.
    LLM_CANDIDATE_LIMIT = 15

    def __init__(self, db: AsyncSession):
        self.db = db
        self._llm = _make_llm_client()
        self._model = _get_model_name()

    # ──────────────────────────────────────────────────────────
    # Keyword-based scoring (always available, no API needed)
    # ──────────────────────────────────────────────────────────

    async def get_keyword_weights(self) -> Counter:
        """
        Build preference profile from approved/rejected grants.
        Approved → positive weight. Rejected → negative penalty.
        """
        weights: Counter = Counter()

        approved = await self.db.execute(
            select(Grant).where(Grant.status == "approved")
        )
        for grant in approved.scalars().all():
            text = f"{grant.title or ''} {grant.description or ''} {grant.category or ''}"
            for word in tokenize(text):
                weights[word] += 2
            if grant.country:
                weights[f"country:{grant.country.lower()}"] += 3
            if grant.category:
                weights[f"category:{grant.category.lower()}"] += 3

        rejected = await self.db.execute(
            select(Grant).where(Grant.status == "rejected")
        )
        for grant in rejected.scalars().all():
            text = f"{grant.title or ''} {grant.description or ''}"
            for word in tokenize(text):
                weights[word] -= 1

        return weights

    async def score_grant(self, grant: Grant, weights: Counter) -> float:
        """Score a grant against learned preference weights."""
        score = 0.0
        text = f"{grant.title or ''} {grant.description or ''} {grant.category or ''}"
        for token in tokenize(text):
            score += weights.get(token, 0)
        if grant.country:
            score += weights.get(f"country:{grant.country.lower()}", 0)
        if grant.category:
            score += weights.get(f"category:{grant.category.lower()}", 0)
        return round(score, 4)

    async def update_all_scores(self) -> int:
        """Recalculate ai_score for all pending grants. Called by nightly scheduler."""
        weights = await self.get_keyword_weights()
        if not weights:
            return 0

        pending = await self.db.execute(
            select(Grant).where(Grant.status == "pending")
        )
        grants = list(pending.scalars().all())

        for grant in grants:
            grant.ai_score = await self.score_grant(grant, weights)

        await self.db.flush()
        logger.info(f"Updated AI scores for {len(grants)} grants")
        return len(grants)

    async def update_scores_after_review(self, grant: Grant, decision: str) -> None:
        """Extract and store features from a reviewed grant for future learning."""
        try:
            text = f"{grant.title or ''} {grant.description or ''}"
            keywords = list(set(tokenize(text)))[:20]
            delta = 1.0 if decision == "approved" else -0.5

            for kw in keywords:
                feature = GrantFeature(
                    grant_id=grant.id,
                    keyword=kw,
                    category=grant.category,
                    country=grant.country,
                    score_delta=delta,
                )
                self.db.add(feature)

            await self.db.flush()
        except Exception as e:
            logger.warning(f"Feature extraction failed: {e}")

    # ──────────────────────────────────────────────────────────
    # LLM-powered recommendations (NVIDIA Qwen3 / OpenAI)
    # ──────────────────────────────────────────────────────────

    async def get_recommendations(self, query: str, limit: int = 10) -> list[Grant]:
        """
        Smart recommendation engine.
        - If NVIDIA/OpenAI API is available: use LLM to rank grants by relevance
        - Fallback: keyword overlap + learned preference scores
        """
        weights = await self.get_keyword_weights()
        query_tokens = set(tokenize(query))

        result = await self.db.execute(
            select(Grant).where(Grant.status.in_(["approved", "pending"]))
        )
        grants = list(result.scalars().all())

        if not grants:
            return []

        # Try LLM-based ranking first
        if self._llm and len(grants) > 0:
            try:
                return await self._llm_rank_grants(query, grants, weights, limit)
            except Exception as e:
                logger.warning(f"LLM ranking failed, falling back to keyword scoring: {e}")

        # Keyword fallback
        return self._keyword_rank_grants(query_tokens, grants, weights, limit)

    async def _llm_rank_grants(
        self, query: str, grants: list[Grant], weights: Counter, limit: int
    ) -> list[Grant]:
        """
        Use LLM (Qwen3-480B or GPT-4o-mini) to intelligently rank grants.
        Sends a compact grant list to the model and asks for relevance scores.
        """
        # Pre-filter by keyword score to keep prompt size and LLM latency bounded
        pre_ranked = self._keyword_rank_grants(
            set(tokenize(query)), grants, weights, self.LLM_CANDIDATE_LIMIT
        )

        if not pre_ranked:
            return []

        # Build compact grant descriptions for the prompt
        grant_lines = []
        for i, g in enumerate(pre_ranked):
            line = f"{i+1}. [{g.id}] {g.title} | {g.organization or 'N/A'} | {g.country or 'N/A'} | {g.category or 'N/A'}"
            if g.deadline:
                line += f" | deadline:{g.deadline}"
            grant_lines.append(line)

        prompt = f"""You are an expert grant analyst for a grant consultancy.
A staff member is looking for: "{query}"

Here are available grants (format: #. [ID] Title | Organization | Country | Category | Deadline):
{chr(10).join(grant_lines)}

Return ONLY a JSON array of grant IDs in order of relevance to the query, most relevant first.
Include only grants that are genuinely relevant. Maximum {limit} IDs.
Example output: [12, 5, 23, 8]
JSON array only, no explanation:"""

        response = await self._llm.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=512,
            timeout=self.LLM_TIMEOUT_SECONDS,
        )

        content = response.choices[0].message.content or ""
        # Parse the JSON array of IDs
        ids = self._parse_id_list(content)

        if not ids:
            return self._keyword_rank_grants(set(tokenize(query)), grants, weights, limit)

        # Map IDs back to grant objects (preserve LLM order)
        grant_map = {g.id: g for g in grants}
        result = [grant_map[gid] for gid in ids if gid in grant_map]

        # If LLM returned fewer than limit, pad with keyword-ranked
        if len(result) < limit:
            seen = {g.id for g in result}
            extras = self._keyword_rank_grants(set(tokenize(query)), grants, weights, limit)
            for g in extras:
                if g.id not in seen:
                    result.append(g)
                if len(result) >= limit:
                    break

        logger.info(f"LLM ({self._model}) ranked {len(result)} grants for query: '{query}'")
        return result[:limit]

    def _keyword_rank_grants(
        self,
        query_tokens: set[str],
        grants: list[Grant],
        weights: Counter,
        limit: int,
    ) -> list[Grant]:
        """Fallback keyword + preference score ranking."""
        scored: list[tuple[float, Grant]] = []
        for grant in grants:
            text = f"{grant.title or ''} {grant.description or ''} {grant.category or ''}"
            tokens = set(tokenize(text))
            overlap = len(query_tokens & tokens)
            pref_score = sum(weights.get(t, 0) for t in tokens)
            if grant.country:
                pref_score += weights.get(f"country:{grant.country.lower()}", 0)
            if grant.category:
                pref_score += weights.get(f"category:{grant.category.lower()}", 0)
            total = overlap * 10 + pref_score
            scored.append((total, grant))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [g for _, g in scored[:limit]]

    @staticmethod
    def _parse_id_list(text: str) -> list[int]:
        """Parse a JSON-like list of integers from LLM output."""
        try:
            import json
            # Find first [...] in the response
            start = text.find("[")
            end = text.rfind("]")
            if start != -1 and end != -1:
                return json.loads(text[start:end + 1])
        except Exception:
            pass
        # Fallback: extract bare integers
        return [int(x) for x in re.findall(r"\d+", text)]

    # ──────────────────────────────────────────────────────────
    # Grant summarization (bonus feature using LLM)
    # ──────────────────────────────────────────────────────────

    async def summarize_grant(self, grant: Grant) -> str:
        """
        Generate a concise 2-3 sentence summary of a grant using LLM.
        Returns original description if LLM unavailable.
        """
        if not self._llm or not grant.description:
            return grant.description or ""

        try:
            prompt = f"""Summarize this grant opportunity in 2-3 clear sentences for a grant consultant.
Focus on: who can apply, what it funds, and key requirements.

Grant: {grant.title}
Organization: {grant.organization or 'N/A'}
Category: {grant.category or 'N/A'}
Country: {grant.country or 'N/A'}
Description: {grant.description[:1500]}

Summary:"""

            response = await self._llm.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=200,
                timeout=self.LLM_TIMEOUT_SECONDS,
            )
            return response.choices[0].message.content or grant.description
        except Exception as e:
            logger.warning(f"Grant summarization failed: {e}")
            return grant.description or ""
