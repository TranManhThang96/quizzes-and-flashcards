import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.models import ReviewLog, ReviewState
from tests.conftest import login


async def _admin(client, make_user):
    await make_user("root", "admin-password", role="admin")
    assert (await login(client, "root", "admin-password")).status_code == 200


async def _question(client, topic_id, *, prompt, answer):
    created = await client.post(
        "/api/admin/items",
        json={
            "topic_id": topic_id,
            "level": "easy",
            "kind": "question",
            "content": {
                "type": "mcq",
                "prompt": prompt,
                "options": ["3", "4"],
                "answer": answer,
                "explanation": "vì 2 + 2 = 4",
            },
        },
    )
    item_id = created.json()["id"]
    await client.post(f"/api/admin/items/{item_id}/publish")
    return item_id


async def _published_exam(client, make_user, make_topic):
    await _admin(client, make_user)
    topic = await make_topic("Toán")
    ids = [
        await _question(client, topic.id, prompt="một?", answer="4"),
        await _question(client, topic.id, prompt="hai?", answer="4"),
        await _question(client, topic.id, prompt="ba?", answer="3"),
    ]
    created = await client.post(
        "/api/admin/exams",
        json={
            "title": "Đề 1",
            "build_config": [{"topic_id": topic.id, "level": "easy", "count": 3}],
        },
    )
    exam_id = created.json()["id"]
    assert (await client.post(f"/api/admin/exams/{exam_id}/publish")).status_code == 200
    return exam_id, ids


async def test_exam_detail_never_leaks_answers(client, make_user, make_topic):
    exam_id, _ = await _published_exam(client, make_user, make_topic)

    resp = await client.get(f"/api/exams/{exam_id}")

    assert resp.status_code == 200
    for item in resp.json()["items"]:
        assert set(item) == {
            "item_id",
            "position",
            "topic_id",
            "level",
            "question_type",
            "prompt",
            "options",
        }
    assert "vì 2 + 2 = 4" not in resp.text


async def test_starting_an_attempt_resumes_the_unfinished_one(
    client, make_user, make_topic
):
    exam_id, _ = await _published_exam(client, make_user, make_topic)

    first = await client.post(f"/api/exams/{exam_id}/attempts")
    second = await client.post(f"/api/exams/{exam_id}/attempts")

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert first.json()["submitted_at"] is None
    assert first.json()["score"] is None


async def test_answers_are_saved_without_grading(client, make_user, make_topic):
    exam_id, _ = await _published_exam(client, make_user, make_topic)
    attempt = (await client.post(f"/api/exams/{exam_id}/attempts")).json()
    item = attempt["items"][0]

    saved = await client.put(
        f"/api/attempts/{attempt['id']}/answers/{item['item_id']}",
        json={"answer": "4"},
    )
    loaded = (await client.get(f"/api/attempts/{attempt['id']}")).json()

    assert saved.status_code == 204
    assert loaded["items"][0]["saved_answer"] == "4"
    assert loaded["items"][0]["correct"] is None
    assert loaded["items"][0]["answer"] is None
    assert loaded["items"][0]["explanation"] is None


async def test_submit_grades_once_and_updates_review_states(
    client, make_user, make_topic, app
):
    exam_id, _ = await _published_exam(client, make_user, make_topic)
    attempt = (await client.post(f"/api/exams/{exam_id}/attempts")).json()
    first, second, third = attempt["items"]
    await client.put(
        f"/api/attempts/{attempt['id']}/answers/{first['item_id']}",
        json={"answer": "4"},
    )
    await client.put(
        f"/api/attempts/{attempt['id']}/answers/{second['item_id']}",
        json={"answer": "4"},
    )

    submitted = await client.post(f"/api/attempts/{attempt['id']}/submit")

    assert submitted.status_code == 200
    body = submitted.json()
    assert body["score"] == 67
    assert body["submitted_at"] is not None
    assert [item["correct"] for item in body["items"]] == [True, True, False]
    assert body["items"][0]["answer"] == "4"
    assert body["items"][0]["explanation"] == "vì 2 + 2 = 4"
    assert body["items"][2]["saved_answer"] is None

    assert (
        await client.post(f"/api/attempts/{attempt['id']}/submit")
    ).status_code == 409
    assert (
        await client.put(
            f"/api/attempts/{attempt['id']}/answers/{first['item_id']}",
            json={"answer": "3"},
        )
    ).status_code == 409

    async with app.state.sessionmaker() as s:
        states = {
            state.item_id: state
            for state in (await s.execute(select(ReviewState))).scalars()
        }
    wrong = states[third["item_id"]]
    assert wrong.lapses == 1 and wrong.reps == 0
    assert wrong.due_at <= datetime.now(UTC) + timedelta(minutes=11)
    assert states[first["item_id"]].reps == 1
    assert states[first["item_id"]].lapses == 0


