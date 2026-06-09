"""
RAG-based Recommendation Endpoint

Uses pgvector semantic search + NVIDIA LLM to answer grant queries.
Anti-hallucination: LLM only uses retrieved verified context.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from schemas.grant import GrantResponse
from services.rag_service import RAGService
from services.ai_service import AIService
from api.deps import get_current_user
from models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("", response_model=list[GrantResponse])
async def get_recommendations(
    q: str = Query(..., description="Natural language query, e.g. 'grants for AI startups in Central Asia'"),
    limit: int = Query(5, ge=1, le=20),
    user_id: str = Query(None, description="Telegram user ID for logging"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    RAG-powered grant recommendations.
    Retrieves verified grants from vector DB, generates grounded response.
    Never invents grants — only returns verified database entries.
    """
    rag = RAGService(db)
    try:
        grants, _ = await rag.recommend(q, limit=limit, user_id=user_id)
    except Exception as e:
        logger.exception("RAG recommendation failed for query=%r", q)
        # Fallback to keyword-based recommendations
        try:
            from services.search_service import SearchService
            search = SearchService(db)
            grants = await search.keyword_search(q, limit=limit)
        except Exception:
            raise HTTPException(
                status_code=500,
                detail=f"Recommendation engine error: {e.__class__.__name__}: {e}",
            )

    # Reconstruct Grant ORM objects for schema validation
    from models.grant import Grant
    grant_objects = []
    for g in grants:
        obj = await db.get(Grant, g["id"])
        if obj:
            grant_objects.append(GrantResponse.model_validate(obj))

    return grant_objects


@router.get("/rag-chat")
async def rag_chat(
    q: str = Query(..., description="Natural language question about grants"),
    limit: int = Query(5, ge=1, le=10),
    user_id: str = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    RAG chat endpoint — returns both grants AND the LLM's grounded response.
    Used by Telegram bot for conversational recommendations.
    """
    rag = RAGService(db)
    try:
        grants, response_text = await rag.recommend(q, limit=limit, user_id=user_id)
    except Exception as e:
        logger.exception("RAG chat failed for query=%r", q)
        raise HTTPException(
            status_code=500,
            detail=f"RAG error: {e.__class__.__name__}: {e}",
        )

    return {
        "query": q,
        "response": response_text,
        "grants": grants,
        "count": len(grants),
        "source": "rag_verified_db",
    }


@router.get("/{grant_id}/summarize")
async def summarize_grant(
    grant_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Generate a concise AI summary of a specific grant (NVIDIA LLM)."""
    from models.grant import Grant
    grant = await db.get(Grant, grant_id)
    if not grant:
        raise HTTPException(status_code=404, detail="Grant not found")

    service = AIService(db)
    try:
        summary = await service.summarize_grant(grant)
    except Exception as e:
        logger.exception("Summarize failed for grant_id=%s", grant_id)
        raise HTTPException(
            status_code=500,
            detail=f"Summarize error: {e.__class__.__name__}: {e}",
        )
    return {
        "grant_id": grant_id,
        "summary": summary,
        "model": service._model if service._llm else "fallback",
        "source": "verified_db",
    }
