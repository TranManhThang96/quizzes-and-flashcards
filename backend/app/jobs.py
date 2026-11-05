"""Hàng đợi job trong Postgres: claim, heartbeat, thu hồi và kết thúc."""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GenerationJob

Clock = Callable[[], datetime]


async def claim_next(session: AsyncSession, *, now: Clock) -> GenerationJob | None:
    """Claim job `queued` lâu nhất. `SKIP LOCKED` để hai worker không nhận trùng."""
    statement = (
        select(GenerationJob)
        .where(GenerationJob.status == "queued")
        .order_by(GenerationJob.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = (await session.execute(statement)).scalar_one_or_none()
    if job is None:
        await session.commit()
        return None
    job.status = "running"
    job.heartbeat_at = now()
    await session.commit()
    return job


async def heartbeat(session: AsyncSession, job_id: int, *, now: Clock) -> bool:
    """Gia hạn heartbeat; trả False nếu job không còn ở trạng thái `running`."""
    job = await session.get(GenerationJob, job_id)
    if job is None or job.status != "running":
        return False
    job.heartbeat_at = now()
    await session.commit()
    return True


async def reclaim_stale(
    session: AsyncSession,
    *,
    now: Clock,
    stale_seconds: float,
    max_attempts: int,
) -> dict[str, int]:
    """Đưa job `running` có heartbeat cũ về `queued`, hoặc `failed` nếu quá số lần."""
    cutoff = now() - timedelta(seconds=stale_seconds)
    statement = (
        select(GenerationJob)
        .where(GenerationJob.status == "running")
        .where(
            or_(
                GenerationJob.heartbeat_at.is_(None),
                GenerationJob.heartbeat_at < cutoff,
            )
        )
        .with_for_update(skip_locked=True)
    )
    requeued = 0
    failed = 0
    for job in (await session.execute(statement)).scalars():
        job.attempts += 1
        if job.attempts >= max_attempts:
            job.status = "failed"
            job.error = f"Worker không phản hồi sau {job.attempts} lần chạy"
            failed += 1
        else:
            job.status = "queued"
            job.heartbeat_at = None
            # The next run starts counting from zero; stale progress must not
            # look like the new run's partial result.
            job.result = None
            job.error = None
            requeued += 1
    await session.commit()
    return {"requeued": requeued, "failed": failed}


async def finish(
    session: AsyncSession,
    job_id: int,
    *,
    status: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> bool:
    """Ghi trạng thái cuối; chỉ áp dụng cho job đang `running`."""
    job = await session.get(GenerationJob, job_id)
    if job is None or job.status != "running":
        return False
    job.status = status
    if result is not None:
        job.result = result
    if error is not None:
        job.error = error[:2000]
    await session.commit()
    return True
