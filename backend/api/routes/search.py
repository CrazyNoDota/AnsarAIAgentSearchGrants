"""
Hybrid Search Endpoint
Combines SQL keyword search + pgvector semantic search via RRF.
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from services.search_service import SearchService
from api.deps import get_current_user
from models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
async def hybrid_search(
    q: str = Query(..., description="Search query"),
    status: Optional[str] = Query(None, description="Filter: pending|approved|rejected"),
    country: Optional[str] = Query(None, description="Filter by country"),
    category: Optional[str] = Query(None, description="Filter by category"),
    limit: int = Query(10, ge=1, le=50),
    user_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Hybrid search: keyword + semantic vector search merged with RRF.
    Best for finding grants when the exact terminology may vary.
    """
    service = SearchService(db)
    results = await service.hybrid_search(
        query=q,
        status=status,
        country=country,
        category=category,
        limit=limit,
        user_id=user_id,
    )
    return {"results": results, "count": len(results), "query": q}
