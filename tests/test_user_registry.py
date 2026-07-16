"""Tests for the user registry — models + in-memory repository (A2).

No database required; the in-memory repo covers the full behavioural contract
that the Postgres implementation must also satisfy.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from novax.bot import (
    DEFAULT_MIN_SCORE,
    InMemoryUserRepository,
    SubscriptionTier,
    UserNotFoundError,
    UserPrefs,
    ensure_user,
)


def _fixed_clock() -> datetime:
    return datetime(2026, 7, 16, 12, 0, tzinfo=UTC)


# ---- models -----------------------------------------------------------------


def test_userprefs_defaults_are_gold_first() -> None:
    prefs = UserPrefs()
    assert prefs.pairs == frozenset({"XAUUSD"})
    assert prefs.sessions == frozenset({"LONDON", "NY"})
    assert prefs.min_score == DEFAULT_MIN_SCORE


def test_userprefs_normalises_case_and_whitespace() -> None:
    prefs = UserPrefs(pairs=frozenset({" eurusd ", "xauusd"}), sessions=frozenset({" london "}))
    assert prefs.pairs == frozenset({"EURUSD", "XAUUSD"})
    assert prefs.sessions == frozenset({"LONDON"})


def test_userprefs_rejects_out_of_range_score() -> None:
    with pytest.raises(ValueError):
        UserPrefs(min_score=101)


def test_userprefs_roundtrips_through_dict() -> None:
    prefs = UserPrefs(pairs=frozenset({"EURUSD"}), sessions=frozenset({"NY"}), min_score=80)
    assert UserPrefs.from_dict(prefs.to_dict()) == prefs


# ---- repository -------------------------------------------------------------


def test_create_or_get_is_idempotent() -> None:
    repo = InMemoryUserRepository(now=_fixed_clock)
    first = repo.create_or_get(42, first_name="Vahid")
    again = repo.create_or_get(42, first_name="Changed")
    assert first == again  # second call does not overwrite
    assert repo.count() == 1
    assert first.tier is SubscriptionTier.FREE
    assert first.created_at == _fixed_clock()


def test_ensure_user_registers_on_first_contact() -> None:
    repo = InMemoryUserRepository(now=_fixed_clock)
    user = ensure_user(repo, 7, first_name="Ada", username="ada")
    assert user.telegram_id == 7
    assert repo.get(7) == user


def test_set_tier_and_prefs_update_and_bump_timestamp() -> None:
    repo = InMemoryUserRepository(now=_fixed_clock)
    repo.create_or_get(1, first_name="A")
    upgraded = repo.set_tier(1, SubscriptionTier.PRO)
    assert upgraded.tier is SubscriptionTier.PRO
    newprefs = UserPrefs(pairs=frozenset({"GBPUSD"}), min_score=90)
    updated = repo.set_prefs(1, newprefs)
    assert updated.prefs == newprefs
    assert updated.updated_at == _fixed_clock()


def test_updates_on_unknown_user_raise() -> None:
    repo = InMemoryUserRepository()
    with pytest.raises(UserNotFoundError):
        repo.set_tier(999, SubscriptionTier.PREMIUM)
    with pytest.raises(UserNotFoundError):
        repo.set_prefs(999, UserPrefs())


def test_list_by_tier_filters() -> None:
    repo = InMemoryUserRepository()
    repo.create_or_get(1)
    repo.create_or_get(2)
    repo.set_tier(2, SubscriptionTier.PREMIUM)
    assert [u.telegram_id for u in repo.list_by_tier(SubscriptionTier.FREE)] == [1]
    assert [u.telegram_id for u in repo.list_by_tier(SubscriptionTier.PREMIUM)] == [2]


def test_inmemory_satisfies_repository_protocol() -> None:
    from novax.bot.registry import UserRepository

    assert isinstance(InMemoryUserRepository(), UserRepository)
