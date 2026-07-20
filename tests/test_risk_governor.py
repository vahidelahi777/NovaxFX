"""Tests for RiskGovernor (P1.2).

No network, no live DB.  Uses tmp_path and injected `now`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from novax.live.risk_governor import RiskGovernor, trading_day

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ny_dt(hour: int, minute: int = 0, day: int = 1) -> datetime:
    """Build a UTC datetime that corresponds to a given NY hour on 2024-01-{day}."""
    from zoneinfo import ZoneInfo

    ny = datetime(2024, 1, day, hour, minute, tzinfo=ZoneInfo("America/New_York"))
    return ny.astimezone(UTC)


def _gov(tmp_path, **kwargs) -> RiskGovernor:
    return RiskGovernor(tmp_path / "ledger.json", **kwargs)


# ---------------------------------------------------------------------------
# trading_day helper
# ---------------------------------------------------------------------------


def test_trading_day_before_roll_is_previous_date() -> None:
    # 16:59 NY on Jan 2 → still trading day "2024-01-01"
    now = _ny_dt(hour=16, minute=59, day=2)
    assert trading_day(now) == "2024-01-01"


def test_trading_day_at_roll_is_new_date() -> None:
    # 17:00 NY on Jan 2 → trading day "2024-01-02"
    now = _ny_dt(hour=17, minute=0, day=2)
    assert trading_day(now) == "2024-01-02"


def test_trading_day_after_roll() -> None:
    now = _ny_dt(hour=20, day=2)
    assert trading_day(now) == "2024-01-02"


# ---------------------------------------------------------------------------
# Fresh ledger
# ---------------------------------------------------------------------------


def test_not_halted_initially(tmp_path) -> None:
    gov = _gov(tmp_path)
    assert not gov.is_halted(_ny_dt(10))


def test_record_fill_does_not_halt_below_limit(tmp_path) -> None:
    gov = _gov(tmp_path, max_daily_loss_r=3.0)
    gov.record_fill(-1.0, _ny_dt(10))
    gov.record_fill(-1.0, _ny_dt(10))
    assert not gov.is_halted(_ny_dt(10))
    assert gov.ledger.realized_r == pytest.approx(-2.0)


# ---------------------------------------------------------------------------
# Loss-limit trip
# ---------------------------------------------------------------------------


def test_loss_limit_trips_halt(tmp_path) -> None:
    gov = _gov(tmp_path, max_daily_loss_r=3.0)
    now = _ny_dt(10)
    gov.record_fill(-1.5, now)
    tripped = gov.record_fill(-1.5, now)
    assert tripped is True
    assert gov.is_halted(now)
    assert gov.ledger.halt_reason is not None
    assert "loss limit" in gov.ledger.halt_reason


def test_loss_limit_returns_true_only_on_trip(tmp_path) -> None:
    gov = _gov(tmp_path, max_daily_loss_r=3.0)
    now = _ny_dt(10)
    assert gov.record_fill(-1.0, now) is False
    assert gov.record_fill(-1.0, now) is False
    assert gov.record_fill(-1.0, now) is True  # this one trips it


# ---------------------------------------------------------------------------
# Trade-count trip
# ---------------------------------------------------------------------------


def test_trade_count_trips_halt(tmp_path) -> None:
    gov = _gov(tmp_path, max_daily_loss_r=99.0, max_daily_trades=3)
    now = _ny_dt(10)
    gov.record_fill(0.5, now)
    gov.record_fill(0.5, now)
    tripped = gov.record_fill(0.5, now)
    assert tripped is True
    assert gov.is_halted(now)
    assert "max daily trades" in (gov.ledger.halt_reason or "")


# ---------------------------------------------------------------------------
# Latch: halted state persists across reload
# ---------------------------------------------------------------------------


def test_halted_state_persists_across_reload(tmp_path) -> None:
    gov = _gov(tmp_path, max_daily_loss_r=1.0)
    now = _ny_dt(10)
    gov.record_fill(-2.0, now)
    assert gov.is_halted(now)

    gov2 = _gov(tmp_path, max_daily_loss_r=1.0)
    assert gov2.is_halted(now)
    assert gov2.ledger.halted_at is not None


def test_record_fill_after_halt_is_noop(tmp_path) -> None:
    gov = _gov(tmp_path, max_daily_loss_r=1.0)
    now = _ny_dt(10)
    gov.record_fill(-2.0, now)
    tripped = gov.record_fill(-1.0, now)  # already halted
    assert tripped is False
    assert gov.ledger.trades == 1  # trade count didn't increase


# ---------------------------------------------------------------------------
# Day rollover clears halt
# ---------------------------------------------------------------------------


def test_day_rollover_clears_halt(tmp_path) -> None:
    gov = _gov(tmp_path, max_daily_loss_r=1.0)
    day1 = _ny_dt(10, day=1)
    gov.record_fill(-2.0, day1)
    assert gov.is_halted(day1)

    # After rollover (next day, past 17:00 NY)
    day2 = _ny_dt(18, day=2)
    assert not gov.is_halted(day2)
    assert gov.ledger.realized_r == pytest.approx(0.0)
    assert gov.ledger.trades == 0


def test_rollover_accumulates_history(tmp_path) -> None:
    gov = _gov(tmp_path, max_daily_loss_r=99.0)
    day1 = _ny_dt(10, day=1)
    gov.record_fill(-0.5, day1)
    gov.record_fill(1.0, day1)

    day2 = _ny_dt(18, day=2)
    gov.is_halted(day2)  # triggers rollover

    prev_day_label = trading_day(day1)
    assert prev_day_label in gov.ledger.history
    assert gov.ledger.history[prev_day_label] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Corrupt file → fail-safe (halted)
# ---------------------------------------------------------------------------


def test_corrupt_file_loads_halted(tmp_path) -> None:
    path = tmp_path / "ledger.json"
    path.write_text("{invalid json!!!", encoding="utf-8")
    gov = RiskGovernor(path)
    assert gov.is_halted(_ny_dt(10))
    assert "corrupt" in (gov.ledger.halt_reason or "")


def test_missing_file_loads_clean(tmp_path) -> None:
    gov = _gov(tmp_path)
    assert not gov.is_halted(_ny_dt(10))
