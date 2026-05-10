"""
APScheduler jobs:
- Every 24h: run all scrapers
- Every 24h: update AI scores for pending grants
- Every 24h at 08:00: send deadline reminders via Telegram
"""
import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


async def job_run_scrapers():
    """Daily scraping job."""
    from scraping.runner import run_all_scrapers_async
    logger.info("Scheduler: starting scraper run")
    summary = await run_all_scrapers_async()
    logger.info(f"Scheduler: scraping done — {summary}")


async def job_update_ai_scores():
    """Nightly AI score recalculation."""
    from database.connection import AsyncSessionLocal
    from services.ai_service import AIService

    logger.info("Scheduler: updating AI scores")
    async with AsyncSessionLocal() as db:
        service = AIService(db)
        count = await service.update_all_scores()
        await db.commit()
    logger.info(f"Scheduler: updated {count} grant scores")


async def job_send_reminders():
    """Daily deadline reminder notifications via Telegram."""
    from database.connection import AsyncSessionLocal
    from services.reminder_service import ReminderService
    from core.config import get_settings
    import httpx

    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.warning("Scheduler: Telegram not configured, skipping reminders")
        return

    logger.info("Scheduler: checking deadlines")
    async with AsyncSessionLocal() as db:
        service = ReminderService(db)
        upcoming = await service.get_upcoming_deadlines(days_ahead=7)

    for grant, days_left in upcoming:
        if days_left in (7, 3, 1):
            text = (
                f"⏰ <b>Deadline Reminder</b>\n\n"
                f"<b>{grant.title}</b>\n"
                f"Organization: {grant.organization or 'N/A'}\n"
                f"Deadline: <b>{grant.deadline}</b> ({days_left} day{'s' if days_left != 1 else ''} left)\n"
                f"<a href='{grant.source_url}'>View Grant</a>"
            )
            url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
            async with httpx.AsyncClient() as client:
                await client.post(url, json={
                    "chat_id": settings.telegram_chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                })

    logger.info(f"Scheduler: sent reminders for {len([x for x in upcoming if x[1] in (7,3,1)])} grants")


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    # Run scrapers every 24 hours
    scheduler.add_job(
        job_run_scrapers,
        trigger=IntervalTrigger(hours=24),
        id="scraper_job",
        replace_existing=True,
        coalesce=True,
    )

    # Update AI scores every 24 hours (1 hour after scrapers)
    scheduler.add_job(
        job_update_ai_scores,
        trigger=IntervalTrigger(hours=24),
        id="ai_scores_job",
        replace_existing=True,
        coalesce=True,
    )

    # Send reminders every day at 08:00
    scheduler.add_job(
        job_send_reminders,
        trigger=CronTrigger(hour=8, minute=0),
        id="reminders_job",
        replace_existing=True,
        coalesce=True,
    )

    return scheduler
