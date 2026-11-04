"""Quản lý nguồn nội dung: dán văn bản, tải PDF, nhập URL."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import require_admin
from app.config import Settings
from app.db import get_db
from app.extract import (
    ExtractionError,
    ExtractionTooLarge,
    extract_pdf,
    extract_url,
    finalize_text,
)
from app.models import Source, User

router = APIRouter(
    prefix="/api/admin/sources", tags=["admin"], dependencies=[Depends(require_admin)]
)

PREVIEW_CHARS = 500


class TextIn(BaseModel):
    text: str = Field(min_length=1)


class UrlIn(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class SourceOut(BaseModel):
    id: int
    kind: str
    chars: int
    url: str | None
    preview: str


class SourceListOut(BaseModel):
    id: int
    kind: str
    chars: int
    url: str | None
    created_at: datetime


def _as_http_error(exc: ExtractionError) -> HTTPException:
    status = 413 if isinstance(exc, ExtractionTooLarge) else 422
    return HTTPException(status_code=status, detail=str(exc))


async def _store(
    db: AsyncSession,
    *,
    kind: str,
    text: str,
    url: str | None,
    admin: User,
) -> SourceOut:
    source = Source(kind=kind, text=text, url=url, created_by=admin.id)
    db.add(source)
    await db.commit()
    return SourceOut(
        id=source.id,
        kind=source.kind,
        chars=len(source.text),
        url=source.url,
        preview=source.text[:PREVIEW_CHARS],
    )


@router.post("/text", response_model=SourceOut, status_code=201)
async def add_text_source(
    body: TextIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> SourceOut:
    settings: Settings = request.app.state.settings
    try:
        text = finalize_text(body.text, max_chars=settings.max_source_chars)
    except ExtractionError as exc:
        raise _as_http_error(exc) from exc
    return await _store(db, kind="text", text=text, url=None, admin=admin)


@router.post("/url", response_model=SourceOut, status_code=201)
async def add_url_source(
    body: UrlIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> SourceOut:
    settings: Settings = request.app.state.settings
    try:
        raw = await extract_url(
            body.url,
            max_bytes=settings.max_url_bytes,
            timeout=settings.url_timeout_seconds,
            max_redirects=settings.url_max_redirects,
        )
        text = finalize_text(raw, max_chars=settings.max_source_chars)
    except ExtractionError as exc:
        raise _as_http_error(exc) from exc
    return await _store(db, kind="url", text=text, url=body.url, admin=admin)


@router.post("/pdf", response_model=SourceOut, status_code=201)
async def add_pdf_source(
    request: Request,
    file: Annotated[UploadFile, File()],
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> SourceOut:
    settings: Settings = request.app.state.settings
    data = await file.read(settings.max_pdf_bytes + 1)
    if len(data) > settings.max_pdf_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"PDF vượt giới hạn {settings.max_pdf_bytes} byte",
        )
    try:
        raw = await extract_pdf(data, max_chars=settings.max_source_chars)
        text = finalize_text(raw, max_chars=settings.max_source_chars)
    except ExtractionError as exc:
        raise _as_http_error(exc) from exc
    return await _store(db, kind="pdf", text=text, url=None, admin=admin)


@router.get("", response_model=list[SourceListOut])
async def list_sources(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[SourceListOut]:
    # Chỉ đếm ký tự ở phía DB: không kéo cả cột `text` (tới 200k ký tự/nguồn).
    statement = (
        select(
            Source.id,
            Source.kind,
            func.length(Source.text),
            Source.url,
            Source.created_at,
        )
        .order_by(Source.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [
        SourceListOut(
            id=row[0], kind=row[1], chars=row[2], url=row[3], created_at=row[4]
        )
        for row in (await db.execute(statement)).all()
    ]
