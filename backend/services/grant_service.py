from typing import Optional
from sqlalchemy import select, func, or_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from models.grant import Grant
from models.review import Review
from schemas.grant import GrantCreate, GrantUpdate


class GrantService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: GrantCreate) -> Grant:
        """Create grant, skip if source_url already exists."""
        existing = await self.db.scalar(
            select(Grant).where(Grant.source_url == data.source_url)
        )
        if existing:
            return existing

        grant = Grant(**data.model_dump())
        self.db.add(grant)
        await self.db.flush()
        await self.db.refresh(grant)
        return grant

    async def get_by_id(self, grant_id: int) -> Optional[Grant]:
        return await self.db.get(Grant, grant_id)

    async def list_grants(
        self,
        status: Optional[str] = None,
        search: Optional[str] = None,
        country: Optional[str] = None,
        category: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[Grant], int]:
        query = select(Grant)

        if status:
            query = query.where(Grant.status == status)
        if country:
            query = query.where(Grant.country.ilike(f"%{country}%"))
        if category:
            query = query.where(Grant.category.ilike(f"%{category}%"))
        if search:
            query = query.where(
                or_(
                    Grant.title.ilike(f"%{search}%"),
                    Grant.organization.ilike(f"%{search}%"),
                    Grant.description.ilike(f"%{search}%"),
                )
            )

        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.scalar(count_query) or 0

        query = (
            query.order_by(Grant.ai_score.desc(), Grant.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await self.db.execute(query)
        grants = list(result.scalars().all())

        return grants, total

    async def update(self, grant_id: int, data: GrantUpdate) -> Optional[Grant]:
        grant = await self.get_by_id(grant_id)
        if not grant:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(grant, field, value)
        await self.db.flush()
        await self.db.refresh(grant)
        return grant

    async def delete(self, grant_id: int) -> bool:
        """Delete a single grant. Cascade removes reviews and features."""
        grant = await self.get_by_id(grant_id)
        if not grant:
            return False
        await self.db.delete(grant)
        await self.db.flush()
        return True

    async def delete_bulk(self, status: Optional[str] = None) -> int:
        """Bulk-delete grants, optionally filtered by status. Returns count removed.

        Uses a single SQL DELETE — the FK on reviews/grant_features is
        ON DELETE CASCADE at the DB level, so children clean up automatically.
        """
        stmt = delete(Grant)
        if status:
            stmt = stmt.where(Grant.status == status)
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount or 0

    async def set_telegram_msg_id(self, grant_id: int, msg_id: int) -> None:
        grant = await self.get_by_id(grant_id)
        if grant:
            grant.telegram_msg_id = msg_id
            await self.db.flush()

    async def list_categories(self) -> list[dict]:
        """Return distinct non-empty categories with grant counts, sorted by count desc."""
        result = await self.db.execute(
            select(Grant.category, func.count(Grant.id).label("n"))
            .where(Grant.category.is_not(None))
            .where(Grant.category != "")
            .group_by(Grant.category)
            .order_by(func.count(Grant.id).desc())
        )
        return [{"category": row[0], "count": row[1]} for row in result.all()]

    async def get_stats(self) -> dict:
        result = await self.db.execute(
            select(Grant.status, func.count(Grant.id))
            .group_by(Grant.status)
        )
        stats = {row[0]: row[1] for row in result.all()}
        return {
            "pending": stats.get("pending", 0),
            "approved": stats.get("approved", 0),
            "rejected": stats.get("rejected", 0),
            "total": sum(stats.values()),
        }
