import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Source


async def test_a_source_cannot_be_deleted_while_an_item_references_it(
    app, make_topic, make_item, make_source
):
    topic = await make_topic("Tài chính")
    source = await make_source()
    item = await make_item(topic.id, content={"front": "a", "back": "b"})

    async with app.state.sessionmaker() as session:
        item_row = await session.get(type(item), item.id)
        item_row.source_id = source.id
        await session.commit()

        with pytest.raises(IntegrityError):
            await session.delete(await session.get(Source, source.id))
            await session.commit()
        await session.rollback()

    async with app.state.sessionmaker() as session:
        assert await session.get(Source, source.id) is not None


async def test_a_new_source_has_no_url_unless_it_came_from_one(app, make_source):
    text_source = await make_source()
    url_source = await make_source(kind="url", url="https://example.com/a")

    assert text_source.url is None
    assert url_source.url == "https://example.com/a"
    assert text_source.kind == "text"


async def test_a_job_starts_queued_with_no_attempts(
    app, make_topic, make_source, make_job
):
    topic = await make_topic("Toán")
    source = await make_source()

    job = await make_job(source_id=source.id, topic_id=topic.id)

    assert job.status == "queued"
    assert job.attempts == 0
    assert job.result is None
    assert job.heartbeat_at is None


async def test_an_unknown_job_status_is_rejected_by_the_database(
    app, make_topic, make_source, make_job
):
    topic = await make_topic("Toán")
    source = await make_source()
    job = await make_job(source_id=source.id, topic_id=topic.id)

    async with app.state.sessionmaker() as session:
        row = await session.get(type(job), job.id)
        row.status = "exploded"
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
