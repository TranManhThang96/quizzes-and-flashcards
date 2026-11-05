from tests.conftest import login


async def _admin(client, make_user):
    await make_user("root", "admin-password", role="admin")
    assert (await login(client, "root", "admin-password")).status_code == 200


def params(kind: str = "flashcard", **levels: int) -> dict:
    return {
        "kind": kind,
        "levels": [{"level": level, "count": count} for level, count in levels.items()],
    }


async def test_creating_a_job_queues_it(client, make_user, make_topic, make_source):
    await _admin(client, make_user)
    topic = await make_topic("Tài chính")
    source = await make_source()

    resp = await client.post(
        "/api/admin/jobs",
        json={
            "source_id": source.id,
            "topic_id": topic.id,
            "params": params(easy=2, hard=1),
        },
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "queued"
    assert body["attempts"] == 0
    assert body["result"] is None
    assert body["params"]["levels"] == [
        {"level": "easy", "count": 2},
        {"level": "hard", "count": 1},
    ]


async def test_total_items_over_the_limit_is_rejected(
    client, make_user, make_topic, make_source, settings
):
    await _admin(client, make_user)
    topic = await make_topic("Tài chính")
    source = await make_source()
    settings.max_job_items = 3

    resp = await client.post(
        "/api/admin/jobs",
        json={
            "source_id": source.id,
            "topic_id": topic.id,
            "params": params(easy=2, hard=2),
        },
    )

    assert resp.status_code == 422
    assert "giới hạn" in resp.json()["detail"]


async def test_unknown_source_or_topic_is_a_404(
    client, make_user, make_topic, make_source
):
    await _admin(client, make_user)
    topic = await make_topic("Tài chính")
    source = await make_source()

    missing_source = await client.post(
        "/api/admin/jobs",
        json={"source_id": 9999, "topic_id": topic.id, "params": params(easy=1)},
    )
    missing_topic = await client.post(
        "/api/admin/jobs",
        json={"source_id": source.id, "topic_id": 9999, "params": params(easy=1)},
    )

    assert missing_source.status_code == 404
    assert missing_topic.status_code == 404


async def test_a_source_without_text_is_rejected(
    client, make_user, make_topic, make_source
):
    await _admin(client, make_user)
    topic = await make_topic("Tài chính")
    source = await make_source(text="   ")

    resp = await client.post(
        "/api/admin/jobs",
        json={"source_id": source.id, "topic_id": topic.id, "params": params(easy=1)},
    )

    assert resp.status_code == 422


async def test_invalid_params_are_rejected_with_422(
    client, make_user, make_topic, make_source
):
    await _admin(client, make_user)
    topic = await make_topic("Tài chính")
    source = await make_source()

    for bad in (
        {"kind": "podcast", "levels": [{"level": "easy", "count": 1}]},
        {"kind": "flashcard", "levels": []},
        {"kind": "flashcard", "levels": [{"level": "easy", "count": 0}]},
        {"kind": "flashcard", "levels": [{"level": "nope", "count": 1}]},
        {
            "kind": "flashcard",
            "levels": [{"level": "easy", "count": 1}, {"level": "easy", "count": 2}],
        },
    ):
        resp = await client.post(
            "/api/admin/jobs",
            json={"source_id": source.id, "topic_id": topic.id, "params": bad},
        )
        assert resp.status_code == 422, bad


async def test_jobs_can_be_listed_by_status_and_fetched(
    client, make_user, make_topic, make_source, make_job
):
    await _admin(client, make_user)
    topic = await make_topic("Tài chính")
    source = await make_source()
    queued = await make_job(source_id=source.id, topic_id=topic.id)
    done = await make_job(source_id=source.id, topic_id=topic.id, status="failed")

    listed = await client.get("/api/admin/jobs", params={"status": "failed"})
    fetched = await client.get(f"/api/admin/jobs/{queued.id}")
    missing = await client.get("/api/admin/jobs/9999")

    assert [job["id"] for job in listed.json()] == [done.id]
    assert fetched.status_code == 200
    assert fetched.json()["id"] == queued.id
    assert missing.status_code == 404


async def test_jobs_require_admin(client, make_user):
    await make_user("bob", "user-password")
    assert (await login(client, "bob", "user-password")).status_code == 200

    assert (await client.get("/api/admin/jobs")).status_code == 403
