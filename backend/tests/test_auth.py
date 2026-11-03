from datetime import timedelta

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from app.auth.deps import utcnow
from app.models import LoginAttempt, UserSession
from tests.conftest import ORIGIN, login


async def test_login_sets_hardened_cookie_and_me_works(client, make_user):
    await make_user("alice", "correct-horse")

    resp = await login(client, "alice", "correct-horse")

    assert resp.status_code == 200
    assert resp.json() == {"id": 1, "username": "alice", "role": "user"}
    cookie = resp.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
    me = await client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["username"] == "alice"
    assert "password" not in me.text


async def test_wrong_password_and_unknown_user_are_indistinguishable(client, make_user):
    await make_user("alice", "correct-horse")

    wrong = await login(client, "alice", "nope-nope-nope")
    unknown = await login(client, "nobody", "nope-nope-nope")

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


async def test_username_is_trimmed_and_case_insensitive(client, make_user):
    await make_user("alice", "correct-horse")

    assert (await login(client, "  Alice ", "correct-horse")).status_code == 200


async def test_me_requires_a_session(client):
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_logout_invalidates_the_token_server_side(client, make_user, app):
    await make_user("alice", "correct-horse")
    await login(client, "alice", "correct-horse")
    stolen = client.cookies["session"]

    assert (await client.post("/api/auth/logout")).status_code == 204
    assert (await client.get("/api/auth/me")).status_code == 401

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url=ORIGIN,
        cookies={"session": stolen},
    ) as replay:
        assert (await replay.get("/api/auth/me")).status_code == 401


async def test_expired_session_is_rejected(client, make_user, app):
    await make_user("alice", "correct-horse")
    await login(client, "alice", "correct-horse")
    async with app.state.sessionmaker() as s:
        await s.execute(update(UserSession).values(expires_at=utcnow() - timedelta(1)))
        await s.commit()

    assert (await client.get("/api/auth/me")).status_code == 401


async def test_session_expiry_slides_forward_on_use(client, make_user, app):
    await make_user("alice", "correct-horse")
    await login(client, "alice", "correct-horse")
    soon = utcnow() + timedelta(days=1)
    async with app.state.sessionmaker() as s:
        await s.execute(update(UserSession).values(expires_at=soon))
        await s.commit()

    assert (await client.get("/api/auth/me")).status_code == 200

    async with app.state.sessionmaker() as s:
        expires = (await s.execute(select(UserSession.expires_at))).scalar_one()
    assert expires - utcnow() > timedelta(days=29)


async def test_lockout_after_repeated_failures_even_for_correct_password(
    client, make_user
):
    await make_user("alice", "correct-horse")
    for _ in range(5):
        assert (await login(client, "alice", "wrong-wrong")).status_code == 401

    locked = await login(client, "alice", "correct-horse")

    assert locked.status_code == 429
    assert locked.headers["retry-after"] == str(15 * 60)


async def test_lockout_also_applies_per_ip_across_usernames(client, make_user):
    await make_user("alice", "correct-horse")
    await make_user("bob", "correct-horse")
    for _ in range(5):
        await login(client, "alice", "wrong-wrong")

    assert (await login(client, "bob", "correct-horse")).status_code == 429


async def test_failures_older_than_the_window_do_not_lock(client, make_user, app):
    await make_user("alice", "correct-horse")
    old = utcnow() - timedelta(minutes=16)
    async with app.state.sessionmaker() as s:
        s.add_all(
            LoginAttempt(username="alice", ip="127.0.0.1", at=old) for _ in range(5)
        )
        await s.commit()

    assert (await login(client, "alice", "correct-horse")).status_code == 200


async def test_deactivated_user_cannot_log_in(client, make_user, app):
    user = await make_user("alice", "correct-horse")
    async with app.state.sessionmaker() as s:
        db_user = await s.get(type(user), user.id)
        db_user.is_active = False
        await s.commit()

    assert (await login(client, "alice", "correct-horse")).status_code == 401


async def test_writes_require_our_origin(app: FastAPI, make_user):
    await make_user("alice", "correct-horse")
    body = {"username": "alice", "password": "correct-horse"}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url=ORIGIN) as bare:
        assert (await bare.post("/api/auth/login", json=body)).status_code == 403
        evil = {"origin": "https://evil.test"}
        assert (
            await bare.post("/api/auth/login", json=body, headers=evil)
        ).status_code == 403
        # Reads never need an Origin.
        assert (await bare.get("/api/health")).status_code == 200


async def test_malformed_username_is_rejected_before_it_reaches_the_database(client):
    # PostgreSQL text cannot hold NUL; letting one through would be a 500.
    for name in ("ali\x00ce", "has space", "UPPER!", "ab", "x" * 65):
        assert (await login(client, name, "correct-horse")).status_code == 422


async def test_oversized_password_is_rejected_before_any_hashing(client, make_user):
    await make_user("alice", "correct-horse")

    assert (await login(client, "alice", "x" * 129)).status_code == 422


async def test_garbage_session_cookie_is_unauthenticated(client):
    client.cookies.set("session", "not-a-real-token")

    assert (await client.get("/api/auth/me")).status_code == 401


async def test_absurd_client_address_does_not_break_the_failure_log(app):
    # Whatever a proxy chain puts in the client address must not turn a bad
    # login into a 500 (login_attempts.ip is varchar(45)).
    transport = ASGITransport(app=app, client=("x" * 80, 1234))
    async with AsyncClient(
        transport=transport, base_url=ORIGIN, headers={"origin": ORIGIN}
    ) as c:
        assert (await login(c, "nobody", "wrong-wrong")).status_code == 401
