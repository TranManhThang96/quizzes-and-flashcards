"""Vòng lặp worker: claim job trong `generation_jobs` rồi chạy tuần tự.

Chạy bằng `python -m app.worker` trong container `worker`. Mọi hàm ở đây tách
khỏi vòng lặp để test gọi trực tiếp, không cần `sleep`.
"""

import asyncio
import contextlib
import logging
import signal
from collections.abc import Callable
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clock import utcnow
from app.config import Settings
from app.db import make_engine, make_sessionmaker
from app.generation import GenerationError, run_job
from app.jobs import claim_next, finish, heartbeat, reclaim_stale
from app.llm import JsonLlm, LlmError, OpenAiJsonLlm
from app.models import GenerationJob

Sessionmaker = async_sessionmaker[AsyncSession]
Clock = Callable[[], datetime]

log = logging.getLogger("app.worker")


async def heartbeat_loop(
    sessionmaker: Sessionmaker,
    job_id: int,
    *,
    interval: float,
    now: Clock,
    stop: asyncio.Event,
) -> None:
    """Gia hạn heartbeat mỗi `interval` giây cho tới khi job xong hoặc dừng."""
    while not stop.is_set():
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        async with sessionmaker() as session:
            if not await heartbeat(session, job_id, now=now):
                return


async def process_job(
    sessionmaker: Sessionmaker,
    job_id: int,
    *,
    llm: JsonLlm,
    now: Clock,
    settings: Settings,
) -> None:
    """Chạy một job đã claim, có heartbeat nền, rồi ghi trạng thái cuối."""
    stop = asyncio.Event()
    beat = asyncio.create_task(
        heartbeat_loop(
            sessionmaker,
            job_id,
            interval=settings.worker_heartbeat_seconds,
            now=now,
            stop=stop,
        )
    )
    try:
        async with sessionmaker() as session:
            job = await session.get(GenerationJob, job_id)
            if job is None:
                return
            result = await run_job(
                session,
                job,
                llm=llm,
                now=now,
                chunk_chars=settings.llm_chunk_chars,
            )
    except (GenerationError, LlmError) as exc:
        log.warning("job %s failed: %s", job_id, exc)
        await _settle(sessionmaker, job_id, status="failed", error=str(exc))
    except Exception as exc:  # noqa: BLE001 - job lỗi bất ngờ vẫn phải đóng lại
        log.exception("job %s crashed", job_id)
        await _settle(sessionmaker, job_id, status="failed", error=f"Lỗi nội bộ: {exc}")
    else:
        await _settle(sessionmaker, job_id, status="succeeded", result=result)
    finally:
        stop.set()
        await beat


async def _settle(
    sessionmaker: Sessionmaker,
    job_id: int,
    *,
    status: str,
    result: dict[str, int] | None = None,
    error: str | None = None,
) -> None:
    async with sessionmaker() as session:
        if not await finish(session, job_id, status=status, result=result, error=error):
            # The job was reclaimed while this worker was still running; its
            # late result must not overwrite the newer run.
            log.warning("job %s was reclaimed; late %s ignored", job_id, status)


async def iteration(
    sessionmaker: Sessionmaker,
    *,
    llm: JsonLlm,
    now: Clock,
    settings: Settings,
) -> bool:
    """Một vòng: thu hồi job chết, claim job kế tiếp, chạy nó. True nếu có việc."""
    async with sessionmaker() as session:
        await reclaim_stale(
            session,
            now=now,
            stale_seconds=settings.worker_stale_seconds,
            max_attempts=settings.worker_max_attempts,
        )
    async with sessionmaker() as session:
        job = await claim_next(session, now=now)
    if job is None:
        return False
    await process_job(sessionmaker, job.id, llm=llm, now=now, settings=settings)
    return True


async def run_forever(
    sessionmaker: Sessionmaker,
    *,
    llm: JsonLlm,
    now: Clock,
    settings: Settings,
    stop: asyncio.Event,
) -> None:
    """Poll mỗi `worker_poll_seconds`; dừng khi `stop` được set (SIGTERM)."""
    while not stop.is_set():
        try:
            did_work = await iteration(
                sessionmaker, llm=llm, now=now, settings=settings
            )
        except Exception:  # noqa: BLE001 - DB restart không được giết worker
            log.exception("vòng lặp job lỗi, thử lại sau")
            did_work = False
        if not did_work:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    stop.wait(), timeout=settings.worker_poll_seconds
                )


async def serve() -> None:
    settings = Settings()
    engine = make_engine(settings.database_url)
    sessionmaker = make_sessionmaker(engine)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    llm: JsonLlm = OpenAiJsonLlm(settings)
    try:
        log.info("worker started")
        await run_forever(
            sessionmaker, llm=llm, now=utcnow, settings=settings, stop=stop
        )
    finally:
        log.info("worker stopped")
        await engine.dispose()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(serve())


if __name__ == "__main__":
    main()
