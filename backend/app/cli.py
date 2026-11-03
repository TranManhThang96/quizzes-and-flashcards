"""Operator commands. Run inside the api container:

docker compose exec api python -m app.cli create-admin --username root
"""

import argparse
import asyncio
import getpass
import os
import sys

from app.config import Settings
from app.db import make_engine, make_sessionmaker
from app.users import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    UsernameTaken,
    create_user,
    normalize_username,
)


async def create_admin(settings: Settings, username: str, password: str) -> None:
    engine = make_engine(settings.database_url)
    try:
        async with make_sessionmaker(engine)() as session:
            await create_user(
                session, username=username, password=password, role="admin"
            )
            await session.commit()
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin", help="Create an administrator account")
    admin.add_argument("--username", required=True)
    args = parser.parse_args(argv)

    # Same normalisation the login endpoint applies, so the stored name is
    # the one the admin can actually type at the login form.
    try:
        username = normalize_username(args.username)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1

    password = os.environ.get("QUIZZ_ADMIN_PASSWORD") or getpass.getpass("Password: ")
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        print(
            f"Password must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters",
            file=sys.stderr,
        )
        return 1
    try:
        asyncio.run(create_admin(Settings(), username, password))
    except UsernameTaken:
        print(f"Username '{username}' already exists", file=sys.stderr)
        return 1
    print(f"Created admin '{username}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
