"""
AI Learning Service

Learns from Aydar's approve/reject decisions to continuously improve
grant recommendations. Tracks patterns by category, country, industry, keywords.

Over time, the system learns what types of grants are most relevant
and automatically boosts similar resources in future rankings.
"""
import logging
import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from models.grant import Grant
from models.preference import UserPreference

logger = logging.getLogger(__name__)

# Common words to exclude from keyword learning
STOP_WORDS = {
    "the", "and", "for", "are", "but", "not", "you", "all", "any",
    "can", "has", "was", "that", "this", "with", "from", "they",
    "have", "been", "will", "more", "also", "into", "over", "such",
    "than", "then", "its", "our", "your", "their", "when", "what",
    "which", "would", "could", "should", "these", "those",
}


class LearningService:
    """Manages AI preference learning from review decisions."""

    def __init__(self, db: AsyncSession):
        self.db = db

    def _extract_keywords(self, text_input: str, max_words: int = 12) -> list[str]:
        """Extract meaningful content keywords from text."""
        words = re.findall(r"\b[a-zA-Z]{4,20}\b", (text_input or "").lower())
        return list({w for w in words if w not in STOP_WORDS})[:max_words]

    async def _upsert_preference(
        self, pref_type: str, value: str, is_approved: bool
    ) -> None:
        """
        Upsert a preference record.
        Approval adds weight (+1.5), rejection subtracts (-0.5).
        Weight never goes below 0.
        """
        weight_delta = 1.5 if is_approved else -0.5
        await self.db.execute(
            text("""
                INSERT INTO user_preferences
                    (preference_type, value, weight, approved_count, rejected_count)
                VALUES (:ptype, :val, :w0, :ac0, :rc0)
                ON CONFLICT (preference_type, value) DO UPDATE SET
                    weight = GREATEST(0, user_preferences.weight + :delta),
                    approved_count = user_preferences.approved_count + :ac,
                    rejected_count = user_preferences.rejected_count + :rc,
                    updated_at = now()
            """),
            {
                "ptype": pref_type,
                "val": value.lower().strip()[:200],
                "w0": max(0.0, 1.0 + weight_delta),
                "ac0": 1 if is_approved else 0,
                "rc0": 0 if is_approved else 1,
                "delta": weight_delta,
                "ac": 1 if is_approved else 0,
                "rc": 0 if is_approved else 1,
            },
        )

    async def learn_from_review(self, grant: Grant, decision: str) -> None:
        """
        Called after every approve/reject decision.
        Updates preference weights for all relevant dimensions.
        """
        is_approved = decision == "approved"

        try:
            # Learn from category
            if grant.category:
                await self._upsert_preference("category", grant.category, is_approved)

            # Learn from country
            if grant.country:
                await self._upsert_preference("country", grant.country, is_approved)

            # Learn from industry
            if grant.industry:
                await self._upsert_preference("industry", grant.industry, is_approved)

            # Learn from startup stage
            if grant.startup_stage:
                await self._upsert_preference("stage", grant.startup_stage, is_approved)

            # Learn from keywords in title + description
            text_content = f"{grant.title or ''} {grant.description or ''}"
            for keyword in self._extract_keywords(text_content):
                await self._upsert_preference("keyword", keyword, is_approved)

            await self.db.flush()
            logger.info(f"Learning updated: grant {grant.id} → {decision}")
        except Exception as e:
            logger.error(f"Learning update failed for grant {grant.id}: {e}")

    async def get_preference_score(self, grant: Grant) -> float:
        """
        Calculate a preference-weighted score for a grant.
        Used to boost/demote grants based on learned patterns.
        Higher = more aligned with Aydar's historical preferences.
        """
        score = 0.0
        try:
            async def _get_weight(ptype: str, val: str) -> float:
                if not val:
                    return 0.0
                r = await self.db.execute(
                    select(UserPreference.weight).where(
                        UserPreference.preference_type == ptype,
                        UserPreference.value == val.lower().strip(),
                    )
                )
                w = r.scalar()
                return float(w) if w else 0.0

            score += await _get_weight("category", grant.category or "") * 3.0
            score += await _get_weight("country", grant.country or "") * 2.5
            score += await _get_weight("industry", grant.industry or "") * 2.0

            text_content = f"{grant.title or ''} {grant.description or ''}"
            for keyword in self._extract_keywords(text_content, max_words=8):
                w = await _get_weight("keyword", keyword)
                score += w * 0.5

        except Exception as e:
            logger.error(f"Preference scoring failed: {e}")

        return round(score, 4)

    async def update_all_scores(self) -> int:
        """
        Recalculate ai_score for all pending grants using learned preferences.
        Called nightly by n8n workflow.
        """
        from sqlalchemy import select as sa_select
        result = await self.db.execute(
            sa_select(Grant).where(Grant.status == "pending")
        )
        grants = list(result.scalars().all())

        for grant in grants:
            pref_score = await self.get_preference_score(grant)
            # Combine with existing ai_score (prefer learning signal)
            grant.ai_score = round(pref_score, 4)

        await self.db.flush()
        logger.info(f"Updated ai_score for {len(grants)} pending grants")
        return len(grants)

    async def get_top_preferences(self) -> dict:
        """Get top learned preferences for the Settings/Insights menu in Telegram."""
        result = await self.db.execute(
            text("""
                SELECT preference_type, value, weight, approved_count, rejected_count
                FROM user_preferences
                WHERE weight > 0.5
                ORDER BY weight DESC
                LIMIT 30
            """)
        )
        rows = result.fetchall()

        prefs: dict = {"categories": [], "countries": [], "keywords": [], "industries": []}
        for row in rows:
            item = {
                "value": row.value,
                "weight": round(row.weight, 1),
                "approved": row.approved_count,
                "rejected": row.rejected_count,
            }
            key = {
                "category": "categories",
                "country": "countries",
                "keyword": "keywords",
                "industry": "industries",
            }.get(row.preference_type)
            if key:
                prefs[key].append(item)

        return prefs
