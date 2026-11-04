import os
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.engine import make_url

from app.config import Settings
from app.content import content_hash, parse_content
from app.main import create_app
from app.models import GenerationJob, Item, Source, Topic, User
from app.text import slugify
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


@pytest_asyncio.fixture
async def make_topic(app: FastAPI) -> Callable[..., Awaitable[Topic]]:
    async def _make(name: str = "Topic") -> Topic:
        async with app.state.sessionmaker() as session:
            topic = Topic(name=name, slug=f"{slugify(name)}-{uuid4().hex[:8]}")
            session.add(topic)
            await session.commit()
            return topic

    return _make


@pytest_asyncio.fixture
async def make_item(app: FastAPI) -> Callable[..., Awaitable[Item]]:
    async def _make(
        topic_id: int,
        *,
        kind: str = "flashcard",
        level: str = "easy",
        content: dict | None = None,
        status: str = "draft",
    ) -> Item:
        if content is None:
            # Unique per call: item content is unique per topic, so identical
            # defaults would collide as soon as a test creates two items.
            token = uuid4().hex[:8]
            content = {
                "flashcard": {"front": f"Front {token}", "back": "Back"},
                "vocab": {
                    "word": f"word-{token}",
                    "part_of_speech": "noun",
                    "meaning": "nghĩa",
                    "ipa": "",
                    "examples": [],
                },
                "question": {
                    "type": "mcq",
                    "prompt": f"2 + 2? ({token})",
                    "options": ["3", "4"],
                    "answer": "4",
                    "explanation": "Bốn",
                },
            }[kind]
        parsed = parse_content(kind, content)
        async with app.state.sessionmaker() as session:
            item = Item(
                topic_id=topic_id,
                kind=kind,
                level=level,
                content=parsed.model_dump(),
                content_hash=content_hash(kind, parsed),
                status=status,
            )
            session.add(item)
            await session.commit()
            return item

    return _make


@pytest_asyncio.fixture
async def make_source(app: FastAPI) -> Callable[..., Awaitable[Source]]:
    async def _make(
        *,
        text: str = "Lãi kép là lãi tính trên cả gốc lẫn lãi đã cộng dồn.",
        kind: str = "text",
        url: str | None = None,
        user_id: int | None = None,
    ) -> Source:
        async with app.state.sessionmaker() as session:
            if user_id is None:
                # Nguồn luôn có người tạo; tạo user riêng để test không phụ
                # thuộc vào việc đã đăng nhập hay chưa.
                user = await create_user(
                    session,
                    username=f"author-{uuid4().hex[:8]}",
                    password="author-password",
                    role="admin",
                )
                await session.flush()
                user_id = user.id
            source = Source(kind=kind, text=text, url=url, created_by=user_id)
            session.add(source)
            await session.commit()
            return source

    return _make


@pytest_asyncio.fixture
async def make_job(app: FastAPI) -> Callable[..., Awaitable[GenerationJob]]:
    async def _make(
        *,
        source_id: int,
        topic_id: int,
        params: dict | None = None,
        status: str = "queued",
    ) -> GenerationJob:
        async with app.state.sessionmaker() as session:
            user = await create_user(
                session,
                username=f"job-{uuid4().hex[:8]}",
                password="job-password",
                role="admin",
            )
            await session.flush()
            job = GenerationJob(
                source_id=source_id,
                topic_id=topic_id,
                params=params
                or {"kind": "flashcard", "levels": [{"level": "easy", "count": 1}]},
                status=status,
                created_by=user.id,
            )
            session.add(job)
            await session.commit()
            return job

    return _make
