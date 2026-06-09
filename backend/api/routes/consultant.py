"""
Phase 5 — AI consultant routes (grounded Q&A + completeness/fit review).

All endpoints are AUTH-scoped to the current user. Any package read goes through
``DocumentService.get_owned(id, user_id)`` and any knowledge-base retrieval
through the user-scoped ``KnowledgeService`` — the consultant never reads another
user's data. Answers are grounded ONLY in the supplied grant data, the user's
owned package, and the user's own retrieved knowledge-base cases.

  - POST /consultant/ask      grounded Q&A about a grant (+ optional package/KB)
  - POST /consultant/review   completeness/fit check + recommendations for an
                              owned package against the grant's requirements
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from api.deps import get_current_user
from models.user import User
from models.grant import Grant
from schemas.consultant import AskRequest, AskResponse, ReviewRequest, ReviewResponse
from services.consultant_service import ConsultantService
from services.document_service import DocumentService
from services.knowledge_service import KnowledgeService
from services.matching_service import MatchingService
from services.profile_service import ProfileService
from services.document_templates import DEFAULT_SECTIONS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/consultant", tags=["consultant"])


def _package_to_dict(pkg) -> dict:
    return {
        "title": pkg.title,
        "status": pkg.status,
        "sections": pkg.sections or [],
    }


@router.post("/ask", response_model=AskResponse)
async def ask_consultant(
    data: AskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Answer a grounded question about a grant's terms/conditions.

    Grounds the answer in the grant data, the user's owned package (if given),
    and the user's own knowledge-base cases (if enabled). Never fabricates.
    """
    grant = None
    if data.grant_id is not None:
        grant = await db.get(Grant, data.grant_id)
        if not grant:
            raise HTTPException(status_code=404, detail="Grant not found")

    package = None
    if data.package_id is not None:
        pkg = await DocumentService(db).get_owned(data.package_id, current_user.id)
        if not pkg:
            raise HTTPException(status_code=404, detail="Application package not found")
        package = _package_to_dict(pkg)

    cases = None
    if data.use_knowledge_base:
        cases = await KnowledgeService(db).retrieve_context(
            data.question, current_user.id, top_k=5
        )

    result = await ConsultantService(db).ask(
        question=data.question,
        grant=grant,
        package=package,
        cases=cases,
    )
    return AskResponse(**result)


@router.post("/review", response_model=ReviewResponse)
async def review_package(
    data: ReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Completeness/fit check + improvement recommendations for an owned package.

    Reports which required sections are missing/TODO, weak spots, and eligibility
    gaps (from the deterministic Phase-2 fit), then grounded recommendations.
    """
    pkg = await DocumentService(db).get_owned(data.package_id, current_user.id)
    if not pkg:
        raise HTTPException(status_code=404, detail="Application package not found")

    grant = None
    if pkg.grant_id is not None:
        grant = await db.get(Grant, pkg.grant_id)

    # Deterministic fit (Phase-2) when the source profile + grant still exist.
    fit = None
    if data.include_fit and grant is not None and pkg.profile_id is not None:
        profile = await ProfileService(db).get_owned(pkg.profile_id, current_user.id)
        if profile is not None:
            try:
                fit = await MatchingService(db).compute_fit(profile, grant)
            except Exception as e:  # fit is best-effort; never break the review
                logger.warning("fit computation failed for review: %s", e)

    cases = None
    if data.use_knowledge_base:
        cases = await KnowledgeService(db).retrieve_context(
            pkg.title, current_user.id, top_k=3
        )

    required_keys = [s.key for s in DEFAULT_SECTIONS]
    result = await ConsultantService(db).review_package(
        package=_package_to_dict(pkg),
        grant=grant,
        fit=fit,
        required_keys=required_keys,
        cases=cases,
    )
    return ReviewResponse(**result)
