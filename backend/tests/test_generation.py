import pytest
from sqlalchemy import select

from app.clock import utcnow
from app.generation import GenerationError, run_job
from app.models import GenerationJob, Item
from tests.fake_llm import FakeLlm, batch, flashcard


async def _run(app, job_id, llm, chunk_chars: int = 8000):
    async with app.state.sessionmaker() as session:
        job = await session.get(GenerationJob, job_id)
        return await run_job(session, job, llm=llm, now=utcnow, chunk_chars=chunk_chars)


async def _items(app):
    async with app.state.sessionmaker() as session:
        return list((await session.execute(select(Item).order_by(Item.id))).scalars())


async def test_created_items_are_drafts_with_the_source(
    app, make_topic, make_source, make_job
):
    topic = await make_topic("Tài chính")
    source = await make_source()
    job = await make_job(
        source_id=source.id,
        topic_id=topic.id,
        params={"kind": "flashcard", "levels": [{"level": "easy", "count": 2}]},
    )
    llm = FakeLlm(
        [
            batch(
                flashcard("easy", "Lãi kép là gì?"),
                flashcard("easy", "Lạm phát là gì?"),
            )
        ]
    )

    result = await _run(app, job.id, llm)

    assert result == {"created": 2, "skipped": 0}
    items = await _items(app)
    assert {item.status for item in items} == {"draft"}
    assert {item.source_id for item in items} == {source.id}
    assert {item.level for item in items} == {"easy"}


async def test_existing_and_archived_content_is_skipped(
    app, make_topic, make_source, make_job, make_item
):
    topic = await make_topic("Tài chính")
    source = await make_source()
    await make_item(topic.id, content={"front": "Lãi kép là gì?", "back": "cũ"})
    await make_item(
        topic.id,
        content={"front": "Lạm phát là gì?", "back": "cũ"},
        status="archived",
    )
    job = await make_job(
        source_id=source.id,
        topic_id=topic.id,
        params={"kind": "flashcard", "levels": [{"level": "easy", "count": 3}]},
    )
    llm = FakeLlm(
        [
            batch(
                flashcard("easy", "Lãi kép là gì?"),
                flashcard("easy", "LẠM PHÁT  là gì?"),
                flashcard("easy", "Cổ phiếu là gì?"),
            )
        ]
    )

    result = await _run(app, job.id, llm)

    assert result == {"created": 1, "skipped": 2}
    assert len(await _items(app)) == 3


async def test_rerunning_the_same_job_creates_no_duplicates(
    app, make_topic, make_source, make_job
):
    topic = await make_topic("Tài chính")
    source = await make_source()
    job = await make_job(
        source_id=source.id,
        topic_id=topic.id,
        params={"kind": "flashcard", "levels": [{"level": "easy", "count": 2}]},
    )
    answers = [
        flashcard("easy", "Lãi kép là gì?"),
        flashcard("easy", "Cổ phiếu là gì?"),
    ]

    first = await _run(app, job.id, FakeLlm([batch(*answers)]))
    second = await _run(app, job.id, FakeLlm([batch(*answers)]))

    assert first == {"created": 2, "skipped": 0}
    assert second == {"created": 0, "skipped": 2}
    assert len(await _items(app)) == 2


async def test_counts_are_distributed_across_chunks(
    app, make_topic, make_source, make_job
):
    topic = await make_topic("Tài chính")
    text = "\n\n".join(f"Đoạn {index} " + "x" * 40 for index in range(3))
    source = await make_source(text=text)
    job = await make_job(
        source_id=source.id,
        topic_id=topic.id,
        params={"kind": "flashcard", "levels": [{"level": "easy", "count": 6}]},
    )
    llm = FakeLlm(
        [
            batch(*(flashcard("easy", f"câu {chunk}-{index}") for index in range(2)))
            for chunk in range(3)
        ]
    )

    result = await _run(app, job.id, llm, chunk_chars=60)

    assert len(llm.calls) == 3
    assert result == {"created": 6, "skipped": 0}
    for call in llm.calls:
        assert "easy: 2" in call[1]["content"]


async def test_invalid_params_fail_the_job_before_calling_the_llm(
    app, make_topic, make_source, make_job
):
    topic = await make_topic("Tài chính")
    source = await make_source()
    job = await make_job(
        source_id=source.id,
        topic_id=topic.id,
        params={"kind": "podcast", "levels": [{"level": "easy", "count": 1}]},
    )
    llm = FakeLlm([])

    with pytest.raises(GenerationError):
        await _run(app, job.id, llm)

    assert llm.calls == []
