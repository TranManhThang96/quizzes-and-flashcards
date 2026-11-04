from datetime import UTC, datetime

from app.models import ReviewLog
from tests.conftest import login


async def _admin(client, make_user):
    await make_user("root", "admin-password", role="admin")
    assert (await login(client, "root", "admin-password")).status_code == 200


async def _question(client, topic_id, *, level="easy", prompt="2 + 2?", answer="4"):
    created = await client.post(
        "/api/admin/items",
        json={
            "topic_id": topic_id,
            "level": level,
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
    assert (await client.post(f"/api/admin/items/{item_id}/publish")).status_code == 200
    return item_id


def _config(topic_id, count, level="easy"):
    return {"build_config": [{"topic_id": topic_id, "level": level, "count": count}]}


async def test_preview_reports_each_line_shortage(client, make_user, make_topic):
    await _admin(client, make_user)
    topic = await make_topic("Toán")
    for prompt in ("a?", "b?"):
        await _question(client, topic.id, prompt=prompt)

    resp = await client.post("/api/admin/exams/preview", json=_config(topic.id, 3))

    assert resp.status_code == 200
    body = resp.json()
    line = body["lines"][0]
    assert line["requested"] == 3 and line["available"] == 2
    assert len(line["selected_ids"]) == 2
    assert len(body["items"]) == 2 and body["total"] == 2


async def test_create_refuses_to_fill_the_gap_from_elsewhere(
    client, make_user, make_topic
):
    await _admin(client, make_user)
    topic = await make_topic("Toán")
    await _question(client, topic.id)
    await _question(client, topic.id, level="hard", prompt="khó?")

    resp = await client.post(
        "/api/admin/exams",
        json={"title": "Thiếu câu", **_config(topic.id, 3)},
    )

    assert resp.status_code == 409
    shortage = resp.json()["detail"]["shortages"][0]
    assert shortage == {
        "topic_id": topic.id,
        "level": "easy",
        "requested": 3,
        "available": 1,
        "missing": 2,
    }


async def test_created_exam_is_a_draft_with_ordered_items(
    client, make_user, make_topic
):
    await _admin(client, make_user)
    topic = await make_topic("Toán")
    first = await _question(client, topic.id, prompt="a?")
    second = await _question(client, topic.id, prompt="b?")

    resp = await client.post(
        "/api/admin/exams", json={"title": "Đề 1", **_config(topic.id, 2)}
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "draft"
    assert [item["id"] for item in body["items"]] == [first, second]
    listed = (await client.get("/api/admin/exams")).json()
    assert listed == [
        {"id": body["id"], "title": "Đề 1", "status": "draft", "item_count": 2}
    ]


async def test_prefer_weak_puts_most_failed_first_and_untried_last(
    client, make_user, make_topic, make_item, app
):
    user = await make_user("alice", "correct-horse")
    await _admin(client, make_user)
    topic = await make_topic("Toán")
    worst = await _question(client, topic.id, prompt="worst?")
    middle = await _question(client, topic.id, prompt="middle?")
    untried = await _question(client, topic.id, prompt="untried?")
    async with app.state.sessionmaker() as s:
        for item_id, correct in (
            (worst, False),
            (worst, False),
            (middle, False),
            (middle, True),
            (middle, True),
        ):
            s.add(
                ReviewLog(
                    user_id=user.id,
                    item_id=item_id,
                    grade="good" if correct else "again",
                    correct=correct,
                    context="study",
                    at=datetime.now(UTC),
                )
            )
        await s.commit()

    weak = await client.post(
        "/api/admin/exams/preview",
        json={**_config(topic.id, 3), "prefer_weak": True},
    )
    assert weak.status_code == 200
    assert weak.json()["lines"][0]["selected_ids"] == [worst, middle, untried]

    random = await client.post("/api/admin/exams/preview", json=_config(topic.id, 3))
    assert set(random.json()["lines"][0]["selected_ids"]) == {
        worst,
        middle,
        untried,
    }


async def test_a_locked_answer_cannot_change_but_other_fields_can(
    client, make_user, make_topic
):
    await _admin(client, make_user)
    topic = await make_topic("Toán")
    item_id = await _question(client, topic.id)
    created = await client.post(
        "/api/admin/exams", json={"title": "Đề", **_config(topic.id, 1)}
    )
    exam_id = created.json()["id"]
    assert (await client.post(f"/api/admin/exams/{exam_id}/publish")).status_code == 200

    locked = await client.patch(
        f"/api/admin/items/{item_id}",
        json={
            "content": {
                "type": "mcq",
                "prompt": "2 + 2?",
                "options": ["3", "4"],
                "answer": "3",
                "explanation": "vì 2 + 2 = 4",
            }
        },
    )
    assert locked.status_code == 409

    allowed = await client.patch(
        f"/api/admin/items/{item_id}",
        json={
            "content": {
                "type": "mcq",
                "prompt": "2 + 2?",
                "options": ["3", "4"],
                "answer": "4",
                "explanation": "giải thích mới",
            }
        },
    )
    assert allowed.status_code == 200
    assert allowed.json()["content"]["explanation"] == "giải thích mới"

    # Archiving the exam releases the lock.
    assert (await client.post(f"/api/admin/exams/{exam_id}/archive")).status_code == 200
    released = await client.patch(
        f"/api/admin/items/{item_id}",
        json={
            "content": {
                "type": "mcq",
                "prompt": "2 + 2?",
                "options": ["3", "4"],
                "answer": "3",
                "explanation": "giải thích mới",
            }
        },
    )
    assert released.status_code == 200


async def test_draft_items_can_be_swapped_but_a_published_list_is_frozen(
    client, make_user, make_topic, make_item
):
    await _admin(client, make_user)
    topic = await make_topic("Toán")
    first = await _question(client, topic.id, prompt="a?")
    second = await _question(client, topic.id, prompt="b?")
    flashcard = await make_item(topic.id, status="published")
    exam_id = (
        await client.post(
            "/api/admin/exams", json={"title": "Đề", **_config(topic.id, 1)}
        )
    ).json()["id"]

    assert (
        await client.patch(
            f"/api/admin/exams/{exam_id}", json={"item_ids": [flashcard.id]}
        )
    ).status_code == 422
    assert (
        await client.patch(f"/api/admin/exams/{exam_id}", json={"item_ids": [9999]})
    ).status_code == 404
    assert (
        await client.patch(
            f"/api/admin/exams/{exam_id}", json={"item_ids": [first, first]}
        )
    ).status_code == 422
    swapped = await client.patch(
        f"/api/admin/exams/{exam_id}", json={"item_ids": [second, first]}
    )
    assert swapped.status_code == 200
    assert [item["id"] for item in swapped.json()["items"]] == [second, first]

    assert (await client.post(f"/api/admin/exams/{exam_id}/publish")).status_code == 200
    assert (
        await client.patch(f"/api/admin/exams/{exam_id}", json={"item_ids": [first]})
    ).status_code == 409
    assert (await client.post(f"/api/admin/exams/{exam_id}/publish")).status_code == 409
    assert (await client.delete(f"/api/admin/exams/{exam_id}")).status_code == 409


async def test_publish_refuses_an_item_archived_after_it_was_picked(
    client, make_user, make_topic
):
    await _admin(client, make_user)
    topic = await make_topic("Toán")
    item_id = await _question(client, topic.id)
    exam_id = (
        await client.post(
            "/api/admin/exams", json={"title": "Đề", **_config(topic.id, 1)}
        )
    ).json()["id"]

    archived = await client.post(f"/api/admin/items/{item_id}/archive")
    assert archived.status_code == 200

    assert (await client.post(f"/api/admin/exams/{exam_id}/publish")).status_code == 409


async def test_regular_users_cannot_manage_exams(client, make_user):
    await make_user("alice", "correct-horse")
    await login(client, "alice", "correct-horse")

    assert (await client.get("/api/admin/exams")).status_code == 403
    assert (
        await client.post("/api/admin/exams", json={"title": "x", **_config(1, 1)})
    ).status_code == 403
