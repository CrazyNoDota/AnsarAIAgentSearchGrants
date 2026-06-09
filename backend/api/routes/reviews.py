"""
Grant Review Endpoint
Handles approve/reject decisions.
After each decision:
  - Updates grant status
  - Triggers AI learning (updates preference weights)
  - Queues embedding generation for approved grants
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from schemas.review import ReviewCreate, ReviewResponse
from services.review_service import ReviewService
from services.learning_service import LearningService
from services.embedding_service import EmbeddingService
from api.deps import get_current_user
from models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/grants", tags=["reviews"])


@router.post("/{grant_id}/review", response_model=ReviewResponse)
async def review_grant(
    grant_id: int,
    data: ReviewCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Submit approve/reject decision for a grant.

    Side effects:
    1. Updates grant.status
    2. Triggers AI learning (updates preference weights for category/country/keywords)
    3. For approved grants: queues embedding generation
    """
    service = ReviewService(db)
    try:
        grant, review = await service.submit_review(
            grant_id=grant_id,
            data=ReviewCreate(
                decision=data.decision,
                reviewer_name=current_user.username,
            ),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Trigger AI learning from this decision
    try:
        learning = LearningService(db)
        await learning.learn_from_review(grant, data.decision)
        await db.commit()
    except Exception as e:
        logger.warning(f"Learning update failed after review (non-fatal): {e}")

    # For approved grants: immediately queue embedding generation
    if data.decision == "approved":
        try:
            emb = EmbeddingService(db)
            await emb.reembed_grant(grant_id)
        except Exception as e:
            logger.warning(f"Post-approval embedding failed (non-fatal): {e}")

    return ReviewResponse.model_validate(review)


@router.get("/learning/preferences")
async def get_learning_preferences(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Return top learned preferences for AI insights view."""
    learning = LearningService(db)
    return await learning.get_top_preferences()


@router.post("/learning/update-scores")
async def update_all_scores(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Recalculate ai_score for all pending grants using learned preferences."""
    learning = LearningService(db)
    count = await learning.update_all_scores()
    await db.commit()
    return {"updated": count}
