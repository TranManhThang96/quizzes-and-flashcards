from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.items import ItemOut
from app.auth.deps import require_admin
from app.db import get_db
from app.exams import BuildLine, LineSelection, select_for_config
from app.models import Exam, ExamItem, Item, Topic, User

router = APIRouter(
    prefix="/api/admin/exams", tags=["admin"], dependencies=[Depends(require_admin)]
)


class BuildRequest(BaseModel):
    build_config: list[BuildLine] = Field(min_length=1, max_length=50)
    prefer_weak: bool = False

    @model_validator(mode="after")
    def _unique_pairs(self) -> "BuildRequest":
        pairs = [(line.topic_id, line.level) for line in self.build_config]
        if len(set(pairs)) != len(pairs):
            raise ValueError("Each topic and level pair may appear only once")
        return self


class ExamIn(BuildRequest):
    title: str = Field(min_length=1, max_length=200)


class ExamPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    item_ids: list[int] | None = None


class ExamSummary(BaseModel):
    id: int
    title: str
    status: str
    item_count: int


class LineOut(BaseModel):
    topic_id: int
    level: str
    requested: int
    available: int
    selected_ids: list[int]


class PreviewOut(BaseModel):
    items: list[ItemOut]
    lines: list[LineOut]
    total: int


class ExamDetail(BaseModel):
    id: int
    title: str
    status: str
    build_config: list[dict[str, Any]]
    created_at: datetime
    items: list[ItemOut]


def _shortages(selections: list[LineSelection]) -> list[dict[str, Any]]:
    return [
        {
            "topic_id": selection.topic_id,
            "level": selection.level,
            "requested": selection.requested,
            "available": selection.available,
            "missing": max(0, selection.requested - selection.available),
        }
        for selection in selections
        if selection.available < selection.requested
    ]


async def _check_topics(db: AsyncSession, lines: list[BuildLine]) -> None:
    ids = {line.topic_id for line in lines}
    found = set((await db.execute(select(Topic.id).where(Topic.id.in_(ids)))).scalars())
    missing = sorted(ids - found)
    if missing:
        raise HTTPException(status_code=404, detail=f"Unknown topic ids: {missing}")


async def _exam_or_404(db: AsyncSession, exam_id: int) -> Exam:
    exam = await db.get(Exam, exam_id)
    if exam is None:
        raise HTTPException(status_code=404, detail="Exam not found")
    return exam


async def _exam_detail(db: AsyncSession, exam: Exam) -> ExamDetail:
    items = list(
        (
            await db.execute(
                select(Item)
                .join(ExamItem, ExamItem.item_id == Item.id)
                .where(ExamItem.exam_id == exam.id)
                .order_by(ExamItem.position)
            )
        ).scalars()
    )
    return ExamDetail(
        id=exam.id,
        title=exam.title,
        status=exam.status,
        build_config=exam.build_config,
        created_at=exam.created_at,
        items=[ItemOut.model_validate(item) for item in items],
    )


@router.get("", response_model=list[ExamSummary])
async def list_exams(
    status: str | None = None, db: AsyncSession = Depends(get_db)
) -> list[ExamSummary]:
    stmt = (
        select(Exam, func.count(ExamItem.item_id))
        .outerjoin(ExamItem, ExamItem.exam_id == Exam.id)
        .group_by(Exam.id)
        .order_by(Exam.id.desc())
    )
    if status is not None:
        stmt = stmt.where(Exam.status == status)
    return [
        ExamSummary(id=exam.id, title=exam.title, status=exam.status, item_count=count)
        for exam, count in (await db.execute(stmt)).all()
    ]


@router.post("/preview", response_model=PreviewOut)
async def preview_exam(
    body: BuildRequest, db: AsyncSession = Depends(get_db)
) -> PreviewOut:
    await _check_topics(db, body.build_config)
    selections = await select_for_config(
        db, body.build_config, prefer_weak=body.prefer_weak
    )
    ids = [item_id for selection in selections for item_id in selection.selected]
    items: list[Item] = []
    if ids:
        by_id = {
            item.id: item
            for item in (
                await db.execute(select(Item).where(Item.id.in_(ids)))
            ).scalars()
        }
        items = [by_id[item_id] for item_id in ids]
    return PreviewOut(
        items=[ItemOut.model_validate(item) for item in items],
        lines=[
            LineOut(
                topic_id=selection.topic_id,
                level=selection.level,
                requested=selection.requested,
                available=selection.available,
                selected_ids=selection.selected,
            )
            for selection in selections
        ],
        total=len(items),
    )


