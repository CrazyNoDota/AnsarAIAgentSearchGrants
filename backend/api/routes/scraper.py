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
    """
    Manually trigger all scrapers + AI Search Agent.
    Automatically scheduled by n8n daily at 02:00 (Asia/Almaty).
    Also callable manually from Telegram (/scrape) or this API.
    """
    from scraping.runner import run_all_scrapers_async
    summary = await run_all_scrapers_async(include_ai_agent=True)
    return {"status": "ok", **summary}
