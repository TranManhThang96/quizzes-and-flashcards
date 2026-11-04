from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.clock import utcnow
from app.db import get_db
from app.models import (
    AttemptAnswer,
    Exam,
    ExamAttempt,
    ExamItem,
    Item,
    User,
)
from app.reviews import apply_review

router = APIRouter(prefix="/api", tags=["exams"])


class ExamSummary(BaseModel):
    id: int
    title: str
    item_count: int


class PublicItem(BaseModel):
    item_id: int
    position: int
    topic_id: int
    level: str
    question_type: str
    prompt: str
    options: list[str]


class ExamDetail(BaseModel):
    id: int
    title: str
    items: list[PublicItem]


class AttemptItem(PublicItem):
    saved_answer: str | None
    correct: bool | None
    answer: str | None
    explanation: str | None


class AttemptOut(BaseModel):
    id: int
    exam_id: int
    submitted_at: datetime | None
    score: int | None
    items: list[AttemptItem]


class AnswerIn(BaseModel):
    answer: str = Field(max_length=2000)


def _public_item(item: Item, position: int) -> PublicItem:
    content: dict[str, Any] = item.content
    return PublicItem(
        item_id=item.id,
        position=position,
        topic_id=item.topic_id,
        level=item.level,
        question_type=content["type"],
        prompt=content["prompt"],
        options=content["options"],
    )


async def _published_exam(db: AsyncSession, exam_id: int) -> Exam:
    exam = await db.get(Exam, exam_id)
    if exam is None or exam.status != "published":
        raise HTTPException(status_code=404, detail="Exam not found")
    return exam


async def _own_attempt(
    db: AsyncSession, attempt_id: int, user_id: int, *, lock: bool = False
) -> ExamAttempt:
    stmt = select(ExamAttempt).where(ExamAttempt.id == attempt_id)
    if lock:
        # Serialises concurrent submit/save requests for the same attempt.
        stmt = stmt.with_for_update()
    attempt = (await db.execute(stmt)).scalar_one_or_none()
    if attempt is None or attempt.user_id != user_id:
        raise HTTPException(status_code=404, detail="Attempt not found")
    return attempt


async def _attempt_out(db: AsyncSession, attempt: ExamAttempt) -> AttemptOut:
    rows = (
        await db.execute(
            select(ExamItem.position, Item)
            .join(Item, Item.id == ExamItem.item_id)
            .where(ExamItem.exam_id == attempt.exam_id)
            .order_by(ExamItem.position)
        )
    ).all()
    answers = {
        answer.item_id: answer
        for answer in (
            await db.execute(
                select(AttemptAnswer).where(AttemptAnswer.attempt_id == attempt.id)
            )
        ).scalars()
    }
    submitted = attempt.submitted_at is not None
    items: list[AttemptItem] = []
    for position, item in rows:
        public = _public_item(item, position)
        saved = answers.get(item.id)
        items.append(
            AttemptItem(
                **public.model_dump(),
                saved_answer=saved.answer if saved is not None else None,
                correct=saved.correct if submitted and saved is not None else None,
                # Snapshot written at submit time, not the live item: editing
                # an item later must not rewrite an old attempt's result.
                answer=saved.answer_text if submitted and saved is not None else None,
                explanation=(
                    saved.explanation_text if submitted and saved is not None else None
                ),
            )
        )
    return AttemptOut(
        id=attempt.id,
        exam_id=attempt.exam_id,
        submitted_at=attempt.submitted_at,
        score=attempt.score,
        items=items,
    )


