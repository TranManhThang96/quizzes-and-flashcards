import hashlib
import secrets

from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

_hasher = PasswordHash((Argon2Hasher(),))

# Verified against when a username does not exist, so an unknown user costs the
# same time as a wrong password and login timing does not reveal valid names.
_DUMMY_HASH = _hasher.hash("dummy-password-for-constant-time-check")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _hasher.verify(password, password_hash)


def verify_dummy(password: str) -> None:
    _hasher.verify(password, _DUMMY_HASH)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_session_token() -> tuple[str, str]:
    """Return (token for the cookie, sha256 hex to store in the database)."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)