@router.post("", response_model=ExamDetail, status_code=201)
async def create_exam(
    body: ExamIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ExamDetail:
    await _check_topics(db, body.build_config)
    selections = await select_for_config(
        db, body.build_config, prefer_weak=body.prefer_weak
    )
    shortages = _shortages(selections)
    if shortages:
        raise HTTPException(
            status_code=409,
            detail={"message": "Not enough questions", "shortages": shortages},
        )
    exam = Exam(
        title=body.title,
        build_config=[line.model_dump() for line in body.build_config],
        created_by=admin.id,
    )
    db.add(exam)
    await db.flush()
    position = 1
    for selection in selections:
        # Chọn ngẫu nhiên nhưng vị trí cố định: preview hiển thị theo
        # selected_ids, còn đề đã tạo thì xếp theo id để test và UI ổn định.
        for item_id in sorted(selection.selected):
            db.add(ExamItem(exam_id=exam.id, item_id=item_id, position=position))
            position += 1
    await db.commit()
    return await _exam_detail(db, exam)


@router.get("/{exam_id}", response_model=ExamDetail)
async def get_exam(exam_id: int, db: AsyncSession = Depends(get_db)) -> ExamDetail:
    return await _exam_detail(db, await _exam_or_404(db, exam_id))


@router.patch("/{exam_id}", response_model=ExamDetail)
async def patch_exam(
    exam_id: int, body: ExamPatch, db: AsyncSession = Depends(get_db)
) -> ExamDetail:
    exam = await _exam_or_404(db, exam_id)
    if body.title is not None:
        exam.title = body.title
    if body.item_ids is not None:
        if exam.status != "draft":
            raise HTTPException(
                status_code=409, detail="Only a draft exam can change its items"
            )
        ids = body.item_ids
        if not ids:
            raise HTTPException(status_code=422, detail="An exam needs an item")
        if len(set(ids)) != len(ids):
            raise HTTPException(status_code=422, detail="Duplicate item ids")
        items = list((await db.execute(select(Item).where(Item.id.in_(ids)))).scalars())
        if len(items) != len(ids):
            raise HTTPException(status_code=404, detail="Item not found")
        if any(item.kind != "question" for item in items):
            raise HTTPException(
                status_code=422, detail="Exams accept question items only"
            )
        if any(item.status != "published" for item in items):
            raise HTTPException(
                status_code=422, detail="Exams accept published items only"
            )
        await db.execute(delete(ExamItem).where(ExamItem.exam_id == exam.id))
        for position, item_id in enumerate(ids, start=1):
            db.add(ExamItem(exam_id=exam.id, item_id=item_id, position=position))
    await db.commit()
    return await _exam_detail(db, exam)


@router.post("/{exam_id}/publish", response_model=ExamDetail)
async def publish_exam(exam_id: int, db: AsyncSession = Depends(get_db)) -> ExamDetail:
    exam = await _exam_or_404(db, exam_id)
    if exam.status != "draft":
        raise HTTPException(status_code=409, detail="Exam is not a draft")
    items = list(
        (
            await db.execute(
                select(Item)
                .join(ExamItem, ExamItem.item_id == Item.id)
                .where(ExamItem.exam_id == exam.id)
            )
        ).scalars()
    )
    if not items:
        raise HTTPException(status_code=409, detail="Exam has no items")
    # An item can be archived (or otherwise change) between picking and
    # publishing. The published list must still be made of questions.
    if any(item.kind != "question" or item.status != "published" for item in items):
        raise HTTPException(
            status_code=409,
            detail="Every exam item must still be a published question",
        )
    exam.status = "published"
    await db.commit()
    return await _exam_detail(db, exam)


@router.post("/{exam_id}/archive", response_model=ExamDetail)
async def archive_exam(exam_id: int, db: AsyncSession = Depends(get_db)) -> ExamDetail:
    exam = await _exam_or_404(db, exam_id)
    if exam.status == "archived":
        raise HTTPException(status_code=409, detail="Exam is already archived")
    exam.status = "archived"
    await db.commit()
    return await _exam_detail(db, exam)


@router.delete("/{exam_id}", status_code=204)
async def delete_exam(exam_id: int, db: AsyncSession = Depends(get_db)) -> Response:
    exam = await _exam_or_404(db, exam_id)
    if exam.status != "draft":
        raise HTTPException(status_code=409, detail="Only a draft exam can be deleted")
    await db.delete(exam)
    await db.commit()
    return Response(status_code=204)
