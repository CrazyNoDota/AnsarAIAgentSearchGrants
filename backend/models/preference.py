from datetime import datetime
from sqlalchemy import String, Float, Integer, Text, DateTime, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from database.connection import Base


class UserPreference(Base):
    """AI learning table — stores patterns from Aydar's approval/rejection decisions."""
    __tablename__ = "user_preferences"
    __table_args__ = (
        UniqueConstraint("preference_type", "value", name="uq_pref_type_value"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    preference_type: Mapped[str] = mapped_column(String(50), nullable=False)  # category|country|keyword|industry
    value: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    approved_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
