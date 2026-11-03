import asyncio
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import require_admin
from app.db import get_db
from app.models import User, UserSession
from app.security import hash_password
from app.users import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    UsernameTaken,
    create_user,
    normalize_username,
)

router = APIRouter(
    prefix="/api/admin/users", tags=["admin"], dependencies=[Depends(require_admin)]
)


class UserCreate(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(
        min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH
    )
    role: Literal["admin", "user"] = "user"

    @field_validator("username")
    @classmethod
    def _normalise_username(cls, value: str) -> str:
        return normalize_username(value)


class UserPatch(BaseModel):
    is_active: bool | None = None
    password: str | None = Field(
        default=None, min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH
    )
    daily_new_limit: int | None = Field(default=None, ge=0, le=200)


class UserAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str
    is_active: bool
    daily_new_limit: int
    created_at: datetime


@router.get("", response_model=list[UserAdminOut])
async def list_users(db: AsyncSession = Depends(get_db)) -> list[User]:
    return list((await db.execute(select(User).order_by(User.id))).scalars())


@router.post("", response_model=UserAdminOut, status_code=201)
async def add_user(body: UserCreate, db: AsyncSession = Depends(get_db)) -> User:
    try:
        user = await create_user(
            db, username=body.username, password=body.password, role=body.role
        )
    except UsernameTaken as exc:
        raise HTTPException(status_code=409, detail="Username already exists") from exc
    await db.commit()
    return user


@router.patch("/{user_id}", response_model=UserAdminOut)
async def patch_user(
    user_id: int,
    body: UserPatch,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id and body.is_active is False:
        raise HTTPException(status_code=409, detail="You cannot deactivate yourself")

    revoke_sessions = False
    if body.is_active is not None:
        user.is_active = body.is_active
        revoke_sessions = revoke_sessions or not body.is_active
    if body.password is not None:
        user.password_hash = await asyncio.to_thread(hash_password, body.password)
        revoke_sessions = True
    if body.daily_new_limit is not None:
        user.daily_new_limit = body.daily_new_limit
    if revoke_sessions:
        await db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    await db.commit()
    return user
