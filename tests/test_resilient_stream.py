"""Tests for P1.4: BarBuilder timestamp rejection + ResilientStream helpers.

No network, no TwelveData SDK import.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from novax.data.stream.resilient_stream import (
    backoff_delay,
    filter_new_bars,
    gap_window,
)
from novax.data.stream.twelvedata_ws import BarBuilder

# ---------------------------------------------------------------------------
# BarBuilder: timestamp rejection
# ---------------------------------------------------------------------------


def _builder() -> BarBuilder:
    emitted: list = []
    bb = BarBuilder("XAU/USD", 900, emitted.append)
    bb._emitted = emitted  # type: ignore[attr-defined]
    return bb


def test_bar_builder_rejects_tick_with_no_timestamp(caplog: pytest.LogCaptureFixture) -> None:
    bb = _builder()
    with caplog.at_level("WARNING"):
        bb.push({"event": "price", "price": "2600.00"})
    assert "Rejecting tick with no timestamp" in caplog.text
    assert bb._bar_ts is None


def test_bar_builder_accepts_timestamp_field() -> None:
    emitted: list = []
    bb = BarBuilder("XAU/USD", 900, emitted.append)
    ts = int(datetime(2026, 1, 15, 12, 0, tzinfo=UTC).timestamp())
    bb.push({"event": "price", "price": "2600.00", "timestamp": ts})
    assert bb._bar_ts is not None


def test_bar_builder_accepts_last_trade_time_field() -> None:
    emitted: list = []
    bb = BarBuilder("XAU/USD", 900, emitted.append)
    ts = int(datetime(2026, 1, 15, 12, 0, tzinfo=UTC).timestamp())
    bb.push({"event": "price", "price": "2600.00", "last_trade_time": ts})
    assert bb._bar_ts is not None


def test_bar_builder_rejects_non_price_events() -> None:
    bb = _builder()
    bb.push({"event": "heartbeat"})
    assert bb._bar_ts is None


def test_bar_builder_rejects_malformed_price() -> None:
    bb = _builder()
    bb.push({"event": "price", "price": "not-a-float", "timestamp": 1234567890})
    assert bb._bar_ts is None


# ---------------------------------------------------------------------------
# backoff_delay
# ---------------------------------------------------------------------------


def test_backoff_first_attempt() -> None:
    assert backoff_delay(0) == 1


def test_backoff_second_attempt() -> None:
    assert backoff_delay(1) == 2


def test_backoff_caps_at_last() -> None:
    assert backoff_delay(100) == 60


def test_backoff_custom_sequence() -> None:
    seq = (5, 10, 20)
    assert backoff_delay(0, seq) == 5
    assert backoff_delay(2, seq) == 20
    assert backoff_delay(99, seq) == 20


# ---------------------------------------------------------------------------
# gap_window
# ---------------------------------------------------------------------------


def test_gap_window_start_is_next_bar() -> None:
    last = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    now = datetime(2026, 1, 15, 13, 0, tzinfo=UTC)
    start, end = gap_window(last, 900, now)
    assert start == datetime(2026, 1, 15, 12, 15, tzinfo=UTC)
    assert end == now


def test_gap_window_end_equals_now() -> None:
    last = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    now = datetime(2026, 1, 15, 14, 30, tzinfo=UTC)
    _, end = gap_window(last, 3600, now)
    assert end == now


# ---------------------------------------------------------------------------
# filter_new_bars
# ---------------------------------------------------------------------------


def _make_bar(ts: datetime) -> MagicMock:
    bar = MagicMock()
    bar.ts = ts
    return bar


def test_filter_new_bars_excludes_equal_ts() -> None:
    anchor = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    bars = [_make_bar(anchor), _make_bar(anchor + timedelta(minutes=15))]
    result = filter_new_bars(bars, anchor)
    assert len(result) == 1
    assert result[0].ts == anchor + timedelta(minutes=15)


def test_filter_new_bars_excludes_older() -> None:
    anchor = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    bars = [_make_bar(anchor - timedelta(minutes=15))]
    assert filter_new_bars(bars, anchor) == []


def test_filter_new_bars_returns_sorted() -> None:
    anchor = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    bars = [
        _make_bar(anchor + timedelta(minutes=30)),
        _make_bar(anchor + timedelta(minutes=15)),
        _make_bar(anchor + timedelta(minutes=45)),
    ]
    result = filter_new_bars(bars, anchor)
    assert [b.ts for b in result] == [
        anchor + timedelta(minutes=15),
        anchor + timedelta(minutes=30),
        anchor + timedelta(minutes=45),
    ]


def test_filter_new_bars_empty_input() -> None:
    anchor = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    assert filter_new_bars([], anchor) == []
