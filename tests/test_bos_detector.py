"""Tests for BOSDetector: BOS, Order Block, CHoCH."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from novax.indicators import BOSDetector, BOSState
from novax.indicators.weekly_levels import WeeklyLevels, WeeklyLevelTracker

# Monday 2024-01-08 00:00 UTC — ISO 2024-W02
WEEK1_MON = datetime(2024, 1, 8, tzinfo=UTC)
H4 = timedelta(hours=4)
DAY = timedelta(days=1)
WEEK = timedelta(weeks=1)


def make_bar(ts: datetime, open_: float, high: float, low: float, close: float):
    from novax.data_sources import Bar

    return Bar(ts=ts, open=open_, high=high, low=low, close=close)


def make_levels(
    prev_high: float,
    prev_low: float,
    curr_high: float,
    curr_low: float,
    week: int = 2,
    year: int = 2024,
) -> WeeklyLevels:
    return WeeklyLevels(
        prev_high=prev_high,
        prev_low=prev_low,
        curr_high=curr_high,
        curr_low=curr_low,
        week=week,
        year=year,
    )


# ---------------------------------------------------------------------------
# Warmup / None propagation
# ---------------------------------------------------------------------------


def test_returns_none_when_levels_none():
    det = BOSDetector()
    bar = make_bar(WEEK1_MON, 1.1000, 1.1010, 1.0990, 1.1005)
    assert det.update(bar, None) is None
    assert det.value is None


def test_buffer_fills_during_none_levels():
    det = BOSDetector()
    for i in range(5):
        ts = WEEK1_MON + i * H4
        bar = make_bar(ts, 1.1000, 1.1010, 1.0990, 1.1005)
        result = det.update(bar, None)
        assert result is None


# ---------------------------------------------------------------------------
# IDLE state — close within range
# ---------------------------------------------------------------------------


def test_idle_when_close_within_range():
    det = BOSDetector()
    lvls = make_levels(prev_high=1.2000, prev_low=1.1000, curr_high=1.1500, curr_low=1.1200)
    bar = make_bar(WEEK1_MON, 1.1400, 1.1450, 1.1380, 1.1420)
    result = det.update(bar, lvls)
    assert result is not None
    assert result.state == BOSState.IDLE
    assert math.isnan(result.bos_level)


# ---------------------------------------------------------------------------
# BOS_UP trigger
# ---------------------------------------------------------------------------


def test_bos_up_on_close_above_prev_high():
    det = BOSDetector()
    lvls = make_levels(prev_high=1.2000, prev_low=1.1000, curr_high=1.1500, curr_low=1.1200)
    bar = make_bar(WEEK1_MON, 1.1900, 1.2100, 1.1880, 1.2050)
    result = det.update(bar, lvls)
    assert result is not None
    assert result.state == BOSState.BOS_UP
    assert result.bos_level == pytest.approx(1.2000)


def test_bos_up_not_triggered_by_wick_alone():
    det = BOSDetector()
    lvls = make_levels(prev_high=1.2000, prev_low=1.1000, curr_high=1.1500, curr_low=1.1200)
    # High > prev_high but close < prev_high
    bar = make_bar(WEEK1_MON, 1.1900, 1.2050, 1.1880, 1.1980)
    result = det.update(bar, lvls)
    assert result is not None
    assert result.state == BOSState.IDLE


# ---------------------------------------------------------------------------
# BOS_DOWN trigger
# ---------------------------------------------------------------------------


def test_bos_down_on_close_below_prev_low():
    det = BOSDetector()
    lvls = make_levels(prev_high=1.2000, prev_low=1.1000, curr_high=1.1500, curr_low=1.1050)
    bar = make_bar(WEEK1_MON, 1.1050, 1.1060, 1.0940, 1.0950)
    result = det.update(bar, lvls)
    assert result is not None
    assert result.state == BOSState.BOS_DOWN
    assert result.bos_level == pytest.approx(1.1000)


def test_bos_down_not_triggered_by_wick_alone():
    det = BOSDetector()
    lvls = make_levels(prev_high=1.2000, prev_low=1.1000, curr_high=1.1500, curr_low=1.1050)
    # Low < prev_low but close > prev_low
    bar = make_bar(WEEK1_MON, 1.1050, 1.1060, 1.0980, 1.1020)
    result = det.update(bar, lvls)
    assert result is not None
    assert result.state == BOSState.IDLE


# ---------------------------------------------------------------------------
# OB detection — BOS_UP
# ---------------------------------------------------------------------------


def test_ob_found_for_bos_up_last_bearish_candle():
    det = BOSDetector()
    lvls = make_levels(prev_high=1.2000, prev_low=1.1000, curr_high=1.1500, curr_low=1.1200)

    # Buffer: bullish bar first, bearish bar second
    bullish = make_bar(WEEK1_MON, 1.1400, 1.1460, 1.1380, 1.1450)
    bearish = make_bar(WEEK1_MON + H4, 1.1460, 1.1500, 1.1430, 1.1440)  # open > close
    det.update(bullish, lvls)
    det.update(bearish, lvls)

    # BOS bar: close must exceed prev_high=1.2000
    bos_bar = make_bar(WEEK1_MON + 2 * H4, 1.1900, 1.2100, 1.1880, 1.2050)
    result = det.update(bos_bar, lvls)

    assert result is not None
    assert result.state == BOSState.BOS_UP
    assert result.has_ob
    assert result.ob_high == pytest.approx(bearish.high)
    assert result.ob_low == pytest.approx(bearish.low)


def test_ob_not_found_when_only_bullish_candles():
    det = BOSDetector()
    lvls = make_levels(prev_high=1.2000, prev_low=1.1000, curr_high=1.1500, curr_low=1.1200)

    # Buffer: only bullish bars
    for i in range(3):
        b = make_bar(WEEK1_MON + i * H4, 1.1400, 1.1460, 1.1380, 1.1450)
        det.update(b, lvls)

    bos_bar = make_bar(WEEK1_MON + 3 * H4, 1.1900, 1.2100, 1.1880, 1.2050)
    result = det.update(bos_bar, lvls)

    assert result is not None
    assert result.state == BOSState.BOS_UP
    assert not result.has_ob
    assert math.isnan(result.ob_high)
    assert math.isnan(result.ob_low)


# ---------------------------------------------------------------------------
# OB detection — BOS_DOWN
# ---------------------------------------------------------------------------


def test_ob_found_for_bos_down_last_bullish_candle():
    det = BOSDetector()
    lvls = make_levels(prev_high=1.2000, prev_low=1.1000, curr_high=1.1500, curr_low=1.1050)

    # Buffer: bearish first, bullish second
    bearish = make_bar(WEEK1_MON, 1.1200, 1.1220, 1.1160, 1.1170)
    bullish = make_bar(WEEK1_MON + H4, 1.1170, 1.1210, 1.1150, 1.1200)  # close > open
    det.update(bearish, lvls)
    det.update(bullish, lvls)

    bos_bar = make_bar(WEEK1_MON + 2 * H4, 1.1050, 1.1060, 1.0940, 1.0950)
    result = det.update(bos_bar, lvls)

    assert result is not None
    assert result.state == BOSState.BOS_DOWN
    assert result.has_ob
    assert result.ob_high == pytest.approx(bullish.high)
    assert result.ob_low == pytest.approx(bullish.low)


# ---------------------------------------------------------------------------
# OB excludes BOS bar itself
# ---------------------------------------------------------------------------


def test_ob_excludes_bos_bar():
    """Buffer is scanned BEFORE appending current bar — BOS bar not its own OB."""
    det = BOSDetector()
    lvls = make_levels(prev_high=1.2000, prev_low=1.1000, curr_high=1.1500, curr_low=1.1200)

    # Feed exactly one bearish bar into the buffer
    bearish = make_bar(WEEK1_MON, 1.1460, 1.1500, 1.1430, 1.1440)
    det.update(bearish, lvls)

    # BOS bar is also bearish — should not be its own OB
    bos_bar = make_bar(WEEK1_MON + H4, 1.1950, 1.2100, 1.1920, 1.2010)
    result = det.update(bos_bar, lvls)

    assert result is not None
    assert result.has_ob
    assert result.ob_high == pytest.approx(bearish.high)
    assert result.ob_low == pytest.approx(bearish.low)


# ---------------------------------------------------------------------------
# State sticky within week
# ---------------------------------------------------------------------------


def test_state_sticky_after_bos_up():
    det = BOSDetector()
    lvls = make_levels(prev_high=1.2000, prev_low=1.1000, curr_high=1.1500, curr_low=1.1200)

    bos_bar = make_bar(WEEK1_MON, 1.1900, 1.2100, 1.1880, 1.2050)
    det.update(bos_bar, lvls)

    for i in range(1, 5):
        bar = make_bar(WEEK1_MON + i * H4, 1.2100, 1.2150, 1.2080, 1.2110)
        result = det.update(bar, lvls)
        assert result is not None
        assert result.state == BOSState.BOS_UP


# ---------------------------------------------------------------------------
# Week reset
# ---------------------------------------------------------------------------


def test_state_resets_on_new_week():
    det = BOSDetector()
    lvls_w2 = make_levels(
        prev_high=1.2000, prev_low=1.1000, curr_high=1.1500, curr_low=1.1200, week=2, year=2024
    )

    # Trigger BOS_UP in week 2
    bos_bar = make_bar(WEEK1_MON, 1.1900, 1.2100, 1.1880, 1.2050)
    result = det.update(bos_bar, lvls_w2)
    assert result is not None
    assert result.state == BOSState.BOS_UP

    # First bar of week 3 — same prev levels (tracker frozen them)
    lvls_w3 = make_levels(
        prev_high=1.2100, prev_low=1.1050, curr_high=1.1900, curr_low=1.1800, week=3, year=2024
    )
    week3_mon = WEEK1_MON + WEEK
    bar_w3 = make_bar(week3_mon, 1.1850, 1.1900, 1.1830, 1.1870)
    result_w3 = det.update(bar_w3, lvls_w3)
    assert result_w3 is not None
    assert result_w3.state == BOSState.IDLE


# ---------------------------------------------------------------------------
# CHoCH
# ---------------------------------------------------------------------------


def test_choch_bearish_detected_week3():
    """W1 high=1.2000, W2 high=1.1900 → choch_bearish True in W3."""
    det = BOSDetector()

    # Week 2: prev_high=1.2000 (W1 high)
    lvls_w2 = make_levels(
        prev_high=1.2000, prev_low=1.1000, curr_high=1.1900, curr_low=1.1100, week=2, year=2024
    )
    bar_w2 = make_bar(WEEK1_MON, 1.1500, 1.1600, 1.1400, 1.1500)
    r2 = det.update(bar_w2, lvls_w2)
    assert r2 is not None
    assert not r2.choch_bearish  # only 1 week of history

    # Week 3: prev_high=1.1900 (W2 high < W1 high=1.2000 → bearish CHoCH)
    #          prev_low=1.0900  (W2 low < W1 low=1.1000 → no bullish CHoCH)
    lvls_w3 = make_levels(
        prev_high=1.1900, prev_low=1.0900, curr_high=1.1800, curr_low=1.1200, week=3, year=2024
    )
    bar_w3 = make_bar(WEEK1_MON + WEEK, 1.1500, 1.1600, 1.1400, 1.1500)
    r3 = det.update(bar_w3, lvls_w3)
    assert r3 is not None
    assert r3.choch_bearish  # prev_high=1.1900 < two_weeks_ago_high=1.2000
    assert not r3.choch_bullish  # prev_low=1.0900 < two_weeks_ago_low=1.1000


def test_choch_bullish_detected_week3():
    """W1 low=1.1800, W2 low=1.1900 → choch_bullish True in W3."""
    det = BOSDetector()

    lvls_w2 = make_levels(
        prev_high=1.2000, prev_low=1.1800, curr_high=1.1900, curr_low=1.1900, week=2, year=2024
    )
    bar_w2 = make_bar(WEEK1_MON, 1.1850, 1.1900, 1.1840, 1.1880)
    det.update(bar_w2, lvls_w2)

    lvls_w3 = make_levels(
        prev_high=1.2000, prev_low=1.1900, curr_high=1.1950, curr_low=1.1920, week=3, year=2024
    )
    bar_w3 = make_bar(WEEK1_MON + WEEK, 1.1930, 1.1960, 1.1920, 1.1940)
    r3 = det.update(bar_w3, lvls_w3)
    assert r3 is not None
    assert r3.choch_bullish  # prev_low=1.1900 > two_weeks_ago_low=1.1800
    assert not r3.choch_bearish


def test_choch_false_with_insufficient_history():
    det = BOSDetector()
    lvls = make_levels(prev_high=1.2000, prev_low=1.1000, curr_high=1.1500, curr_low=1.1200)
    bar = make_bar(WEEK1_MON, 1.1400, 1.1450, 1.1380, 1.1420)
    result = det.update(bar, lvls)
    assert result is not None
    assert not result.choch_bearish
    assert not result.choch_bullish


# ---------------------------------------------------------------------------
# Year boundary W52 → W01
# ---------------------------------------------------------------------------


def test_year_boundary_w52_to_w01():
    """2024-12-30 is ISO 2025-W01 — week key changes, state resets."""
    det = BOSDetector()

    # W52 of 2024 (e.g. 2024-12-23 Mon)
    mon_w52 = datetime(2024, 12, 23, tzinfo=UTC)
    lvls_w52 = make_levels(
        prev_high=2650.0, prev_low=2600.0, curr_high=2640.0, curr_low=2610.0, week=52, year=2024
    )
    bos_bar = make_bar(mon_w52, 2648.0, 2655.0, 2646.0, 2652.0)
    r52 = det.update(bos_bar, lvls_w52)
    assert r52 is not None
    assert r52.state == BOSState.BOS_UP

    # W01 of 2025 (2024-12-30)
    mon_w01 = datetime(2024, 12, 30, tzinfo=UTC)
    lvls_w01 = make_levels(
        prev_high=2640.0, prev_low=2610.0, curr_high=2635.0, curr_low=2615.0, week=1, year=2025
    )
    bar_w01 = make_bar(mon_w01, 2620.0, 2628.0, 2618.0, 2623.0)
    r01 = det.update(bar_w01, lvls_w01)
    assert r01 is not None
    assert r01.state == BOSState.IDLE  # reset on new (year, week) key


# ---------------------------------------------------------------------------
# value property
# ---------------------------------------------------------------------------


def test_value_property_matches_last_update():
    det = BOSDetector()
    lvls = make_levels(prev_high=1.2000, prev_low=1.1000, curr_high=1.1500, curr_low=1.1200)
    bar = make_bar(WEEK1_MON, 1.1400, 1.1450, 1.1380, 1.1420)
    result = det.update(bar, lvls)
    assert det.value is result


# ---------------------------------------------------------------------------
# Integration smoke test — 3 full synthetic weeks of H4 bars
# ---------------------------------------------------------------------------


def test_integration_three_weeks():
    """
    Week 1: WeeklyLevelTracker returns None → BOSDetector returns None.
    Week 2: first bar IDLE, last bar triggers BOS_UP.
    Week 3: Monday resets to IDLE.
    """
    tracker = WeeklyLevelTracker()
    det = BOSDetector()

    # Synthetic H4: 6 bars/day × 5 days = 30 bars/week
    # Week 1 — 2024-01-08 to 2024-01-12
    bars_w1 = []
    base_w1 = datetime(2024, 1, 8, tzinfo=UTC)
    for day in range(5):
        for h in range(6):
            ts = base_w1 + day * DAY + h * H4
            bars_w1.append(make_bar(ts, 1.1000, 1.1050, 1.0990, 1.1020))

    for bar in bars_w1:
        lvls = tracker.update(bar)
        result = det.update(bar, lvls)
        assert result is None, "Week 1: BOSDetector must return None (no prev week yet)"

    # Week 2 — 2024-01-15 to 2024-01-19
    # Keep close below prev_high=1.1050 for first 29 bars, then spike on last
    bars_w2 = []
    base_w2 = datetime(2024, 1, 15, tzinfo=UTC)
    for day in range(5):
        for h in range(6):
            ts = base_w2 + day * DAY + h * H4
            if day == 4 and h == 5:
                # Last bar of week 2 — BOS_UP: close > prev_high
                bars_w2.append(make_bar(ts, 1.1040, 1.1080, 1.1030, 1.1060))
            else:
                bars_w2.append(make_bar(ts, 1.1010, 1.1040, 1.1000, 1.1020))

    week2_states = []
    for bar in bars_w2:
        lvls = tracker.update(bar)
        result = det.update(bar, lvls)
        assert result is not None
        week2_states.append(result.state)

    assert week2_states[-1] == BOSState.BOS_UP, "Last W2 bar must be BOS_UP"
    assert all(s == BOSState.IDLE for s in week2_states[:-1]), "W2 bars before BOS must be IDLE"

    # Week 3 — first bar resets to IDLE
    base_w3 = datetime(2024, 1, 22, tzinfo=UTC)
    first_w3 = make_bar(base_w3, 1.1050, 1.1080, 1.1040, 1.1055)
    lvls_w3 = tracker.update(first_w3)
    result_w3 = det.update(first_w3, lvls_w3)
    assert result_w3 is not None
    assert result_w3.state == BOSState.IDLE, "Week 3 first bar must reset to IDLE"
