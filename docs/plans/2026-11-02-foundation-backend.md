# Nền tảng backend: kế hoạch triển khai

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dựng backend FastAPI + PostgreSQL chạy bằng Docker Compose, có đăng nhập user/password, admin quản lý tài khoản, kèm nginx snippet, backup và `docs/` làm SSOT.

**Architecture:** Một app FastAPI async (SQLAlchemy 2 + psycopg) phục vụ `/api`. Phiên đăng nhập là token ngẫu nhiên, chỉ lưu hash trong bảng `sessions`, gửi qua cookie. Compose chạy `db` và `api`, cổng `api` chỉ bind `127.0.0.1`, nginx trên host lo TLS và proxy.

**Tech Stack:** Python 3.12, FastAPI 0.162.0, SQLAlchemy 2.1.6, Alembic 1.20.1, psycopg 3.3.6, pwdlib (Argon2) 0.3.1, pytest, ruff, mypy, Docker Compose, PostgreSQL 17.11, nginx 1.29.

**Spec:** `docs/specs/2026-11-02-quizzes-and-flashcards-design.md` (mục 4, 5, 10, 12 và các bảng `users`, `sessions`, `login_attempts` của mục 6).

## Phạm vi và các plan tiếp theo

Spec gồm nhiều subsystem độc lập. Mỗi plan phải ra phần mềm chạy và test được.

| Plan | Nội dung | Spec |
|---|---|---|
| 1 (file này) | Nền tảng backend, đăng nhập, quản lý tài khoản, deploy `db` + `api`, backup, docs | 4, 5, 10, 12 |
| 2 | Chủ đề, item, SRS, ôn tập, đề kiểm tra | 6, 7, 8 |
| 3 | Pipeline sinh nội dung bằng AI và container `worker` | 9 |
| 4 | SPA React, PWA và container `web` | 11 |

Plan 2 đến 4 chưa viết. Mỗi plan được viết sau khi plan trước xong, để dùng đúng interface thực tế. Plan này chỉ có hai container (`db`, `api`). `web` và `worker` thuộc plan 3 và 4.

Spec mục 5 yêu cầu chuyển `task.md` thành `docs/product/vision.md`. Việc này hoãn lại cho tới khi chủ dự án commit `task.md`, `docs/specs/` và `docs/plans/` (xem Task 1 bước 1). Vì vậy `docs/README.md` trong plan này không link tới các file chưa được theo dõi đó.

## Global Constraints

- Python `>=3.12`, FastAPI, uvicorn, `uv`.
- PostgreSQL, SQLAlchemy 2 async + Alembic, driver `psycopg` (cài `psycopg[binary]`), `sqlalchemy[asyncio]`.
- Docker Compose trên VPS, nginx sẵn có trên host làm reverse proxy. Cổng của `api` chỉ bind `127.0.0.1`.
- Bí mật nằm trong file env trên VPS, không đóng vào image.
- Mật khẩu băm bằng Argon2 (`pwdlib`). Username 3 đến 64 ký tự `[a-z0-9_.-]`, chữ thường. Mật khẩu 8 đến 128 ký tự.
- Phiên: token ngẫu nhiên, chỉ lưu hash, cookie `HttpOnly`, `Secure`, `SameSite=Lax`, hết hạn sau 30 ngày không dùng.
- Quá 5 lần đăng nhập sai trong 15 phút cho cùng username hoặc IP thì tạm khóa.
- Mọi request ghi (POST, PUT, PATCH, DELETE) phải có header `Origin` khớp domain.
- `/api/admin/*` yêu cầu role `admin`.
- Production tắt docs và `/openapi.json`. Ở dev chúng nằm dưới `/api/docs` và `/api/openapi.json`.
- Phiên bản gói được pin chính xác. Test chạy trên Postgres thật, không dùng SQLite.
- Thay đổi hành vi, schema hay deploy thì cập nhật `docs/` trong cùng commit.

## Review Focus

Năm điều spec ngầm đòi hỏi nhưng dễ bị bỏ sót, theo thứ tự dễ gây lỗi nhất. Mỗi dòng đã có test hoặc bước kiểm tra ở task chủ.

1. Username lạ ở form đăng nhập (byte NUL, khoảng trắng, quá dài) phải trả 422, không phải 500. Test ở Task 3.
2. Mật khẩu quá dài phải bị từ chối trước khi băm, nếu không một request nhỏ cũng tốn CPU Argon2. Test ở Task 3.
3. Địa chỉ client dài bất thường (chuỗi proxy lạ) không được làm hỏng ghi nhật ký đăng nhập sai. Test ở Task 3.
4. Hai request tạo cùng một username đồng thời: đúng một thành công, một trả 409, session vẫn dùng được. Test ở Task 3 (service) và Task 4 (HTTP).
5. Chạy test với biến môi trường trỏ nhầm vào DB thật không được xóa dữ liệu. `conftest.py` từ chối DB có tên không kết thúc bằng `_test`. Kiểm tra tay ở Task 1.

## Cấu trúc file

| File | Trách nhiệm |
|---|---|
| `backend/pyproject.toml` | Phụ thuộc pin chính xác, cấu hình pytest, ruff, mypy |
| `backend/app/config.py` | `Settings` đọc từ biến `QUIZZ_*` |
| `backend/app/db.py` | Engine, sessionmaker, dependency `get_db` |
| `backend/app/models/` | `Base` (đặt tên constraint cố định) và model `User`, `UserSession`, `LoginAttempt` |
| `backend/alembic/` | Migration, `env.py` lấy URL từ môi trường |
| `backend/app/security.py` | Băm mật khẩu, tạo và băm token phiên |
| `backend/app/users.py` | `create_user` dùng chung cho CLI và API, hằng số ràng buộc |
| `backend/app/cli.py` | `create-admin` |
| `backend/app/auth/deps.py` | Origin guard, đọc phiên, gia hạn, `require_admin`, cookie |
| `backend/app/auth/router.py` | `/api/auth/login`, `logout`, `me` |
| `backend/app/admin/users.py` | `/api/admin/users` |
| `backend/app/main.py` | `create_app` |
| `backend/scripts/export_openapi.py` | Xuất hợp đồng API vào `docs/architecture/` |
| `deploy/` | Compose, nginx snippet, backup |
| `docs/` | SSOT |

---

### Task 1: Khung dự án, cấu hình, model và migration đầu tiên

**Files:**
- Create: `.gitignore`, `.pre-commit-config.yaml`
- Create: `backend/pyproject.toml`, `backend/uv.lock` (do `uv sync` sinh ra)
- Create: `backend/app/__init__.py`, `config.py`, `db.py`, `models/__init__.py`, `models/base.py`, `models/user.py`
- Create: `backend/alembic.ini`, `backend/alembic/` (sinh bằng `alembic init`), `backend/alembic/env.py`, `backend/alembic/versions/0001_users_sessions_login_attempts.py`
- Test: `backend/tests/__init__.py`, `conftest.py`, `test_config.py`, `test_migrations.py`

**Interfaces:**
- Consumes: không.
- Produces:
  - `app.config.Settings` với các trường `database_url: str`, `app_origin: str`, `environment: Literal["dev","prod"]`, `cookie_secure: bool`, `session_ttl_days: int`, `login_max_failures: int`, `login_window_minutes: int`. Biến môi trường có tiền tố `QUIZZ_`.
  - `app.db.make_engine(url) -> AsyncEngine`, `make_sessionmaker(engine) -> async_sessionmaker[AsyncSession]`, `get_db(request)` (đọc `request.app.state.sessionmaker`).
  - `app.models.Base`, `User`, `UserSession`, `LoginAttempt`.
  - Test: hằng `TEST_DB_URL`, `ORIGIN`, `BACKEND_DIR` và fixture `settings` trong `tests/conftest.py`.

- [ ] **Bước 1: Tạo nhánh và `.gitignore`**

Repo chưa có commit nào, và `docs/specs/`, `docs/plans/`, `task.md` đang là file chưa theo dõi. Chủ dự án đã nói chưa commit chúng, nên **không** `git add` các file đó. Mọi lệnh `git add` trong plan này liệt kê file cụ thể.

Chạy:

```bash
git switch -c feat/foundation
```

Kỳ vọng: dòng `Switched to a new branch 'feat/foundation'`.

Tạo `.gitignore`:

