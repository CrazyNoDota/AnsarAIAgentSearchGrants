from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from database.connection import Base


class SearchLog(Base):
    """Logs all search queries for analytics and improvement tracking."""
    __tablename__ = "search_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    results_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    search_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # semantic|keyword|hybrid
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
