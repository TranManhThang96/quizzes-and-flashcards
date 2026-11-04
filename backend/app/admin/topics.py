from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import require_admin
from app.db import get_db
from app.models import Item, Topic
from app.text import normalize_ws, slugify

router = APIRouter(
    prefix="/api/admin/topics", tags=["admin"], dependencies=[Depends(require_admin)]
)


class TopicIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def _clean(cls, value: str) -> str:
        name = normalize_ws(value)
        if not name:
            raise ValueError("Name must not be blank")
        return name


class TopicOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str


async def _unique_slug(db: AsyncSession, name: str) -> str:
    base = slugify(name)
    if not base:
        raise HTTPException(
            status_code=422, detail="Name must contain a letter or digit"
        )
    slug = base
    suffix = 1
    while (await db.execute(select(Topic.id).where(Topic.slug == slug))).first():
        suffix += 1
        slug = f"{base}-{suffix}"
    return slug


@router.get("", response_model=list[TopicOut])
async def list_topics(db: AsyncSession = Depends(get_db)) -> list[Topic]:
    stmt = select(Topic).order_by(Topic.name)
    return list((await db.execute(stmt)).scalars())


@router.post("", response_model=TopicOut, status_code=201)
async def add_topic(body: TopicIn, db: AsyncSession = Depends(get_db)) -> Topic:
    topic = Topic(name=body.name, slug=await _unique_slug(db, body.name))
    db.add(topic)
    try:
        await db.flush()
    except IntegrityError as exc:
        # Two admins creating the same name at once can still race the slug
        # lookup. The unique constraint is the authority; the loser gets 409.
        await db.rollback()
        raise HTTPException(status_code=409, detail="Topic already exists") from exc
    await db.commit()
    return topic


@router.patch("/{topic_id}", response_model=TopicOut)
async def rename_topic(
    topic_id: int, body: TopicIn, db: AsyncSession = Depends(get_db)
) -> Topic:
    topic = await db.get(Topic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    topic.name = body.name
    await db.commit()
    return topic


@router.delete("/{topic_id}", status_code=204)
async def delete_topic(topic_id: int, db: AsyncSession = Depends(get_db)) -> Response:
    topic = await db.get(Topic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    count = (
        await db.execute(
            select(func.count()).select_from(Item).where(Item.topic_id == topic_id)
        )
    ).scalar_one()
    if count:
        raise HTTPException(status_code=409, detail="Topic still has items")
    await db.delete(topic)
    await db.commit()
    return Response(status_code=204)
