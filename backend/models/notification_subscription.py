from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database.connection import Base


class NotificationSubscription(Base):
    __tablename__ = "notification_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Phase 4: optional email channel ALONGSIDE Telegram (not a replacement).
    # `email` is the destination address; `email_enabled` lets a subscriber keep
    # an address on file but mute email delivery. A subscriber receives email
    # reminders only when both an address is present AND email_enabled is true.
    email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    email_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
