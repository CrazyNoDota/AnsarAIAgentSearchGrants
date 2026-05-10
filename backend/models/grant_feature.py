from sqlalchemy import Text, String, Float, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.connection import Base


class GrantFeature(Base):
    """Stores extracted keywords/features from grants for AI learning."""

    __tablename__ = "grant_features"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    grant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("grants.id", ondelete="CASCADE"), nullable=False
    )
    keyword: Mapped[str] = mapped_column(String(256), nullable=False)
    category: Mapped[str] = mapped_column(String(256), nullable=True)
    country: Mapped[str] = mapped_column(String(256), nullable=True)
    score_delta: Mapped[float] = mapped_column(Float, default=0.0)

    grant: Mapped["Grant"] = relationship("Grant", back_populates="features")
