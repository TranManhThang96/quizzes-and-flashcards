from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import get_db
from app.models import User, UserSession
from app.security import hash_token

SESSION_COOKIE = "session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# A session is only re-written when it would gain more than this, so reading
# the app does not cause a database write on every request.
RENEW_AFTER = timedelta(hours=1)


def utcnow() -> datetime:
    return datetime.now(UTC)


async def require_origin(request: Request) -> None:
    """CSRF guard: every write request must carry our own Origin."""
    if request.method in SAFE_METHODS:
        return
    if request.headers.get("origin") != request.app.state.settings.app_origin:
        raise HTTPException(status_code=403, detail="Origin not allowed")


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_days * 86400,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


async def get_current_user(
    request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> User:
    settings: Settings = request.app.state.settings
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    now = utcnow()
    row = (
        await db.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(
                UserSession.token_hash == hash_token(token),
                UserSession.expires_at > now,
            )
        )
    ).first()
    if row is None or not row.User.is_active:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session_row, user = row.UserSession, row.User
    new_expiry = now + timedelta(days=settings.session_ttl_days)
    if new_expiry - session_row.expires_at > RENEW_AFTER:
        session_row.expires_at = new_expiry
        await db.commit()
        set_session_cookie(response, token, settings)
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user
