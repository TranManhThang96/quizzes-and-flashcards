"""Trích văn bản từ PDF, HTML và URL, có chặn SSRF."""

import asyncio
import io
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

import httpx
import trafilatura
from pypdf import PdfReader
from pypdf.errors import PyPdfError

MAX_SOURCE_CHARS = 200_000
MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_URL_BYTES = 5 * 1024 * 1024
URL_TIMEOUT_SECONDS = 15.0
PDF_TIMEOUT_SECONDS = 60.0
MAX_REDIRECTS = 3
_USER_AGENT = "quizz-content-bot/1.0"


class ExtractionError(ValueError):
    """Lỗi trích xuất hiển thị được cho admin (HTTP 422)."""


class UnsafeUrlError(ExtractionError):
    """URL trỏ vào địa chỉ không công khai (SSRF)."""


class ExtractionTooLarge(ExtractionError):
    """Nội dung vượt giới hạn ký tự (HTTP 413)."""


def clean_text(raw: str) -> str:
    """Chuẩn hóa text đã trích xuất.

    Postgres từ chối byte NUL trong cột text, nên NUL phải bị bỏ trước khi ghi.
    """
    text = raw.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines).strip()


def finalize_text(raw: str, max_chars: int = MAX_SOURCE_CHARS) -> str:
    """Làm sạch, kiểm tra rỗng và giới hạn ký tự. Dùng chung cho mọi nguồn."""
    text = clean_text(raw)
    if not text:
        raise ExtractionError("Không trích xuất được văn bản nào")
    if len(text) > max_chars:
        raise ExtractionTooLarge(
            f"Văn bản có {len(text)} ký tự, vượt giới hạn {max_chars}"
        )
    return text


def _read_pdf(data: bytes, max_chars: int) -> str:
    """Phần đồng bộ của extract_pdf: chạy trong threadpool, không chặn loop."""
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ExtractionError("PDF có mật khẩu, không đọc được")
        pages: list[str] = []
        total = 0
        for page in reader.pages:
            text = page.extract_text() or ""
            pages.append(text)
            total += len(text)
            if total > max_chars:
                raise ExtractionTooLarge(f"PDF dài hơn giới hạn {max_chars} ký tự")
        joined = "\n\n".join(pages)
    except (ExtractionError, ExtractionTooLarge):
        raise
    except PyPdfError as exc:
        raise ExtractionError(f"Không đọc được PDF: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - pypdf ném nhiều loại lỗi khác nhau
        raise ExtractionError("Tệp không phải PDF hợp lệ") from exc
    if not clean_text(joined):
        raise ExtractionError(
            "PDF không có lớp văn bản (có thể là bản scan); hệ thống không hỗ trợ OCR"
        )
    return joined


async def extract_pdf(
    data: bytes,
    max_chars: int = MAX_SOURCE_CHARS,
    timeout: float = PDF_TIMEOUT_SECONDS,
) -> str:
    """Trích text từ PDF; pypdf chạy trong threadpool, có trần thời gian."""
    try:
        async with asyncio.timeout(timeout):
            return await asyncio.to_thread(_read_pdf, data, max_chars)
    except TimeoutError as exc:
        raise ExtractionError("Đọc PDF quá thời gian chờ") from exc


Resolver = Callable[[str, int], Sequence[str]]


def _system_resolver(host: str, port: int) -> list[str]:
    """Phân giải DNS qua getaddrinfo và chỉ trả về địa chỉ."""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]).split("%", 1)[0] for info in infos]


@dataclass(frozen=True)
class PinnedTarget:
    """URL đã kiểm tra, kèm IP đã xác thực để kết nối và Host gốc."""

    url: httpx.URL
    ip: str
    host_header: str


# NAT64 prefixes nhúng một địa chỉ IPv4 mà stack nội bộ dịch ngược lại, nên
# 64:ff9b::a9fe:a9fe thực chất là 169.254.169.254; is_global không bắt được.
_NAT64_NETWORKS = (
    ipaddress.IPv6Network("64:ff9b::/96"),
    ipaddress.IPv6Network("64:ff9b:1::/48"),
)


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    # is_global loại trừ loopback, private, link-local và multicast.
    if not ip.is_global or ip.is_multicast:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        # is_global bỏ sót khối reserved ::/8 (gồm cả IPv4-compatible ::7f00:1)
        # và site-local fec0::/10.
        if ip.is_reserved or ip.is_site_local:
            return False
        if any(ip in network for network in _NAT64_NETWORKS):
            return False
    return True


