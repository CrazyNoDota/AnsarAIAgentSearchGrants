"""
Phase 2 — Company/Project Profile routes + fit analysis.

Endpoints:
  - CRUD for profiles (consistent with /grants).
  - GET /profiles/{id}/recommendations — grants ranked by deterministic fit
    score, each with a probability + strengths/weaknesses + LLM explanation.
  - GET /profiles/{id}/fit/{grant_id} — single profile↔grant fit analysis.

Candidate gathering reuses the existing RAG semantic search (pgvector) to
shortlist relevant grants, then MatchingService re-ranks them with the
deterministic feature-based fit score.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from schemas.profile import (
    ProfileCreate,
    ProfileResponse,
    ProfileUpdate,
    FitResult,
    FitRecommendation,
)
from services.profile_service import ProfileService
from services.matching_service import MatchingService
from services.rag_service import RAGService
from models.grant import Grant
from models.profile import CompanyProfile
from api.deps import get_current_user
from models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/profiles", tags=["profiles"])


# ── CRUD ──────────────────────────────────────────────────────────────────

@router.post("", response_model=ProfileResponse, status_code=201)
async def create_profile(
    data: ProfileCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProfileService(db)
    profile = await service.create(data, user_id=current_user.id)
    return ProfileResponse.model_validate(profile)


@router.get("", response_model=dict)
async def list_profiles(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProfileService(db)
    profiles, total = await service.list_for_user(
        current_user.id, page=page, size=size
    )
    return {
        "items": [ProfileResponse.model_validate(p) for p in profiles],
        "total": total,
        "page": page,
        "size": size,
    }


@router.get("/{profile_id}", response_model=ProfileResponse)
async def get_profile(
    profile_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProfileService(db)
    profile = await service.get_owned(profile_id, current_user.id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return ProfileResponse.model_validate(profile)


@router.patch("/{profile_id}", response_model=ProfileResponse)
async def update_profile(
    profile_id: int,
    data: ProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProfileService(db)
    profile = await service.update(profile_id, data, user_id=current_user.id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return ProfileResponse.model_validate(profile)


@router.delete("/{profile_id}", status_code=204)
async def delete_profile(
    profile_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProfileService(db)
    if not await service.delete(profile_id, user_id=current_user.id):
        raise HTTPException(status_code=404, detail="Profile not found")
    return None


# ── Fit analysis ────────────────────────────────────────────────────────────

async def _candidate_grants(
    db: AsyncSession, profile: CompanyProfile, pool: int
) -> list[Grant]:
    """Shortlist candidate grants for ranking.

    UNION of two sources so nothing valid is silently excluded:
      * RAG semantic search (pgvector) over the profile text — surfaces
        semantically close grants that may not rank on structured fields alone;
      * most-recent active grants — guarantees grants WITHOUT embeddings are
        still considered (the fit engine simply drops the semantic dimension
        for them). Relying on RAG hits alone would hide every unembedded grant
        whenever embeddings are only partially populated.
    """
    rag = RAGService(db)
    try:
        hits = await rag.semantic_search(profile.profile_text(), top_k=pool)
    except Exception as e:
        logger.warning("semantic candidate search failed: %s", e)
        hits = []

    by_id: dict[int, Grant] = {}

    grant_ids = [h["id"] for h in hits]
    if grant_ids:
        result = await db.execute(select(Grant).where(Grant.id.in_(grant_ids)))
        for g in result.scalars().all():
            by_id[g.id] = g

    # Always also pull a base set of recent active grants and merge.
    result = await db.execute(
        select(Grant)
        .where(Grant.status.in_(["approved", "pending"]))
        .order_by(Grant.created_at.desc())
        .limit(pool)
    )
    for g in result.scalars().all():
        by_id.setdefault(g.id, g)

    return list(by_id.values())


@router.get("/{profile_id}/recommendations", response_model=list[FitRecommendation])
async def recommend_for_profile(
    profile_id: int,
    limit: int = Query(10, ge=1, le=50),
    explain: bool = Query(True, description="Generate LLM explanations for top results"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return grants ranked by deterministic fit score for this profile."""
    profile = await ProfileService(db).get_owned(profile_id, current_user.id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Pull a wider candidate pool than `limit` so ranking has room to work.
    grants = await _candidate_grants(db, profile, pool=max(limit * 3, 30))
    matcher = MatchingService(db)
    ranked = await matcher.rank_for_profile(
        profile, grants, limit=limit, with_llm=explain
    )

    grant_map = {g.id: g for g in grants}
    out: list[FitRecommendation] = []
    for fit in ranked:
        g = grant_map.get(fit["grant_id"])
        out.append(
            FitRecommendation(
                **fit,
                source_url=g.source_url if g else None,
                organization=g.organization if g else None,
                deadline=str(g.deadline) if g and g.deadline else None,
                grant_amount=g.grant_amount if g else None,
            )
        )
    return out


@router.get("/{profile_id}/fit/{grant_id}", response_model=FitResult)
async def fit_for_grant(
    profile_id: int,
    grant_id: int,
    explain: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Single profile↔grant fit analysis with probability + reasons."""
    profile = await ProfileService(db).get_owned(profile_id, current_user.id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    grant = await db.get(Grant, grant_id)
    if not grant:
        raise HTTPException(status_code=404, detail="Grant not found")

    matcher = MatchingService(db)
    fit = await matcher.analyze_pair(profile, grant, with_llm=explain)
    return FitResult(**fit)