```gitignore
# secrets and local config
deploy/.env

# python
.venv/
__pycache__/
*.pyc
.pytest_cache/
.mypy_cache/
.ruff_cache/

# web (added by the frontend plan)
node_modules/
web/dist/
```

- [ ] **Bước 2: Tạo `backend/pyproject.toml` và cài phụ thuộc**

Tạo `backend/pyproject.toml`:

```toml
[project]
name = "quizz-backend"
version = "0.1.0"
description = "Quizzes and flashcards API"
requires-python = ">=3.12"
dependencies = [
    "fastapi==0.162.0",
    "uvicorn[standard]==0.54.0",
    "sqlalchemy[asyncio]==2.1.6",
    "alembic==1.20.1",
    "psycopg[binary]==3.3.6",
    "pydantic==2.14.2",
    "pydantic-settings==2.16.2",
    "pwdlib[argon2]==0.3.1",
]

[dependency-groups]
dev = [
    "httpx==0.28.1",
    "mypy==2.4.1",
    "pre-commit==4.7.0",
    "pytest==9.2.0",
    "pytest-asyncio==1.4.1.post1",
    "ruff==0.17.3",
]

[tool.uv]
package = false

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
pythonpath = ["."]
testpaths = ["tests"]

[tool.mypy]
python_version = "3.12"
plugins = ["pydantic.mypy"]
ignore_missing_imports = true
check_untyped_defs = true
warn_redundant_casts = true
warn_unused_ignores = true
files = ["app"]

[tool.ruff]
target-version = "py312"
line-length = 88
extend-exclude = ["alembic/versions"]

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B", "SIM"]
ignore = ["E501", "B008"]

[tool.ruff.lint.isort]
known-first-party = ["app"]
known-third-party = ["alembic"]
```

Chạy:

```bash
cd backend && uv sync
```

Kỳ vọng: kết thúc không lỗi, sinh `backend/uv.lock` và `backend/.venv`.

- [ ] **Bước 3: Khởi động Postgres dùng cho test**

Dùng tmpfs nên dữ liệu mất khi xóa container. Cổng `55432` chỉ mở trên loopback.

Chạy:

```bash
docker run -d --name quizz-testdb --tmpfs /var/lib/postgresql/data \
  -e POSTGRES_USER=quizz -e POSTGRES_PASSWORD=test -e POSTGRES_DB=quizz_test \
  -p 127.0.0.1:55432:5432 postgres:17.11-alpine
for i in $(seq 1 30); do docker exec quizz-testdb pg_isready -U quizz -d quizz_test && break; sleep 1; done
```

Kỳ vọng: dòng `accepting connections`. Nếu cổng 55432 đã bị chiếm, đổi cổng và đặt `QUIZZ_TEST_DATABASE_URL` cho khớp.

- [ ] **Bước 4: Viết test (chưa có code)**

Tạo `backend/tests/__init__.py`:

```python
```

Tạo `backend/tests/conftest.py`:

```python
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
```

Tạo `backend/tests/test_config.py`:

```python
from app.config import Settings


def test_origin_setting_ignores_a_trailing_slash():
    # A trailing slash would never match a browser's Origin header and every
    # write request would be rejected with 403.
    settings = Settings(
        database_url="postgresql+psycopg://u:p@localhost/db",
        app_origin="https://quizz.test/",
    )

    assert settings.app_origin == "https://quizz.test"
```

Tạo `backend/tests/test_migrations.py`:

```python
from alembic import command
from alembic.config import Config

from tests.conftest import BACKEND_DIR


def test_migrations_match_the_models():
    # Fails with "New upgrade operations detected" when a model changed
    # without a new migration.
    command.check(Config(str(BACKEND_DIR / "alembic.ini")))
```

- [ ] **Bước 5: Chạy test, phải fail**

Chạy:

```bash
cd backend && uv run pytest -q --no-header -p no:cacheprovider -x
```

Kỳ vọng: FAIL ngay lúc nạp `conftest.py` với `ModuleNotFoundError: No module named 'app'`.

- [ ] **Bước 6: Viết cấu hình, DB và model**

Tạo `backend/app/__init__.py`:

```python
```

Tạo `backend/app/config.py`:

```python
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every field is read from a QUIZZ_* env variable."""

    model_config = SettingsConfigDict(env_prefix="QUIZZ_")

    database_url: str
    app_origin: str = "https://quizz.thangtm.io.vn"
    environment: Literal["dev", "prod"] = "dev"
    cookie_secure: bool = True
    session_ttl_days: int = Field(default=30, ge=1)
    login_max_failures: int = Field(default=5, ge=1)
    login_window_minutes: int = Field(default=15, ge=1)

    @field_validator("app_origin")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        # Browsers send Origin without a trailing slash; a configured value
        # with one would reject every write request.
        return value.rstrip("/")
```

Tạo `backend/app/db.py`:

```python
from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def make_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=True)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session
```

Tạo `backend/app/models/base.py`:

```python
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Deterministic constraint names keep Alembic migrations and error handling
# (e.g. matching "uq_users_username") stable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
```

Tạo `backend/app/models/user.py`:

```python
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
```

Tạo `backend/app/models/__init__.py`:

```python
from app.models.base import Base
from app.models.user import LoginAttempt, User, UserSession

__all__ = ["Base", "LoginAttempt", "User", "UserSession"]
```

- [ ] **Bước 7: Tạo Alembic và migration đầu tiên**

Sinh khung bằng `alembic init`, rồi thay `env.py` (lấy URL từ `QUIZZ_DATABASE_URL`, gắn metadata của app) và thêm migration. Migration dưới đây là đầu ra của `alembic revision --autogenerate` với các model ở bước 6.

Chạy:

```bash
cd backend && uv run alembic init -t async alembic
```

Kỳ vọng: sinh `alembic.ini`, `alembic/README`, `alembic/script.py.mako`, `alembic/env.py`, `alembic/versions/`.

Ghi đè `backend/alembic/env.py`:

