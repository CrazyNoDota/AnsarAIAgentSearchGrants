from datetime import datetime
from typing import Optional
from sqlalchemy import Text, String, Numeric, Integer, DateTime, func, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from database.connection import Base


class CompanyProfile(Base):
    """Phase 2: Company / project profile used to match grants against.

    Captures the structured signals needed to compute a deterministic fit
    score versus a grant's Phase-1 structured fields (industry / region /
    budget / stage) plus a free-text description used for semantic (pgvector)
    matching. This is intentionally additive — no existing table is modified.
    """
    __tablename__ = "company_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # Owner — profiles are private to the user who created them. All access is
    # scoped by user_id (see ProfileService); never expose other users' profiles.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)

    # Structured matching signals — mirror the Grant Phase-1 fields so the
    # matching engine can compare like-for-like.
    industry: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    # idea | mvp | growth | scaling | established  (free text, lowercased on match)
    stage: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    region: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    # Funding amount the company is seeking (single target value).
    funding_amount_sought: Mapped[Optional[float]] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    team_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # startup | sme | nonprofit | university | research_center | individual ...
    organization_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # Comma/space separated keywords used to bias matching.
    keywords: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Total prior funding raised (optional signal, not currently scored hard).
    past_funding: Mapped[Optional[float]] = mapped_column(Numeric(18, 2), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def profile_text(self) -> str:
        """Build the natural-language text used for semantic (RAG) matching."""
        parts = [f"Company: {self.name}"]
        if self.organization_type:
            parts.append(f"Organization type: {self.organization_type}")
        if self.industry:
            parts.append(f"Industry: {self.industry}")
        if self.stage:
            parts.append(f"Stage: {self.stage}")
        if self.region:
            parts.append(f"Region: {self.region}")
        if self.country:
            parts.append(f"Country: {self.country}")
        if self.funding_amount_sought is not None:
            cur = self.currency or ""
            parts.append(f"Funding sought: {cur} {self.funding_amount_sought}".strip())
        if self.team_size is not None:
            parts.append(f"Team size: {self.team_size}")
        if self.keywords:
            parts.append(f"Keywords: {self.keywords}")
        if self.description:
            parts.append(f"Description: {self.description}")
        return "\n".join(parts)
