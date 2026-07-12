"""Tests for WeeklyLevelTracker.

All timestamps are UTC-aware. Weeks run Mon–Fri (no Sat/Sun bars, matching
the real XAU/USD H4 dataset).

Year-boundary dates verified with:
    date(2024, 12, 23).isocalendar()  → IsoCalendarDate(year=2024, week=52, weekday=1)
    date(2024, 12, 30).isocalendar()  → IsoCalendarDate(year=2025, week=1,  weekday=1)
    date(2025, 1,  6 ).isocalendar()  → IsoCalendarDate(year=2025, week=2,  weekday=1)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from novax.data_sources import Bar
from novax.indicators import WeeklyLevels, WeeklyLevelTracker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bar(ts: datetime, high: float, low: float) -> Bar:
    mid = (high + low) / 2.0
    return Bar(ts=ts, open=mid, high=high, low=low, close=mid, source="test")


def _monday(year: int, month: int, day: int, hour: int = 0) -> datetime:
    dt = datetime(year, month, day, hour, tzinfo=UTC)
    assert dt.weekday() == 0, f"{dt.date()} is not Monday (weekday={dt.weekday()})"
    return dt


def _feed_week(
    tracker: WeeklyLevelTracker,
    week_start: datetime,
    highs: list[float],
    lows: list[float],
) -> WeeklyLevels | None:
    """Feed one bar per weekday (Mon–Fri). Returns result from the last bar."""
    result: WeeklyLevels | None = None
    for i, (h, lo) in enumerate(zip(highs, lows, strict=True)):
        ts = week_start + timedelta(days=i, hours=8)
        result = tracker.update(_bar(ts, h, lo))
    return result


def _synthetic_year(
    week_start: datetime,
    n_weeks: int,
    bars_per_week: int = 5,
    high: float = 2050.0,
    low: float = 2040.0,
) -> list[Bar]:
    bars: list[Bar] = []
    for w in range(n_weeks):
        for d in range(bars_per_week):
            ts = week_start + timedelta(weeks=w, days=d, hours=8)
            bars.append(_bar(ts, high + w, low + w))
    return bars


# ---------------------------------------------------------------------------
# Returns None during first incomplete week
# ---------------------------------------------------------------------------


class TestWarmup:
    def test_returns_none_on_first_bar(self) -> None:
        tracker = WeeklyLevelTracker()
        result = tracker.update(_bar(_monday(2024, 1, 8), 2050.0, 2040.0))
        assert result is None
        assert tracker.value is None

    def test_returns_none_throughout_first_week(self) -> None:
        tracker = WeeklyLevelTracker()
        for day_offset in range(5):  # Mon–Fri
            ts = datetime(2024, 1, 8, tzinfo=UTC) + timedelta(days=day_offset, hours=8)
            assert tracker.update(_bar(ts, 2050.0, 2040.0)) is None

    def test_returns_none_after_many_bars_same_week(self) -> None:
        tracker = WeeklyLevelTracker()
        # 20 bars, all within ISO week 2 of 2024
        for hour in range(0, 80, 4):
            ts = _monday(2024, 1, 8) + timedelta(hours=hour)
            if ts.weekday() in (5, 6):  # skip weekend
                continue
            assert tracker.update(_bar(ts, 2055.0, 2045.0)) is None


# ---------------------------------------------------------------------------
# First valid result on second week
# ---------------------------------------------------------------------------


class TestFirstResult:
    def test_first_result_on_second_week_first_bar(self) -> None:
        tracker = WeeklyLevelTracker()
        _feed_week(
            tracker,
            week_start=_monday(2024, 1, 8),
            highs=[2055, 2060, 2050, 2058, 2052],
            lows=[2040, 2045, 2038, 2044, 2042],
        )
        result = tracker.update(_bar(_monday(2024, 1, 15), 2065.0, 2058.0))
        assert result is not None
        assert result.prev_high == pytest.approx(2060.0)
        assert result.prev_low == pytest.approx(2038.0)

    def test_prev_high_is_max_of_week_highs(self) -> None:
        tracker = WeeklyLevelTracker()
        _feed_week(
            tracker,
            week_start=_monday(2024, 1, 8),
            highs=[2100, 2080, 2090, 2095, 2085],
            lows=[2060, 2060, 2060, 2060, 2060],
        )
        result = tracker.update(_bar(_monday(2024, 1, 15), 2070.0, 2060.0))
        assert result is not None
        assert result.prev_high == pytest.approx(2100.0)

    def test_prev_low_is_min_of_week_lows(self) -> None:
        tracker = WeeklyLevelTracker()
        _feed_week(
            tracker,
            week_start=_monday(2024, 1, 8),
            highs=[2100, 2100, 2100, 2100, 2100],
            lows=[2050, 2030, 2045, 2040, 2055],
        )
        result = tracker.update(_bar(_monday(2024, 1, 15), 2070.0, 2060.0))
        assert result is not None
        assert result.prev_low == pytest.approx(2030.0)

    def test_curr_levels_seeded_from_first_monday_bar(self) -> None:
        tracker = WeeklyLevelTracker()
        _feed_week(
            tracker,
            week_start=_monday(2024, 1, 8),
            highs=[2060, 2060, 2060, 2060, 2060],
            lows=[2040, 2040, 2040, 2040, 2040],
        )
        first_mon_bar = _bar(_monday(2024, 1, 15), 2075.0, 2065.0)
        result = tracker.update(first_mon_bar)
        assert result is not None
        # curr_high/low seeded from THIS Monday bar, not the previous week
        assert result.curr_high == pytest.approx(2075.0)
        assert result.curr_low == pytest.approx(2065.0)


# ---------------------------------------------------------------------------
# prev_high / prev_low frozen during current week
# ---------------------------------------------------------------------------


class TestPrevLevelsFrozen:
    def test_prev_levels_do_not_change_on_intraweek_bars(self) -> None:
        tracker = WeeklyLevelTracker()
        _feed_week(
            tracker,
            week_start=_monday(2024, 1, 8),
            highs=[2060, 2060, 2060, 2060, 2060],
            lows=[2040, 2040, 2040, 2040, 2040],
        )
        first = tracker.update(_bar(_monday(2024, 1, 15), 2070.0, 2060.0))
        assert first is not None
        saved_prev_h = first.prev_high
        saved_prev_l = first.prev_low

        # Feed 10 more bars in the same week with extreme values
        for i in range(1, 11):
            ts = _monday(2024, 1, 15) + timedelta(hours=4 * i)
            if ts.weekday() in (5, 6):
                continue
            result = tracker.update(_bar(ts, 9999.0, 1000.0))
            assert result is not None
            assert result.prev_high == pytest.approx(saved_prev_h)
            assert result.prev_low == pytest.approx(saved_prev_l)

    def test_week_metadata_frozen_during_week(self) -> None:
        tracker = WeeklyLevelTracker()
        _feed_week(
            tracker,
            week_start=_monday(2024, 1, 8),
            highs=[2060.0] * 5,
            lows=[2040.0] * 5,
        )
        first = tracker.update(_bar(_monday(2024, 1, 15), 2070.0, 2060.0))
        assert first is not None
        assert first.week == _monday(2024, 1, 15).isocalendar().week
        assert first.year == _monday(2024, 1, 15).isocalendar().year

        for i in range(1, 5):
            ts = _monday(2024, 1, 15) + timedelta(days=i, hours=8)
            result = tracker.update(_bar(ts, 2070.0, 2060.0))
            assert result is not None
            assert result.week == first.week
            assert result.year == first.year


# ---------------------------------------------------------------------------
# curr_high / curr_low update within a week
# ---------------------------------------------------------------------------


class TestCurrLevels:
    def _tracker_at_week2(self) -> WeeklyLevelTracker:
        tracker = WeeklyLevelTracker()
        _feed_week(
            tracker,
            week_start=_monday(2024, 1, 8),
            highs=[2060.0] * 5,
            lows=[2040.0] * 5,
        )
        tracker.update(_bar(_monday(2024, 1, 15), 2070.0, 2060.0))
        return tracker

    def test_curr_high_tracks_running_max(self) -> None:
        tracker = self._tracker_at_week2()
        highs = [2071.0, 2085.0, 2080.0, 2090.0]
        expected_max = 2070.0
        for i, h in enumerate(highs):
            expected_max = max(expected_max, h)
            ts = _monday(2024, 1, 15) + timedelta(hours=4 * (i + 1))
            result = tracker.update(_bar(ts, h, h - 5.0))
            assert result is not None
            assert result.curr_high == pytest.approx(expected_max)

    def test_curr_low_tracks_running_min(self) -> None:
        tracker = self._tracker_at_week2()
        lows = [2059.0, 2055.0, 2050.0, 2052.0]
        expected_min = 2060.0
        for i, lo in enumerate(lows):
            expected_min = min(expected_min, lo)
            ts = _monday(2024, 1, 15) + timedelta(hours=4 * (i + 1))
            result = tracker.update(_bar(ts, lo + 5.0, lo))
            assert result is not None
            assert result.curr_low == pytest.approx(expected_min)

    def test_curr_levels_reset_on_new_week(self) -> None:
        tracker = self._tracker_at_week2()
        # Push curr_high/low to extremes within week 2
        for i in range(1, 5):
            ts = _monday(2024, 1, 15) + timedelta(days=i, hours=8)
            tracker.update(_bar(ts, 2200.0, 1900.0))

        # Start week 3 — curr_high/low must reset to this bar's high/low
        mon3_bar = _bar(_monday(2024, 1, 22), 2075.0, 2065.0)
        result = tracker.update(mon3_bar)
        assert result is not None
        assert result.curr_high == pytest.approx(2075.0)
        assert result.curr_low == pytest.approx(2065.0)


# ---------------------------------------------------------------------------
# Three consecutive weeks chain correctly
# ---------------------------------------------------------------------------


class TestThreeWeekChain:
    def test_three_weeks_prev_levels_chain(self) -> None:
        tracker = WeeklyLevelTracker()

        # Week A: high=2100, low=2000
        _feed_week(
            tracker,
            week_start=_monday(2024, 1, 8),
            highs=[2100, 2090, 2095, 2085, 2080],
            lows=[2000, 2010, 2005, 2015, 2020],
        )

        # Week B: at start, prev should be week A
        _feed_week(
            tracker,
            week_start=_monday(2024, 1, 15),
            highs=[2150, 2140, 2145, 2135, 2130],
            lows=[2050, 2060, 2055, 2065, 2070],
        )
        result_b_start = tracker.update(_bar(_monday(2024, 1, 15), 2150.0, 2050.0))
        # (week B was already started above, so this is mid-week B — but prev is still A)
        assert result_b_start is not None
        assert result_b_start.prev_high == pytest.approx(2100.0)
        assert result_b_start.prev_low == pytest.approx(2000.0)

        # Week C: at start, prev should be week B
        result_c = tracker.update(_bar(_monday(2024, 1, 22), 2200.0, 2100.0))
        assert result_c is not None
        assert result_c.prev_high == pytest.approx(2150.0)
        assert result_c.prev_low == pytest.approx(2050.0)

    def test_three_weeks_curr_seeded_from_each_monday(self) -> None:
        tracker = WeeklyLevelTracker()
        _feed_week(tracker, _monday(2024, 1, 8), [2100.0] * 5, [2000.0] * 5)
        _feed_week(tracker, _monday(2024, 1, 15), [2150.0] * 5, [2050.0] * 5)
        result = tracker.update(_bar(_monday(2024, 1, 22), 2210.0, 2110.0))
        assert result is not None
        assert result.curr_high == pytest.approx(2210.0)
        assert result.curr_low == pytest.approx(2110.0)


# ---------------------------------------------------------------------------
# Year boundary: ISO week 52 (2024) → ISO week 1 (2025)
# ---------------------------------------------------------------------------


class TestYearBoundary:
    def test_year_boundary_2024_to_2025(self) -> None:
        # 2024-12-23 → ISO 2024-W52  (Monday)
        # 2024-12-30 → ISO 2025-W01  (Monday)
        tracker = WeeklyLevelTracker()

        # Feed week W52-2024 (Mon Dec 23 → Fri Dec 27)
        _feed_week(
            tracker,
            week_start=datetime(2024, 12, 23, tzinfo=UTC),
            highs=[2650.0, 2660.0, 2645.0, 2655.0, 2640.0],
            lows=[2620.0, 2625.0, 2615.0, 2630.0, 2610.0],
        )

        # First bar of W01-2025 (Mon Dec 30)
        result = tracker.update(_bar(datetime(2024, 12, 30, tzinfo=UTC), 2670.0, 2660.0))
        assert result is not None
        assert result.prev_high == pytest.approx(2660.0)
        assert result.prev_low == pytest.approx(2610.0)
        assert result.year == 2025
        assert result.week == 1

    def test_year_boundary_prev_levels_correct_after_crossing(self) -> None:
        tracker = WeeklyLevelTracker()
        _feed_week(
            tracker,
            week_start=datetime(2024, 12, 23, tzinfo=UTC),
            highs=[2650.0] * 5,
            lows=[2600.0] * 5,
        )
        # Feed W01-2025 and W02-2025
        _feed_week(
            tracker,
            week_start=datetime(2024, 12, 30, tzinfo=UTC),
            highs=[2680.0] * 5,
            lows=[2640.0] * 5,
        )
        result = tracker.update(_bar(datetime(2025, 1, 6, tzinfo=UTC), 2700.0, 2680.0))
        assert result is not None
        assert result.prev_high == pytest.approx(2680.0)
        assert result.prev_low == pytest.approx(2640.0)
        assert result.year == 2025
        assert result.week == 2


# ---------------------------------------------------------------------------
# value property
# ---------------------------------------------------------------------------


class TestValueProperty:
    def test_value_is_none_before_first_week(self) -> None:
        tracker = WeeklyLevelTracker()
        assert tracker.value is None

    def test_value_matches_last_update_return(self) -> None:
        tracker = WeeklyLevelTracker()
        _feed_week(tracker, _monday(2024, 1, 8), [2060.0] * 5, [2040.0] * 5)
        bar = _bar(_monday(2024, 1, 15), 2065.0, 2055.0)
        ret = tracker.update(bar)
        assert ret is tracker.value

    def test_value_updates_each_bar(self) -> None:
        tracker = WeeklyLevelTracker()
        _feed_week(tracker, _monday(2024, 1, 8), [2060.0] * 5, [2040.0] * 5)
        tracker.update(_bar(_monday(2024, 1, 15), 2070.0, 2060.0))

        prev_value = tracker.value
        tracker.update(_bar(_monday(2024, 1, 15) + timedelta(hours=4), 2080.0, 2070.0))
        assert tracker.value is not prev_value  # new dataclass instance each update


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_single_bar_per_week(self) -> None:
        tracker = WeeklyLevelTracker()
        # Week 1: one bar only
        tracker.update(_bar(_monday(2024, 1, 8), 2055.0, 2045.0))
        # Week 2: one bar — triggers week boundary
        result = tracker.update(_bar(_monday(2024, 1, 15), 2065.0, 2055.0))
        assert result is not None
        assert result.prev_high == pytest.approx(2055.0)
        assert result.prev_low == pytest.approx(2045.0)

    def test_multiple_bars_on_monday(self) -> None:
        tracker = WeeklyLevelTracker()
        _feed_week(tracker, _monday(2024, 1, 8), [2060.0] * 5, [2040.0] * 5)
        # Three bars on the same Monday — only first triggers the boundary
        r1 = tracker.update(_bar(_monday(2024, 1, 15, 0), 2070.0, 2060.0))
        r2 = tracker.update(_bar(_monday(2024, 1, 15, 4), 2075.0, 2065.0))
        r3 = tracker.update(_bar(_monday(2024, 1, 15, 8), 2080.0, 2070.0))
        assert r1 is not None
        assert r2 is not None
        assert r3 is not None
        # prev levels must not change between r1, r2, r3
        assert r1.prev_high == r2.prev_high == r3.prev_high
        assert r1.prev_low == r2.prev_low == r3.prev_low
        # curr_high must grow
        assert r3.curr_high == pytest.approx(2080.0)
        assert r3.curr_low == pytest.approx(2060.0)

    def test_prev_high_always_above_prev_low(self) -> None:
        tracker = WeeklyLevelTracker()
        _feed_week(
            tracker,
            week_start=_monday(2024, 1, 8),
            highs=[2060.0, 2058.0, 2062.0, 2057.0, 2059.0],
            lows=[2040.0, 2042.0, 2038.0, 2043.0, 2041.0],
        )
        result = tracker.update(_bar(_monday(2024, 1, 15), 2065.0, 2055.0))
        assert result is not None
        assert result.prev_high > result.prev_low


# ---------------------------------------------------------------------------
# Integration: week count over a synthetic year
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_week_count_on_synthetic_year(self) -> None:
        tracker = WeeklyLevelTracker()
        bars = _synthetic_year(
            week_start=_monday(2024, 1, 8),
            n_weeks=52,
            bars_per_week=5,
        )
        non_none = sum(1 for bar in bars if tracker.update(bar) is not None)
        # Week 1 (5 bars) → None. Weeks 2–52 (51 × 5 = 255 bars) → non-None.
        assert non_none == 51 * 5

    def test_levels_against_real_data(self) -> None:
        """Verify tracker runs without error on the real XAU/USD data structure."""
        from datetime import UTC
        from pathlib import Path

        try:
            from novax.data.loader.bar_loader import load_bars

            bars = load_bars(
                Path("data/market"),
                "XAU/USD",
                "4h",
                datetime(2023, 7, 1, tzinfo=UTC),
                datetime(2024, 1, 1, tzinfo=UTC),
            )
        except Exception:
            pytest.skip("real data not available")

        tracker = WeeklyLevelTracker()
        results = [tracker.update(b) for b in bars]
        non_none = [r for r in results if r is not None]
        assert len(non_none) > 0
        for r in non_none:
            assert r.prev_high > r.prev_low
            assert r.curr_high >= r.curr_low
