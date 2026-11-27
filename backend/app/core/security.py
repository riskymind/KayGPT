"""Password hashing (Argon2id), session tokens and CSRF tokens."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()  # Argon2id with library defaults (RFC 9106 low-memory profile)

# Verified against when an email does not exist, so login timing does not reveal accounts.
_DUMMY_HASH = _hasher.hash("kaygpt-timing-equalizer")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """Session tokens are stored hashed so a database leak does not yield usable sessions."""
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token_for(session_token: str, secret_key: str) -> str:
    """CSRF token bound to the session via HMAC: no storage, rotates with the session."""
    return hmac.new(
        secret_key.encode(), f"csrf:{session_token}".encode(), hashlib.sha256
    ).hexdigest()


def csrf_token_matches(session_token: str, provided: str | None, secret_key: str) -> bool:
    if not provided:
        return False
    return hmac.compare_digest(csrf_token_for(session_token, secret_key), provided)
