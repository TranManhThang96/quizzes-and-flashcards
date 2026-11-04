import pytest

from app.extract import UnsafeUrlError
from tests.conftest import login
from tests.pdf_factory import make_pdf_bytes


async def _admin(client, make_user):
    await make_user("root", "admin-password", role="admin")
    assert (await login(client, "root", "admin-password")).status_code == 200


async def test_pasted_text_becomes_a_source_with_a_preview(client, make_user):
    await _admin(client, make_user)

    resp = await client.post(
        "/api/admin/sources/text", json={"text": "Lãi kép là lãi trên lãi.\n\n" * 30}
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["kind"] == "text"
    assert body["url"] is None
    assert body["chars"] == len(("Lãi kép là lãi trên lãi.\n\n" * 30).strip())
    assert len(body["preview"]) == 500


async def test_empty_and_oversized_text_are_rejected(client, make_user, settings):
    await _admin(client, make_user)

    assert (
        await client.post("/api/admin/sources/text", json={"text": "   "})
    ).status_code == 422
    too_long = "x" * (settings.max_source_chars + 1)
    resp = await client.post("/api/admin/sources/text", json={"text": too_long})
    assert resp.status_code == 413


async def test_pdf_upload_extracts_text(client, make_user):
    await _admin(client, make_user)

    resp = await client.post(
        "/api/admin/sources/pdf",
        files={"file": ("bai.pdf", make_pdf_bytes("Lai kep"), "application/pdf")},
    )

    assert resp.status_code == 201
    assert resp.json()["kind"] == "pdf"
    assert resp.json()["preview"] == "Lai kep"


async def test_pdf_without_a_text_layer_is_a_422(client, make_user):
    await _admin(client, make_user)

    resp = await client.post(
        "/api/admin/sources/pdf",
        files={"file": ("scan.pdf", make_pdf_bytes(None), "application/pdf")},
    )

    assert resp.status_code == 422
    assert "lớp văn bản" in resp.json()["detail"]


async def test_oversized_pdf_is_rejected(client, make_user, settings):
    await _admin(client, make_user)
    settings.max_pdf_bytes = 1024

    resp = await client.post(
        "/api/admin/sources/pdf",
        files={"file": ("big.pdf", make_pdf_bytes("x" * 5000), "application/pdf")},
    )

    assert resp.status_code == 413


async def test_url_source_uses_the_extractor(client, make_user, monkeypatch):
    await _admin(client, make_user)

    async def fake_extract(url: str, **_: object) -> str:
        return f"Nội dung của {url}"

    monkeypatch.setattr("app.admin.sources.extract_url", fake_extract)

    resp = await client.post(
        "/api/admin/sources/url", json={"url": "https://example.com/a"}
    )

    assert resp.status_code == 201
    assert resp.json() == {
        "id": 1,
        "kind": "url",
        "chars": len("Nội dung của https://example.com/a"),
        "url": "https://example.com/a",
        "preview": "Nội dung của https://example.com/a",
    }


async def test_blocked_url_returns_422(client, make_user, monkeypatch):
    await _admin(client, make_user)

    async def blocked(url: str, **_: object) -> str:
        raise UnsafeUrlError("URL trỏ tới địa chỉ nội bộ hoặc không công khai")

    monkeypatch.setattr("app.admin.sources.extract_url", blocked)

    resp = await client.post(
        "/api/admin/sources/url", json={"url": "http://127.0.0.1/admin"}
    )

    assert resp.status_code == 422
    assert "nội bộ" in resp.json()["detail"]


async def test_source_list_reports_lengths_without_the_text(client, make_user):
    await _admin(client, make_user)
    await client.post("/api/admin/sources/text", json={"text": "một hai ba"})

    resp = await client.get("/api/admin/sources")

    assert resp.status_code == 200
    assert resp.json()[0]["chars"] == len("một hai ba")
    assert "text" not in resp.json()[0]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/admin/sources/text"),
        ("post", "/api/admin/sources/url"),
        ("get", "/api/admin/sources"),
    ],
)
async def test_sources_require_admin(client, make_user, method, path):
    await make_user("bob", "user-password")
    assert (await login(client, "bob", "user-password")).status_code == 200
    kwargs = (
        {"json": {"text": "abc", "url": "https://example.com/"}}
        if method == "post"
        else {}
    )
    resp = await getattr(client, method)(path, **kwargs)
    assert resp.status_code == 403
