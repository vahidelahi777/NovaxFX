"""Admin authentication: password hashing, signed session tokens, CSRF, rate-limiting.

Pure module — no FastAPI, no psycopg, no network. Fully unit-testable.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import argon2
import argon2.exceptions
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

__all__ = [
    "RateLimiter",
    "generate_csrf",
    "hash_password",
    "issue_session",
    "verify_csrf",
    "verify_password",
    "verify_session",
]

_PH = argon2.PasswordHasher()

_SESSION_SALT = "session-v1"
_CSRF_SALT = "csrf-v1"


# ---------------------------------------------------------------------------
# Password
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    """Return an argon2id hash of *password* (for the setup/keygen tool)."""
    return _PH.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Return True iff *password* matches *password_hash*; never raises."""
    try:
        _PH.verify(password_hash, password)
        return True
    except argon2.exceptions.VerifyMismatchError:
        return False
    except argon2.exceptions.VerificationError:
        return False
    except argon2.exceptions.InvalidHashError:
        return False


# ---------------------------------------------------------------------------
# Session tokens
# ---------------------------------------------------------------------------


def issue_session(secret: str, identity: str) -> str:
    """Return a signed, timestamped session token for *identity*."""
    s = URLSafeTimedSerializer(secret, salt=_SESSION_SALT)
    token: str = s.dumps(identity)
    return token


def verify_session(secret: str, token: str, max_age: int = 8 * 3600) -> str | None:
    """Return the identity embedded in *token* if valid and fresh; else None."""
    s = URLSafeTimedSerializer(secret, salt=_SESSION_SALT)
    try:
        payload = s.loads(token, max_age=max_age)
        return str(payload)
    except (SignatureExpired, BadSignature):
        return None


# ---------------------------------------------------------------------------
# CSRF tokens
# ---------------------------------------------------------------------------


def generate_csrf(secret: str) -> str:
    """Return a signed CSRF token (include as a hidden form field)."""
    s = URLSafeTimedSerializer(secret, salt=_CSRF_SALT)
    token: str = s.dumps("csrf")
    return token


def verify_csrf(secret: str, token: str, max_age: int = 3600) -> bool:
    """Return True iff *token* is a valid, unexpired CSRF token."""
    s = URLSafeTimedSerializer(secret, salt=_CSRF_SALT)
    try:
        s.loads(token, max_age=max_age)
        return True
    except (SignatureExpired, BadSignature):
        return False


# ---------------------------------------------------------------------------
# Login rate-limiter
# ---------------------------------------------------------------------------


class RateLimiter:
    """In-memory per-key login rate-limiter.

    Args:
        max_failures:    Failures before lockout.
        lockout_seconds: Lockout duration after threshold is reached.
        clock:           Monotonic clock (injectable for testing).
    """

    def __init__(
        self,
        max_failures: int = 5,
        lockout_seconds: float = 300.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.max_failures = max_failures
        self.lockout_seconds = lockout_seconds
        self._clock: Callable[[], float] = clock if clock is not None else time.monotonic
        self._failures: dict[str, int] = {}
        self._lockout_until: dict[str, float] = {}

    def is_locked(self, key: str) -> bool:
        """Return True if *key* is currently in a lockout window."""
        until = self._lockout_until.get(key, 0.0)
        if self._clock() < until:
            return True
        if until > 0.0:
            self._failures.pop(key, None)
            self._lockout_until.pop(key, None)
        return False

    def record_failure(self, key: str) -> None:
        """Record a failed attempt; lock *key* when threshold is reached."""
        if self.is_locked(key):
            return
        count = self._failures.get(key, 0) + 1
        self._failures[key] = count
        if count >= self.max_failures:
            self._lockout_until[key] = self._clock() + self.lockout_seconds

    def reset(self, key: str) -> None:
        """Clear failure count and lockout for *key* (call on successful login)."""
        self._failures.pop(key, None)
        self._lockout_until.pop(key, None)
