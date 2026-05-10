"""Vercel Cron: deadline reminders to Telegram."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

import httpx
from fastapi import FastAPI, Header, HTTPException

from database.connection import AsyncSessionLocal
from services.reminder_service import ReminderService
from core.config import get_settings

app = FastAPI()
CRON_SECRET = os.getenv("CRON_SECRET", "")


def _check_auth(authorization: str | None) -> None:
    if not CRON_SECRET:
        return
    if authorization != f"Bearer {CRON_SECRET}":
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/api/cron/reminders")
async def run_reminders(authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return {"ok": False, "reason": "telegram not configured"}

    async with AsyncSessionLocal() as db:
        service = ReminderService(db)
        upcoming = await service.get_upcoming_deadlines(days_ahead=7)

    sent = 0
    async with httpx.AsyncClient() as client:
        for grant, days_left in upcoming:
            if days_left not in (7, 3, 1):
                continue
            text = (
                f"⏰ <b>Напоминание о сроке</b>\n\n"
                f"<b>{grant.title}</b>\n"
                f"Организация: {grant.organization or 'не указана'}\n"
                f"Срок: <b>{grant.deadline}</b> "
                f"(осталось дн.: {days_left})\n"
                f"<a href='{grant.source_url}'>Открыть грант</a>"
            )
            url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
            await client.post(url, json={
                "chat_id": settings.telegram_chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            })
            sent += 1
    return {"ok": True, "sent": sent}
