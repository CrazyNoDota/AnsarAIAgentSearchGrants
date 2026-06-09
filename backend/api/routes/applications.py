"""
Phase 3 — Application document package routes.

Endpoints (all auth-scoped to the current user):
  - POST   /applications/generate         generate + persist a package
  - GET    /applications                   list the user's packages
  - GET    /applications/{id}              fetch one owned package
  - PATCH  /applications/{id}              replace sections (manual edits)
  - DELETE /applications/{id}              delete an owned package
  - GET    /applications/{id}/export       download as .docx/.pdf/.md
  - POST   /applications/extract           multimodal OCR of an uploaded
                                           grant-call PDF/image → grounding text
"""
import logging

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    UploadFile,
    File,
    Form,
)
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from api.deps import get_current_user
from models.user import User
from models.grant import Grant
from schemas.application import (
    GenerateRequest,
    ApplicationResponse,
    ApplicationUpdate,
    ExtractResponse,
)
from services.document_service import DocumentService
from services.profile_service import ProfileService
from services.export_service import render, EXPORT_FORMATS
from services.multimodal_service import MultimodalService, DEFAULT_INSTRUCTION

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/applications", tags=["applications"])

# Max upload size for multimodal extraction (10 MB) — keeps memory bounded.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@router.post("/generate", response_model=ApplicationResponse, status_code=201)
async def generate_application(
    data: GenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate and persist an application package for an owned profile."""
    profile = await ProfileService(db).get_owned(data.profile_id, current_user.id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    grant = await db.get(Grant, data.grant_id)
    if not grant:
        raise HTTPException(status_code=404, detail="Grant not found")

    service = DocumentService(db)
    try:
        content = await service.generate_package_content(
            profile, grant, section_keys=data.sections, extra_ctx=data.extra_context
        )
    except ValueError as e:  # unknown section key(s)
        raise HTTPException(status_code=400, detail=str(e))

    pkg = await service.create_package(
        user_id=current_user.id, profile=profile, grant=grant, content=content
    )
    return ApplicationResponse.model_validate(pkg)


@router.get("", response_model=dict)
async def list_applications(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    packages, total = await DocumentService(db).list_for_user(
        current_user.id, page=page, size=size
    )
    return {
        "items": [ApplicationResponse.model_validate(p) for p in packages],
        "total": total,
        "page": page,
        "size": size,
    }


@router.get("/{package_id}", response_model=ApplicationResponse)
async def get_application(
    package_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pkg = await DocumentService(db).get_owned(package_id, current_user.id)
    if not pkg:
        raise HTTPException(status_code=404, detail="Application package not found")
    return ApplicationResponse.model_validate(pkg)


@router.patch("/{package_id}", response_model=ApplicationResponse)
async def update_application(
    package_id: int,
    data: ApplicationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pkg = await DocumentService(db).update_sections(
        package_id, current_user.id, [s.model_dump() for s in data.sections]
    )
    if not pkg:
        raise HTTPException(status_code=404, detail="Application package not found")
    return ApplicationResponse.model_validate(pkg)


@router.delete("/{package_id}", status_code=204)
async def delete_application(
    package_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not await DocumentService(db).delete(package_id, current_user.id):
        raise HTTPException(status_code=404, detail="Application package not found")
    return None


@router.get("/{package_id}/export")
async def export_application(
    package_id: int,
    format: str = Query("docx", description="Export format: md | docx | pdf"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Render an owned package to the requested format and stream it back."""
    if format not in EXPORT_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format. Choose one of: {', '.join(EXPORT_FORMATS)}",
        )
    pkg = await DocumentService(db).get_owned(package_id, current_user.id)
    if not pkg:
        raise HTTPException(status_code=404, detail="Application package not found")

    package_dict = {"title": pkg.title, "sections": pkg.sections or []}
    try:
        rendered = render(package_dict, format)
    except RuntimeError as e:  # optional export dependency missing
        raise HTTPException(status_code=501, detail=str(e))

    from services.export_service import _safe_filename

    filename = f"{_safe_filename(pkg.title)}.{rendered.extension}"
    return Response(
        content=rendered.content,
        media_type=rendered.media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/extract", response_model=ExtractResponse)
async def extract_grant_call(
    file: UploadFile = File(...),
    instruction: str = Form(DEFAULT_INSTRUCTION),
    current_user: User = Depends(get_current_user),
):
    """Multimodal OCR of an uploaded grant-call PDF/image.

    Returns the extracted text to pass back into /applications/generate as
    `extra_context`, grounding the draft in the real call wording.
    """
    # Bounded read: stop after one byte past the limit so an oversized body is
    # never fully buffered into memory before we reject it.
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)",
        )

    service = MultimodalService()
    if not service.available:
        return ExtractResponse(text=None, pages_or_images=0, available=False)

    try:
        text, pages = await service.extract_from_upload(
            data, file.content_type or "", instruction
        )
    except ValueError as e:  # unsupported type OR unreadable/corrupt file
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:  # PyMuPDF missing
        raise HTTPException(status_code=501, detail=str(e))

    return ExtractResponse(text=text, pages_or_images=pages, available=True)