@router.get("/exams", response_model=list[ExamSummary])
async def list_exams(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[ExamSummary]:
    stmt = (
        select(Exam, func.count(ExamItem.item_id))
        .outerjoin(ExamItem, ExamItem.exam_id == Exam.id)
        .where(Exam.status == "published")
        .group_by(Exam.id)
        .order_by(Exam.id)
    )
    return [
        ExamSummary(id=exam.id, title=exam.title, item_count=count)
        for exam, count in (await db.execute(stmt)).all()
    ]


@router.get("/exams/{exam_id}", response_model=ExamDetail)
async def get_exam(
    exam_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExamDetail:
    exam = await _published_exam(db, exam_id)
    rows = (
        await db.execute(
            select(ExamItem.position, Item)
            .join(Item, Item.id == ExamItem.item_id)
            .where(ExamItem.exam_id == exam.id)
            .order_by(ExamItem.position)
        )
    ).all()
    return ExamDetail(
        id=exam.id,
        title=exam.title,
        items=[_public_item(item, position) for position, item in rows],
    )


@router.post("/exams/{exam_id}/attempts", response_model=AttemptOut, status_code=201)
async def start_attempt(
    exam_id: int,
    response: Response,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AttemptOut:
    user_id = user.id
    exam = await _published_exam(db, exam_id)
    existing = (
        (
            await db.execute(
                select(ExamAttempt)
                .where(
                    ExamAttempt.user_id == user_id,
                    ExamAttempt.exam_id == exam.id,
                    ExamAttempt.submitted_at.is_(None),
                )
                .order_by(ExamAttempt.id.desc())
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        response.status_code = 200
        return await _attempt_out(db, existing)
    attempt = ExamAttempt(user_id=user_id, exam_id=exam.id)
    db.add(attempt)
    try:
        await db.commit()
    except IntegrityError:
        # Two requests opened an attempt at the same time. The partial unique
        # index `uq_exam_attempts_open` lets exactly one win; return its row.
        await db.rollback()
        winner = (
            (
                await db.execute(
                    select(ExamAttempt).where(
                        ExamAttempt.user_id == user_id,
                        ExamAttempt.exam_id == exam_id,
                        ExamAttempt.submitted_at.is_(None),
                    )
                )
            )
            .scalars()
            .first()
        )
        if winner is None:
            raise HTTPException(
                status_code=409, detail="Attempt already submitted"
            ) from None
        response.status_code = 200
        return await _attempt_out(db, winner)
    return await _attempt_out(db, attempt)


@router.get("/attempts/{attempt_id}", response_model=AttemptOut)
async def get_attempt(
    attempt_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AttemptOut:
    return await _attempt_out(db, await _own_attempt(db, attempt_id, user.id))


@router.put("/attempts/{attempt_id}/answers/{item_id}", status_code=204)
async def save_answer(
    attempt_id: int,
    item_id: int,
    body: AnswerIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    attempt = await _own_attempt(db, attempt_id, user.id, lock=True)
    if attempt.submitted_at is not None:
        raise HTTPException(status_code=409, detail="Attempt already submitted")
    belongs = (
        await db.execute(
            select(ExamItem).where(
                ExamItem.exam_id == attempt.exam_id,
                ExamItem.item_id == item_id,
            )
        )
    ).scalar_one_or_none()
    if belongs is None:
        raise HTTPException(status_code=404, detail="Item not in this exam")
    item = await db.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    if body.answer not in item.content.get("options", []):
        raise HTTPException(status_code=422, detail="Answer must be an option")
    row = await db.get(AttemptAnswer, (attempt.id, item_id))
    now = utcnow()
    if row is None:
        db.add(
            AttemptAnswer(
                attempt_id=attempt.id,
                item_id=item_id,
                answer=body.answer,
                answered_at=now,
            )
        )
    else:
        row.answer = body.answer
        row.answered_at = now
    await db.commit()
    return Response(status_code=204)


@router.post("/attempts/{attempt_id}/submit", response_model=AttemptOut)
async def submit_attempt(
    attempt_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AttemptOut:
    attempt = await _own_attempt(db, attempt_id, user.id, lock=True)
    if attempt.submitted_at is not None:
        raise HTTPException(status_code=409, detail="Attempt already submitted")
    items = list(
        (
            await db.execute(
                select(Item)
                .join(ExamItem, ExamItem.item_id == Item.id)
                .where(ExamItem.exam_id == attempt.exam_id)
            )
        ).scalars()
    )
    answers = {
        answer.item_id: answer
        for answer in (
            await db.execute(
                select(AttemptAnswer).where(AttemptAnswer.attempt_id == attempt.id)
            )
        ).scalars()
    }
    now = utcnow()
    correct_count = 0
    for item in items:
        row = answers.get(item.id)
        correct = row is not None and row.answer == item.content.get("answer")
        if correct:
            correct_count += 1
        if row is None:
            db.add(
                AttemptAnswer(
                    attempt_id=attempt.id,
                    item_id=item.id,
                    answer=None,
                    correct=correct,
                    answer_text=item.content.get("answer"),
                    explanation_text=item.content.get("explanation", ""),
                    answered_at=now,
                )
            )
        else:
            row.correct = correct
            row.answer_text = item.content.get("answer")
            row.explanation_text = item.content.get("explanation", "")
        await apply_review(
            db,
            user_id=user.id,
            item_id=item.id,
            grade="good" if correct else "again",
            context="exam",
            now=now,
        )
    attempt.submitted_at = now
    attempt.score = int(100 * correct_count / len(items) + 0.5) if items else 0
    await db.commit()
    return await _attempt_out(db, attempt)
