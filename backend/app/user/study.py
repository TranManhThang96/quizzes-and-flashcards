from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.clock import utcnow
from app.content import Level
from app.db import get_db
from app.models import Item, User
from app.reviews import QueueCard, apply_review, build_queue, stats, wrong_cards
from app.srs import Grade

router = APIRouter(prefix="/api", tags=["study"])


class AnswerIn(BaseModel):
    item_id: int
    grade: Grade
    source: Literal["study", "wrong_queue"] = "study"


class ReviewStateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    item_id: int
    due_at: datetime
    interval_days: int
    ease: float
    reps: int
    lapses: int


@router.post("/review/answer", response_model=ReviewStateOut)
async def answer(
    body: AnswerIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReviewStateOut:
    item = await db.get(Item, body.item_id)
    if item is None or item.status != "published":
        raise HTTPException(status_code=404, detail="Item not found")
    if item.kind == "question" and body.grade not in ("again", "good"):
        raise HTTPException(
            status_code=422, detail="Questions are graded good or again"
        )
    row = await apply_review(
        db,
        user_id=user.id,
        item_id=item.id,
        grade=body.grade,
        context=body.source,
        now=utcnow(),
    )
    await db.commit()
    return ReviewStateOut.model_validate(row)


class QueueCardOut(BaseModel):
    item_id: int
    topic_id: int
    topic_name: str
    kind: str
    level: str
    content: dict[str, Any]
    is_new: bool
    due_at: datetime | None


class StatsOut(BaseModel):
    due_today: int
    new_remaining: int
    reviews_today: int
    accuracy_7d: float
    streak_days: int


def _card_out(card: QueueCard) -> QueueCardOut:
    return QueueCardOut(
        item_id=card.item.id,
        topic_id=card.item.topic_id,
        topic_name=card.topic_name,
        kind=card.item.kind,
        level=card.item.level,
        content=card.item.content,
        is_new=card.is_new,
        due_at=card.due_at,
    )


@router.get("/study/queue", response_model=list[QueueCardOut])
async def queue(
    request: Request,
    limit: int = Query(default=30, ge=1, le=100),
    topic_id: int | None = None,
    level: Level | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[QueueCardOut]:
    tz = ZoneInfo(request.app.state.settings.app_timezone)
    cards = await build_queue(
        db,
        user=user,
        now=utcnow(),
        tz=tz,
        limit=limit,
        topic_id=topic_id,
        level=level,
    )
    return [_card_out(card) for card in cards]


@router.get("/review/wrong", response_model=list[QueueCardOut])
async def wrong(
    limit: int = Query(default=30, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[QueueCardOut]:
    cards = await wrong_cards(db, user_id=user.id, now=utcnow(), limit=limit)
    return [_card_out(card) for card in cards]


@router.get("/stats", response_model=StatsOut)
async def get_stats(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StatsOut:
    tz = ZoneInfo(request.app.state.settings.app_timezone)
    result = await stats(db, user=user, now=utcnow(), tz=tz)
    return StatsOut(**result.__dict__)