def ensure_public_url(url: str, *, resolver: Resolver | None = None) -> PinnedTarget:
    """Kiểm tra URL công khai và trả về IP đã xác thực để kết nối.

    Mọi địa chỉ mà DNS trả về đều phải công khai; kết nối đi tới đúng IP đã
    kiểm tra kèm Host/SNI của host gốc, nên DNS rebinding giữa bước kiểm tra
    và bước kết nối không đổi được đích.
    """
    resolve = resolver or _system_resolver
    try:
        parsed = httpx.URL(url)
        scheme = parsed.scheme
        host = parsed.host
        port = parsed.port
    except (ValueError, httpx.InvalidURL) as exc:
        # Hostname hỏng làm .host ném UnicodeError/IDNAError, cả hai là
        # ValueError; httpx ném InvalidURL khi URL sai cấu trúc.
        raise UnsafeUrlError(f"URL không hợp lệ: {exc}") from exc
    if scheme not in ("http", "https"):
        raise UnsafeUrlError("Chỉ chấp nhận URL http hoặc https")
    if not host:
        raise UnsafeUrlError("URL thiếu host")
    if parsed.userinfo:
        raise UnsafeUrlError("URL không được chứa thông tin đăng nhập")
    if port is not None and not 1 <= port <= 65535:
        raise UnsafeUrlError(f"Cổng không hợp lệ: {port}")
    connect_port = port or (443 if scheme == "https" else 80)
    try:
        resolved = [str(address) for address in resolve(host, connect_port)]
    except (OSError, UnicodeError) as exc:
        # Nhãn hostname quá dài làm getaddrinfo ném UnicodeError, không phải
        # OSError; route chỉ đổi ExtractionError thành 422.
        raise UnsafeUrlError(f"Không phân giải được host: {host}") from exc
    if not resolved:
        raise UnsafeUrlError(f"Không phân giải được host: {host}")
    # Chỉ cần một địa chỉ nội bộ là cả URL bị từ chối: kẻ tấn công có thể trả
    # về cả IP công khai lẫn IP nội bộ và mong ta kết nối vào cái sau.
    for address in resolved:
        try:
            parsed_ip = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError as exc:
            raise UnsafeUrlError(f"Địa chỉ không hợp lệ: {address}") from exc
        if not _is_public(parsed_ip):
            raise UnsafeUrlError(
                f"URL trỏ tới địa chỉ nội bộ hoặc không công khai ({address})"
            )
    return PinnedTarget(
        url=parsed,
        ip=resolved[0].split("%", 1)[0],
        host_header=parsed.netloc.decode("ascii"),
    )


async def fetch_html(
    url: str,
    *,
    max_bytes: int = MAX_URL_BYTES,
    timeout: float = URL_TIMEOUT_SECONDS,
    max_redirects: int = MAX_REDIRECTS,
    resolver: Resolver | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[bytes, str]:
    """Tải HTML qua kết nối đã ghim IP, tự theo redirect và kiểm tra lại."""
    try:
        return await _fetch_html(
            url,
            max_bytes=max_bytes,
            timeout=timeout,
            max_redirects=max_redirects,
            resolver=resolver,
            transport=transport,
        )
    except TimeoutError as exc:
        # `asyncio.timeout` raises outside the httpx handlers below; the API
        # promises a 422 for a slow URL, not a 500.
        raise ExtractionError("Tải URL quá thời gian chờ") from exc


async def _fetch_html(
    url: str,
    *,
    max_bytes: int,
    timeout: float,
    max_redirects: int,
    resolver: Resolver | None,
    transport: httpx.AsyncBaseTransport | None,
) -> tuple[bytes, str]:
    async with asyncio.timeout(timeout):
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        ) as client:
            current = url
            for _ in range(max_redirects + 1):
                target = await asyncio.to_thread(
                    ensure_public_url, current, resolver=resolver
                )
                pinned = target.url.copy_with(host=target.ip)
                try:
                    # SNI vẫn là host gốc nên chứng chỉ TLS được kiểm tra đúng
                    # tên miền, dù socket nối tới IP đã xác thực.
                    async with client.stream(
                        "GET",
                        pinned,
                        headers={
                            "Host": target.host_header,
                            "User-Agent": _USER_AGENT,
                            "Accept": "text/html,application/xhtml+xml",
                        },
                        extensions={"sni_hostname": str(target.url.host)},
                    ) as response:
                        if response.is_redirect:
                            location = response.headers.get("location")
                            if not location:
                                raise ExtractionError("Redirect thiếu header Location")
                            current = str(target.url.join(location))
                            continue
                        if response.status_code >= 400:
                            raise ExtractionError(
                                f"Máy chủ trả về HTTP {response.status_code}"
                            )
                        content_type = response.headers.get("content-type", "")
                        if not content_type.lower().startswith(
                            ("text/html", "application/xhtml+xml")
                        ):
                            raise ExtractionError(
                                "URL không trả về HTML "
                                f"(content-type: {content_type or 'trống'})"
                            )
                        buffer = bytearray()
                        async for chunk in response.aiter_bytes():
                            buffer.extend(chunk)
                            if len(buffer) > max_bytes:
                                raise ExtractionTooLarge(
                                    f"Trang lớn hơn giới hạn {max_bytes} byte"
                                )
                        return bytes(buffer), str(target.url)
                except httpx.TimeoutException as exc:
                    raise ExtractionError("Tải URL quá thời gian chờ") from exc
                except httpx.HTTPError as exc:
                    raise ExtractionError(f"Không tải được URL: {exc}") from exc
            raise ExtractionError(f"URL chuyển hướng quá {max_redirects} lần")


def html_to_text(data: bytes) -> str:
    """Bóc nội dung chính khỏi HTML bằng trafilatura (hàm đồng bộ)."""
    text = trafilatura.extract(
        data,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    if not text:
        raise ExtractionError("Không tìm thấy nội dung đọc được trong trang")
    return text


Fetch = Callable[[str], Awaitable[tuple[bytes, str]]]


async def extract_url(
    url: str,
    *,
    fetch: Fetch | None = None,
    max_bytes: int = MAX_URL_BYTES,
    timeout: float = URL_TIMEOUT_SECONDS,
    max_redirects: int = MAX_REDIRECTS,
) -> str:
    """Tải URL rồi trích nội dung chính; trafilatura chạy trong threadpool."""
    fetcher: Fetch = fetch or (
        lambda target: fetch_html(
            target,
            max_bytes=max_bytes,
            timeout=timeout,
            max_redirects=max_redirects,
        )
    )
    data, final_url = await fetcher(url)
    try:
        text = await asyncio.to_thread(html_to_text, data)
    except ExtractionError as exc:
        raise ExtractionError(f"{exc} (URL cuối: {final_url})") from exc
    return text
