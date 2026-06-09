from datetime import date
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from schemas.grant import GrantCreate, GrantResponse, GrantListResponse, GrantUpdate
from services.grant_service import GrantService
from api.deps import get_current_user
from models.user import User

router = APIRouter(prefix="/grants", tags=["grants"])


@router.get("", response_model=GrantListResponse)
async def list_grants(
    status: Optional[str] = Query(None, description="Filter by status: pending|approved|rejected"),
    search: Optional[str] = Query(None, description="Full-text search"),
    country: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    region: Optional[str] = Query(None, description="Geo region bucket: Europe|United Kingdom|Global..."),
    industry: Optional[str] = Query(None, description="Target industry/sector"),
    deadline_before: Optional[date] = Query(None, description="Deadline on/before this date"),
    deadline_after: Optional[date] = Query(None, description="Deadline on/after this date"),
    budget_min: Optional[float] = Query(None, description="Minimum budget overlap"),
    budget_max: Optional[float] = Query(None, description="Maximum budget overlap"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    service = GrantService(db)
    grants, total = await service.list_grants(
        status=status,
        search=search,
        country=country,
        category=category,
        region=region,
        industry=industry,
        deadline_before=deadline_before,
        deadline_after=deadline_after,
        budget_min=budget_min,
        budget_max=budget_max,
        page=page,
        size=size,
    )
    return GrantListResponse(
        items=[GrantResponse.model_validate(g) for g in grants],
        total=total,
        page=page,
        size=size,
    )


@router.get("/categories")
async def list_categories(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Distinct grant categories with counts (used for filter menus)."""
    service = GrantService(db)
    return {"items": await service.list_categories()}


@router.get("/{grant_id}", response_model=GrantResponse)
async def get_grant(
    grant_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    service = GrantService(db)
    grant = await service.get_by_id(grant_id)
    if not grant:
        raise HTTPException(status_code=404, detail="Grant not found")
    return GrantResponse.model_validate(grant)


@router.post("", response_model=GrantResponse, status_code=201)
async def create_grant(
    data: GrantCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    service = GrantService(db)
    grant = await service.create(data)
    return GrantResponse.model_validate(grant)


@router.patch("/{grant_id}", response_model=GrantResponse)
async def update_grant(
    grant_id: int,
    data: GrantUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    service = GrantService(db)
    grant = await service.update(grant_id, data)
    if not grant:
        raise HTTPException(status_code=404, detail="Grant not found")
    return GrantResponse.model_validate(grant)


@router.delete("/{grant_id}", status_code=204)
async def delete_grant(
    grant_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Permanently remove a grant (and its reviews/features via cascade)."""
    service = GrantService(db)
    deleted = await service.delete(grant_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Grant not found")
    return None


@router.delete("")
async def delete_grants_bulk(
    status: Optional[str] = Query(
        None,
        description="Optional status filter: pending|approved|rejected. Omit to wipe ALL grants.",
    ),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Bulk-delete grants. Without `status`, deletes everything."""
    service = GrantService(db)
    count = await service.delete_bulk(status=status)
    return {"deleted": count, "status": status or "all"}
