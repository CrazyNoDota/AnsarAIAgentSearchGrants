from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.profile import CompanyProfile
from schemas.profile import ProfileCreate, ProfileUpdate


class ProfileService:
    """CRUD for company/project profiles (Phase 2). Mirrors GrantService.

    SECURITY: profiles are PRIVATE to their owner. Every method is scoped by
    ``user_id`` so one user can never read or mutate another user's profile.
    There is deliberately no unscoped ``get_by_id`` — callers must pass the
    authenticated user's id, and ownership is enforced in the query itself.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: ProfileCreate, user_id: int) -> CompanyProfile:
        profile = CompanyProfile(**data.model_dump(), user_id=user_id)
        self.db.add(profile)
        await self.db.flush()
        await self.db.refresh(profile)
        return profile

    async def get_owned(
        self, profile_id: int, user_id: int
    ) -> Optional[CompanyProfile]:
        """Fetch a profile only if it belongs to ``user_id`` (else None)."""
        result = await self.db.execute(
            select(CompanyProfile).where(
                CompanyProfile.id == profile_id,
                CompanyProfile.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self, user_id: int, page: int = 1, size: int = 20
    ) -> tuple[list[CompanyProfile], int]:
        from sqlalchemy import func

        total = await self.db.scalar(
            select(func.count()).select_from(CompanyProfile)
            .where(CompanyProfile.user_id == user_id)
        ) or 0
        result = await self.db.execute(
            select(CompanyProfile)
            .where(CompanyProfile.user_id == user_id)
            .order_by(CompanyProfile.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        return list(result.scalars().all()), total

    async def update(
        self, profile_id: int, data: ProfileUpdate, user_id: int
    ) -> Optional[CompanyProfile]:
        profile = await self.get_owned(profile_id, user_id)
        if not profile:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(profile, field, value)
        await self.db.flush()
        await self.db.refresh(profile)
        return profile

    async def delete(self, profile_id: int, user_id: int) -> bool:
        profile = await self.get_owned(profile_id, user_id)
        if not profile:
            return False
        await self.db.delete(profile)
        await self.db.flush()
        return True