```python
import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.models import Base

config = context.config
if config.config_file_name is not None:
    # Keep loggers the app created before migrations run (tests run them
    # in-process); the default would silently disable them.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

# The URL comes from the environment so no credentials live in alembic.ini.
# "%" is doubled because ConfigParser treats it as interpolation syntax.
config.set_main_option(
    "sqlalchemy.url", os.environ["QUIZZ_DATABASE_URL"].replace("%", "%%")
)


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

Tạo `backend/alembic/versions/0001_users_sessions_login_attempts.py`:

```python
"""users sessions login attempts

Revision ID: 0001
Revises: 
Create Date: 2026-11-02 22:25:31.798062

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('login_attempts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('ip', sa.String(length=45), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_login_attempts'))
    )
    op.create_index('ix_login_attempts_ip_at', 'login_attempts', ['ip', 'at'], unique=False)
    op.create_index('ix_login_attempts_username_at', 'login_attempts', ['username', 'at'], unique=False)
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=16), server_default='user', nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('daily_new_limit', sa.Integer(), server_default='10', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role in ('admin', 'user')", name=op.f('ck_users_role')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('username', name=op.f('uq_users_username'))
    )
    op.create_table('sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_sessions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sessions')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_sessions_token_hash'))
    )
    op.create_index(op.f('ix_sessions_user_id'), 'sessions', ['user_id'], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_sessions_user_id'), table_name='sessions')
    op.drop_table('sessions')
    op.drop_table('users')
    op.drop_index('ix_login_attempts_username_at', table_name='login_attempts')
    op.drop_index('ix_login_attempts_ip_at', table_name='login_attempts')
    op.drop_table('login_attempts')
    # ### end Alembic commands ###
```

- [ ] **Bước 8: Chạy test, lint và kiểm tra kiểu, phải pass**

Chạy:

```bash
cd backend
uv run ruff check --fix . && uv run ruff format .
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest -q --no-header -p no:cacheprovider
```

Kỳ vọng: `All checks passed!`, `Success: no issues found in 6 source files`, `2 passed`.

- [ ] **Bước 9: Kiểm tra tay: chặn chạy test lên DB không phải `_test` (Review Focus 5)**

Chạy:

```bash
cd backend
QUIZZ_TEST_DATABASE_URL="postgresql+psycopg://quizz:test@127.0.0.1:55432/quizz" uv run pytest -q --no-header -p no:cacheprovider; echo "exit=$?"
```

Kỳ vọng: dòng `Refusing to run: test database name must end with '_test', got 'quizz'` và `exit=2`. DB `quizz` không bị đụng tới (container test không có DB này, nên lệnh chỉ chứng minh guard chạy trước khi kết nối).

- [ ] **Bước 10: Thêm pre-commit và chạy**

Tạo `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: local
    hooks:
      - id: ruff-check
        name: ruff check
        entry: uv run --project backend ruff check backend
        language: system
        pass_filenames: false
        files: ^backend/
      - id: ruff-format
        name: ruff format --check
        entry: uv run --project backend ruff format --check backend
        language: system
        pass_filenames: false
        files: ^backend/
      - id: mypy
        name: mypy
        entry: bash -c 'cd backend && uv run mypy'
        language: system
        pass_filenames: false
        files: ^backend/
```

Chạy:

```bash
git add .gitignore .pre-commit-config.yaml backend/pyproject.toml backend/uv.lock backend/alembic.ini backend/alembic backend/app backend/tests
uv run --project backend pre-commit install
uv run --project backend pre-commit run --all-files
```

Kỳ vọng: `pre-commit installed at .git/hooks/pre-commit`; ba hook `ruff check`, `ruff format --check`, `mypy` đều `Passed`. Từ đây mỗi `git commit` tự chạy các hook này.

- [ ] **Bước 11: Commit**

```bash
git commit -m "feat(backend): project scaffold, settings, user models and first migration"
```

### Task 2: Băm mật khẩu, tạo user dùng chung và CLI `create-admin`

**Files:**
- Create: `backend/app/security.py`, `backend/app/users.py`, `backend/app/cli.py`
- Test: `backend/tests/test_cli.py`

**Interfaces:**
- Consumes: `app.models.User`, `app.config.Settings`, `app.db.make_engine`, `make_sessionmaker` (Task 1).
- Produces:
  - `app.security.hash_password(password: str) -> str`, `verify_password(password: str, password_hash: str) -> bool`, `verify_dummy(password: str) -> None` (băm giả để thời gian không lộ username tồn tại), `hash_token(token: str) -> str`, `new_session_token() -> tuple[str, str]` (token cho cookie, sha256 hex để lưu).
  - `app.users.create_user(session, *, username: str, password: str, role: str = "user") -> User`: `flush`, caller `commit`. Ném `UsernameTaken` khi trùng, đã `rollback` nên session dùng tiếp được.
  - Hằng `MIN_PASSWORD_LENGTH = 8`, `MAX_PASSWORD_LENGTH = 128`, `USERNAME_PATTERN`, `USERNAME_RULE` (thông báo lỗi).
  - `app.users.normalize_username(value: str) -> str`: cắt khoảng trắng, hạ chữ thường, kiểm `USERNAME_PATTERN`, ném `ValueError(USERNAME_RULE)`. Là chỗ duy nhất áp quy tắc username; CLI, `LoginIn` (Task 3) và `UserCreate` (Task 4) đều gọi nó.
  - Lệnh `python -m app.cli create-admin --username NAME`, mật khẩu lấy từ `QUIZZ_ADMIN_PASSWORD` hoặc hỏi bằng `getpass`.

- [ ] **Bước 1: Viết test CLI**

Tạo `backend/tests/test_cli.py`:

```python
import psycopg

from app.cli import main
from tests.conftest import TEST_DB_URL


def _rows() -> list[tuple[str, str]]:
    with psycopg.connect(TEST_DB_URL.replace("+psycopg", "", 1)) as conn:
        return conn.execute("select username, role from users order by id").fetchall()


def _env(monkeypatch, password: str = "admin-password") -> None:
    monkeypatch.setenv("QUIZZ_DATABASE_URL", TEST_DB_URL)
    monkeypatch.setenv("QUIZZ_ADMIN_PASSWORD", password)


def test_create_admin_stores_and_reports_the_normalised_username(monkeypatch, capsys):
    _env(monkeypatch)

    assert main(["create-admin", "--username", " Root "]) == 0

    assert _rows() == [("root", "admin")]
    assert "Created admin 'root'" in capsys.readouterr().out


def test_create_admin_refuses_a_duplicate_name_even_with_different_case(
    monkeypatch, capsys
):
    _env(monkeypatch)
    assert main(["create-admin", "--username", "root"]) == 0

    assert main(["create-admin", "--username", "ROOT"]) == 1

    assert "already exists" in capsys.readouterr().err
    assert _rows() == [("root", "admin")]


def test_create_admin_rejects_unusable_usernames_and_passwords(monkeypatch, capsys):
    _env(monkeypatch)
    for name in ("ab", "has space", "UPPER!", "x" * 65):
        assert main(["create-admin", "--username", name]) == 1
        assert "Username must be" in capsys.readouterr().err

    for password in ("short", "x" * 129):
        _env(monkeypatch, password)
        assert main(["create-admin", "--username", "valid"]) == 1
        assert "Password must be 8-128" in capsys.readouterr().err

    assert _rows() == []
```

- [ ] **Bước 2: Chạy, phải fail**

Chạy:

```bash
cd backend && uv run pytest -q --no-header -p no:cacheprovider -x tests/test_cli.py
```

Kỳ vọng: `ERROR tests/test_cli.py` và `Interrupted: 1 error during collection` (chưa có `app.cli`).

- [ ] **Bước 3: Viết code**

Tạo `backend/app/security.py`:

```python
import hashlib
import secrets

from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

_hasher = PasswordHash((Argon2Hasher(),))

# Verified against when a username does not exist, so an unknown user costs the
# same time as a wrong password and login timing does not reveal valid names.
_DUMMY_HASH = _hasher.hash("dummy-password-for-constant-time-check")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _hasher.verify(password, password_hash)


def verify_dummy(password: str) -> None:
    _hasher.verify(password, _DUMMY_HASH)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_session_token() -> tuple[str, str]:
    """Return (token for the cookie, sha256 hex to store in the database)."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)
```

Tạo `backend/app/users.py`:

```python
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
```

Tạo `backend/app/cli.py`:

```python
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
```

- [ ] **Bước 4: Chạy test, lint, kiểm tra kiểu**

Chạy:

```bash
cd backend
uv run ruff check --fix . && uv run ruff format .
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run pytest -q --no-header -p no:cacheprovider
```

Kỳ vọng: `Success: no issues found in 9 source files`, `5 passed`.

- [ ] **Bước 5: Commit**

```bash
git add backend/app/security.py backend/app/users.py backend/app/cli.py backend/tests/test_cli.py
git commit -m "feat(backend): password hashing, shared user creation and create-admin CLI"
```

### Task 3: Đăng nhập, phiên, khóa thử sai, Origin guard và app factory

**Files:**
- Create: `backend/app/auth/__init__.py`, `auth/deps.py`, `auth/router.py`, `backend/app/main.py`
- Modify: `backend/tests/conftest.py` (thêm fixture `app`, `client`, `other_client`, `make_user`, hàm `login`)
- Test: `backend/tests/test_app.py`, `test_auth.py`, `test_users_service.py`

**Interfaces:**
- Consumes: mọi thứ của Task 1 và Task 2.
- Produces:
  - `app.main.create_app(settings: Settings | None = None) -> FastAPI`. Gắn `app.state.settings`, `app.state.engine`, `app.state.sessionmaker`. Dependency toàn cục `require_origin`. Route `GET /api/health`.
  - `app.auth.deps`: `SESSION_COOKIE = "session"`, `utcnow() -> datetime`, `require_origin(request)`, `set_session_cookie(response, token, settings)`, `get_current_user(...) -> User`, `require_admin(...) -> User`.
  - Route `POST /api/auth/login` (body `{username, password}` trả `{id, username, role}`), `POST /api/auth/logout` (204), `GET /api/auth/me`.
  - Fixture: `app`, `client` (có sẵn header `Origin`), `other_client` (cookie jar khác), `make_user(username="alice", password="correct-horse", role="user") -> User`; hàm `login(client, username, password) -> Response`.

**Ghi chú:** `test_users_service.py` kiểm tra `create_user` của Task 2 nhưng cần fixture `app`, nên nằm ở task này.

- [ ] **Bước 1: Thay `conftest.py` bằng bản đầy đủ và viết test**

Thay toàn bộ `backend/tests/conftest.py`:

```python
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
```

Tạo `backend/tests/test_app.py`:

```python
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from tests.conftest import ORIGIN, TEST_DB_URL


async def test_health_checks_the_database(client):
    resp = await client.get("/api/health")

    assert resp.status_code == 200 and resp.json() == {"status": "ok"}


