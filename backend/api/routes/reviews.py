from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from schemas.review import ReviewCreate, ReviewResponse
from services.review_service import ReviewService
from api.deps import get_current_user
from models.user import User

router = APIRouter(prefix="/grants", tags=["reviews"])


@router.post("/{grant_id}/review", response_model=ReviewResponse)
async def review_grant(
    grant_id: int,
    data: ReviewCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Submit an approve/reject decision for a grant."""
    service = ReviewService(db)
    try:
        _, review = await service.submit_review(
            grant_id=grant_id,
            data=ReviewCreate(
                decision=data.decision,
                reviewer_name=current_user.username,
            ),
        )
        return ReviewResponse.model_validate(review)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
