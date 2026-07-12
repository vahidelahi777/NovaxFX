"""Tests for H4BarScheduler."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from novax.live import H4BarScheduler

_H4 = 4 * 3600  # 14 400 seconds


def _utc(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0
) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


class TestNextBarClose:
    def test_next_close_mid_bar(self) -> None:
        # 09:30 UTC → next H4 close is 12:00
        now = _utc(2024, 1, 8, 9, 30)
        nxt = H4BarScheduler.next_bar_close(now)
        assert nxt == _utc(2024, 1, 8, 12, 0)

    def test_next_close_at_exact_boundary(self) -> None:
        # Exactly on 08:00 boundary → next close is 12:00 (never returns now)
        now = _utc(2024, 1, 8, 8, 0, 0)
        nxt = H4BarScheduler.next_bar_close(now)
        assert nxt == _utc(2024, 1, 8, 12, 0)

    def test_next_close_near_boundary(self) -> None:
        # One second before 12:00 → next close is 12:00
        now = _utc(2024, 1, 8, 11, 59, 59)
        nxt = H4BarScheduler.next_bar_close(now)
        assert nxt == _utc(2024, 1, 8, 12, 0)

    def test_next_close_last_bar_of_day(self) -> None:
        # 23:30 → next H4 close is 00:00 next day
        now = _utc(2024, 1, 8, 23, 30)
        nxt = H4BarScheduler.next_bar_close(now)
        assert nxt == _utc(2024, 1, 9, 0, 0)

    def test_next_close_at_20h_boundary(self) -> None:
        # Exactly on 20:00 boundary → next close is 00:00 next day
        now = _utc(2024, 1, 8, 20, 0, 0)
        nxt = H4BarScheduler.next_bar_close(now)
        assert nxt == _utc(2024, 1, 9, 0, 0)

    def test_next_close_result_is_utc_aware(self) -> None:
        now = _utc(2024, 1, 8, 9, 0)
        nxt = H4BarScheduler.next_bar_close(now)
        assert nxt.tzinfo is not None
        assert nxt.utcoffset() == timedelta(0)

    def test_next_close_hour_is_multiple_of_4(self) -> None:
        # Over 3 days sampled every 30 minutes, result hour is always 0,4,8,12,16,20
        base = _utc(2024, 1, 1, 0, 0)
        for i in range(3 * 24 * 2):  # 144 samples
            now = base + timedelta(minutes=30 * i)
            nxt = H4BarScheduler.next_bar_close(now)
            assert nxt.minute == 0 and nxt.second == 0
            assert nxt.hour % 4 == 0

    def test_next_close_always_strictly_after_now(self) -> None:
        # 48 half-hour increments — result always > input
        base = _utc(2024, 3, 10, 0, 0)
        for i in range(48):
            now = base + timedelta(minutes=30 * i)
            nxt = H4BarScheduler.next_bar_close(now)
            assert nxt > now

    def test_next_close_non_utc_input_works(self) -> None:
        # Input in +05:30 (IST) — result should equal UTC 12:00
        ist = timezone(timedelta(hours=5, minutes=30))
        # 09:30 UTC is 15:00 IST; next close is 12:00 UTC = 17:30 IST
        now_ist = datetime(2024, 1, 8, 15, 0, tzinfo=ist)
        nxt = H4BarScheduler.next_bar_close(now_ist)
        assert nxt == _utc(2024, 1, 8, 12, 0)


class TestSecondsUntilNext:
    def test_seconds_until_positive(self) -> None:
        now = _utc(2024, 1, 8, 9, 30)
        assert H4BarScheduler.seconds_until_next(now) > 0

    def test_seconds_until_quantitative(self) -> None:
        # 09:30 → 12:00 is 2.5 hours = 9000 seconds
        now = _utc(2024, 1, 8, 9, 30)
        assert H4BarScheduler.seconds_until_next(now) == pytest.approx(9000.0)

    def test_seconds_until_at_boundary(self) -> None:
        # At 08:00:00 exactly → 4h = 14400 seconds until 12:00
        now = _utc(2024, 1, 8, 8, 0, 0)
        assert H4BarScheduler.seconds_until_next(now) == pytest.approx(14400.0)


class TestNaiveDatetimeRaises:
    def test_naive_datetime_raises(self) -> None:
        naive = datetime(2024, 1, 8, 9, 30)  # no tzinfo
        with pytest.raises(ValueError, match="tz-aware"):
            H4BarScheduler.next_bar_close(naive)