async def test_api_docs_exist_only_in_dev():
    for env, expected in (("prod", 404), ("dev", 200)):
        app = create_app(
            Settings(database_url=TEST_DB_URL, app_origin=ORIGIN, environment=env)
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as c:
            assert (await c.get("/api/openapi.json")).status_code == expected
            assert (await c.get("/api/docs")).status_code == expected
        await app.state.engine.dispose()
```

Tạo `backend/tests/test_auth.py`:

```python
from datetime import timedelta

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from app.auth.deps import utcnow
from app.models import LoginAttempt, UserSession
from tests.conftest import ORIGIN, login


async def test_login_sets_hardened_cookie_and_me_works(client, make_user):
    await make_user("alice", "correct-horse")

    resp = await login(client, "alice", "correct-horse")

    assert resp.status_code == 200
    assert resp.json() == {"id": 1, "username": "alice", "role": "user"}
    cookie = resp.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
    me = await client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["username"] == "alice"
    assert "password" not in me.text


async def test_wrong_password_and_unknown_user_are_indistinguishable(client, make_user):
    await make_user("alice", "correct-horse")

    wrong = await login(client, "alice", "nope-nope-nope")
    unknown = await login(client, "nobody", "nope-nope-nope")

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


async def test_username_is_trimmed_and_case_insensitive(client, make_user):
    await make_user("alice", "correct-horse")

    assert (await login(client, "  Alice ", "correct-horse")).status_code == 200


async def test_me_requires_a_session(client):
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_logout_invalidates_the_token_server_side(client, make_user, app):
    await make_user("alice", "correct-horse")
    await login(client, "alice", "correct-horse")
    stolen = client.cookies["session"]

    assert (await client.post("/api/auth/logout")).status_code == 204
    assert (await client.get("/api/auth/me")).status_code == 401

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url=ORIGIN,
        cookies={"session": stolen},
    ) as replay:
        assert (await replay.get("/api/auth/me")).status_code == 401


async def test_expired_session_is_rejected(client, make_user, app):
    await make_user("alice", "correct-horse")
    await login(client, "alice", "correct-horse")
    async with app.state.sessionmaker() as s:
        await s.execute(update(UserSession).values(expires_at=utcnow() - timedelta(1)))
        await s.commit()

    assert (await client.get("/api/auth/me")).status_code == 401


async def test_session_expiry_slides_forward_on_use(client, make_user, app):
    await make_user("alice", "correct-horse")
    await login(client, "alice", "correct-horse")
    soon = utcnow() + timedelta(days=1)
    async with app.state.sessionmaker() as s:
        await s.execute(update(UserSession).values(expires_at=soon))
        await s.commit()

    assert (await client.get("/api/auth/me")).status_code == 200

    async with app.state.sessionmaker() as s:
        expires = (await s.execute(select(UserSession.expires_at))).scalar_one()
    assert expires - utcnow() > timedelta(days=29)


async def test_lockout_after_repeated_failures_even_for_correct_password(
    client, make_user
):
    await make_user("alice", "correct-horse")
    for _ in range(5):
        assert (await login(client, "alice", "wrong-wrong")).status_code == 401

    locked = await login(client, "alice", "correct-horse")

    assert locked.status_code == 429
    assert locked.headers["retry-after"] == str(15 * 60)


async def test_lockout_also_applies_per_ip_across_usernames(client, make_user):
    await make_user("alice", "correct-horse")
    await make_user("bob", "correct-horse")
    for _ in range(5):
        await login(client, "alice", "wrong-wrong")

    assert (await login(client, "bob", "correct-horse")).status_code == 429


async def test_failures_older_than_the_window_do_not_lock(client, make_user, app):
    await make_user("alice", "correct-horse")
    old = utcnow() - timedelta(minutes=16)
    async with app.state.sessionmaker() as s:
        s.add_all(
            LoginAttempt(username="alice", ip="127.0.0.1", at=old) for _ in range(5)
        )
        await s.commit()

    assert (await login(client, "alice", "correct-horse")).status_code == 200


async def test_deactivated_user_cannot_log_in(client, make_user, app):
    user = await make_user("alice", "correct-horse")
    async with app.state.sessionmaker() as s:
        db_user = await s.get(type(user), user.id)
        db_user.is_active = False
        await s.commit()

    assert (await login(client, "alice", "correct-horse")).status_code == 401


async def test_writes_require_our_origin(app: FastAPI, make_user):
    await make_user("alice", "correct-horse")
    body = {"username": "alice", "password": "correct-horse"}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url=ORIGIN) as bare:
        assert (await bare.post("/api/auth/login", json=body)).status_code == 403
        evil = {"origin": "https://evil.test"}
        assert (
            await bare.post("/api/auth/login", json=body, headers=evil)
        ).status_code == 403
        # Reads never need an Origin.
        assert (await bare.get("/api/health")).status_code == 200


async def test_malformed_username_is_rejected_before_it_reaches_the_database(client):
    # PostgreSQL text cannot hold NUL; letting one through would be a 500.
    for name in ("ali\x00ce", "has space", "UPPER!", "ab", "x" * 65):
        assert (await login(client, name, "correct-horse")).status_code == 422


async def test_oversized_password_is_rejected_before_any_hashing(client, make_user):
    await make_user("alice", "correct-horse")

    assert (await login(client, "alice", "x" * 129)).status_code == 422


async def test_garbage_session_cookie_is_unauthenticated(client):
    client.cookies.set("session", "not-a-real-token")

    assert (await client.get("/api/auth/me")).status_code == 401


async def test_absurd_client_address_does_not_break_the_failure_log(app):
    # Whatever a proxy chain puts in the client address must not turn a bad
    # login into a 500 (login_attempts.ip is varchar(45)).
    transport = ASGITransport(app=app, client=("x" * 80, 1234))
    async with AsyncClient(
        transport=transport, base_url=ORIGIN, headers={"origin": ORIGIN}
    ) as c:
        assert (await login(c, "nobody", "wrong-wrong")).status_code == 401
```

Tạo `backend/tests/test_users_service.py`:

```python
import asyncio

import pytest
from sqlalchemy import func, select

from app.models import User
from app.security import verify_password
from app.users import UsernameTaken, create_user


async def test_password_is_stored_as_an_argon2_hash(app):
    async with app.state.sessionmaker() as s:
        user = await create_user(s, username="alice", password="correct-horse")
        await s.commit()

    assert user.password_hash.startswith("$argon2id$")
    assert "correct-horse" not in user.password_hash
    assert verify_password("correct-horse", user.password_hash)


async def test_duplicate_username_raises_and_the_session_stays_usable(app):
    async with app.state.sessionmaker() as s:
        await create_user(s, username="alice", password="correct-horse")
        await s.commit()

        with pytest.raises(UsernameTaken):
            await create_user(s, username="alice", password="another-pass")

        count = (await s.execute(select(func.count()).select_from(User))).scalar_one()
        assert count == 1


async def test_concurrent_creation_of_one_name_yields_exactly_one_user(app):
    async def attempt(password: str) -> bool:
        async with app.state.sessionmaker() as s:
            try:
                await create_user(s, username="alice", password=password)
                await s.commit()
            except UsernameTaken:
                return False
            return True

    results = await asyncio.gather(attempt("first-pass-1"), attempt("second-pass-2"))

    assert sorted(results) == [False, True]
    async with app.state.sessionmaker() as s:
        count = (await s.execute(select(func.count()).select_from(User))).scalar_one()
    assert count == 1
```

- [ ] **Bước 2: Chạy, phải fail**

Chạy:

```bash
cd backend && uv run pytest -q --no-header -p no:cacheprovider -x
```

Kỳ vọng: FAIL lúc nạp `conftest.py` với `ModuleNotFoundError: No module named 'app.main'`.

- [ ] **Bước 3: Viết code**

Lưu ý: `main.py` ở bước này chưa có router admin. Task 4 sẽ thêm.

Tạo `backend/app/auth/__init__.py`:

```python
```

Tạo `backend/app/auth/deps.py`:

```python
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
```

Tạo `backend/app/auth/router.py`:

```python
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
```

Tạo `backend/app/main.py`:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import require_origin
from app.auth.router import router as auth_router
from app.config import Settings
from app.db import get_db, make_engine, make_sessionmaker


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = make_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()

    # Interactive docs only exist in dev, and live under /api so the nginx
    # `/api/` location reaches them.
    dev = settings.environment == "dev"
    app = FastAPI(
        title="Quizzes and Flashcards",
        docs_url="/api/docs" if dev else None,
        openapi_url="/api/openapi.json" if dev else None,
        redoc_url=None,
        dependencies=[Depends(require_origin)],
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)

    @app.get("/api/health", tags=["ops"])
    async def health(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
        await db.execute(text("select 1"))
        return {"status": "ok"}

    app.include_router(auth_router)
    return app
```

