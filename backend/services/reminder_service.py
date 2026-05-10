import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.grant import Grant
from core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class ReminderService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_upcoming_deadlines(
        self, days_ahead: int = 7
    ) -> list[tuple[Grant, int]]:
        """
        Returns approved grants with deadlines within the next `days_ahead` days.
        Returns list of (grant, days_remaining) tuples.
        """
        today = date.today()
        cutoff = today + timedelta(days=days_ahead)

        result = await self.db.execute(
            select(Grant).where(
                Grant.status == "approved",
                Grant.deadline.isnot(None),
                Grant.deadline >= today,
                Grant.deadline <= cutoff,
            )
        )
        grants = list(result.scalars().all())

        return [
            (g, (g.deadline - today).days)
            for g in grants
        ]
