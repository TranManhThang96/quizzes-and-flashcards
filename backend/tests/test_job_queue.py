import asyncio
from datetime import UTC, datetime, timedelta

from app.clock import utcnow
from app.jobs import claim_next, finish, heartbeat, reclaim_stale
from app.models import GenerationJob


async def _job_state(app, job_id: int) -> GenerationJob:
    async with app.state.sessionmaker() as session:
        job = await session.get(GenerationJob, job_id)
        assert job is not None
        return job


async def test_claiming_moves_the_job_to_running(
    app, make_topic, make_source, make_job
):
    topic = await make_topic("Toán")
    source = await make_source()
    job = await make_job(source_id=source.id, topic_id=topic.id)

    async with app.state.sessionmaker() as session:
        claimed = await claim_next(session, now=utcnow)
    async with app.state.sessionmaker() as session:
        assert await claim_next(session, now=utcnow) is None

    assert claimed is not None and claimed.id == job.id
    stored = await _job_state(app, job.id)
    assert stored.status == "running"
    assert stored.heartbeat_at is not None


async def test_two_workers_claim_a_single_job_exactly_once(
    app, make_topic, make_source, make_job
):
    topic = await make_topic("Toán")
    source = await make_source()
    job = await make_job(source_id=source.id, topic_id=topic.id)

    async def claim():
        async with app.state.sessionmaker() as session:
            return await claim_next(session, now=utcnow)

    first, second = await asyncio.gather(claim(), claim())

    winners = [candidate for candidate in (first, second) if candidate is not None]
    assert [candidate.id for candidate in winners] == [job.id]


async def test_heartbeat_only_extends_a_running_job(
    app, make_topic, make_source, make_job
):
    topic = await make_topic("Toán")
    source = await make_source()
    job = await make_job(source_id=source.id, topic_id=topic.id)

    fixed = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)

    async with app.state.sessionmaker() as session:
        assert await heartbeat(session, job.id, now=utcnow) is False
        await claim_next(session, now=lambda: datetime(2020, 1, 1, tzinfo=UTC))
    async with app.state.sessionmaker() as session:
        assert await heartbeat(session, job.id, now=lambda: fixed) is True
    stored = await _job_state(app, job.id)
    assert stored.heartbeat_at == fixed


async def test_a_job_with_an_old_heartbeat_is_requeued_with_one_more_attempt(
    app, make_topic, make_source, make_job
):
    topic = await make_topic("Toán")
    source = await make_source()
    job = await make_job(source_id=source.id, topic_id=topic.id, status="running")
    async with app.state.sessionmaker() as session:
        row = await session.get(GenerationJob, job.id)
        row.heartbeat_at = datetime.now(UTC) - timedelta(minutes=10)
        await session.commit()

    async with app.state.sessionmaker() as session:
        outcome = await reclaim_stale(
            session, now=utcnow, stale_seconds=300, max_attempts=3
        )

    assert outcome == {"requeued": 1, "failed": 0}
    stored = await _job_state(app, job.id)
    assert stored.status == "queued"
    assert stored.attempts == 1
    assert stored.heartbeat_at is None


async def test_a_stale_job_fails_after_the_last_allowed_attempt(
    app, make_topic, make_source, make_job
):
    topic = await make_topic("Toán")
    source = await make_source()
    job = await make_job(source_id=source.id, topic_id=topic.id, status="running")
    async with app.state.sessionmaker() as session:
        row = await session.get(GenerationJob, job.id)
        row.heartbeat_at = datetime.now(UTC) - timedelta(minutes=10)
        row.attempts = 2
        await session.commit()

    async with app.state.sessionmaker() as session:
        outcome = await reclaim_stale(
            session, now=utcnow, stale_seconds=300, max_attempts=3
        )

    assert outcome == {"requeued": 0, "failed": 1}
    stored = await _job_state(app, job.id)
    assert stored.status == "failed"
    assert stored.attempts == 3
    assert "không phản hồi" in (stored.error or "")


async def test_a_fresh_running_job_is_left_alone(
    app, make_topic, make_source, make_job
):
    topic = await make_topic("Toán")
    source = await make_source()
    job = await make_job(source_id=source.id, topic_id=topic.id, status="running")
    async with app.state.sessionmaker() as session:
        row = await session.get(GenerationJob, job.id)
        row.heartbeat_at = utcnow()
        await session.commit()

    async with app.state.sessionmaker() as session:
        outcome = await reclaim_stale(
            session, now=utcnow, stale_seconds=300, max_attempts=3
        )

    assert outcome == {"requeued": 0, "failed": 0}
    assert (await _job_state(app, job.id)).status == "running"


async def test_finish_only_settles_a_running_job(
    app, make_topic, make_source, make_job
):
    topic = await make_topic("Toán")
    source = await make_source()
    job = await make_job(source_id=source.id, topic_id=topic.id)

    async with app.state.sessionmaker() as session:
        assert await finish(session, job.id, status="succeeded") is False
        await claim_next(session, now=utcnow)
    async with app.state.sessionmaker() as session:
        assert (
            await finish(
                session,
                job.id,
                status="succeeded",
                result={"created": 1, "skipped": 0},
            )
            is True
        )
        assert await finish(session, job.id, status="failed") is False

    stored = await _job_state(app, job.id)
    assert stored.status == "succeeded"
    assert stored.result == {"created": 1, "skipped": 0}
