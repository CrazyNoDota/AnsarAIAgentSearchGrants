from datetime import datetime, date
from typing import Optional, List
from sqlalchemy import Text, String, Float, BigInteger, DateTime, Date, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.connection import Base


class Grant(Base):
    __tablename__ = "grants"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    organization: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    deadline: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    source_url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    ai_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # Telegram message ID to allow editing/deleting sent messages
    telegram_msg_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    reviews: Mapped[List["Review"]] = relationship(
        "Review", back_populates="grant", cascade="all, delete-orphan"
    )
    features: Mapped[List["GrantFeature"]] = relationship(
        "GrantFeature", back_populates="grant", cascade="all, delete-orphan"
    )
