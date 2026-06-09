from datetime import datetime
from typing import Optional
from sqlalchemy import Integer, Text, String, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.connection import Base


class GrantEmbedding(Base):
    """Stores vector embeddings for grants — enables RAG semantic search."""
    __tablename__ = "grant_embeddings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    grant_id: Mapped[int] = mapped_column(Integer, ForeignKey("grants.id", ondelete="CASCADE"), nullable=False)
    chunk_type: Mapped[str] = mapped_column(String(50), nullable=False)  # summary | eligibility | full
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    # embedding column is vector(1024) — managed via raw SQL in queries
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    grant: Mapped["Grant"] = relationship("Grant", back_populates="embeddings")
