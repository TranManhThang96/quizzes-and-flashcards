from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Exam(Base):
    __tablename__ = "exams"
    __table_args__ = (
        CheckConstraint("status in ('draft', 'published', 'archived')", name="status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(
        String(16), default="draft", server_default="draft"
    )
    build_config: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ExamItem(Base):
    __tablename__ = "exam_items"
    __table_args__ = (UniqueConstraint("exam_id", "position", name="position"),)

    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), primary_key=True
    )
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer)


class ExamAttempt(Base):
    __tablename__ = "exam_attempts"
    __table_args__ = (
        Index("ix_exam_attempts_user_exam", "user_id", "exam_id"),
        # At most one unfinished attempt per user and exam, enforced by the DB
        # so two concurrent POST /attempts cannot both insert.
        Index(
            "uq_exam_attempts_open",
            "user_id",
            "exam_id",
            unique=True,
            postgresql_where=text("submitted_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AttemptAnswer(Base):
    __tablename__ = "attempt_answers"

    attempt_id: Mapped[int] = mapped_column(
        ForeignKey("exam_attempts.id", ondelete="CASCADE"), primary_key=True
    )
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    answer: Mapped[str | None] = mapped_column(JSONB, nullable=True)
    correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Copied from the item at submit time. Serving the live item would let a
    # later edit rewrite an old attempt's displayed answer.
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
