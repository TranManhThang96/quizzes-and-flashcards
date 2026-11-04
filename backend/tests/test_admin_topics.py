from tests.conftest import login


async def _admin(client, make_user):
    await make_user("root", "admin-password", role="admin")
    assert (await login(client, "root", "admin-password")).status_code == 200


async def test_topics_are_admin_only(client, make_user):
    assert (await client.get("/api/admin/topics")).status_code == 401

    await make_user("alice", "correct-horse")
    await login(client, "alice", "correct-horse")
    assert (await client.get("/api/admin/topics")).status_code == 403
    created = await client.post("/api/admin/topics", json={"name": "Toán"})
    assert created.status_code == 403


async def test_slugs_are_ascii_and_unique(client, make_user):
    await _admin(client, make_user)

    first = await client.post("/api/admin/topics", json={"name": "Lập trình"})
    second = await client.post("/api/admin/topics", json={"name": "  lập   TRÌNH "})

    assert first.status_code == second.status_code == 201
    assert first.json()["slug"] == "lap-trinh"
    assert second.json()["slug"] == "lap-trinh-2"
    listed = (await client.get("/api/admin/topics")).json()
    assert [topic["slug"] for topic in listed] == ["lap-trinh", "lap-trinh-2"]


async def test_rename_keeps_the_stable_slug(client, make_user):
    await _admin(client, make_user)
    topic_id = (await client.post("/api/admin/topics", json={"name": "Toán"})).json()[
        "id"
    ]

    renamed = await client.patch(
        f"/api/admin/topics/{topic_id}", json={"name": "Toán học"}
    )

    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Toán học"
    assert renamed.json()["slug"] == "toan"
    assert (
        await client.patch("/api/admin/topics/9999", json={"name": "X"})
    ).status_code == 404


async def test_blank_or_oversized_names_are_422(client, make_user):
    await _admin(client, make_user)

    for payload in ({"name": ""}, {"name": "   "}, {"name": "x" * 121}):
        assert (await client.post("/api/admin/topics", json=payload)).status_code == 422
