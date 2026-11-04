from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db import get_db
from app.models import Item, Topic, User

router = APIRouter(prefix="/api", tags=["topics"])


class TopicCard(BaseModel):
    id: int
    name: str
    slug: str
    published_items: int


@router.get("/topics", response_model=list[TopicCard])
async def list_topics(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[TopicCard]:
    stmt = (
        select(Topic.id, Topic.name, Topic.slug, func.count(Item.id))
        .outerjoin(Item, (Item.topic_id == Topic.id) & (Item.status == "published"))
        .group_by(Topic.id, Topic.name, Topic.slug)
        .order_by(Topic.name)
    )
    return [
        TopicCard(id=row[0], name=row[1], slug=row[2], published_items=row[3])
        for row in (await db.execute(stmt)).all()
    ]
