from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, Integer, DateTime, JSON, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from database.connection import Base


class ApplicationPackage(Base):
    """Phase 3: a generated grant-application document package.

    One row per (profile, grant) generation. The drafted sections are stored as
    JSON (ordered list of ``{key, title, content}``) so the package can be
    re-exported to .docx/.pdf/.md or edited without re-running generation.

    SECURITY: packages are PRIVATE to their owner (Phase 2 lesson). ``user_id``
    is NOT NULL and every access path is scoped by it (see DocumentService);
    there is deliberately no unscoped getter.
    """

    __tablename__ = "application_packages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Profile/grant the package was generated for. SET NULL on delete so a
    # generated package survives deletion of its source profile/grant.
    profile_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("company_profiles.id", ondelete="SET NULL"), nullable=True
    )
    grant_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("grants.id", ondelete="SET NULL"), nullable=True
    )
    # Denormalized grant title so the package stays meaningful if the grant row
    # is later removed.
    grant_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    title: Mapped[str] = mapped_column(Text, nullable=False)
    # draft | complete | generating | failed
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    # Ordered list of {"key", "title", "content"}.
    sections: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
