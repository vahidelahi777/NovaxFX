"""User registry — repository interface + in-memory implementation (Phase 0 · A2).

The protocol defines the contract; ``InMemoryUserRepository`` is the tested,
dependency-free implementation used in unit tests and local dev. The Postgres
implementation lives in ``db_postgres.py`` and honours the same protocol.

A ``now`` clock is injectable so timestamps are deterministic under test.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from .models import SubscriptionTier, User, UserPrefs

__all__ = [
    "InMemoryUserRepository",
    "UserNotFoundError",
    "UserRepository",
    "ensure_user",
]


class UserNotFoundError(KeyError):
    """Raised when an update targets a telegram_id that is not registered."""


@runtime_checkable
class UserRepository(Protocol):
    """Storage contract for bot users. All implementations are interchangeable."""

    def get(self, telegram_id: int) -> User | None: ...

    def create_or_get(
        self, telegram_id: int, first_name: str | None = None, username: str | None = None
    ) -> User: ...

    def set_tier(self, telegram_id: int, tier: SubscriptionTier) -> User: ...

    def set_prefs(self, telegram_id: int, prefs: UserPrefs) -> User: ...

    def list_by_tier(self, tier: SubscriptionTier) -> list[User]: ...

    def list_all(self) -> list[User]: ...

    def count(self) -> int: ...


def _utcnow() -> datetime:
    return datetime.now(UTC)


class InMemoryUserRepository:
    """Dict-backed repository — for tests and local development only."""

    def __init__(self, now: Callable[[], datetime] = _utcnow) -> None:
        self._now = now
        self._users: dict[int, User] = {}

    def get(self, telegram_id: int) -> User | None:
        return self._users.get(telegram_id)

    def create_or_get(
        self, telegram_id: int, first_name: str | None = None, username: str | None = None
    ) -> User:
        existing = self._users.get(telegram_id)
        if existing is not None:
            return existing
        ts = self._now()
        user = User(
            telegram_id=telegram_id,
            first_name=first_name,
            username=username,
            tier=SubscriptionTier.FREE,
            prefs=UserPrefs(),
            created_at=ts,
            updated_at=ts,
        )
        self._users[telegram_id] = user
        return user

    def _require(self, telegram_id: int) -> User:
        user = self._users.get(telegram_id)
        if user is None:
            raise UserNotFoundError(telegram_id)
        return user

    def set_tier(self, telegram_id: int, tier: SubscriptionTier) -> User:
        from dataclasses import replace

        user = replace(self._require(telegram_id), tier=tier, updated_at=self._now())
        self._users[telegram_id] = user
        return user

    def set_prefs(self, telegram_id: int, prefs: UserPrefs) -> User:
        from dataclasses import replace

        user = replace(self._require(telegram_id), prefs=prefs, updated_at=self._now())
        self._users[telegram_id] = user
        return user

    def list_by_tier(self, tier: SubscriptionTier) -> list[User]:
        return [u for u in self._users.values() if u.tier == tier]

    def list_all(self) -> list[User]:
        return sorted(self._users.values(), key=lambda u: u.telegram_id)

    def count(self) -> int:
        return len(self._users)


def ensure_user(
    repo: UserRepository,
    telegram_id: int,
    first_name: str | None = None,
    username: str | None = None,
) -> User:
    """Idempotently register a user on first contact (called from /start).

    Thin service helper so command handlers stay free of storage details.
    """
    return repo.create_or_get(telegram_id, first_name=first_name, username=username)
