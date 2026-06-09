"""
Hybrid Search Service

Combines:
  1. SQL keyword search (fast, exact, filterable)
  2. Vector semantic search (fuzzy, meaning-based)
  3. Merges results using Reciprocal Rank Fusion (RRF)

This gives the best of both worlds:
  - Exact matches surface reliably
  - Conceptually similar grants are discovered even without exact keyword overlap
"""
import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, text

from models.grant import Grant
from models.search_log import SearchLog
from core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _rrf_score(rank: int, k: int = 60) -> float:
    """Reciprocal Rank Fusion score. Higher rank = higher score."""
    return 1.0 / (k + rank)


class SearchService:
    """Hybrid grant search combining SQL keywords + vector similarity."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def keyword_search(
        self,
        query: str,
        status: Optional[str] = None,
        country: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        """SQL ILIKE full-text keyword search with optional filters."""
        from sqlalchemy import select

        stmt = select(Grant)

        # Text search across title + description + organization
        if query:
            terms = query.lower().split()
            conditions = []
            for term in terms[:5]:  # Max 5 terms to avoid slow queries
                conditions.append(
                    or_(
                        Grant.title.ilike(f"%{term}%"),
                        Grant.description.ilike(f"%{term}%"),
                        Grant.organization.ilike(f"%{term}%"),
                        Grant.category.ilike(f"%{term}%"),
                        Grant.country.ilike(f"%{term}%"),
                    )
                )
            if conditions:
                # AND all term conditions (every word must appear somewhere)
                from sqlalchemy import and_
                stmt = stmt.where(and_(*conditions))

        # Filters
        if status:
            stmt = stmt.where(Grant.status == status)
        else:
            stmt = stmt.where(Grant.status.in_(["approved", "pending"]))
        if country:
            stmt = stmt.where(Grant.country.ilike(f"%{country}%"))
        if category:
            stmt = stmt.where(Grant.category.ilike(f"%{category}%"))

        stmt = stmt.order_by(Grant.ai_score.desc()).limit(limit)
        result = await self.db.execute(stmt)
        grants = result.scalars().all()

        return [self._grant_to_dict(g) for g in grants]

    def _grant_to_dict(self, g: Grant) -> dict:
        return {
            "id": g.id,
            "title": g.title,
            "organization": g.organization,
            "country": g.country,
            "category": g.category,
            "description": g.description,
            "deadline": str(g.deadline) if g.deadline else None,
            "source_url": g.source_url,
            "status": g.status,
            "ai_score": g.ai_score,
            "grant_amount": g.grant_amount,
            "eligibility": g.eligibility,
            "industry": g.industry,
            "startup_stage": g.startup_stage,
            "application_url": g.application_url,
            "confidence_score": g.confidence_score,
            "similarity_score": 0.0,
        }

    async def hybrid_search(
        self,
        query: str,
        status: Optional[str] = None,
        country: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 10,
        user_id: Optional[str] = None,
    ) -> list[dict]:
        """
        Hybrid search: combines SQL keyword results + vector results via RRF.
        Falls back gracefully if embeddings don't exist yet.
        """
        # 1. Keyword search
        keyword_results = await self.keyword_search(
            query, status=status, country=country, category=category, limit=20
        )

        # 2. Vector search (if embeddings available)
        vector_results = []
        try:
            from services.rag_service import RAGService
            rag = RAGService(self.db)
            vector_results = await rag.semantic_search(query, top_k=20)
        except Exception as e:
            logger.warning(f"Vector search failed in hybrid: {e}")

        # 3. Apply filters to vector results
        if country:
            vector_results = [g for g in vector_results if g.get("country", "").lower().find(country.lower()) != -1]
        if category:
            vector_results = [g for g in vector_results if g.get("category", "").lower().find(category.lower()) != -1]

        # 4. RRF merge
        scores: dict[int, float] = {}
        id_to_grant: dict[int, dict] = {}

        for rank, g in enumerate(keyword_results):
            gid = g["id"]
            scores[gid] = scores.get(gid, 0.0) + _rrf_score(rank)
            id_to_grant[gid] = g

        for rank, g in enumerate(vector_results):
            gid = g["id"]
            scores[gid] = scores.get(gid, 0.0) + _rrf_score(rank)
            if gid not in id_to_grant:
                id_to_grant[gid] = g

        # Sort by RRF score descending
        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
        results = [id_to_grant[gid] for gid in sorted_ids[:limit]]

        # Log search
        try:
            log = SearchLog(
                query=query,
                user_id=user_id,
                results_count=len(results),
                search_type="hybrid" if vector_results else "keyword",
            )
            self.db.add(log)
            await self.db.flush()
        except Exception:
            pass

        return results
