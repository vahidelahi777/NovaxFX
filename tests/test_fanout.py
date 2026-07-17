"""Tests for B1: per-user signal fan-out (fanout.py) and delivery wiring.

No network, no DB, no telegram dependency.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from novax.bot import (
    InMemoryUserRepository,
    Recipient,
    SubscriptionTier,
    User,
    UserPrefs,
    format_signal_message,
    select_recipients,
)
from novax.bot.delivery import deliver
from novax.bot.messages import DISCLAIMER

# ---------------------------------------------------------------------------
# Test fixtures — fake signal satisfying SignalInfo protocol
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
    session_ts: datetime | None = None,
    direction: str = "LONG",
    score: int = 75,
    entry: float = 2350.00,
    sl: float = 2335.00,
    tp: float = 2380.00,
    rr: float = 2.0,
) -> _FakeSignal:
    ts = session_ts or datetime(2026, 7, 16, 10, 0, tzinfo=UTC)  # London session
    return _FakeSignal(
        symbol=symbol,
        ts=ts,
        direction=direction,
        entry_price=entry,
        sl=sl,
        tp=tp,
        rr=rr,
        score=_FakeScore(total=score, label="HIGH" if score >= 70 else "MEDIUM"),
        confidence_label="🟢 High (72% win rate, n=55)",
        regime="trending",
    )


def _user(
    uid: int = 1,
    pairs: frozenset[str] | None = None,
    sessions: frozenset[str] | None = None,
    min_score: int = 70,
    tier: SubscriptionTier = SubscriptionTier.FREE,
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


# ---------------------------------------------------------------------------
# select_recipients — filter tests
# ---------------------------------------------------------------------------


def test_matching_user_is_included() -> None:
    users = [_user(uid=1)]
    result = select_recipients(_signal(), users, _london)
    assert len(result) == 1
    assert result[0].user.telegram_id == 1


def test_wrong_pair_excluded() -> None:
    users = [_user(pairs=frozenset({"EURUSD"}))]
    result = select_recipients(_signal(symbol="XAUUSD"), users, _london)
    assert result == []


def test_wrong_session_excluded() -> None:
    users = [_user(sessions=frozenset({"NEWYORK"}))]
    result = select_recipients(_signal(), users, _london)  # session_of → "LONDON"
    assert result == []


def test_score_below_min_excluded() -> None:
    users = [_user(min_score=80)]
    result = select_recipients(_signal(score=75), users, _london)
    assert result == []


def test_score_equal_to_min_included() -> None:
    users = [_user(min_score=75)]
    result = select_recipients(_signal(score=75), users, _london)
    assert len(result) == 1


def test_banned_user_excluded() -> None:
    users = [_user(banned=True)]
    result = select_recipients(_signal(), users, _london)
    assert result == []


def test_off_hours_session_excludes_all() -> None:
    users = [_user(sessions=frozenset({"LONDON", "NEWYORK"}))]
    result = select_recipients(_signal(), users, _none)
    assert result == []


def test_multiple_users_filtered_independently() -> None:
    good = _user(uid=1)
    bad_pair = _user(uid=2, pairs=frozenset({"EURUSD"}))
    bad_score = _user(uid=3, min_score=90)
    banned = _user(uid=4, banned=True)
    users = [good, bad_pair, bad_score, banned]
    result = select_recipients(_signal(), users, _london)
    assert len(result) == 1
    assert result[0].user.telegram_id == 1


# ---------------------------------------------------------------------------
# select_recipients — delay tests
# ---------------------------------------------------------------------------


def test_free_tier_gets_default_delay() -> None:
    users = [_user(tier=SubscriptionTier.FREE)]
    result = select_recipients(_signal(), users, _london, free_delay_seconds=1800)
    assert result[0].delay_seconds == 1800


def test_premium_tier_gets_zero_delay() -> None:
    users = [_user(tier=SubscriptionTier.PREMIUM)]
    result = select_recipients(_signal(), users, _london)
    assert result[0].delay_seconds == 0


def test_pro_tier_gets_zero_delay() -> None:
    users = [_user(tier=SubscriptionTier.PRO)]
    result = select_recipients(_signal(), users, _london)
    assert result[0].delay_seconds == 0


def test_custom_free_delay() -> None:
    users = [_user(tier=SubscriptionTier.FREE)]
    result = select_recipients(_signal(), users, _london, free_delay_seconds=900)
    assert result[0].delay_seconds == 900


# ---------------------------------------------------------------------------
# format_signal_message
# ---------------------------------------------------------------------------


def test_message_contains_direction() -> None:
    text = format_signal_message(_signal(direction="LONG"))
    assert "LONG" in text


def test_message_contains_symbol() -> None:
    text = format_signal_message(_signal(symbol="XAUUSD"))
    assert "XAUUSD" in text


def test_message_contains_entry_sl_tp() -> None:
    text = format_signal_message(_signal(entry=2350.00, sl=2335.00, tp=2380.00))
    assert "2350.00" in text
    assert "2335.00" in text
    assert "2380.00" in text


def test_message_contains_score() -> None:
    text = format_signal_message(_signal(score=75))
    assert "75" in text


def test_message_contains_disclaimer() -> None:
    text = format_signal_message(_signal())
    assert DISCLAIMER in text


def test_message_handles_none_levels() -> None:
    sig = _FakeSignal(
        symbol="XAUUSD",
        ts=datetime(2026, 7, 16, 10, 0, tzinfo=UTC),
        direction=None,
        entry_price=None,
        sl=None,
        tp=None,
        rr=None,
        score=_FakeScore(total=72, label="HIGH"),
        confidence_label="⚪ Unproven (5 samples)",
        regime="ranging",
    )
    text = format_signal_message(sig)
    assert "FLAT" in text
    assert "—" in text
    assert DISCLAIMER in text


# ---------------------------------------------------------------------------
# list_all — InMemoryUserRepository
# ---------------------------------------------------------------------------


def test_list_all_empty_repo() -> None:
    repo = InMemoryUserRepository()
    assert repo.list_all() == []


def test_list_all_returns_all_users_sorted() -> None:
    repo = InMemoryUserRepository()
    repo.create_or_get(3, first_name="C")
    repo.create_or_get(1, first_name="A")
    repo.create_or_get(2, first_name="B")
    ids = [u.telegram_id for u in repo.list_all()]
    assert ids == [1, 2, 3]


def test_list_all_count_matches() -> None:
    repo = InMemoryUserRepository()
    for i in range(5):
        repo.create_or_get(i)
    assert len(repo.list_all()) == repo.count()


def test_inmemory_satisfies_repository_protocol_with_list_all() -> None:
    from novax.bot.registry import UserRepository

    assert isinstance(InMemoryUserRepository(), UserRepository)


# ---------------------------------------------------------------------------
# deliver() — async wiring
# ---------------------------------------------------------------------------


def test_deliver_sends_to_all_recipients() -> None:
    calls: list[tuple[int, str]] = []
    sleep_calls: list[float] = []

    async def fake_send(uid: int, text: str) -> None:
        calls.append((uid, text))

    async def fake_sleep(secs: float) -> None:
        sleep_calls.append(secs)

    sig = _signal()
    recipients = [
        Recipient(user=_user(uid=1, tier=SubscriptionTier.PREMIUM), delay_seconds=0),
        Recipient(user=_user(uid=2, tier=SubscriptionTier.FREE), delay_seconds=1800),
    ]

    asyncio.run(deliver(sig, recipients, fake_send, sleep=fake_sleep))

    expected_text = format_signal_message(sig)
    assert (1, expected_text) in calls
    assert (2, expected_text) in calls


def test_deliver_sleeps_for_free_tier() -> None:
    sleep_calls: list[float] = []

    async def fake_send(_uid: int, _text: str) -> None:
        pass

    async def fake_sleep(secs: float) -> None:
        sleep_calls.append(secs)

    recipients = [
        Recipient(user=_user(uid=1, tier=SubscriptionTier.FREE), delay_seconds=1800),
    ]
    asyncio.run(deliver(_signal(), recipients, fake_send, sleep=fake_sleep))
    assert sleep_calls == [1800.0]


def test_deliver_no_sleep_for_premium() -> None:
    sleep_calls: list[float] = []

    async def fake_send(_uid: int, _text: str) -> None:
        pass

    async def fake_sleep(secs: float) -> None:
        sleep_calls.append(secs)

    recipients = [
        Recipient(user=_user(uid=1, tier=SubscriptionTier.PREMIUM), delay_seconds=0),
    ]
    asyncio.run(deliver(_signal(), recipients, fake_send, sleep=fake_sleep))
    assert sleep_calls == []


def test_deliver_empty_recipients_is_noop() -> None:
    called = False

    async def fake_send(_uid: int, _text: str) -> None:
        nonlocal called
        called = True

    asyncio.run(deliver(_signal(), [], fake_send))
    assert not called


def test_deliver_uses_correct_telegram_ids() -> None:
    calls: list[int] = []

    async def fake_send(uid: int, _text: str) -> None:
        calls.append(uid)

    async def fake_sleep(_secs: float) -> None:
        pass

    recipients = [
        Recipient(user=_user(uid=42, tier=SubscriptionTier.PREMIUM), delay_seconds=0),
        Recipient(user=_user(uid=99, tier=SubscriptionTier.FREE), delay_seconds=600),
    ]
    asyncio.run(deliver(_signal(), recipients, fake_send, sleep=fake_sleep))
    assert sorted(calls) == [42, 99]


# ---------------------------------------------------------------------------
# Recipient dataclass
# ---------------------------------------------------------------------------


def test_recipient_is_frozen() -> None:
    import dataclasses

    r = Recipient(user=_user(), delay_seconds=0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.delay_seconds = 99
