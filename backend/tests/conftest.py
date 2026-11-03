import os
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import psycopg
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.engine import make_url

from app.config import Settings
from app.main import create_app
from app.models import User
from app.users import create_user

TEST_DB_URL = os.environ.get(
    "QUIZZ_TEST_DATABASE_URL",
    "postgresql+psycopg://quizz:test@127.0.0.1:55432/quizz_test",
)
ORIGIN = "https://quizz.test"
BACKEND_DIR = Path(__file__).resolve().parents[1]


def _libpq_url() -> str:
    return TEST_DB_URL.replace("+psycopg", "", 1)


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    """Recreate the schema from the real migrations, once per test session."""
    database = make_url(TEST_DB_URL).database or ""
    # This fixture runs `drop schema public cascade`. Refuse anything that is
    # not clearly a throwaway database so a wrong env var cannot wipe real data.
    if not database.endswith("_test"):
        pytest.exit(
            f"Refusing to run: test database name must end with '_test', got '{database}'",
            returncode=2,
        )
    with psycopg.connect(_libpq_url(), autocommit=True) as conn:
        conn.execute("drop schema public cascade")
        conn.execute("create schema public")
    os.environ["QUIZZ_DATABASE_URL"] = TEST_DB_URL
    command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")


@pytest.fixture(autouse=True)
def clean_db(migrated_database: None) -> None:
    """Empty every table except alembic_version before each test."""
    with psycopg.connect(_libpq_url(), autocommit=True) as conn:
        tables = [
            row[0]
            for row in conn.execute(
                "select quote_ident(tablename) from pg_tables "
                "where schemaname = 'public' and tablename <> 'alembic_version'"
            )
        ]
        if tables:
            conn.execute(f"truncate {', '.join(tables)} restart identity cascade")


@pytest.fixture
def settings() -> Settings:
    return Settings(database_url=TEST_DB_URL, app_origin=ORIGIN, environment="prod")


@pytest_asyncio.fixture
async def app(settings: Settings, clean_db: None) -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    yield application
    await application.state.engine.dispose()


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url=ORIGIN,
        headers={"origin": ORIGIN},
    ) as c:
        yield c


@pytest_asyncio.fixture
async def other_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """A second browser: separate cookie jar, same app."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url=ORIGIN,
        headers={"origin": ORIGIN},
    ) as c:
        yield c


@pytest_asyncio.fixture
async def make_user(app: FastAPI) -> Callable[..., Awaitable[User]]:
    async def _make(
        username: str = "alice", password: str = "correct-horse", role: str = "user"
    ) -> User:
        async with app.state.sessionmaker() as session:
            user = await create_user(
                session, username=username, password=password, role=role
            )
            await session.commit()
            return user

    return _make


async def login(client: AsyncClient, username: str, password: str) -> Response:
    return await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
