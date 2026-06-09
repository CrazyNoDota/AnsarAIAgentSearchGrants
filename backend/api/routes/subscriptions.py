"""
Subscription management endpoints.
The bot uses these to register/unsubscribe users for notifications.
No hardcoded TELEGRAM_CHAT_ID needed — subscribers are stored in the DB.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, field_validator

from database.connection import get_db
from models.notification_subscription import NotificationSubscription
from api.deps import get_current_user
from models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


def _validate_email(v: Optional[str]) -> Optional[str]:
    """Lightweight email check (avoids the email-validator dependency).

    Accepts None/empty (clears the address); otherwise requires a single '@'
    with non-empty local + domain parts and a dot in the domain.
    """
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    local, _, domain = v.partition("@")
    if not local or "@" in domain or "." not in domain or domain.startswith(".") \
            or domain.endswith(".") or " " in v or len(v) > 320:
        raise ValueError("invalid email address")
    return v


class SubscribeRequest(BaseModel):
    telegram_user_id: int
    telegram_chat_id: int
    # Phase 4: optional email channel registered alongside Telegram.
    email: Optional[str] = None
    email_enabled: bool = True

    _v_email = field_validator("email")(staticmethod(_validate_email))


class EmailPrefRequest(BaseModel):
    """Set/clear the email channel for an existing subscriber."""

    telegram_user_id: int
    email: Optional[str] = None
    email_enabled: bool = True

    _v_email = field_validator("email")(staticmethod(_validate_email))


@router.post("/register")
async def register_subscriber(
    data: SubscribeRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Register or update a Telegram subscriber. Called on /start and /subscribe.

    Optionally records an email address for the email notification channel.
    """
    existing = await db.scalar(
        select(NotificationSubscription).where(
            NotificationSubscription.telegram_user_id == data.telegram_user_id
        )
    )
    if existing:
        existing.telegram_chat_id = data.telegram_chat_id
        if data.email is not None:
            existing.email = data.email
            existing.email_enabled = data.email_enabled
        await db.commit()
        return {"status": "updated", "chat_id": data.telegram_chat_id}

    db.add(NotificationSubscription(
        telegram_user_id=data.telegram_user_id,
        telegram_chat_id=data.telegram_chat_id,
        email=data.email,
        email_enabled=data.email_enabled,
    ))
    await db.commit()
    return {"status": "registered", "chat_id": data.telegram_chat_id}


@router.post("/email")
async def set_email_preference(
    data: EmailPrefRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Set or clear the email address / toggle email delivery for a subscriber."""
    sub = await db.scalar(
        select(NotificationSubscription).where(
            NotificationSubscription.telegram_user_id == data.telegram_user_id
        )
    )
    if not sub:
        raise HTTPException(status_code=404, detail="Subscriber not found")
    sub.email = data.email
    sub.email_enabled = data.email_enabled
    await db.commit()
    return {
        "status": "updated",
        "email": sub.email,
        "email_enabled": sub.email_enabled,
    }


@router.delete("/unregister/{telegram_user_id}")
async def unregister_subscriber(
    telegram_user_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Remove a Telegram subscriber."""
    result = await db.execute(
        delete(NotificationSubscription).where(
            NotificationSubscription.telegram_user_id == telegram_user_id
        )
    )
    await db.commit()
    return {"status": "removed" if result.rowcount else "not_found"}


@router.get("/status/{telegram_user_id}")
async def check_subscription(
    telegram_user_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Check if a user is subscribed."""
    sub = await db.scalar(
        select(NotificationSubscription).where(
            NotificationSubscription.telegram_user_id == telegram_user_id
        )
    )
    return {
        "subscribed": sub is not None,
        "since": sub.created_at.isoformat() if sub else None,
    }


@router.get("/all")
async def list_subscribers(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """List all subscribers (used by digest/reminder workflows)."""
    result = await db.execute(select(NotificationSubscription))
    subs = result.scalars().all()
    return [
        {
            "user_id": s.telegram_user_id,
            "chat_id": s.telegram_chat_id,
            "email": s.email,
            "email_enabled": s.email_enabled,
        }
        for s in subs
    ]
