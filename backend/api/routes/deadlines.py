"""
Deadline Tracking Endpoints
Returns upcoming deadlines and sends reminders via Telegram.
"""
import hmac
import logging
from datetime import date, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from database.connection import get_db
from schemas.grant import GrantResponse
from models.grant import Grant
from api.deps import get_current_user
from models.user import User
from services import calendar_service as cal
from services.document_service import DocumentService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/deadlines", tags=["deadlines"])


@router.get("")
async def get_upcoming_deadlines(
    days: int = Query(30, ge=1, le=365, description="Look ahead N days"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Get approved grants with deadlines in the next N days."""
    today = date.today()
    cutoff = today + timedelta(days=days)

    result = await db.execute(
        select(Grant).where(
            Grant.status == "approved",
            Grant.deadline.isnot(None),
            Grant.deadline >= today,
            Grant.deadline <= cutoff,
        ).order_by(Grant.deadline.asc())
    )
    grants = result.scalars().all()

    items = []
    for g in grants:
        days_left = (g.deadline - today).days
        items.append({
            **GrantResponse.model_validate(g).model_dump(),
            "days_left": days_left,
            "urgency": (
                "critical" if days_left <= 1 else
                "high" if days_left <= 7 else
                "medium" if days_left <= 14 else
                "normal"
            ),
        })

    return {"items": items, "total": len(items), "days_ahead": days}


@router.get("/calendar")
async def get_grant_calendar(
    days: int = Query(90, ge=1, le=365, description="Look ahead N days"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Calendar of active (approved) grants with deadlines in the next N days.

    Returns events sorted by deadline plus the same events grouped into urgency
    buckets (critical/high/medium/normal), for a calendar/agenda view.
    """
    today = date.today()
    cutoff = today + timedelta(days=days)
    result = await db.execute(
        select(Grant).where(
            Grant.status == "approved",
            Grant.deadline.isnot(None),
            Grant.deadline >= today,
            Grant.deadline <= cutoff,
        ).order_by(Grant.deadline.asc())
    )
    grants = result.scalars().all()
    events = [cal.grant_to_calendar_event(g, today) for g in grants]
    return {
        "events": events,
        "buckets": cal.bucket_by_urgency(events),
        "total": len(events),
        "days_ahead": days,
        "generated_at": str(today),
    }


@router.get("/readiness")
async def list_readiness(
    limit: int = Query(50, ge=1, le=100, description="Maximum items to return"),
    offset: int = Query(0, ge=0, le=10000, description="Items to skip"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Application-prep readiness checklist for the CURRENT USER's packages.

    For each of the user's application packages, reports per-section drafted vs.
    TODO/missing status, an overall prep stage + percent-complete, and (when the
    source grant still exists) the grant deadline + urgency. USER-SCOPED: only
    packages owned by the authenticated user are read.
    """
    packages, total = await DocumentService(db).list_for_user(
        current_user.id, page=1, size=limit, offset=offset
    )
    today = date.today()
    items = []
    for pkg in packages:
        deadline = None
        if pkg.grant_id is not None:
            grant = await db.get(Grant, pkg.grant_id)
            if grant is not None:
                deadline = grant.deadline
        items.append(
            cal.build_readiness(
                package_id=pkg.id,
                title=pkg.title,
                status=pkg.status,
                grant_id=pkg.grant_id,
                grant_title=pkg.grant_title,
                sections=pkg.sections or [],
                deadline=deadline,
                today=today,
            )
        )
    return {
        "items": items,
        "count": len(items),
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/readiness/{package_id}")
async def get_readiness(
    package_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Readiness checklist for one owned package (404 if not owned)."""
    from fastapi import HTTPException

    pkg = await DocumentService(db).get_owned(package_id, current_user.id)
    if not pkg:
        raise HTTPException(status_code=404, detail="Application package not found")
    deadline = None
    if pkg.grant_id is not None:
        grant = await db.get(Grant, pkg.grant_id)
        if grant is not None:
            deadline = grant.deadline
    return cal.build_readiness(
        package_id=pkg.id,
        title=pkg.title,
        status=pkg.status,
        grant_id=pkg.grant_id,
        grant_title=pkg.grant_title,
        sections=pkg.sections or [],
        deadline=deadline,
    )


@router.get("/reminders")
async def send_deadline_reminders(
    reminder_secret: Optional[str] = Header(None, alias="X-Reminder-Secret"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Check for grants needing reminders (30/14/7/1 days before deadline).
    Called by n8n daily workflow at 08:00.
    Sends reminders for each upcoming deadline over Telegram AND email.
    """
    settings = get_settings()
    if settings.reminder_cron_secret and not hmac.compare_digest(
        reminder_secret or "", settings.reminder_cron_secret
    ):
        raise HTTPException(status_code=403, detail="Invalid reminder secret")

    today = date.today()
    reminder_days = [30, 14, 7, 1]
    sent = []

    for days_ahead in reminder_days:
        target_date = today + timedelta(days=days_ahead)

        result = await db.execute(
            select(Grant).where(
                Grant.status == "approved",
                Grant.deadline == target_date,
            )
        )
        grants = result.scalars().all()

        for g in grants:
            sent.append({
                "grant_id": g.id,
                "title": g.title,
                "deadline": str(g.deadline),
                "days_left": days_ahead,
                "source_url": g.source_url,
            })

    channels = {"telegram": 0, "email": 0}
    if sent:
        # Telegram (existing behaviour — broadcast to all subscribers).
        try:
            await _send_deadline_telegram_alerts(sent)
            channels["telegram"] = len(sent)
        except Exception as e:
            logger.error(f"Telegram deadline alerts failed: {e}")
        # Email (Phase 4 — additional channel; never aborts the run).
        try:
            channels["email"] = await _send_deadline_email_alerts(sent)
        except Exception as e:
            logger.error(f"Email deadline alerts failed: {e}")

    return {
        "reminders_sent": len(sent),
        "items": sent,
        "date": str(today),
        "channels": channels,
    }


async def _send_deadline_email_alerts(items: list[dict]) -> int:
    """Email deadline reminders to subscribers who have email enabled.

    Returns the number of emails delivered. Degrades gracefully: if email is
    unconfigured or no subscriber has an email address, logs and returns 0
    (never raises) — mirrors the Telegram alert path.
    """
    from sqlalchemy import select as sa_select
    from database.connection import AsyncSessionLocal
    from models.notification_subscription import NotificationSubscription
    from services.email_service import EmailService, render_deadline_email

    email_service = EmailService()
    if not email_service.available:
        logger.warning("Email not configured — skipping email deadline alerts")
        return 0

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            sa_select(NotificationSubscription).where(
                NotificationSubscription.email.isnot(None),
                NotificationSubscription.email_enabled.is_(True),
            )
        )
        subscribers = result.scalars().all()

    recipients = [s.email for s in subscribers if s.email]
    if not recipients:
        logger.info("No email subscribers — skipping email deadline alerts")
        return 0

    subject, text_body, html_body = render_deadline_email(items)
    return await email_service.send_bulk(recipients, subject, text_body, html_body)


async def _send_deadline_telegram_alerts(items: list[dict]) -> None:
    """
    Send deadline reminders to ALL registered subscribers (from notification_subscriptions).
    No hardcoded TELEGRAM_CHAT_ID needed — works as long as users have sent /start to the bot.
    """
    import httpx
    from sqlalchemy import select as sa_select
    from database.connection import AsyncSessionLocal
    from models.notification_subscription import NotificationSubscription
    from core.config import get_settings

    settings = get_settings()
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN not set — skipping deadline alerts")
        return

    # Get all subscribers from DB
    async with AsyncSessionLocal() as db:
        result = await db.execute(sa_select(NotificationSubscription))
        subscribers = result.scalars().all()

    if not subscribers:
        logger.info("No subscribers found — skipping deadline alerts (users need to /start the bot)")
        return

    chat_ids = [s.telegram_chat_id for s in subscribers]

    for item in items:
        days = item["days_left"]
        urgency_emoji = "🔴" if days <= 1 else "🟡" if days <= 7 else "🔵"
        text = (
            f"{urgency_emoji} <b>Deadline Reminder</b>\n\n"
            f"<b>{item['title']}</b>\n"
            f"⏰ Deadline: <b>{item['deadline']}</b>\n"
            f"📅 Days remaining: <b>{days}</b>\n\n"
            f'🔗 <a href="{item["source_url"]}">Open Grant</a>'
        )

        async with httpx.AsyncClient() as client:
            for chat_id in chat_ids:
                try:
                    await client.post(
                        f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                        json={
                            "chat_id": chat_id,
                            "text": text,
                            "parse_mode": "HTML",
                            "disable_web_page_preview": True,
                        },
                        timeout=10,
                    )
                except Exception as e:
                    logger.warning(f"Failed to send deadline alert to {chat_id}: {e}")