- [ ] **Bước 4: Chạy test, lint, kiểm tra kiểu**

Chạy:

```bash
cd backend
uv run ruff check --fix . && uv run ruff format .
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run pytest -q --no-header -p no:cacheprovider
```

Kỳ vọng: `Success: no issues found in 13 source files`, `26 passed`.

- [ ] **Bước 5: Commit**

```bash
git add backend/app/auth backend/app/main.py backend/tests/conftest.py backend/tests/test_app.py backend/tests/test_auth.py backend/tests/test_users_service.py
git commit -m "feat(backend): login, sessions, failed-login lockout, origin guard and app factory"
```

### Task 4: Quản lý tài khoản bởi admin

**Files:**
- Create: `backend/app/admin/__init__.py`, `backend/app/admin/users.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_admin_users.py`

**Interfaces:**
- Consumes: `require_admin`, `get_db`, `create_user`, `normalize_username`, `UsernameTaken`, `hash_password`, `UserSession` (Task 1 đến 3), fixture `client`, `other_client`, `make_user`, `login`.
- Produces:
  - `GET /api/admin/users` trả danh sách `{id, username, role, is_active, daily_new_limit, created_at}`, không bao giờ có trường mật khẩu.
  - `POST /api/admin/users` body `{username, password, role}`, trả 201, trả 409 khi trùng. Username được chuẩn hóa bằng `normalize_username` như ở form đăng nhập (`"  Bob2 "` lưu thành `bob2`).
  - `PATCH /api/admin/users/{id}` body có thể chứa `is_active`, `password`, `daily_new_limit` (0 đến 200). Vô hiệu hoặc đổi mật khẩu xóa mọi phiên của user đó, kể cả phiên đang dùng khi admin tự đổi mật khẩu của chính mình (đúng spec mục 10: request trả 200, request kế tiếp 401, phải đăng nhập lại). Admin không tự vô hiệu mình (409).

- [ ] **Bước 1: Viết test**

Tạo `backend/tests/test_admin_users.py`:

```python
import asyncio

from tests.conftest import login


async def _admin(client, make_user):
    await make_user("root", "admin-password", role="admin")
    assert (await login(client, "root", "admin-password")).status_code == 200


async def test_anonymous_and_regular_users_are_kept_out(client, make_user):
    assert (await client.get("/api/admin/users")).status_code == 401

    await make_user("alice", "correct-horse")
    await login(client, "alice", "correct-horse")

    assert (await client.get("/api/admin/users")).status_code == 403
    created = await client.post(
        "/api/admin/users", json={"username": "eve", "password": "long-enough"}
    )
    assert created.status_code == 403


async def test_admin_creates_a_user_who_can_then_log_in(
    client, other_client, make_user
):
    await _admin(client, make_user)

    resp = await client.post(
        "/api/admin/users", json={"username": "bob", "password": "long-enough"}
    )

    assert resp.status_code == 201
    assert resp.json()["role"] == "user" and resp.json()["daily_new_limit"] == 10
    assert "password" not in resp.text
    assert (await login(other_client, "bob", "long-enough")).status_code == 200


async def test_duplicate_and_invalid_input_is_rejected(client, make_user):
    await _admin(client, make_user)
    ok = {"username": "bob", "password": "long-enough"}
    assert (await client.post("/api/admin/users", json=ok)).status_code == 201

    assert (await client.post("/api/admin/users", json=ok)).status_code == 409
    for bad in (
        {"username": "has space", "password": "long-enough"},
        {"username": "x", "password": "long-enough"},
        {"username": "carol", "password": "short"},
        {"username": "carol", "password": "x" * 129},
        {"username": "carol", "password": "long-enough", "role": "owner"},
    ):
        assert (await client.post("/api/admin/users", json=bad)).status_code == 422


async def test_admin_created_username_is_normalised_like_login(
    client, other_client, make_user
):
    await _admin(client, make_user)

    resp = await client.post(
        "/api/admin/users", json={"username": "  Bob2 ", "password": "long-enough"}
    )

    assert resp.status_code == 201 and resp.json()["username"] == "bob2"
    dup = await client.post(
        "/api/admin/users", json={"username": "BOB2", "password": "long-enough"}
    )
    assert dup.status_code == 409
    assert (await login(other_client, "Bob2", "long-enough")).status_code == 200


async def test_list_never_exposes_password_hashes(client, make_user):
    await _admin(client, make_user)
    await make_user("alice", "correct-horse")

    rows = (await client.get("/api/admin/users")).json()

    assert [r["username"] for r in rows] == ["root", "alice"]
    assert all("password" not in r for r in rows)


async def test_deactivating_a_user_ends_their_sessions_immediately(
    client, other_client, make_user
):
    await _admin(client, make_user)
    victim = await make_user("alice", "correct-horse")
    await login(other_client, "alice", "correct-horse")
    assert (await other_client.get("/api/auth/me")).status_code == 200

    resp = await client.patch(
        f"/api/admin/users/{victim.id}", json={"is_active": False}
    )

    assert resp.status_code == 200 and resp.json()["is_active"] is False
    assert (await other_client.get("/api/auth/me")).status_code == 401
    assert (await login(other_client, "alice", "correct-horse")).status_code == 401


async def test_password_reset_revokes_sessions_and_swaps_the_password(
    client, other_client, make_user
):
    await _admin(client, make_user)
    target = await make_user("alice", "correct-horse")
    await login(other_client, "alice", "correct-horse")

    resp = await client.patch(
        f"/api/admin/users/{target.id}", json={"password": "brand-new-pass"}
    )

    assert resp.status_code == 200
    assert (await other_client.get("/api/auth/me")).status_code == 401
    assert (await login(other_client, "alice", "correct-horse")).status_code == 401
    assert (await login(other_client, "alice", "brand-new-pass")).status_code == 200


async def test_admin_cannot_deactivate_themselves(client, make_user):
    await _admin(client, make_user)

    resp = await client.patch("/api/admin/users/1", json={"is_active": False})

    assert resp.status_code == 409
    assert (await client.get("/api/auth/me")).status_code == 200


async def test_patch_validates_target_and_limits(client, make_user):
    await _admin(client, make_user)
    target = await make_user("alice", "correct-horse")

    assert (await client.patch("/api/admin/users/999", json={})).status_code == 404
    over = await client.patch(
        f"/api/admin/users/{target.id}", json={"daily_new_limit": 201}
    )
    assert over.status_code == 422
    ok = await client.patch(
        f"/api/admin/users/{target.id}", json={"daily_new_limit": 0}
    )
    assert ok.status_code == 200 and ok.json()["daily_new_limit"] == 0


async def test_two_requests_for_the_same_new_name_give_one_201_and_one_409(
    client, make_user
):
    await _admin(client, make_user)
    body = {"username": "bob", "password": "long-enough"}

    first, second = await asyncio.gather(
        client.post("/api/admin/users", json=body),
        client.post("/api/admin/users", json=body),
    )

    assert sorted([first.status_code, second.status_code]) == [201, 409]
    rows = (await client.get("/api/admin/users")).json()
    assert [r["username"] for r in rows].count("bob") == 1
```

- [ ] **Bước 2: Chạy, phải fail**

Chạy:

```bash
cd backend && uv run pytest -q --no-header -p no:cacheprovider tests/test_admin_users.py
```

Kỳ vọng: `10 failed` (route `/api/admin/users` chưa tồn tại).

- [ ] **Bước 3: Viết code**

Tạo `backend/app/admin/__init__.py`:

```python
```

Tạo `backend/app/admin/users.py`:

```python
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
```

