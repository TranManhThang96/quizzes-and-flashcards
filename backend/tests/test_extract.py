import asyncio

import httpx
import pytest

from app.extract import (
    ExtractionError,
    ExtractionTooLarge,
    UnsafeUrlError,
    ensure_public_url,
    extract_pdf,
    extract_url,
    fetch_html,
    finalize_text,
)
from tests.pdf_factory import make_pdf_bytes


def fake_resolver(*addresses: str):
    """Resolver giả: trả về đúng danh sách địa chỉ, không chạm mạng."""

    def _resolve(host: str, port: int) -> list[str]:
        return list(addresses)

    return _resolve


async def test_pdf_text_layer_is_extracted():
    data = make_pdf_bytes("Compound interest grows the base")
    assert "Compound interest grows the base" in await extract_pdf(data)


async def test_pdf_without_text_layer_is_a_clear_error():
    with pytest.raises(ExtractionError) as excinfo:
        await extract_pdf(make_pdf_bytes(None))
    assert "lớp văn bản" in str(excinfo.value)
    assert "OCR" in str(excinfo.value)


async def test_pdf_that_is_not_a_pdf_is_rejected():
    with pytest.raises(ExtractionError):
        await extract_pdf(b"definitely not a pdf")


async def test_pdf_over_the_character_limit_is_rejected():
    data = make_pdf_bytes("x" * 100)
    with pytest.raises(ExtractionTooLarge):
        await extract_pdf(data, max_chars=10)


def test_nul_bytes_and_control_noise_are_removed():
    assert finalize_text("a\x00b\r\nc  \n\n") == "ab\nc"


def test_empty_text_is_rejected():
    with pytest.raises(ExtractionError):
        finalize_text("  \n\t ")


def test_text_over_the_character_limit_is_rejected():
    with pytest.raises(ExtractionTooLarge):
        finalize_text("abc", max_chars=2)


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.1.1", "169.254.169.254"],
)
def test_private_and_loopback_addresses_are_blocked(address):
    with pytest.raises(UnsafeUrlError):
        ensure_public_url("http://example.com/", resolver=fake_resolver(address))


@pytest.mark.parametrize("address", ["::1", "fe80::1", "::ffff:127.0.0.1"])
def test_ipv6_local_addresses_are_blocked(address):
    with pytest.raises(UnsafeUrlError):
        ensure_public_url("http://example.com/", resolver=fake_resolver(address))


def test_one_private_answer_blocks_the_whole_url():
    # Một tên miền trả cả IP công khai lẫn IP nội bộ phải bị từ chối.
    with pytest.raises(UnsafeUrlError):
        ensure_public_url(
            "http://example.com/",
            resolver=fake_resolver("93.184.216.34", "10.0.0.7"),
        )


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("ftp://example.com/", "http"),
        ("file:///etc/passwd", "http"),
        ("http://user:secret@example.com/", "đăng nhập"),
        ("http:///path", "host"),
    ],
)
def test_non_http_or_credentialed_urls_are_blocked(url, reason):
    with pytest.raises(UnsafeUrlError) as excinfo:
        ensure_public_url(url, resolver=fake_resolver("93.184.216.34"))
    assert reason in str(excinfo.value)


def test_public_url_returns_the_validated_ip_and_host():
    target = ensure_public_url(
        "https://example.com:8443/a?b=1", resolver=fake_resolver("93.184.216.34")
    )
    assert target.ip == "93.184.216.34"
    assert target.host_header == "example.com:8443"
    assert target.url.path == "/a"


async def test_fetch_pins_the_connection_and_keeps_the_original_host():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["host"] = str(request.url.host)
        seen["header"] = request.headers["host"]
        seen["sni"] = request.extensions["sni_hostname"]
        return httpx.Response(
            200, headers={"content-type": "text/html"}, text="<p>hi</p>"
        )

    body, final_url = await fetch_html(
        "https://example.com/page",
        resolver=fake_resolver("93.184.216.34"),
        transport=httpx.MockTransport(handler),
    )
    assert body == b"<p>hi</p>"
    assert final_url == "https://example.com/page"
    assert seen == {
        "host": "93.184.216.34",
        "header": "example.com",
        "sni": "example.com",
    }


async def test_redirect_to_a_private_address_is_blocked():
    def generator(request: httpx.Request) -> httpx.Response:
        host = str(request.url.host)
        if host == "93.184.216.34":
            return httpx.Response(302, headers={"location": "http://internal.test/x"})
        raise AssertionError("phải không bao giờ kết nối tới IP nội bộ")

    def resolver(host: str, port: int) -> list[str]:
        return ["10.0.0.5"] if host == "internal.test" else ["93.184.216.34"]

    with pytest.raises(UnsafeUrlError):
        await fetch_html(
            "https://example.com/",
            resolver=resolver,
            transport=httpx.MockTransport(generator),
        )


async def test_redirect_chain_is_followed_and_limited():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "/again"})

    with pytest.raises(ExtractionError) as excinfo:
        await fetch_html(
            "https://example.com/",
            resolver=fake_resolver("93.184.216.34"),
            transport=httpx.MockTransport(handler),
        )
    assert "chuyển hướng" in str(excinfo.value)


async def test_body_over_the_byte_cap_is_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"x" * 2048,
        )

    with pytest.raises(ExtractionTooLarge):
        await fetch_html(
            "https://example.com/",
            max_bytes=1024,
            resolver=fake_resolver("93.184.216.34"),
            transport=httpx.MockTransport(handler),
        )


async def test_a_slow_response_is_a_clean_extraction_error():
    class SlowTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(0.2)
            return httpx.Response(
                200, headers={"content-type": "text/html"}, content=b"<html></html>"
            )

    with pytest.raises(ExtractionError) as excinfo:
        await fetch_html(
            "https://example.com/",
            timeout=0.05,
            resolver=fake_resolver("93.184.216.34"),
            transport=SlowTransport(),
        )
    assert "thời gian" in str(excinfo.value)


async def test_non_html_response_is_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "application/pdf"}, content=b"%PDF-"
        )

    with pytest.raises(ExtractionError) as excinfo:
        await fetch_html(
            "https://example.com/",
            resolver=fake_resolver("93.184.216.34"),
            transport=httpx.MockTransport(handler),
        )
    assert "HTML" in str(excinfo.value)


async def test_http_error_status_is_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, headers={"content-type": "text/html"})

    with pytest.raises(ExtractionError) as excinfo:
        await fetch_html(
            "https://example.com/",
            resolver=fake_resolver("93.184.216.34"),
            transport=httpx.MockTransport(handler),
        )
    assert "404" in str(excinfo.value)


async def test_extract_url_uses_the_fetcher_and_returns_article_text():
    html = (
        "<html><body><nav>menu</nav><article>"
        + "<p>Lãi kép là lãi tính trên cả gốc lẫn lãi đã cộng dồn.</p>" * 5
        + "</article><footer>foot</footer></body></html>"
    ).encode()

    async def fake_fetch(url: str) -> tuple[bytes, str]:
        return html, url

    text = await extract_url("https://example.com/a", fetch=fake_fetch)
    assert "Lãi kép" in text
    assert "menu" not in text


async def test_extract_url_rejects_a_page_without_content():
    async def fake_fetch(url: str) -> tuple[bytes, str]:
        return b"<html><body></body></html>", url

    with pytest.raises(ExtractionError):
        await extract_url("https://example.com/a", fetch=fake_fetch)
