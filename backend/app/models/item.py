from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (
        CheckConstraint("kind in ('flashcard', 'vocab', 'question')", name="kind"),
        CheckConstraint("level in ('easy', 'medium', 'hard', 'expert')", name="level"),
        CheckConstraint("status in ('draft', 'published', 'archived')", name="status"),
        UniqueConstraint("topic_id", "content_hash"),
        Index("ix_items_topic_status_level", "topic_id", "status", "level"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"))
    level: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(
        String(16), default="draft", server_default="draft"
    )
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
