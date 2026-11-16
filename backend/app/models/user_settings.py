import enum
import uuid

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Theme(enum.StrEnum):
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


class UserSettings(TimestampMixin, Base):
    """One optional row per user: the preferences the Settings page can change.

    A NULL retrieval value means "use the server default", so changing the default later
    still reaches users who never chose their own.
    """

    __tablename__ = "user_settings"
    __table_args__ = (
        CheckConstraint("theme IN ('light', 'dark', 'system')", name="theme"),
        CheckConstraint("retrieval_top_k BETWEEN 1 AND 20", name="retrieval_top_k"),
        CheckConstraint(
            "retrieval_score_threshold BETWEEN 0 AND 1", name="retrieval_score_threshold"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    theme: Mapped[str] = mapped_column(String(10), server_default=Theme.SYSTEM.value)
    retrieval_top_k: Mapped[int | None] = mapped_column(Integer)
    retrieval_score_threshold: Mapped[float | None] = mapped_column(Float)
