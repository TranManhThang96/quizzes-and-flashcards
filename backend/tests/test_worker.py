import asyncio

from sqlalchemy import select

from app.clock import utcnow
from app.jobs import claim_next
from app.llm import LlmError
from app.models import GenerationJob, Item
from app.worker import heartbeat_loop, iteration, process_job, run_forever
from tests.fake_llm import FakeLlm, batch, flashcard


async def _job_state(app, job_id: int) -> GenerationJob:
    async with app.state.sessionmaker() as session:
        job = await session.get(GenerationJob, job_id)
        assert job is not None
        return job


def flashcard_job_params() -> dict:
    return {"kind": "flashcard", "levels": [{"level": "easy", "count": 1}]}


async def test_one_iteration_claims_runs_and_finishes_a_job(
    app, settings, make_topic, make_source, make_job
):
    topic = await make_topic("Tài chính")
    source = await make_source()
    job = await make_job(
        source_id=source.id, topic_id=topic.id, params=flashcard_job_params()
    )
    llm = FakeLlm([batch(flashcard("easy", "Lãi kép là gì?"))])

    did_work = await iteration(
        app.state.sessionmaker, llm=llm, now=utcnow, settings=settings
    )
    stored = await _job_state(app, job.id)
    async with app.state.sessionmaker() as session:
        items = list((await session.execute(select(Item))).scalars())
    idle = await iteration(
        app.state.sessionmaker, llm=llm, now=utcnow, settings=settings
    )

    assert did_work is True
    assert idle is False
    assert stored.status == "succeeded"
    assert stored.result == {"created": 1, "skipped": 0}
    assert stored.error is None
    assert len(items) == 1


async def test_stop_event_ends_the_loop_before_claiming(
    app, settings, make_topic, make_source, make_job
):
    topic = await make_topic("Tài chính")
    source = await make_source()
    job = await make_job(
        source_id=source.id, topic_id=topic.id, params=flashcard_job_params()
    )
    stop = asyncio.Event()
    stop.set()

    await run_forever(
        app.state.sessionmaker,
        llm=FakeLlm([]),
        now=utcnow,
        settings=settings,
        stop=stop,
    )

    assert (await _job_state(app, job.id)).status == "queued"


async def test_llm_failure_marks_the_job_failed(
    app, settings, make_topic, make_source, make_job
):
    topic = await make_topic("Tài chính")
    source = await make_source()
    job = await make_job(
        source_id=source.id, topic_id=topic.id, params=flashcard_job_params()
    )
    llm = FakeLlm([LlmError("gateway trả 503")])
    async with app.state.sessionmaker() as session:
        assert await claim_next(session, now=utcnow) is not None

    await process_job(
        app.state.sessionmaker, job.id, llm=llm, now=utcnow, settings=settings
    )

    stored = await _job_state(app, job.id)
    assert stored.status == "failed"
    assert "503" in (stored.error or "")


async def test_unexpected_errors_are_recorded_not_raised(
    app, settings, make_topic, make_source, make_job
):
    topic = await make_topic("Tài chính")
    source = await make_source()
    job = await make_job(
        source_id=source.id, topic_id=topic.id, params=flashcard_job_params()
    )

    class Broken:
        async def __call__(self, messages):
            raise RuntimeError("bùm")

    async with app.state.sessionmaker() as session:
        assert await claim_next(session, now=utcnow) is not None

    await process_job(
        app.state.sessionmaker, job.id, llm=Broken(), now=utcnow, settings=settings
    )

    stored = await _job_state(app, job.id)
    assert stored.status == "failed"
    assert "Lỗi nội bộ" in (stored.error or "")


async def test_a_failing_iteration_does_not_kill_the_loop(app, settings, monkeypatch):
    stop = asyncio.Event()
    calls: list[int] = []

    async def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("db tạm mất kết nối")
        stop.set()
        return False

    monkeypatch.setattr("app.worker.iteration", flaky)

    await run_forever(
        app.state.sessionmaker,
        llm=FakeLlm([]),
        now=utcnow,
        settings=settings,
        stop=stop,
    )

    assert len(calls) == 2


async def test_heartbeat_loop_stops_when_the_job_is_not_running(
    app, make_topic, make_source, make_job
):
    topic = await make_topic("Tài chính")
    source = await make_source()
    job = await make_job(source_id=source.id, topic_id=topic.id)
    stop = asyncio.Event()

    # interval 0 nên vòng lặp chạy đúng một nhịp rồi thoát vì job chưa running.
    await heartbeat_loop(
        app.state.sessionmaker, job.id, interval=0.0, now=utcnow, stop=stop
    )

    assert (await _job_state(app, job.id)).status == "queued"
