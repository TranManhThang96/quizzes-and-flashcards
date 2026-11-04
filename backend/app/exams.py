from dataclasses import dataclass

from pydantic import BaseModel, Field
from sqlalchemy import Float, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content import Level
from app.models import Item, ReviewLog


class BuildLine(BaseModel):
    topic_id: int
    level: Level
    count: int = Field(ge=1, le=200)


@dataclass(frozen=True)
class LineSelection:
    topic_id: int
    level: str
    requested: int
    available: int
    selected: list[int]


async def select_for_config(
    db: AsyncSession, lines: list[BuildLine], *, prefer_weak: bool
) -> list[LineSelection]:
    """Pick questions for every requested (topic, level) row, never borrowing."""
    selections: list[LineSelection] = []
    for line in lines:
        total = func.count(ReviewLog.id)
        wrong = func.count(ReviewLog.id).filter(ReviewLog.correct.is_(False))
        stmt = (
            select(Item.id)
            .outerjoin(ReviewLog, ReviewLog.item_id == Item.id)
            .where(
                Item.topic_id == line.topic_id,
                Item.level == line.level,
                Item.kind == "question",
                Item.status == "published",
            )
            .group_by(Item.id)
        )
        if prefer_weak:
            ratio = wrong.cast(Float) / func.nullif(total, 0)
            stmt = stmt.order_by(ratio.desc().nulls_last(), func.random())
        else:
            stmt = stmt.order_by(func.random())
        ids = list((await db.execute(stmt)).scalars())
        selections.append(
            LineSelection(
                topic_id=line.topic_id,
                level=line.level,
                requested=line.count,
                available=len(ids),
                selected=ids[: line.count],
            )
        )
    return selections
