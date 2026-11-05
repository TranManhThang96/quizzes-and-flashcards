"""Tạo và theo dõi job sinh nội dung."""

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import require_admin
from app.config import Settings
from app.db import get_db
from app.generation import JobParams
from app.models import GenerationJob, Source, Topic, User

router = APIRouter(
    prefix="/api/admin/jobs", tags=["admin"], dependencies=[Depends(require_admin)]
)

JobStatus = Literal["queued", "running", "succeeded", "failed"]


class JobIn(BaseModel):
    source_id: int
    topic_id: int
    params: JobParams


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    topic_id: int
    params: dict[str, Any]
    status: str
    attempts: int
    result: dict[str, Any] | None
    error: str | None
    heartbeat_at: datetime | None
    created_at: datetime


@router.get("", response_model=list[JobOut])
async def list_jobs(
    status: JobStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: AsyncSession = Depends(get_db),
) -> list[GenerationJob]:
    statement = (
        select(GenerationJob)
        .order_by(GenerationJob.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if status is not None:
        statement = statement.where(GenerationJob.status == status)
    return list((await db.execute(statement)).scalars())


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: int, db: AsyncSession = Depends(get_db)) -> GenerationJob:
    job = await db.get(GenerationJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("", response_model=JobOut, status_code=201)
async def add_job(
    body: JobIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> GenerationJob:
    settings: Settings = request.app.state.settings
    if body.params.total > settings.max_job_items:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Tổng số item {body.params.total} vượt giới hạn "
                f"{settings.max_job_items} mỗi job"
            ),
        )
    source = await db.get(Source, body.source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    if not source.text.strip():
        raise HTTPException(status_code=422, detail="Nguồn không có văn bản")
    if await db.get(Topic, body.topic_id) is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    job = GenerationJob(
        source_id=body.source_id,
        topic_id=body.topic_id,
        params=body.params.model_dump(),
        created_by=admin.id,
    )
    db.add(job)
    await db.commit()
    return job
