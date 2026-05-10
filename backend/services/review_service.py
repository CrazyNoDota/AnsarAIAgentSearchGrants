from sqlalchemy.ext.asyncio import AsyncSession

from models.grant import Grant
from models.review import Review
from schemas.review import ReviewCreate
from services.ai_service import AIService


class ReviewService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def submit_review(
        self, grant_id: int, data: ReviewCreate
    ) -> tuple[Grant, Review]:
        """
        Approve or reject a grant.
        Updates grant.status, creates Review record, triggers AI scoring update.
        """
        grant = await self.db.get(Grant, grant_id)
        if not grant:
            raise ValueError(f"Grant {grant_id} not found")

        if data.decision not in ("approved", "rejected"):
            raise ValueError("Decision must be 'approved' or 'rejected'")

        # Update grant status
        grant.status = data.decision

        # Create review record
        review = Review(
            grant_id=grant_id,
            reviewer_name=data.reviewer_name,
            decision=data.decision,
        )
        self.db.add(review)
        await self.db.flush()

        # Trigger lightweight AI learning update
        ai_service = AIService(self.db)
        await ai_service.update_scores_after_review(grant, data.decision)

        await self.db.refresh(grant)
        return grant, review
