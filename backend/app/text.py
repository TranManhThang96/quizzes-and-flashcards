import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")
_NON_SLUG = re.compile(r"[^a-z0-9]+")


def normalize_ws(value: str) -> str:
    """Trim and collapse every run of whitespace to a single space."""
    return _WHITESPACE.sub(" ", value).strip()


def fold(value: str) -> str:
    """Unicode NFC, casefold and whitespace collapse: the dedupe key form."""
    return normalize_ws(unicodedata.normalize("NFC", value).casefold())


def slugify(value: str) -> str:
    """ASCII, lowercase, hyphen-separated slug. Vietnamese đ becomes d."""
    decomposed = unicodedata.normalize("NFD", value.casefold())
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _NON_SLUG.sub("-", ascii_only.replace("đ", "d")).strip("-")
