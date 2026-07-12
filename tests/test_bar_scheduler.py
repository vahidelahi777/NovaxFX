"""Tests for BarScheduler (generic interval scheduler)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from novax.live import BarScheduler


def _utc(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0
) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


class TestBarScheduler15m:
    def test_15m_next_close_alignment_mid_window(self) -> None:
        # 09:07 → next 15M close is 09:15
        now = _utc(2024, 1, 8, 9, 7)
        nxt = BarScheduler(900).next_bar_close(now)
        assert nxt == _utc(2024, 1, 8, 9, 15)

    def test_15m_at_exact_boundary_advances(self) -> None:
        # 09:15:00 exactly → next close is 09:30 (never returns current instant)
        now = _utc(2024, 1, 8, 9, 15, 0)
        nxt = BarScheduler(900).next_bar_close(now)
        assert nxt == _utc(2024, 1, 8, 9, 30)

    def test_15m_always_strictly_after_now(self) -> None:
        base = _utc(2024, 3, 10, 0, 0)
        sched = BarScheduler(900)
        for i in range(96):  # one full day in 15-min steps
            now = base + timedelta(minutes=15 * i)
            assert sched.next_bar_close(now) > now

    def test_15m_result_minutes_multiple_of_15(self) -> None:
        base = _utc(2024, 1, 1, 0, 0)
        sched = BarScheduler(900)
        for i in range(2 * 24 * 4):  # 2 days sampled every 15 min
            now = base + timedelta(minutes=15 * i + 7)  # mid-window
            nxt = sched.next_bar_close(now)
            assert nxt.second == 0
            assert nxt.minute % 15 == 0


class TestBarScheduler1h:
    def test_1h_next_close_alignment(self) -> None:
        # 09:30 → next 1H close is 10:00
        now = _utc(2024, 1, 8, 9, 30)
        nxt = BarScheduler(3600).next_bar_close(now)
        assert nxt == _utc(2024, 1, 8, 10, 0)

    def test_1h_at_exact_boundary_advances(self) -> None:
        now = _utc(2024, 1, 8, 10, 0, 0)
        nxt = BarScheduler(3600).next_bar_close(now)
        assert nxt == _utc(2024, 1, 8, 11, 0)

    def test_1h_result_hour_aligned(self) -> None:
        sched = BarScheduler(3600)
        base = _utc(2024, 1, 1, 0, 0)
        for i in range(48):
            now = base + timedelta(minutes=30 * i)
            nxt = sched.next_bar_close(now)
            assert nxt.minute == 0 and nxt.second == 0


class TestBarSchedulerValidation:
    def test_invalid_interval_45s_raises(self) -> None:
        with pytest.raises(ValueError, match="multiple of 60"):
            BarScheduler(45)

    def test_invalid_interval_90s_raises(self) -> None:
        with pytest.raises(ValueError, match="multiple of 60"):
            BarScheduler(90)

    def test_invalid_interval_zero_raises(self) -> None:
        with pytest.raises(ValueError):
            BarScheduler(0)

    def test_invalid_interval_negative_raises(self) -> None:
        with pytest.raises(ValueError):
            BarScheduler(-900)

    def test_valid_interval_60s_accepted(self) -> None:
        sched = BarScheduler(60)
        now = _utc(2024, 1, 8, 9, 0, 30)
        nxt = sched.next_bar_close(now)
        assert nxt == _utc(2024, 1, 8, 9, 1, 0)

    def test_naive_datetime_raises(self) -> None:
        sched = BarScheduler(900)
        with pytest.raises(ValueError, match="tz-aware"):
            sched.next_bar_close(datetime(2024, 1, 8, 9, 7))


class TestBarSchedulerSecondsUntil:
    def test_seconds_until_positive(self) -> None:
        now = _utc(2024, 1, 8, 9, 7)
        assert BarScheduler(900).seconds_until_next(now) > 0

    def test_seconds_until_15m_quantitative(self) -> None:
        # 09:07 → 09:15 is 8 minutes = 480 seconds
        now = _utc(2024, 1, 8, 9, 7)
        assert BarScheduler(900).seconds_until_next(now) == pytest.approx(480.0)

    def test_seconds_until_at_boundary(self) -> None:
        # At 09:15:00 exactly → full 900 seconds until 09:30
        now = _utc(2024, 1, 8, 9, 15, 0)
        assert BarScheduler(900).seconds_until_next(now) == pytest.approx(900.0)
