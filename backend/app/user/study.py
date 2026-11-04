from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.clock import utcnow
from app.db import get_db
from app.models import Item, User
from app.reviews import apply_review
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