Thay toàn bộ `backend/app/main.py` (thêm import và `include_router` của router admin):

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.users import router as admin_users_router
from app.auth.deps import require_origin
from app.auth.router import router as auth_router
from app.config import Settings
from app.db import get_db, make_engine, make_sessionmaker


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = make_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()

    # Interactive docs only exist in dev, and live under /api so the nginx
    # `/api/` location reaches them.
    dev = settings.environment == "dev"
    app = FastAPI(
        title="Quizzes and Flashcards",
        docs_url="/api/docs" if dev else None,
        openapi_url="/api/openapi.json" if dev else None,
        redoc_url=None,
        dependencies=[Depends(require_origin)],
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)

    @app.get("/api/health", tags=["ops"])
    async def health(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
        await db.execute(text("select 1"))
        return {"status": "ok"}

    app.include_router(auth_router)
    app.include_router(admin_users_router)
    return app
```

- [ ] **Bước 4: Chạy test, lint, kiểm tra kiểu**

Chạy:

```bash
cd backend
uv run ruff check --fix . && uv run ruff format .
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run pytest -q --no-header -p no:cacheprovider
```

Kỳ vọng: `Success: no issues found in 15 source files`, `36 passed`.

- [ ] **Bước 5: Commit**

```bash
git add backend/app/admin backend/app/main.py backend/tests/test_admin_users.py
git commit -m "feat(backend): admin user management"
```

### Task 5: Docker, nginx, backup, hợp đồng API và tài liệu

**Files:**
- Create: `backend/Dockerfile`, `backend/.dockerignore`, `backend/scripts/export_openapi.py`
- Create: `deploy/docker-compose.yml`, `deploy/.env.example`, `deploy/nginx/quizz-limit.conf`, `deploy/nginx/quizz-api.conf`, `deploy/backup/backup.sh`
- Create: `docs/README.md`, `docs/architecture/deploy.md`, `docs/architecture/openapi.json` (sinh ra)
- Modify: `.pre-commit-config.yaml` (thêm hook `openapi-contract`)

**Interfaces:**
- Consumes: ứng dụng hoàn chỉnh của Task 1 đến 4, `backend/uv.lock`.
- Produces:
  - Image `api` chạy bằng user không phải root, lệnh `uvicorn app.main:create_app --factory`.
  - Compose gồm `db` và `api`. `api` publish `127.0.0.1:8000`. Thêm service mới ở plan sau bằng cách sửa file này.
  - `deploy/backup/backup.sh` (`BACKUP_DIR`, `KEEP`).
  - `docs/architecture/openapi.json` sinh bằng `python -m scripts.export_openapi`.

**Ghi chú:** task này kiểm chứng bằng cách chạy thật: build image, dựng stack, gọi HTTP, thử nginx và thử backup rồi restore. Không có test pytest mới. Việc triển khai lên VPS thật là thao tác production và không nằm trong plan này; làm theo `docs/architecture/deploy.md` khi chủ dự án xác nhận.

- [ ] **Bước 1: Viết Dockerfile và script xuất OpenAPI**

Tạo `backend/.dockerignore`:

```gitignore
.venv
.pytest_cache
.mypy_cache
.ruff_cache
__pycache__
tests
*.pyc
```

Tạo `backend/Dockerfile`:

```dockerfile
FROM python:3.12.16-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.4 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first so code edits do not invalidate this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

RUN useradd --system --no-create-home app
USER app

EXPOSE 8000
# FORWARDED_ALLOW_IPS is read by uvicorn: which peers may set X-Forwarded-*.
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
```

Tạo `backend/scripts/export_openapi.py`:

```python
"""Write the API contract to docs/architecture/openapi.json.

Run from backend/:  uv run python -m scripts.export_openapi
No database connection is made; the engine is created lazily.
"""

import json
from pathlib import Path

from app.config import Settings
from app.main import create_app

OUTPUT = Path(__file__).resolve().parents[2] / "docs" / "architecture" / "openapi.json"


def main() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        environment="dev",
    )
    schema = create_app(settings).openapi()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
```

- [ ] **Bước 2: Viết compose, biến môi trường mẫu, nginx và backup**

Tạo `deploy/docker-compose.yml`:

```yaml
name: quizz

services:
  db:
    image: postgres:17.11-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: quizz
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in deploy/.env}
      POSTGRES_DB: quizz
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U quizz -d quizz"]
      interval: 5s
      timeout: 3s
      retries: 10

  api:
    build: ../backend
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    environment:
      QUIZZ_DATABASE_URL: postgresql+psycopg://quizz:${POSTGRES_PASSWORD}@db:5432/quizz
      QUIZZ_APP_ORIGIN: ${QUIZZ_APP_ORIGIN:?set QUIZZ_APP_ORIGIN in deploy/.env}
      QUIZZ_ENVIRONMENT: ${QUIZZ_ENVIRONMENT:-prod}
      QUIZZ_COOKIE_SECURE: ${QUIZZ_COOKIE_SECURE:-true}
      FORWARDED_ALLOW_IPS: ${FORWARDED_ALLOW_IPS:-*}
    ports:
      # Loopback only: the host nginx is the single public entry point.
      - "127.0.0.1:8000:8000"

volumes:
  pgdata:
```

Tạo `deploy/.env.example`:

```bash
# Copy to deploy/.env and fill in. Never commit deploy/.env.
# Generate the password with:  openssl rand -hex 24
# (hex only: it is embedded in a URL, so avoid characters like @ : / %)
POSTGRES_PASSWORD=

QUIZZ_APP_ORIGIN=https://quizz.thangtm.io.vn
QUIZZ_ENVIRONMENT=prod
QUIZZ_COOKIE_SECURE=true

# Which peers uvicorn trusts for X-Forwarded-*. "*" is safe ONLY while `api`
# is the sole container on the compose network: the published port is
# 127.0.0.1-only, so the only other peer is the host nginx. A plan that adds
# `web` or `worker` MUST replace "*" with the bridge gateway address that
# nginx connections arrive from, or any container could spoof client IPs.
FORWARDED_ALLOW_IPS=*
```

Tạo `deploy/nginx/quizz-limit.conf`:

```nginx
# http{} context. Include once, e.g. from /etc/nginx/conf.d/quizz-limit.conf.
# 10 requests/minute per client IP on the login endpoint (see quizz-api.conf).
limit_req_zone $binary_remote_addr zone=quizz_login:10m rate=10r/m;
```

Tạo `deploy/nginx/quizz-api.conf`:

```nginx
# server{} context of the quizz.thangtm.io.vn server block (TLS is configured
# there, not here). The api container publishes 127.0.0.1:8000 only.

# OVERWRITE, never append ($proxy_add_x_forwarded_for): the API trusts the
# first X-Forwarded-For entry as the client IP for the login lockout, so a
# client-supplied header must not survive.
proxy_set_header Host $host;
proxy_set_header X-Forwarded-For $remote_addr;
proxy_set_header X-Forwarded-Proto $scheme;

location = /api/auth/login {
    limit_req zone=quizz_login burst=5 nodelay;
    limit_req_status 429;
    client_max_body_size 4k;
    proxy_pass http://127.0.0.1:8000;
}

location /api/ {
    # Large enough for the PDF upload added in the AI-pipeline plan.
    client_max_body_size 25m;
    proxy_read_timeout 120s;
    proxy_pass http://127.0.0.1:8000;
}
```

Tạo `deploy/backup/backup.sh`:

```bash
#!/usr/bin/env bash
# Nightly logical backup of the quizz database.
#   BACKUP_DIR  where dumps go (default /var/backups/quizz): keep it OUTSIDE the
#               Docker volume, ideally on another disk.
#   KEEP        how many dumps to keep (default 14)
# Restore: see docs/architecture/deploy.md.
set -euo pipefail
# Dumps contain password hashes: owner-readable only.
umask 077

cd "$(dirname "$0")/.."   # deploy/, where docker-compose.yml lives

BACKUP_DIR="${BACKUP_DIR:-/var/backups/quizz}"
KEEP="${KEEP:-14}"

mkdir -p "$BACKUP_DIR"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
partial="$BACKUP_DIR/.quizz-$stamp.partial"
final="$BACKUP_DIR/quizz-$stamp.dump"

# A failed or interrupted dump must never look like a valid backup.
trap 'rm -f "$partial"' EXIT

docker compose exec -T db pg_dump -U quizz -d quizz --format=custom > "$partial"
[ -s "$partial" ] || { echo "backup is empty, aborting" >&2; exit 1; }
mv "$partial" "$final"
trap - EXIT

