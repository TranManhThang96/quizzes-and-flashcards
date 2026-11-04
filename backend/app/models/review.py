from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ReviewState(Base):
    __tablename__ = "review_states"
    __table_args__ = (
        CheckConstraint("ease >= 1.3", name="ease"),
        Index("ix_review_states_user_due", "user_id", "due_at"),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    interval_days: Mapped[int] = mapped_column(default=0, server_default="0")
    ease: Mapped[float] = mapped_column(default=2.5, server_default="2.5")
    reps: Mapped[int] = mapped_column(default=0, server_default="0")
    lapses: Mapped[int] = mapped_column(default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ReviewLog(Base):
    __tablename__ = "review_logs"
    __table_args__ = (
        CheckConstraint("grade in ('again', 'hard', 'good', 'easy')", name="grade"),
        CheckConstraint("context in ('study', 'exam', 'wrong_queue')", name="context"),
        Index("ix_review_logs_user_at", "user_id", "at"),
        Index("ix_review_logs_item_at", "item_id", "at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    grade: Mapped[str] = mapped_column(String(8))
    correct: Mapped[bool] = mapped_column(Boolean)
    context: Mapped[str] = mapped_column(String(16))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
