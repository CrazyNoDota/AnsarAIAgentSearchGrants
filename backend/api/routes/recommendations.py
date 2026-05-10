import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from schemas.grant import GrantResponse
from services.ai_service import AIService
from api.deps import get_current_user
from models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("", response_model=list[GrantResponse])
async def get_recommendations(
    q: str = Query(..., description="Search query, e.g. 'AI grants for startups in Europe'"),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """AI-powered grant recommendations using Qwen3-480B (NVIDIA) or keyword scoring."""
    service = AIService(db)
    try:
        grants = await service.get_recommendations(q, limit=limit)
    except Exception as e:
        # Never let an empty 500 reach the bot — the user just sees
        # "Recommendation failed:" with no detail. Surface the cause.
        logger.exception("recommendation failure for query=%r", q)
        raise HTTPException(
            status_code=500,
            detail=f"recommendation engine error: {e.__class__.__name__}: {e}",
        )
    return [GrantResponse.model_validate(g) for g in grants]


@router.get("/{grant_id}/summarize")
async def summarize_grant(
    grant_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Generate a concise LLM summary of a specific grant."""
    from models.grant import Grant
    grant = await db.get(Grant, grant_id)
    if not grant:
        raise HTTPException(status_code=404, detail="Grant not found")

    service = AIService(db)
    try:
        summary = await service.summarize_grant(grant)
    except Exception as e:
        logger.exception("summarize failure for grant_id=%s", grant_id)
        raise HTTPException(
            status_code=500,
            detail=f"summarize error: {e.__class__.__name__}: {e}",
        )
    model_name = service._model if service._llm else "fallback"
    return {"grant_id": grant_id, "summary": summary, "model": model_name}

