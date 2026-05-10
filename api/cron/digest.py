"""Vercel Cron: daily digest of new pending grants to subscribed users."""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

import httpx
from fastapi import FastAPI, Header, HTTPException
from sqlalchemy import select

from database.connection import AsyncSessionLocal
from models.grant import Grant
from models.notification_subscription import NotificationSubscription
from core.config import get_settings

app = FastAPI()
CRON_SECRET = os.getenv("CRON_SECRET", "")

MAX_GRANTS_PER_MESSAGE = 10  # Telegram messages have a 4096-char limit


def _check_auth(authorization: str | None) -> None:
    if not CRON_SECRET:
        return
    if authorization != f"Bearer {CRON_SECRET}":
        raise HTTPException(status_code=401, detail="unauthorized")


def _format_digest(grants: list[Grant]) -> list[str]:
    """Build one or more Telegram messages from the grant list."""
    if not grants:
        return []

    chunks: list[str] = []
    header = f"📰 <b>Ежедневный дайджест</b> — новых грантов: {len(grants)}\n\n"
    body_lines: list[str] = []

    for g in grants:
        deadline = f" — срок {g.deadline}" if g.deadline else ""
        org = f" ({g.organization})" if g.organization else ""
        body_lines.append(
            f"• <a href='{g.source_url}'>{g.title}</a>{org}{deadline}"
        )

    for i in range(0, len(body_lines), MAX_GRANTS_PER_MESSAGE):
        page = body_lines[i:i + MAX_GRANTS_PER_MESSAGE]
        prefix = header if i == 0 else "📰 <b>Ежедневный дайджест</b> (продолжение)\n\n"
        chunks.append(prefix + "\n".join(page))

    return chunks


@app.get("/api/cron/digest")
async def run_digest(authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    settings = get_settings()
    if not settings.telegram_bot_token:
        return {"ok": False, "reason": "telegram_bot_token not configured"}

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    async with AsyncSessionLocal() as db:
        new_grants = (await db.execute(
            select(Grant)
            .where(Grant.status == "pending")
            .where(Grant.created_at >= cutoff)
            .order_by(Grant.ai_score.desc(), Grant.created_at.desc())
        )).scalars().all()

        subs = (await db.execute(select(NotificationSubscription))).scalars().all()

    if not subs:
        return {"ok": True, "subscribers": 0, "new_grants": len(new_grants), "sent": 0}

    if not new_grants:
        return {"ok": True, "subscribers": len(subs), "new_grants": 0, "sent": 0}

    messages = _format_digest(list(new_grants))
    sent = 0
    failed = 0
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"

    async with httpx.AsyncClient(timeout=15) as client:
        for sub in subs:
            for text in messages:
                resp = await client.post(url, json={
                    "chat_id": sub.telegram_chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                })
                if resp.status_code == 200 and resp.json().get("ok"):
                    sent += 1
                else:
                    failed += 1

    return {
        "ok": True,
        "subscribers": len(subs),
        "new_grants": len(new_grants),
        "sent": sent,
        "failed": failed,
    }
