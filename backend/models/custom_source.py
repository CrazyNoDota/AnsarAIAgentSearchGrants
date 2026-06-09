from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String,
    Text,
    Integer,
    DateTime,
    Boolean,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.connection import Base


class CustomSource(Base):
    """Phase 7: a user-registered grant source URL.

    Beyond the 37 built-in scrapers + the AI Search Agent, an operator can add an
    arbitrary grant/funding listing page from the Telegram bot (``/addsource``).
    On each scrape cycle (and on demand) we fetch the page and run the
    ``AdaptiveParser`` (LLM-writes-a-reusable-CSS-strategy, cached per source;
    direct-LLM extraction fallback) over it — the same engine used for the fragile
    built-in sources. Extracted grants flow into the normal ``grants`` table with
    ``status = 'pending'`` so they show up in /pending, /search and /recommend.

    The ``last_*`` columns record the outcome of the most recent run so the bot
    can show each source's health (``/sources``).
    """

    __tablename__ = "custom_sources"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # The listing URL to scrape. Unique so the same page isn't registered twice.
    url: Mapped[str] = mapped_column(String(2000), nullable=False, unique=True)
    # Friendly label shown in the bot (defaults to the URL when absent).
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Optional country/region hint applied to grants that don't carry their own.
    country: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Who registered it (Telegram username or id) — informational only.
    added_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # Disabled sources are skipped by the scheduled run but can still be run
    # one-off via /scrapesource.
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # ── Last-run health ──────────────────────────────────────────────
    last_scraped_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # ok | error | None (never run)
    last_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # Number of NEW grants added on the last run.
    last_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "name": self.name,
            "country": self.country,
            "added_by": self.added_by,
            "enabled": self.enabled,
            "last_scraped_at": (
                self.last_scraped_at.isoformat() if self.last_scraped_at else None
            ),
            "last_status": self.last_status,
            "last_count": self.last_count,
            "last_error": self.last_error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
