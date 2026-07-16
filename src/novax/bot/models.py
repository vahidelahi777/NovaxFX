"""Domain models for the product bot's user registry (Phase 0 · A2).

Pure, immutable, dependency-free — no database, no telegram. The Postgres and
in-memory repositories both round-trip these types.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Any

__all__ = [
    "DEFAULT_MIN_SCORE",
    "SubscriptionTier",
    "User",
    "UserPrefs",
]

# Repo convention: signal_score >= 70 is "high-confidence / send alert".
DEFAULT_MIN_SCORE = 70


class SubscriptionTier(StrEnum):
    """Monetisation tiers (see task F1). Stored as its lowercase value."""

    FREE = "free"
    PREMIUM = "premium"
    PRO = "pro"


def _norm_pairs(pairs: frozenset[str]) -> frozenset[str]:
    return frozenset(p.strip().upper() for p in pairs if p.strip())


def _norm_sessions(sessions: frozenset[str]) -> frozenset[str]:
    return frozenset(s.strip().upper() for s in sessions if s.strip())


@dataclass(frozen=True)
class UserPrefs:
    """A user's signal-delivery preferences."""

    pairs: frozenset[str] = frozenset({"XAUUSD"})
    sessions: frozenset[str] = frozenset({"LONDON", "NY"})
    min_score: int = DEFAULT_MIN_SCORE

    def __post_init__(self) -> None:
        object.__setattr__(self, "pairs", _norm_pairs(self.pairs))
        object.__setattr__(self, "sessions", _norm_sessions(self.sessions))
        if not 0 <= self.min_score <= 100:
            raise ValueError(f"min_score must be in [0, 100], got {self.min_score}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "pairs": sorted(self.pairs),
            "sessions": sorted(self.sessions),
            "min_score": self.min_score,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> UserPrefs:
        pairs = frozenset(str(p) for p in (data.get("pairs") or []))
        sessions = frozenset(str(s) for s in (data.get("sessions") or []))
        raw_score = data.get("min_score", DEFAULT_MIN_SCORE)
        min_score = int(raw_score) if isinstance(raw_score, int | str) else DEFAULT_MIN_SCORE
        return cls(pairs=pairs, sessions=sessions, min_score=min_score)


@dataclass(frozen=True)
class User:
    """A registered bot user."""

    telegram_id: int
    first_name: str | None = None
    username: str | None = None
    tier: SubscriptionTier = SubscriptionTier.FREE
    prefs: UserPrefs = field(default_factory=UserPrefs)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def with_tier(self, tier: SubscriptionTier) -> User:
        return replace(self, tier=tier)

    def with_prefs(self, prefs: UserPrefs) -> User:
        return replace(self, prefs=prefs)
