import asyncio
import re

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.security import hash_password

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
USERNAME_PATTERN = r"^[a-z0-9][a-z0-9_.-]{2,63}$"
USERNAME_RULE = (
    "Username must be 3-64 characters: lowercase letters, digits, '_', '.', '-'"
)


class UsernameTaken(Exception):
    pass


def normalize_username(value: str) -> str:
    """Trim and lowercase, then enforce the username rule. Raises ValueError.

    The one place the rule lives: the CLI, the login form and the admin API
    all call it, so a stored name is always one that can be typed at login.
    """
    username = value.strip().lower()
    if not re.fullmatch(USERNAME_PATTERN, username):
        raise ValueError(USERNAME_RULE)
    return username


async def create_user(
    session: AsyncSession, *, username: str, password: str, role: str = "user"
) -> User:
    """Insert a user. The caller commits. Raises UsernameTaken on a duplicate."""
    password_hash = await asyncio.to_thread(hash_password, password)
    user = User(username=username, password_hash=password_hash, role=role)
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise UsernameTaken(username) from exc
    return user
