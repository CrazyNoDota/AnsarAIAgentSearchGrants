from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String,
    Text,
    Integer,
    DateTime,
    JSON,
    ForeignKey,
    Boolean,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.connection import Base


class KnowledgeEntry(Base):
    """Phase 5: a knowledge-base entry — the user's grant "memory".

    A single, flexible table holds the four knowledge kinds from the plan:
      - ``past_application``  — a submitted application (often linked to a
                                Phase-3 ApplicationPackage).
      - ``successful_case``   — a won/successful case worth reusing.
      - ``template``          — a reusable section/application template.
      - ``submission``        — submission history + result (won/rejected/...).

    ``content`` is the searchable free text (problem statement, sections,
    lessons learned, etc.). ``meta`` is a small JSON bag for kind-specific
    fields (e.g. outcome, award amount, funder) so the table stays additive
    without per-kind columns.

    SECURITY: knowledge entries are PRIVATE to their owner (Phase 2/3 lesson).
    ``user_id`` is NOT NULL and every access path is scoped by it
    (see KnowledgeService); there is deliberately no unscoped getter. A user
    never reads another user's past applications / cases / templates.
    """

    __tablename__ = "knowledge_entries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # past_application | successful_case | template | submission
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Outcome of a submission/case: won | rejected | submitted | pending | None.
    outcome: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # Optional links to the source rows. SET NULL on delete so a knowledge
    # entry survives deletion of the package/grant it was derived from.
    package_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("application_packages.id", ondelete="SET NULL"), nullable=True
    )
    grant_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("grants.id", ondelete="SET NULL"), nullable=True
    )
    # Denormalized funder/grant title so the entry stays meaningful after the
    # source grant row is removed.
    funder: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Small kind-specific JSON bag (award amount, tags, lessons, etc.).
    meta: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    # Whether this entry has a stored embedding for semantic retrieval.
    embedding_status: Mapped[str] = mapped_column(
        String(32), default="pending", nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def search_text(self) -> str:
        """Deterministic text used for embedding + keyword search."""
        parts = [f"Title: {self.title}", f"Kind: {self.kind}"]
        if self.funder:
            parts.append(f"Funder: {self.funder}")
        if self.outcome:
            parts.append(f"Outcome: {self.outcome}")
        if self.content:
            parts.append(self.content)
        return "\n".join(parts)
