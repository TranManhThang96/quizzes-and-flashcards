from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from tests.conftest import ORIGIN, TEST_DB_URL


async def test_health_checks_the_database(client):
    resp = await client.get("/api/health")

    assert resp.status_code == 200 and resp.json() == {"status": "ok"}


async def test_api_docs_exist_only_in_dev():
    for env, expected in (("prod", 404), ("dev", 200)):
        app = create_app(
            Settings(database_url=TEST_DB_URL, app_origin=ORIGIN, environment=env)
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as c:
            assert (await c.get("/api/openapi.json")).status_code == expected
            assert (await c.get("/api/docs")).status_code == expected
        await app.state.engine.dispose()
