from tests.conftest import login


async def _admin(client, make_user):
    await make_user("root", "admin-password", role="admin")
    assert (await login(client, "root", "admin-password")).status_code == 200


async def test_question_content_is_validated(client, make_user):
    await _admin(client, make_user)
    topic_id = (await client.post("/api/admin/topics", json={"name": "Toán"})).json()[
        "id"
    ]
    base = {"topic_id": topic_id, "level": "easy", "kind": "question"}

    for content in (
        {
            "type": "mcq",
            "prompt": "2 + 2?",
            "options": ["4"],
            "answer": "4",
        },
        {
            "type": "mcq",
            "prompt": "2 + 2?",
            "options": ["3", "4"],
            "answer": "5",
        },
        {
            "type": "true_false",
            "prompt": "2 + 2 = 4?",
            "options": ["Đúng", "Sai", "Không rõ"],
            "answer": "Đúng",
        },
        {"type": "short_answer", "prompt": "2 + 2?", "options": ["4"], "answer": "4"},
    ):
        resp = await client.post("/api/admin/items", json={**base, "content": content})
        assert resp.status_code == 422, content

    ok = await client.post(
        "/api/admin/items",
        json={
            **base,
            "content": {
                "type": "mcq",
                "prompt": "2 + 2?",
                "options": ["3", "4"],
                "answer": "4",
            },
        },
    )
    assert ok.status_code == 201
    assert ok.json()["status"] == "draft"
    assert ok.json()["kind"] == "question"


async def test_duplicate_content_is_rejected_after_normalisation(client, make_user):
    await _admin(client, make_user)
    topic_id = (await client.post("/api/admin/topics", json={"name": "Anh"})).json()[
        "id"
    ]
    other_id = (await client.post("/api/admin/topics", json={"name": "Khác"})).json()[
        "id"
    ]

    def payload(topic: int, front: str):
        return {
            "topic_id": topic,
            "level": "easy",
            "kind": "flashcard",
            "content": {"front": front, "back": "nghĩa"},
        }

    first = await client.post(
        "/api/admin/items", json=payload(topic_id, "  Hello   World ")
    )
    assert first.status_code == 201
    assert (
        await client.post("/api/admin/items", json=payload(topic_id, "hello world"))
    ).status_code == 409
    assert (
        await client.post("/api/admin/items", json=payload(other_id, "hello world"))
    ).status_code == 201

    item_id = first.json()["id"]
    assert (await client.post(f"/api/admin/items/{item_id}/archive")).status_code == 200
    # Archived items keep their hash: the same content must not come back.
    assert (
        await client.post("/api/admin/items", json=payload(topic_id, "HELLO WORLD"))
    ).status_code == 409


async def test_publish_and_archive_drive_the_catalog_count(client, make_user):
    await _admin(client, make_user)
    topic_id = (await client.post("/api/admin/topics", json={"name": "Toán"})).json()[
        "id"
    ]
    created = await client.post(
        "/api/admin/items",
        json={
            "topic_id": topic_id,
            "level": "medium",
            "kind": "flashcard",
            "content": {"front": "một", "back": "1"},
        },
    )
    item_id = created.json()["id"]

    catalog = (await client.get("/api/topics")).json()
    assert catalog[0]["published_items"] == 0

    assert (await client.post(f"/api/admin/items/{item_id}/publish")).status_code == 200
    assert (await client.get("/api/topics")).json()[0]["published_items"] == 1

    assert (await client.post(f"/api/admin/items/{item_id}/archive")).status_code == 200
    assert (await client.get("/api/topics")).json()[0]["published_items"] == 0


async def test_the_catalog_requires_login(client):
    assert (await client.get("/api/topics")).status_code == 401


async def test_deleting_a_topic_requires_no_items(client, make_user):
    await _admin(client, make_user)
    empty = (await client.post("/api/admin/topics", json={"name": "Rỗng"})).json()["id"]
    used = (await client.post("/api/admin/topics", json={"name": "Có item"})).json()[
        "id"
    ]
    await client.post(
        "/api/admin/items",
        json={
            "topic_id": used,
            "level": "easy",
            "kind": "flashcard",
            "content": {"front": "a", "back": "b"},
        },
    )

    assert (await client.delete(f"/api/admin/topics/{used}")).status_code == 409
    assert (await client.delete(f"/api/admin/topics/{empty}")).status_code == 204
    assert (await client.delete("/api/admin/topics/9999")).status_code == 404
