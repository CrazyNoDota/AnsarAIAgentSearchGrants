from datetime import datetime, date
from typing import Optional, List
from sqlalchemy import Text, String, Float, BigInteger, DateTime, Date, Numeric, func
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
    telegram_msg_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # New fields added in migration 003
    grant_amount: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    eligibility: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    industry: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    startup_stage: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    application_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.85, nullable=False)
    embedding_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)

    # Phase 1 structured filter fields (deadline already exists above as Date).
    # budget_* are normalized numeric values parsed from grant_amount; region is
    # a coarse geo bucket (e.g. "Europe", "United Kingdom", "Global") used for
    # geo filtering independent of the free-text `country`.
    budget_min: Mapped[Optional[float]] = mapped_column(Numeric(18, 2), nullable=True)
    budget_max: Mapped[Optional[float]] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    region: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    reviews: Mapped[List["Review"]] = relationship(
        "Review", back_populates="grant", cascade="all, delete-orphan"
    )
    features: Mapped[List["GrantFeature"]] = relationship(
        "GrantFeature", back_populates="grant", cascade="all, delete-orphan"
    )
    embeddings: Mapped[List["GrantEmbedding"]] = relationship(
        "GrantEmbedding", back_populates="grant", cascade="all, delete-orphan"
    )
