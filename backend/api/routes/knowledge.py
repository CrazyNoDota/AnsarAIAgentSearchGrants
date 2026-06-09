"""
Phase 5 — Knowledge base routes (past applications, cases, templates, history).

All endpoints are AUTH-scoped to the current user; every accessor enforces
``user_id`` (no unscoped read). Entries are private to their owner.

  - POST   /knowledge            create an entry (auto-indexed for semantic search)
  - GET    /knowledge            list the user's entries (filter by kind)
  - GET    /knowledge/search     semantic/keyword search over the user's entries
  - GET    /knowledge/{id}       fetch one owned entry
  - PATCH  /knowledge/{id}       update an owned entry (re-indexes on content change)
  - DELETE /knowledge/{id}       delete an owned entry
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from api.deps import get_current_user
from models.user import User
from schemas.knowledge import (
    KnowledgeCreate,
    KnowledgeUpdate,
    KnowledgeResponse,
    KnowledgeSearchResult,
)
from services.document_service import DocumentService
from services.knowledge_service import KnowledgeService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.post("", response_model=KnowledgeResponse, status_code=201)
async def create_entry(
    data: KnowledgeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = KnowledgeService(db)
    if data.package_id is not None:
        package = await DocumentService(db).get_owned(data.package_id, current_user.id)
        if not package:
            raise HTTPException(status_code=404, detail="Application package not found")
    try:
        entry = await service.create(
            user_id=current_user.id,
            kind=data.kind,
            title=data.title,
            content=data.content,
            outcome=data.outcome,
            package_id=data.package_id,
            grant_id=data.grant_id,
            funder=data.funder,
            meta=data.meta,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Best-effort semantic indexing — never blocks/raises the write.
    await service.index_entry(entry, current_user.id)
    return KnowledgeResponse.model_validate(entry)


@router.get("", response_model=dict)
async def list_entries(
    kind: Optional[str] = Query(None, description="Filter by kind"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = KnowledgeService(db)
    try:
        entries, total = await service.list_for_user(
            current_user.id, kind=kind, limit=limit, offset=offset
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "items": [KnowledgeResponse.model_validate(e) for e in entries],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/search", response_model=dict)
async def search_entries(
    q: str = Query(..., min_length=1, max_length=2000),
    top_k: int = Query(5, ge=1, le=25),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Search the CURRENT USER's knowledge base (semantic, keyword fallback)."""
    results = await KnowledgeService(db).retrieve_context(
        q, current_user.id, top_k=top_k
    )
    return {
        "items": [KnowledgeSearchResult(**r) for r in results],
        "count": len(results),
        "query": q,
    }


@router.get("/{entry_id}", response_model=KnowledgeResponse)
async def get_entry(
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    entry = await KnowledgeService(db).get_owned(entry_id, current_user.id)
    if not entry:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")
    return KnowledgeResponse.model_validate(entry)


@router.patch("/{entry_id}", response_model=KnowledgeResponse)
async def update_entry(
    entry_id: int,
    data: KnowledgeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = KnowledgeService(db)
    try:
        entry = await service.update(
            entry_id, current_user.id, data.model_dump(exclude_unset=True)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not entry:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")
    # Re-index if the stored embedding was invalidated by a search-text change.
    if entry.embedding_status == "pending":
        await service.index_entry(entry, current_user.id)
    return KnowledgeResponse.model_validate(entry)


@router.delete("/{entry_id}", status_code=204)
async def delete_entry(
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not await KnowledgeService(db).delete(entry_id, current_user.id):
        raise HTTPException(status_code=404, detail="Knowledge entry not found")
    return None
