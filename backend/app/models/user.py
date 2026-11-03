from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role in ('admin', 'user')", name="role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="user", server_default="user")
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    daily_new_limit: Mapped[int] = mapped_column(default=10, server_default="10")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class LoginAttempt(Base):
    """One row per FAILED login. Used for lockout; pruned after a day."""

    __tablename__ = "login_attempts"
    __table_args__ = (
        Index("ix_login_attempts_username_at", "username", "at"),
        Index("ix_login_attempts_ip_at", "ip", "at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64))
    ip: Mapped[str] = mapped_column(String(45))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
