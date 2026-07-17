"""Tests for novax.admin.auth — no network, no DB, no live server."""

from __future__ import annotations

from novax.admin.auth import (
    RateLimiter,
    generate_csrf,
    hash_password,
    issue_session,
    verify_csrf,
    verify_password,
    verify_session,
)

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


def test_hash_and_verify_correct_password() -> None:
    h = hash_password("correct-horse-battery")
    assert verify_password(h, "correct-horse-battery") is True


def test_wrong_password_rejected() -> None:
    h = hash_password("correct")
    assert verify_password(h, "wrong") is False


def test_invalid_hash_string_rejected() -> None:
    assert verify_password("not-a-valid-argon2-hash", "anything") is False


def test_empty_password_against_hash() -> None:
    h = hash_password("somepassword")
    assert verify_password(h, "") is False


# ---------------------------------------------------------------------------
# Session tokens
# ---------------------------------------------------------------------------

_SECRET = "test-session-secret-long-enough"


def test_session_round_trip() -> None:
    token = issue_session(_SECRET, "admin")
    assert verify_session(_SECRET, token) == "admin"


def test_session_wrong_secret_rejected() -> None:
    token = issue_session("secret-a", "admin")
    assert verify_session("secret-b", token) is None


def test_session_tampered_rejected() -> None:
    token = issue_session(_SECRET, "admin")
    assert verify_session(_SECRET, token + "x") is None


def test_session_expired() -> None:
    token = issue_session(_SECRET, "admin")
    # max_age=-1 makes every token immediately expired
    assert verify_session(_SECRET, token, max_age=-1) is None


def test_session_empty_string_rejected() -> None:
    assert verify_session(_SECRET, "") is None


# ---------------------------------------------------------------------------
# CSRF tokens
# ---------------------------------------------------------------------------


def test_csrf_round_trip() -> None:
    token = generate_csrf(_SECRET)
    assert verify_csrf(_SECRET, token) is True


def test_csrf_tampered_rejected() -> None:
    token = generate_csrf(_SECRET)
    assert verify_csrf(_SECRET, token[:-4] + "xxxx") is False


def test_csrf_wrong_secret_rejected() -> None:
    token = generate_csrf("secret-a")
    assert verify_csrf("secret-b", token) is False


def test_csrf_expired() -> None:
    token = generate_csrf(_SECRET)
    assert verify_csrf(_SECRET, token, max_age=-1) is False


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------


def _fake_clock(initial: float = 0.0) -> list[float]:
    """Return a mutable single-element list whose value is the fake 'now'."""
    return [initial]


def test_rate_limiter_not_locked_before_threshold() -> None:
    limiter = RateLimiter(max_failures=3)
    limiter.record_failure("ip1")
    limiter.record_failure("ip1")
    assert limiter.is_locked("ip1") is False


def test_rate_limiter_locked_at_threshold() -> None:
    now: list[float] = [0.0]
    limiter = RateLimiter(max_failures=3, lockout_seconds=60.0, clock=lambda: now[0])
    for _ in range(3):
        limiter.record_failure("ip1")
    assert limiter.is_locked("ip1") is True


def test_rate_limiter_lockout_expires() -> None:
    now: list[float] = [0.0]
    limiter = RateLimiter(max_failures=3, lockout_seconds=60.0, clock=lambda: now[0])
    for _ in range(3):
        limiter.record_failure("ip1")
    assert limiter.is_locked("ip1") is True
    now[0] = 61.0
    assert limiter.is_locked("ip1") is False


def test_rate_limiter_reset_clears_lockout() -> None:
    limiter = RateLimiter(max_failures=3)
    for _ in range(3):
        limiter.record_failure("ip1")
    assert limiter.is_locked("ip1") is True
    limiter.reset("ip1")
    assert limiter.is_locked("ip1") is False


def test_rate_limiter_reset_clears_partial_failures() -> None:
    limiter = RateLimiter(max_failures=5)
    limiter.record_failure("ip1")
    limiter.record_failure("ip1")
    limiter.reset("ip1")
    # After reset, need another max_failures attempts to lock
    for _ in range(4):
        limiter.record_failure("ip1")
    assert limiter.is_locked("ip1") is False
    limiter.record_failure("ip1")
    assert limiter.is_locked("ip1") is True


def test_rate_limiter_keys_are_independent() -> None:
    limiter = RateLimiter(max_failures=3)
    for _ in range(3):
        limiter.record_failure("ip1")
    assert limiter.is_locked("ip1") is True
    assert limiter.is_locked("ip2") is False


def test_rate_limiter_record_during_lockout_is_ignored() -> None:
    now: list[float] = [0.0]
    limiter = RateLimiter(max_failures=3, lockout_seconds=60.0, clock=lambda: now[0])
    for _ in range(3):
        limiter.record_failure("ip1")
    # Extra failures during lockout don't extend or reset anything
    for _ in range(10):
        limiter.record_failure("ip1")
    now[0] = 61.0
    # Lockout expired — should be unlocked
    assert limiter.is_locked("ip1") is False
