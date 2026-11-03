import os
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from app.config import Settings

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
