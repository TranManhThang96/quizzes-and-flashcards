from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.exams import router as admin_exams_router
from app.admin.items import router as admin_items_router
from app.admin.topics import router as admin_topics_router
from app.admin.users import router as admin_users_router
from app.auth.deps import require_origin
from app.auth.router import router as auth_router
from app.config import Settings
from app.db import get_db, make_engine, make_sessionmaker
from app.user.study import router as user_study_router
from app.user.topics import router as user_topics_router


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
    app.include_router(admin_topics_router)
    app.include_router(admin_items_router)
    app.include_router(admin_exams_router)
    app.include_router(user_topics_router)
    app.include_router(user_study_router)
    return app