# Prune: newest $KEEP stay.
ls -1t "$BACKUP_DIR"/quizz-*.dump | tail -n +"$((KEEP + 1))" | xargs -r rm --
echo "backup written: $final"
```

Chạy:

```bash
chmod +x deploy/backup/backup.sh
```

- [ ] **Bước 3: Dựng stack thử**

Cổng `8000` và `18081` phải còn trống. Dự án compose đặt tên `quizz-smoke` để không đụng stack nào khác.

Chạy:

```bash
cd deploy
printf 'POSTGRES_PASSWORD=%s\nQUIZZ_APP_ORIGIN=http://127.0.0.1:8000\nQUIZZ_ENVIRONMENT=prod\nQUIZZ_COOKIE_SECURE=false\n' "$(openssl rand -hex 24)" > .env
docker compose -p quizz-smoke build
docker compose -p quizz-smoke up -d db
docker compose -p quizz-smoke run --rm api alembic upgrade head
docker compose -p quizz-smoke up -d api
sleep 3
docker compose -p quizz-smoke ps --format '{{.Service}} {{.State}} {{.Ports}}'
cd ..
```

Kỳ vọng: log migration có `Running upgrade  -> 0001`; `api running 127.0.0.1:8000->8000/tcp` và `db running 5432/tcp`.

- [ ] **Bước 4: Gọi HTTP qua cổng `api`**

Chạy:

```bash
O='http://127.0.0.1:8000'
C='docker compose -f deploy/docker-compose.yml -p quizz-smoke'
curl -s -w ' [%{http_code}]\n' $O/api/health
curl -s -o /dev/null -w '%{http_code} ' $O/api/docs $O/api/openapi.json $O/docs; echo
$C exec -T -e QUIZZ_ADMIN_PASSWORD=admin-password api python -m app.cli create-admin --username Root
curl -s -w ' [%{http_code}]\n' -X POST $O/api/auth/login -H 'content-type: application/json' -d '{"username":"root","password":"admin-password"}'
curl -s -i -c /tmp/quizz-jar -X POST $O/api/auth/login -H 'content-type: application/json' -H "origin: $O" -d '{"username":"root","password":"admin-password"}' | grep -iE '^(HTTP|set-cookie|\{)' | sed -E 's/(session=)[^;]+/\1<redacted>/'
curl -s -b /tmp/quizz-jar -w ' [%{http_code}]\n' $O/api/auth/me
curl -s -b /tmp/quizz-jar -o /dev/null -w '%{http_code}\n' $O/api/admin/users
$C exec -T api id -un
rm -f /tmp/quizz-jar
```

Kỳ vọng: 
```
{"status":"ok"} [200]
404 404 404
Created admin 'root'
{"detail":"Origin not allowed"} [403]
HTTP/1.1 200 OK
set-cookie: session=<redacted>; HttpOnly; Max-Age=2592000; Path=/; SameSite=lax
{"id":1,"username":"root","role":"admin"}
{"id":1,"username":"root","role":"admin"} [200]
200
app
```

`404 404 404` nghĩa là docs bị tắt ở `prod`. Cookie không có `Secure` vì bước 3 đặt `QUIZZ_COOKIE_SECURE=false` để thử qua HTTP; ở production phải `true` và test `test_login_sets_hardened_cookie_and_me_works` đã kiểm chứng điều đó.

- [ ] **Bước 5: Thử cấu hình nginx với `X-Forwarded-For` giả**

Chạy:

```bash
mkdir -p /tmp/quizz-nginx-test
cat > /tmp/quizz-nginx-test/nginx.conf <<'EOF'
events {}
http {
  include /etc/nginx/quizz/quizz-limit.conf;
  server { listen 18081; include /etc/nginx/quizz/quizz-api.conf; }
}
EOF
M="-v /tmp/quizz-nginx-test/nginx.conf:/etc/nginx/nginx.conf:ro -v $(pwd)/deploy/nginx:/etc/nginx/quizz:ro"
C='docker compose -f deploy/docker-compose.yml -p quizz-smoke'
docker run --rm --network host $M nginx:1.29-alpine nginx -t 2>&1 | tail -1
docker rm -f quizz-nginx-test >/dev/null 2>&1 || true
docker run -d --name quizz-nginx-test --network host $M nginx:1.29-alpine >/dev/null; sleep 1
curl -s -w ' [%{http_code}]\n' http://127.0.0.1:18081/api/health
$C exec -T db psql -U quizz -d quizz -qc "truncate login_attempts"
curl -s -o /dev/null -w 'spoofed XFF login: %{http_code}\n' -X POST http://127.0.0.1:18081/api/auth/login -H 'content-type: application/json' -H 'origin: http://127.0.0.1:8000' -H 'X-Forwarded-For: 198.51.100.77, 203.0.113.10' -d '{"username":"root","password":"wrong-password"}'
$C exec -T db psql -U quizz -d quizz -tAc "select ip from login_attempts"
for i in $(seq 1 15); do curl -s -o /dev/null -w '%{http_code} ' -X POST http://127.0.0.1:18081/api/auth/login -H 'content-type: application/json' -H 'origin: http://127.0.0.1:8000' -d '{}'; done; echo
docker rm -f quizz-nginx-test >/dev/null
```

Kỳ vọng: 
```
nginx: configuration file /etc/nginx/nginx.conf test is successful
{"status":"ok"} [200]
spoofed XFF login: 401
127.0.0.1
422 422 422 422 422 429 429 429 429 429 429 429 429 429 429
```

Dòng `127.0.0.1` chứng minh header giả không được ghi vào nhật ký. Với `rate=10r/m burst=5 nodelay`, nginx cho qua liền 6 request (1 cộng burst 5) rồi trả 429. Request giả XFF ở trên đã dùng 1 suất, nên vòng lặp thấy 5 lần 422 (body rỗng) rồi 429. Vùng hồi 1 suất mỗi 6 giây: nếu từ request giả tới vòng lặp quá 6 giây (lệnh `psql` chậm) sẽ thấy 6 lần 422, kết quả đó vẫn đúng.

- [ ] **Bước 6: Thử backup, prune và restore thật**

Chạy:

```bash
export COMPOSE_PROJECT_NAME=quizz-smoke
cd deploy
B=$(mktemp -d)
for i in 1 2 3; do BACKUP_DIR=$B KEEP=2 ./backup/backup.sh; sleep 1; done
echo "kept:"; ls -1 "$B"
latest=$(ls -1t "$B"/quizz-*.dump | head -1)
docker compose exec -T db psql -U quizz -d postgres -qc "drop database if exists quizz_restore" -c "create database quizz_restore"
docker compose exec -T db pg_restore -U quizz -d quizz_restore --no-owner < "$latest"
docker compose exec -T db psql -U quizz -d quizz_restore -tAc "select 'users=' || count(*) from users"
docker compose exec -T db psql -U quizz -d quizz_restore -tAc "select 'alembic=' || version_num from alembic_version"
docker compose exec -T db psql -U quizz -d postgres -qc "drop database quizz_restore"
BACKUP_DIR=$B COMPOSE_PROJECT_NAME=doesnotexist ./backup/backup.sh >/dev/null 2>&1 || echo "failed-run exit=$?"
ls -a "$B" | grep -c partial || true
rm -rf "$B"; cd ..; unset COMPOSE_PROJECT_NAME
```

Kỳ vọng: ba dòng `backup written`; `kept:` liệt kê đúng hai file `quizz-*.dump`; `users=1`; `alembic=0001`; `failed-run exit=1`; số file `.partial` còn lại là `0`.

- [ ] **Bước 7: Dọn stack thử**

Chạy:

```bash
docker compose -f deploy/docker-compose.yml -p quizz-smoke down -v
rm -f deploy/.env
rm -rf /tmp/quizz-nginx-test
docker ps -a --format '{{.Names}}' | grep -E 'quizz-smoke|quizz-nginx' || echo "no leftovers"
```

Kỳ vọng: `no leftovers`.

- [ ] **Bước 8: Viết tài liệu và xuất hợp đồng API**

Tạo `docs/README.md`:

```markdown
# Tài liệu dự án

`docs/` là nguồn sự thật duy nhất (SSOT) của dự án.

| Thư mục | Nội dung |
|---|---|
| `product/` | Mục tiêu và phạm vi |
| `architecture/` | Kiến trúc, mô hình dữ liệu, SRS, triển khai, `openapi.json` |
| `decisions/` | Quyết định kiến trúc ngắn, mỗi quyết định một file |
| `specs/` | Spec thiết kế |
| `plans/` | Kế hoạch triển khai |

