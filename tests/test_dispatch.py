"""Tests for B5: dispatch_signal — fan-out wiring.

No network, no DB, no telegram dependency.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from novax.bot import (
    InMemoryUserRepository,
    SubscriptionTier,
    User,
    UserPrefs,
)
from novax.bot.dispatch import dispatch_signal

# ---------------------------------------------------------------------------
# Minimal fakes (same pattern as test_fanout.py)
# ---------------------------------------------------------------------------


@dataclass
class _FakeScore:
    total: int
    label: str


@dataclass
class _FakeSignal:
    symbol: str
    ts: datetime
    direction: str | None
    entry_price: float | None
    sl: float | None
    tp: float | None
    rr: float | None
    score: _FakeScore
    confidence_label: str
    regime: str


def _signal(
    symbol: str = "XAUUSD",
    direction: str = "LONG",
    score: int = 75,
) -> _FakeSignal:
    return _FakeSignal(
        symbol=symbol,
        ts=datetime(2026, 7, 16, 10, 0, tzinfo=UTC),  # London session
        direction=direction,
        entry_price=2350.00,
        sl=2335.00,
        tp=2380.00,
        rr=2.0,
        score=_FakeScore(total=score, label="HIGH" if score >= 70 else "MEDIUM"),
        confidence_label="🟢 High (72% win rate, n=55)",
        regime="trending",
    )


def _user(
    uid: int = 1,
    pairs: frozenset[str] | None = None,
    sessions: frozenset[str] | None = None,
    min_score: int = 70,
    tier: SubscriptionTier = SubscriptionTier.PREMIUM,
    banned: bool = False,
) -> User:
    prefs = UserPrefs(
        pairs=pairs or frozenset({"XAUUSD"}),
        sessions=sessions or frozenset({"LONDON"}),
        min_score=min_score,
    )
    return User(telegram_id=uid, tier=tier, prefs=prefs, banned=banned)


def _london(_dt: datetime) -> str:
    return "LONDON"


def _none(_dt: datetime) -> str | None:
    return None


def _repo(*users: User) -> InMemoryUserRepository:
    repo = InMemoryUserRepository()
    for u in users:
        repo._users[u.telegram_id] = u  # noqa: SLF001
    return repo


# ---------------------------------------------------------------------------
# dispatch_signal — basic fan-out
# ---------------------------------------------------------------------------


def test_matched_user_receives_message() -> None:
    calls: list[tuple[int, str]] = []

    async def fake_send(uid: int, text: str) -> None:
        calls.append((uid, text))

    repo = _repo(_user(uid=1))
    asyncio.run(dispatch_signal(_signal(), repo, fake_send, _london))
    assert len(calls) == 1
    assert calls[0][0] == 1


def test_banned_user_not_dispatched() -> None:
    calls: list[int] = []

    async def fake_send(uid: int, _text: str) -> None:
        calls.append(uid)

    repo = _repo(_user(uid=1, banned=True))
    asyncio.run(dispatch_signal(_signal(), repo, fake_send, _london))
    assert calls == []


def test_wrong_pair_not_dispatched() -> None:
    calls: list[int] = []

    async def fake_send(uid: int, _text: str) -> None:
        calls.append(uid)

    repo = _repo(_user(uid=1, pairs=frozenset({"EURUSD"})))
    asyncio.run(dispatch_signal(_signal(symbol="XAUUSD"), repo, fake_send, _london))
    assert calls == []


def test_low_score_not_dispatched() -> None:
    calls: list[int] = []

    async def fake_send(uid: int, _text: str) -> None:
        calls.append(uid)

    repo = _repo(_user(uid=1, min_score=90))
    asyncio.run(dispatch_signal(_signal(score=75), repo, fake_send, _london))
    assert calls == []


def test_returns_correct_recipient_count() -> None:
    async def fake_send(_uid: int, _text: str) -> None:
        pass

    repo = _repo(_user(uid=1), _user(uid=2, pairs=frozenset({"EURUSD"})))
    n = asyncio.run(dispatch_signal(_signal(), repo, fake_send, _london))
    assert n == 1


def test_empty_repo_returns_zero() -> None:
    async def fake_send(_uid: int, _text: str) -> None:
        pass

    repo = InMemoryUserRepository()
    n = asyncio.run(dispatch_signal(_signal(), repo, fake_send, _london))
    assert n == 0


def test_off_hours_returns_zero() -> None:
    async def fake_send(_uid: int, _text: str) -> None:
        pass

    repo = _repo(_user(uid=1))
    n = asyncio.run(dispatch_signal(_signal(), repo, fake_send, _none))
    assert n == 0


# ---------------------------------------------------------------------------
# dispatch_signal — killswitch
# ---------------------------------------------------------------------------


def test_killswitch_active_skips_fanout() -> None:
    calls: list[int] = []

    async def fake_send(uid: int, _text: str) -> None:
        calls.append(uid)

    repo = _repo(_user(uid=1))
    n = asyncio.run(dispatch_signal(_signal(), repo, fake_send, _london, killswitch=lambda: True))
    assert n == 0
    assert calls == []


def test_killswitch_inactive_allows_fanout() -> None:
    calls: list[int] = []

    async def fake_send(uid: int, _text: str) -> None:
        calls.append(uid)

    repo = _repo(_user(uid=1))
    n = asyncio.run(dispatch_signal(_signal(), repo, fake_send, _london, killswitch=lambda: False))
    assert n == 1
    assert calls == [1]


# ---------------------------------------------------------------------------
# dispatch_signal — protocol compatibility
# ---------------------------------------------------------------------------


def test_dispatch_accepts_any_signalinfocompat_object() -> None:
    """dispatch_signal works with any object structurally satisfying SignalInfo."""
    sig = _signal()

    async def fake_send(_uid: int, _text: str) -> None:
        pass

    # Passes when the object has all required fields — no TypeError from protocol
    asyncio.run(dispatch_signal(sig, InMemoryUserRepository(), fake_send, _london))
