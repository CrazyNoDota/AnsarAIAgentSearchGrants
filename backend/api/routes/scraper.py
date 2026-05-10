from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from api.deps import get_current_user
from models.user import User

router = APIRouter(prefix="/scraper", tags=["scraper"])


@router.post("/run")
async def trigger_scraper(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Manually trigger all scrapers. Runs synchronously — on Vercel the
    daily Cron at /api/cron/scrape is the recommended automation path."""
    from scraping.runner import run_all_scrapers_async
    summary = await run_all_scrapers_async()
    return {"status": "ok", "summary": summary}
