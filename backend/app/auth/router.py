import asyncio
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import (
    SESSION_COOKIE,
    get_current_user,
    set_session_cookie,
    utcnow,
)
from app.config import Settings
from app.db import get_db
from app.models import LoginAttempt, User, UserSession
from app.security import (
    hash_token,
    new_session_token,
    verify_dummy,
    verify_password,
)
from app.users import MAX_PASSWORD_LENGTH, normalize_username

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)

    @field_validator("username")
    @classmethod
    def _normalise_username(cls, value: str) -> str:
        # Shared with create-admin and the admin API, so only names that can
        # exist ever reach a query. This also keeps NUL bytes (rejected by
        # PostgreSQL text) out of the database.
        return normalize_username(value)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str


async def _recent_failures(db: AsyncSession, column, value, since) -> int:
    stmt = (
        select(func.count())
        .select_from(LoginAttempt)
        .where(column == value, LoginAttempt.at > since)
    )
    return (await db.execute(stmt)).scalar_one()


@router.post("/login", response_model=UserOut)
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> User:
    settings: Settings = request.app.state.settings
    username = body.username
    # login_attempts.ip is varchar(45): longer than any IPv6 text form. Cut it
    # so an odd proxy chain can never turn a failed login into a 500.
    ip = (request.client.host if request.client else "unknown")[:45]
    now = utcnow()
    since = now - timedelta(minutes=settings.login_window_minutes)

    # Locked out: refuse even the correct password, otherwise an attacker
    # simply keeps guessing. Blocked attempts are not recorded, so the lock
    # lifts one window after the last recorded failure.
    by_username = await _recent_failures(db, LoginAttempt.username, username, since)
    by_ip = await _recent_failures(db, LoginAttempt.ip, ip, since)
    if max(by_username, by_ip) >= settings.login_max_failures:
        raise HTTPException(
            status_code=429,
            detail="Too many failed attempts. Try again later.",
            headers={"Retry-After": str(settings.login_window_minutes * 60)},
        )

    # Housekeeping on every evaluated attempt, so neither table grows without
    # bound, even while every attempt fails. Committed by either branch below.
    await db.execute(
        delete(LoginAttempt).where(LoginAttempt.at < now - timedelta(days=1))
    )
    await db.execute(delete(UserSession).where(UserSession.expires_at < now))

    user = (
        await db.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        await asyncio.to_thread(verify_dummy, body.password)
        authenticated = False
    else:
        authenticated = await asyncio.to_thread(
            verify_password, body.password, user.password_hash
        )

    if not authenticated or user is None:
        db.add(LoginAttempt(username=username, ip=ip, at=now))
        await db.commit()
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token, token_hash = new_session_token()
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=now + timedelta(days=settings.session_ttl_days),
        )
    )
    await db.commit()
    set_session_cookie(response, token, settings)
    return user


@router.post("/logout", status_code=204)
async def logout(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    settings: Settings = request.app.state.settings
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await db.execute(
            delete(UserSession).where(UserSession.token_hash == hash_token(token))
        )
        await db.commit()
    response = Response(status_code=204)
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    return response


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> User:
    return user
