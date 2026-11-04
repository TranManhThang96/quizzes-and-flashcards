import asyncio
from datetime import timedelta

from sqlalchemy import select

from app.auth.deps import utcnow
from app.models import ReviewLog, ReviewState


async def test_answering_creates_a_state_and_a_log(
    client, app, make_user, make_topic, make_item
):
    user = await make_user("alice", "correct-horse")
    topic = await make_topic("Toán")
    item = await make_item(topic.id, status="published")
    await client.post(
        "/api/auth/login", json={"username": "alice", "password": "correct-horse"}
    )

    resp = await client.post(
        "/api/review/answer", json={"item_id": item.id, "grade": "good"}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["item_id"] == item.id
    assert body["interval_days"] == 1 and body["reps"] == 1
    assert body["ease"] == 2.5 and body["lapses"] == 0

    async with app.state.sessionmaker() as s:
        assert isinstance(await s.get(ReviewState, (user.id, item.id)), ReviewState)
        logs = list((await s.execute(select(ReviewLog))).scalars())
    assert len(logs) == 1 and logs[0].grade == "good" and logs[0].correct is True
    assert logs[0].context == "study"


async def test_grades_accumulate_across_answers(
    client, make_user, make_topic, make_item
):
    await make_user("alice", "correct-horse")
    topic = await make_topic("Toán")
    item = await make_item(topic.id, status="published")
    await client.post(
        "/api/auth/login", json={"username": "alice", "password": "correct-horse"}
    )

    for grade in ("good", "good", "hard"):
        resp = await client.post(
            "/api/review/answer", json={"item_id": item.id, "grade": grade}
        )
        assert resp.status_code == 200

    body = resp.json()
    assert body["reps"] == 2
    assert body["interval_days"] == 4  # 3 * 1.2 = 3.6 -> 4
    assert body["ease"] < 2.5


async def test_a_question_only_takes_good_or_again(
    client, make_user, make_topic, make_item
):
    await make_user("alice", "correct-horse")
    topic = await make_topic("Toán")
    item = await make_item(topic.id, kind="question", status="published")
    await client.post(
        "/api/auth/login", json={"username": "alice", "password": "correct-horse"}
    )

    for grade in ("hard", "easy"):
        resp = await client.post(
            "/api/review/answer", json={"item_id": item.id, "grade": grade}
        )
        assert resp.status_code == 422

    assert (
        await client.post(
            "/api/review/answer", json={"item_id": item.id, "grade": "again"}
        )
    ).status_code == 200


async def test_draft_and_archived_items_are_not_reviewable(
    client, make_user, make_topic, make_item
):
    await make_user("alice", "correct-horse")
    topic = await make_topic("Toán")
    draft = await make_item(topic.id)
    archived = await make_item(topic.id, kind="vocab", status="archived")
    await client.post(
        "/api/auth/login", json={"username": "alice", "password": "correct-horse"}
    )

    for item in (draft, archived):
        resp = await client.post(
            "/api/review/answer", json={"item_id": item.id, "grade": "good"}
        )
        assert resp.status_code == 404
    assert (
        await client.post("/api/review/answer", json={"item_id": 9999, "grade": "good"})
    ).status_code == 404


async def test_the_wrong_queue_source_is_recorded(
    client, app, make_user, make_topic, make_item
):
    await make_user("alice", "correct-horse")
    topic = await make_topic("Toán")
    item = await make_item(topic.id, status="published")
    await client.post(
        "/api/auth/login", json={"username": "alice", "password": "correct-horse"}
    )

    await client.post(
        "/api/review/answer",
        json={"item_id": item.id, "grade": "again", "source": "wrong_queue"},
    )

    async with app.state.sessionmaker() as s:
        log = (await s.execute(select(ReviewLog))).scalar_one()
    assert log.context == "wrong_queue" and log.correct is False
    assert log.at >= utcnow() - timedelta(minutes=1)


async def test_answering_requires_login(client, make_topic, make_item):
    topic = await make_topic("Toán")
    item = await make_item(topic.id, status="published")

    resp = await client.post(
        "/api/review/answer", json={"item_id": item.id, "grade": "good"}
    )

    assert resp.status_code == 401


async def test_simultaneous_answers_for_a_new_item_all_succeed(
    client, app, make_user, make_topic, make_item
):
    await make_user("alice", "correct-horse")
    topic = await make_topic("Toán")
    item = await make_item(topic.id, status="published")
    await client.post(
        "/api/auth/login", json={"username": "alice", "password": "correct-horse"}
    )

    responses = await asyncio.gather(
        *(
            client.post(
                "/api/review/answer", json={"item_id": item.id, "grade": "good"}
            )
            for _ in range(4)
        )
    )

    assert [r.status_code for r in responses] == [200, 200, 200, 200]
    async with app.state.sessionmaker() as s:
        states = list((await s.execute(select(ReviewState))).scalars())
        logs = list((await s.execute(select(ReviewLog))).scalars())
    assert len(states) == 1 and len(logs) == 4
    assert states[0].reps == 4