Thư mục nào chưa có thì tạo khi có tài liệu đầu tiên.

## Quy ước

- Thay đổi hành vi, schema hay deploy thì cập nhật tài liệu trong cùng commit.
- Hợp đồng API lấy từ OpenAPI của FastAPI: chạy `cd backend && uv run python -m scripts.export_openapi` rồi commit `architecture/openapi.json`. Không sửa tay.
- Tài liệu lệch code thì tài liệu là chuẩn cho tới khi có quyết định mới được ghi lại.

## Mục lục

- [Triển khai](architecture/deploy.md)
```

Tạo `docs/architecture/deploy.md`:

```markdown
# Triển khai

Cập nhật lần cuối cùng với plan nền tảng backend. Hiện có hai container: `db` (PostgreSQL 17.11) và `api`. `web` và `worker` được thêm bởi các plan sau.

## Biến môi trường

Sao `deploy/.env.example` thành `deploy/.env` và điền. File này không được commit.

| Biến | Ý nghĩa |
|---|---|
| `POSTGRES_PASSWORD` | Mật khẩu DB. Dùng `openssl rand -hex 24` (chỉ hex vì nó nằm trong URL) |
| `QUIZZ_APP_ORIGIN` | Origin công khai, ví dụ `https://quizz.thangtm.io.vn`. Request ghi có `Origin` khác sẽ bị 403 |
| `QUIZZ_ENVIRONMENT` | `prod` tắt docs và `/api/openapi.json` |
| `QUIZZ_COOKIE_SECURE` | `true` ở production. Chỉ đặt `false` khi thử qua HTTP thuần |
| `FORWARDED_ALLOW_IPS` | Các peer mà uvicorn tin `X-Forwarded-*`. `*` chỉ an toàn khi `api` là container duy nhất trong mạng compose (cổng chỉ publish ở `127.0.0.1`, peer còn lại duy nhất là nginx trên host). Plan nào thêm `web` hoặc `worker` phải thay `*` bằng địa chỉ gateway của bridge, nếu không container khác giả được IP client |

## Chạy lần đầu

```bash
cd deploy
docker compose build
docker compose up -d db
docker compose run --rm api alembic upgrade head
docker compose up -d api
docker compose exec api python -m app.cli create-admin --username <tên>
```

Lệnh cuối hỏi mật khẩu bằng `getpass`, cần terminal tương tác. Đã kiểm chứng đường `QUIZZ_ADMIN_PASSWORD`; đường `getpass` chưa chạy thử.

Cập nhật phiên bản mới: `docker compose build`, `docker compose run --rm api alembic upgrade head`, rồi `docker compose up -d api`.

## nginx

Hai file mẫu nằm trong `deploy/nginx/`:

- `quizz-limit.conf` thuộc ngữ cảnh `http {}`. Đặt vào `/etc/nginx/conf.d/`. Nó khai báo vùng `limit_req` cho trang đăng nhập.
- `quizz-api.conf` thuộc ngữ cảnh `server {}` của `quizz.thangtm.io.vn`. Thêm `include` vào server block có TLS sẵn.

Điểm quan trọng: `X-Forwarded-For` được **ghi đè** bằng `$remote_addr`, không nối thêm. API lấy phần tử đầu làm IP client cho việc khóa đăng nhập, nên header do client gửi phải bị bỏ. Đã kiểm chứng với nginx 1.29 trong container: header giả `198.51.100.77, 203.0.113.10` không xuất hiện trong `login_attempts.ip`. Cấu hình trên nginx thật của VPS chưa được thử.

Sau khi sửa nginx: `nginx -t` rồi mới `nginx -s reload`.

## Mở khóa đăng nhập

Khóa thử sai tính theo cả username lẫn IP, nên người lạ đoán sai 5 lần với username của admin là khóa được admin 15 phút. Khóa tự mở sau 15 phút kể từ lần sai cuối. Muốn mở ngay:

```bash
cd deploy
docker compose exec -T db psql -U quizz -d quizz -c "delete from login_attempts where username = '<tên>'"
```

Bị khóa theo IP thì thay điều kiện bằng `ip = '<địa chỉ>'`.

## Sao lưu và khôi phục

`deploy/backup/backup.sh` ghi `pg_dump` dạng custom vào `BACKUP_DIR` (mặc định `/var/backups/quizz`, nên đặt ngoài volume Docker, tốt nhất khác ổ đĩa) và giữ `KEEP` bản gần nhất (mặc định 14). Dump lỗi hoặc rỗng không để lại file hợp lệ.

Ví dụ cron (chưa chạy thử), chạy bằng user có quyền dùng Docker:

```
0 3 * * * /đường/dẫn/repo/deploy/backup/backup.sh >> /var/log/quizz-backup.log 2>&1
```

Khôi phục vào một database mới (quy trình này đã được kiểm chứng):

```bash
cd deploy
docker compose exec -T db psql -U quizz -d postgres -c "create database quizz_restore"
docker compose exec -T db pg_restore -U quizz -d quizz_restore --no-owner < /var/backups/quizz/quizz-<thời điểm>.dump
docker compose exec -T db psql -U quizz -d quizz_restore -c "select count(*) from users"
```

Khôi phục đè lên database đang chạy **chưa** được kiểm chứng. Cách an toàn là khôi phục vào database mới như trên, kiểm tra, rồi mới quyết định chuyển.

## Hợp đồng API

`docs/architecture/openapi.json` được sinh từ code, không viết tay:

```bash
cd backend && uv run python -m scripts.export_openapi
```
```

Chạy:

```bash
cd backend && uv run python -m scripts.export_openapi
```

Kỳ vọng: dòng `wrote .../docs/architecture/openapi.json`. File chứa các path `/api/admin/users`, `/api/admin/users/{user_id}`, `/api/auth/login`, `/api/auth/logout`, `/api/auth/me`, `/api/health`.

- [ ] **Bước 9: Thêm hook kiểm tra hợp đồng API, chạy lại toàn bộ kiểm tra và commit**

Thêm vào cuối danh sách `hooks` trong `.pre-commit-config.yaml` (cùng mức thụt lề với hook `mypy`):

```yaml
      - id: openapi-contract
        name: openapi.json up to date
        entry: bash -c 'cd backend && uv run python -m scripts.export_openapi >/dev/null && git diff --exit-code -- ../docs/architecture/openapi.json'
        language: system
        pass_filenames: false
        files: ^(backend/|docs/architecture/openapi\.json$)
```

Hook sinh lại file rồi so với bản đã stage. Đổi route hay schema mà quên xuất lại thì commit bị chặn, và file đã được sinh lại sẵn để `git add`. Plan 4 sinh kiểu TypeScript từ file này nên nó không được lệch.

Chạy:

```bash
cd backend
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --no-header -p no:cacheprovider
cd ..
git add .pre-commit-config.yaml backend/Dockerfile backend/.dockerignore backend/scripts deploy docs/README.md docs/architecture
uv run --project backend pre-commit run --all-files
git commit -m "feat(deploy): docker image, compose, nginx snippets, backup and docs"
```

Kỳ vọng: `36 passed` và bốn hook pre-commit `Passed`. `deploy/.env` đã bị xóa ở bước 7 và `.gitignore` chặn nó.

Dọn container test khi xong hẳn: `docker rm -f quizz-testdb`.

---

## Kiểm tra cuối của plan

Sau Task 5, các điều sau phải đúng:

- `cd backend && uv run pytest -q` cho `36 passed` trên Postgres thật.
- `docker compose build` và dựng stack từ đầu thành công, `GET /api/health` trả 200.
- Tài khoản admin tạo được bằng CLI, đăng nhập được và gọi được `/api/admin/users`.
- Backup tạo file, prune đúng số lượng, restore ra database mới có dữ liệu.
- `docs/architecture/openapi.json` khớp code. Hook pre-commit `openapi-contract` chặn commit khi lệch.

Chưa được kiểm chứng và không nằm trong plan: nginx thật trên VPS, đường `getpass` của CLI, cron backup, restore đè lên database đang chạy.

Bàn giao cho plan 3 và 4: thêm `worker` hoặc `web` vào compose thì phải thay `FORWARDED_ALLOW_IPS=*` bằng địa chỉ gateway của bridge (xem `deploy/.env.example`). Spec mục 5 còn việc chuyển `task.md` thành `docs/product/vision.md`, làm khi chủ dự án commit các file đó.