async def test_an_answer_must_be_one_of_the_options(client, make_user, make_topic):
    exam_id, _ = await _published_exam(client, make_user, make_topic)
    attempt = (await client.post(f"/api/exams/{exam_id}/attempts")).json()
    item = attempt["items"][0]

    resp = await client.put(
        f"/api/attempts/{attempt['id']}/answers/{item['item_id']}",
        json={"answer": "42"},
    )

    assert resp.status_code == 422


async def test_attempts_belong_to_one_user(client, other_client, make_user, make_topic):
    exam_id, _ = await _published_exam(client, make_user, make_topic)
    attempt = (await client.post(f"/api/exams/{exam_id}/attempts")).json()

    await make_user("bob", "correct-horse")
    await login(other_client, "bob", "correct-horse")

    assert (await other_client.get(f"/api/attempts/{attempt['id']}")).status_code == 404
    assert (
        await other_client.post(f"/api/attempts/{attempt['id']}/submit")
    ).status_code == 404


async def test_published_exams_keep_archived_items(client, make_user, make_topic):
    exam_id, ids = await _published_exam(client, make_user, make_topic)
    assert (await client.post(f"/api/admin/items/{ids[0]}/archive")).status_code == 200

    detail = await client.get(f"/api/exams/{exam_id}")

    assert [item["item_id"] for item in detail.json()["items"]] == ids


async def test_past_results_do_not_change_when_an_item_is_edited(
    client, make_user, make_topic
):
    exam_id, ids = await _published_exam(client, make_user, make_topic)
    attempt = (await client.post(f"/api/exams/{exam_id}/attempts")).json()
    item = attempt["items"][0]
    await client.put(
        f"/api/attempts/{attempt['id']}/answers/{item['item_id']}",
        json={"answer": "4"},
    )
    await client.post(f"/api/attempts/{attempt['id']}/submit")
    await client.post(f"/api/admin/exams/{exam_id}/archive")

    await client.patch(
        f"/api/admin/items/{ids[0]}",
        json={
            "content": {
                "type": "mcq",
                "prompt": "đã đổi?",
                "options": ["3", "4"],
                "answer": "3",
                "explanation": "đã đổi",
            }
        },
    )

    loaded = (await client.get(f"/api/attempts/{attempt['id']}")).json()
    assert loaded["score"] == 33
    assert loaded["items"][0]["correct"] is True
    # The result must show the answer that was graded, not the edited one.
    assert loaded["items"][0]["answer"] == "4"
    assert loaded["items"][0]["explanation"] == "vì 2 + 2 = 4"


async def test_concurrent_submit_grades_only_once(client, make_user, make_topic, app):
    exam_id, _ = await _published_exam(client, make_user, make_topic)
    attempt = (await client.post(f"/api/exams/{exam_id}/attempts")).json()

    responses = await asyncio.gather(
        client.post(f"/api/attempts/{attempt['id']}/submit"),
        client.post(f"/api/attempts/{attempt['id']}/submit"),
    )

    assert sorted(response.status_code for response in responses) == [200, 409]
    async with app.state.sessionmaker() as session:
        logs = (
            await session.execute(select(func.count()).select_from(ReviewLog))
        ).scalar_one()
    assert logs == len(attempt["items"])


async def test_only_published_exams_are_visible(client, make_user, make_topic):
    exam_id, _ = await _published_exam(client, make_user, make_topic)

    assert [exam["id"] for exam in (await client.get("/api/exams")).json()] == [exam_id]
    await client.post(f"/api/admin/exams/{exam_id}/archive")

    assert (await client.get("/api/exams")).json() == []
    assert (await client.get(f"/api/exams/{exam_id}")).status_code == 404
