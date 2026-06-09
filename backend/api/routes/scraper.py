from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from api.deps import get_current_user
from models.user import User
from models.custom_source import CustomSource
from core.url_guard import assert_public_url, UnsafeURLError

router = APIRouter(prefix="/scraper", tags=["scraper"])


@router.post("/run")
async def trigger_scraper(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Manually trigger all scrapers + AI Search Agent + custom sources.
    Automatically scheduled by n8n daily at 02:00 (Asia/Almaty).
    Also callable manually from Telegram (/scrape) or this API.
    """
    from scraping.runner import run_all_scrapers_async
    summary = await run_all_scrapers_async(include_ai_agent=True)
    return {"status": "ok", **summary}


# ── Custom sources (Phase 7) ─────────────────────────────────────────
# Operator-registered grant listing URLs scraped via the AdaptiveParser. Managed
# from the Telegram bot (/addsource, /sources, /delsource, /scrapesource).


class SourceCreate(BaseModel):
    # Max lengths mirror the CustomSource columns so overlong input is a clean 422
    # rather than a DB error.
    url: str = Field(max_length=2000)
    name: Optional[str] = Field(default=None, max_length=255)
    country: Optional[str] = Field(default=None, max_length=255)
    added_by: Optional[str] = Field(default=None, max_length=128)

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        v = (v or "").strip()
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("url must be a valid http(s) URL")
        return v

    @field_validator("name", "country", "added_by")
    @classmethod
    def _trim(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        return v or None


@router.get("/sources")
async def list_sources(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """List all registered custom sources (newest first)."""
    rows = await db.execute(
        select(CustomSource).order_by(CustomSource.created_at.desc())
    )
    sources = rows.scalars().all()
    return {"items": [s.to_dict() for s in sources], "total": len(sources)}


@router.post("/sources", status_code=status.HTTP_201_CREATED)
async def add_source(
    payload: SourceCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Register a new custom source. Idempotent on URL — re-adding an existing
    URL returns the existing row (and re-enables it) instead of erroring."""
    # Reject URLs that resolve to non-public addresses up front (SSRF guard);
    # the scrape path re-checks every redirect hop at fetch time.
    try:
        await assert_public_url(payload.url)
    except UnsafeURLError as e:
        raise HTTPException(status_code=400, detail=str(e))

    existing = await db.scalar(
        select(CustomSource).where(CustomSource.url == payload.url)
    )
    if existing is not None:
        # Re-enable + refresh label if it was previously disabled/renamed.
        existing.enabled = True
        if payload.name:
            existing.name = payload.name
        if payload.country:
            existing.country = payload.country
        await db.flush()
        return {"status": "exists", "source": existing.to_dict()}

    source = CustomSource(
        url=payload.url,
        name=payload.name,
        country=payload.country,
        added_by=payload.added_by,
    )
    db.add(source)
    await db.flush()
    return {"status": "created", "source": source.to_dict()}


@router.delete("/sources/{source_id}")
async def delete_source(
    source_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Remove a custom source. Does NOT delete grants already harvested from it."""
    source = await db.get(CustomSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    await db.delete(source)
    return {"status": "deleted", "id": source_id}


@router.post("/sources/{source_id}/toggle")
async def toggle_source(
    source_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Enable/disable a source (disabled sources are skipped by scheduled runs)."""
    source = await db.get(CustomSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    source.enabled = not source.enabled
    await db.flush()
    return {"status": "ok", "source": source.to_dict()}


@router.post("/sources/{source_id}/run")
async def run_source(
    source_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Scrape a single custom source immediately and return its result."""
    source = await db.get(CustomSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    from scraping.runner import run_custom_sources_async
    result = await run_custom_sources_async(db, source_id=source_id)
    return {"status": "ok", **result}
