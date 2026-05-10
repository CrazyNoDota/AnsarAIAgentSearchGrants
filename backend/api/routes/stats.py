from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from services.grant_service import GrantService
from api.deps import get_current_user
from models.user import User

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Dashboard statistics: counts by status."""
    service = GrantService(db)
    return await service.get_stats()
