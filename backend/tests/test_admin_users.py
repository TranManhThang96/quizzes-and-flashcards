import asyncio

from tests.conftest import login


async def _admin(client, make_user):
    await make_user("root", "admin-password", role="admin")
    assert (await login(client, "root", "admin-password")).status_code == 200


async def test_anonymous_and_regular_users_are_kept_out(client, make_user):
    assert (await client.get("/api/admin/users")).status_code == 401

    await make_user("alice", "correct-horse")
    await login(client, "alice", "correct-horse")

    assert (await client.get("/api/admin/users")).status_code == 403
    created = await client.post(
        "/api/admin/users", json={"username": "eve", "password": "long-enough"}
    )
    assert created.status_code == 403


async def test_admin_creates_a_user_who_can_then_log_in(
    client, other_client, make_user
):
    await _admin(client, make_user)

    resp = await client.post(
        "/api/admin/users", json={"username": "bob", "password": "long-enough"}
    )

    assert resp.status_code == 201
    assert resp.json()["role"] == "user" and resp.json()["daily_new_limit"] == 10
    assert "password" not in resp.text
    assert (await login(other_client, "bob", "long-enough")).status_code == 200


async def test_duplicate_and_invalid_input_is_rejected(client, make_user):
    await _admin(client, make_user)
    ok = {"username": "bob", "password": "long-enough"}
    assert (await client.post("/api/admin/users", json=ok)).status_code == 201

    assert (await client.post("/api/admin/users", json=ok)).status_code == 409
    for bad in (
        {"username": "has space", "password": "long-enough"},
        {"username": "x", "password": "long-enough"},
        {"username": "carol", "password": "short"},
        {"username": "carol", "password": "x" * 129},
        {"username": "carol", "password": "long-enough", "role": "owner"},
    ):
        assert (await client.post("/api/admin/users", json=bad)).status_code == 422


async def test_admin_created_username_is_normalised_like_login(
    client, other_client, make_user
):
    await _admin(client, make_user)

    resp = await client.post(
        "/api/admin/users", json={"username": "  Bob2 ", "password": "long-enough"}
    )

    assert resp.status_code == 201 and resp.json()["username"] == "bob2"
    dup = await client.post(
        "/api/admin/users", json={"username": "BOB2", "password": "long-enough"}
    )
    assert dup.status_code == 409
    assert (await login(other_client, "Bob2", "long-enough")).status_code == 200


async def test_list_never_exposes_password_hashes(client, make_user):
    await _admin(client, make_user)
    await make_user("alice", "correct-horse")

    rows = (await client.get("/api/admin/users")).json()

    assert [r["username"] for r in rows] == ["root", "alice"]
    assert all("password" not in r for r in rows)


async def test_deactivating_a_user_ends_their_sessions_immediately(
    client, other_client, make_user
):
    await _admin(client, make_user)
    victim = await make_user("alice", "correct-horse")
    await login(other_client, "alice", "correct-horse")
    assert (await other_client.get("/api/auth/me")).status_code == 200

    resp = await client.patch(
        f"/api/admin/users/{victim.id}", json={"is_active": False}
    )

    assert resp.status_code == 200 and resp.json()["is_active"] is False
    assert (await other_client.get("/api/auth/me")).status_code == 401
    assert (await login(other_client, "alice", "correct-horse")).status_code == 401


async def test_password_reset_revokes_sessions_and_swaps_the_password(
    client, other_client, make_user
):
    await _admin(client, make_user)
    target = await make_user("alice", "correct-horse")
    await login(other_client, "alice", "correct-horse")

    resp = await client.patch(
        f"/api/admin/users/{target.id}", json={"password": "brand-new-pass"}
    )

    assert resp.status_code == 200
    assert (await other_client.get("/api/auth/me")).status_code == 401
    assert (await login(other_client, "alice", "correct-horse")).status_code == 401
    assert (await login(other_client, "alice", "brand-new-pass")).status_code == 200


async def test_admin_cannot_deactivate_themselves(client, make_user):
    await _admin(client, make_user)

    resp = await client.patch("/api/admin/users/1", json={"is_active": False})

    assert resp.status_code == 409
    assert (await client.get("/api/auth/me")).status_code == 200


async def test_patch_validates_target_and_limits(client, make_user):
    await _admin(client, make_user)
    target = await make_user("alice", "correct-horse")

    assert (await client.patch("/api/admin/users/999", json={})).status_code == 404
    over = await client.patch(
        f"/api/admin/users/{target.id}", json={"daily_new_limit": 201}
    )
    assert over.status_code == 422
    ok = await client.patch(
        f"/api/admin/users/{target.id}", json={"daily_new_limit": 0}
    )
    assert ok.status_code == 200 and ok.json()["daily_new_limit"] == 0


async def test_two_requests_for_the_same_new_name_give_one_201_and_one_409(
    client, make_user
):
    await _admin(client, make_user)
    body = {"username": "bob", "password": "long-enough"}

    first, second = await asyncio.gather(
        client.post("/api/admin/users", json=body),
        client.post("/api/admin/users", json=body),
    )

    assert sorted([first.status_code, second.status_code]) == [201, 409]
    rows = (await client.get("/api/admin/users")).json()
    assert [r["username"] for r in rows].count("bob") == 1
