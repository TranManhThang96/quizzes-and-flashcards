"""Chia văn bản nguồn thành chunk và rải số item theo level."""

import re

_WHITESPACE = re.compile(r"\s+")
_WHITESPACE_CHARS = " \t\n\r\f\v"


def normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def _split_long(paragraph: str, size: int) -> list[str]:
    """Cắt một đoạn quá dài ở khoảng trắng gần cuối, không cắt giữa từ."""
    pieces: list[str] = []
    rest = paragraph.strip()
    while len(rest) > size:
        window = rest[:size]
        cut = max(window.rfind(char) for char in _WHITESPACE_CHARS)
        if cut <= 0:
            cut = size
        pieces.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        pieces.append(rest)
    return pieces


def chunk_text(text: str, size: int) -> list[str]:
    """Gộp đoạn theo ranh giới đoạn văn, mỗi chunk không quá `size` ký tự."""
    if size <= 0:
        raise ValueError("size must be positive")
    pieces: list[str] = []
    for paragraph in text.split("\n\n"):
        if not paragraph.strip():
            continue
        if len(paragraph) <= size:
            pieces.append(paragraph.strip())
        else:
            pieces.extend(_split_long(paragraph, size))
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current}\n\n{piece}" if current else piece
        if len(candidate) <= size:
            current = candidate
            continue
        chunks.append(current)
        current = piece
    if current:
        chunks.append(current)
    return chunks


def distribute(total: int, parts: int) -> list[int]:
    """Chia `total` cho `parts` phần, phần đầu nhận dư một item."""
    if parts <= 0:
        raise ValueError("parts must be positive")
    if total < 0:
        raise ValueError("total must not be negative")
    base, extra = divmod(total, parts)
    return [base + (1 if index < extra else 0) for index in range(parts)]


def plan_chunks(counts: dict[str, int], n_chunks: int) -> list[dict[str, int]]:
    """Số item mỗi level cho từng chunk; chunk không có item nào thì bỏ trống."""
    plan: list[dict[str, int]] = [{} for _ in range(n_chunks)]
    for level, total in counts.items():
        for index, share in enumerate(distribute(total, n_chunks)):
            if share:
                plan[index][level] = share
    return plan
