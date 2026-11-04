from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import require_admin
from app.content import (
    Content,
    ItemStatus,
    Kind,
    Level,
    content_hash,
    parse_content,
)
from app.db import get_db
from app.models import Item, Topic

router = APIRouter(
    prefix="/api/admin/items", tags=["admin"], dependencies=[Depends(require_admin)]
)


class ItemIn(BaseModel):
    topic_id: int
    level: Level
    kind: Kind
    content: dict[str, Any]


class ItemPatch(BaseModel):
    level: Level | None = None
    content: dict[str, Any] | None = None


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    topic_id: int
    level: str
    kind: str
    content: dict[str, Any]
    status: str
    content_hash: str
    created_at: datetime
    updated_at: datetime


def _validated(kind: str, raw: dict[str, Any]) -> Content:
    try:
        return parse_content(kind, raw)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Invalid content",
                "errors": [
                    {"loc": list(error["loc"]), "msg": error["msg"]}
                    for error in exc.errors()
                ],
            },
        ) from exc


async def _get_item(db: AsyncSession, item_id: int) -> Item:
    item = await db.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@router.get("", response_model=list[ItemOut])
async def list_items(
    status: ItemStatus | None = None,
    topic_id: int | None = None,
    kind: Kind | None = None,
    level: Level | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[Item]:
    stmt = select(Item).order_by(Item.id.desc()).limit(limit).offset(offset)
    if status is not None:
        stmt = stmt.where(Item.status == status)
    if topic_id is not None:
        stmt = stmt.where(Item.topic_id == topic_id)
    if kind is not None:
        stmt = stmt.where(Item.kind == kind)
    if level is not None:
        stmt = stmt.where(Item.level == level)
    return list((await db.execute(stmt)).scalars())


@router.get("/{item_id}", response_model=ItemOut)
async def get_item(item_id: int, db: AsyncSession = Depends(get_db)) -> Item:
    return await _get_item(db, item_id)


@router.post("", response_model=ItemOut, status_code=201)
async def add_item(body: ItemIn, db: AsyncSession = Depends(get_db)) -> Item:
    if await db.get(Topic, body.topic_id) is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    parsed = _validated(body.kind, body.content)
    item = Item(
        topic_id=body.topic_id,
        level=body.level,
        kind=body.kind,
        content=parsed.model_dump(),
        content_hash=content_hash(body.kind, parsed),
    )
    db.add(item)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="This content already exists in the topic"
        ) from exc
    await db.commit()
    return item


@router.patch("/{item_id}", response_model=ItemOut)
async def patch_item(
    item_id: int, body: ItemPatch, db: AsyncSession = Depends(get_db)
) -> Item:
    item = await _get_item(db, item_id)
    if body.level is not None:
        item.level = body.level
    if body.content is not None:
        parsed = _validated(item.kind, body.content)
        item.content = parsed.model_dump()
        item.content_hash = content_hash(item.kind, parsed)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="This content already exists in the topic"
        ) from exc
    await db.commit()
    # updated_at is a SQL expression, so it is expired after the UPDATE;
    # refresh inside the async greenlet instead of during response rendering.
    await db.refresh(item)
    return item


@router.post("/{item_id}/publish", response_model=ItemOut)
async def publish_item(item_id: int, db: AsyncSession = Depends(get_db)) -> Item:
    item = await _get_item(db, item_id)
    item.status = "published"
    await db.commit()
    await db.refresh(item)
    return item


@router.post("/{item_id}/archive", response_model=ItemOut)
async def archive_item(item_id: int, db: AsyncSession = Depends(get_db)) -> Item:
    item = await _get_item(db, item_id)
    item.status = "archived"
    await db.commit()
    await db.refresh(item)
    return item
