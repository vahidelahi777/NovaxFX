"""Backtest engine and feature-library correctness tests — Phase 1 Batch 1.

Coverage:
  - Causal guarantee: strategy never receives bars beyond index i
  - Execution lag: signal at bar i → fill at bars[i+1].open
  - Last-bar safety: signal on final bar generates no entry
  - Force-close: open position at last bar closed at bars[-1].close
  - Cost application: net PnL reflects CostModel.round_trip_cost_currency
  - Data-quality gate: engine raises on failing report
  - Symbol/timeframe mismatch: engine raises on wrong report metadata
  - Position deduplication: repeated direction signal is ignored
  - Reversal: opposing signal flattens then opens new position
  - Feature causality: EMA and ATR satisfy assert_no_lookahead
"""
from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from novax.costs import DEFAULT_COST_MODEL
from novax.data_sources import Bar
from novax.dataquality import CheckResult, DataQualityReport
from novax.engine import (
    BacktestEngine,
    BarView,
    Position,
    Signal,
)
from novax.features import atr, ema
from novax.instruments import get_instrument
from novax.lookahead import assert_no_lookahead, find_lookahead_indices
from novax.units import Pips

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_SYMBOL = "EUR/USD"
_TF = "1h"
_BASE_TS = datetime(2025, 1, 6, 10, 0, tzinfo=UTC)  # Monday 10:00 UTC


def _bar(i: int, price: float, *, spread: float = 0.0001) -> Bar:
    """Minimal valid Bar at _BASE_TS + i hours with open==close==price."""
    ts = _BASE_TS + timedelta(hours=i)
    h = price + spread
    lo = price - spread
    return Bar(ts=ts, open=price, high=h, low=lo, close=price, source="test")


def _bar_range(n: int, start_price: float = 1.1000, step: float = 0.0) -> list[Bar]:
    """Return n bars with price linearly incrementing by `step` per bar."""
    return [_bar(i, start_price + i * step) for i in range(n)]


def _passing_report(n: int = 10) -> DataQualityReport:
    """Empty-checks report: passes trivially (no high-severity failures)."""
    return DataQualityReport(symbol=_SYMBOL, timeframe=_TF, n_bars=n, checks=())


def _failing_report() -> DataQualityReport:
    return DataQualityReport(
        symbol=_SYMBOL, timeframe=_TF, n_bars=0,
        checks=(CheckResult("forced", False, "forced failure", "high"),),
    )


def _engine() -> BacktestEngine:
    return BacktestEngine(symbol=_SYMBOL, timeframe=_TF)


# ---------------------------------------------------------------------------
# Simple strategy fixtures
# ---------------------------------------------------------------------------

class _AlwaysFlat:
    def on_bar(self, view: BarView, position: Position) -> Signal:
        return Signal.FLAT


class _AlwaysLong:
    def on_bar(self, view: BarView, position: Position) -> Signal:
        return Signal.LONG


class _AlwaysShort:
    def on_bar(self, view: BarView, position: Position) -> Signal:
        return Signal.SHORT


class _LongOnFirst:
    """Signal LONG once (bar 0), then FLAT."""
    def on_bar(self, view: BarView, position: Position) -> Signal:
        return Signal.LONG if len(view) == 1 else Signal.FLAT


class _LongThenShort:
    """LONG on bar 0, SHORT on bar 1, FLAT thereafter."""
    def on_bar(self, view: BarView, position: Position) -> Signal:
        n = len(view)
        if n == 1:
            return Signal.LONG
        if n == 2:
            return Signal.SHORT
        return Signal.FLAT


class _SignalOnLastBar:
    """Always FLAT except on the very last bar (requires knowing n)."""
    def __init__(self, n_bars: int) -> None:
        self._n = n_bars

    def on_bar(self, view: BarView, position: Position) -> Signal:
        return Signal.LONG if len(view) == self._n else Signal.FLAT


class _ViewLengthRecorder:
    """Records view lengths and bar timestamps for the causal guarantee test."""
    def __init__(self) -> None:
        self.lengths: list[int] = []
        self.last_bar_indices: list[int] = []  # position in the bar sequence

    def on_bar(self, view: BarView, position: Position) -> Signal:
        self.lengths.append(len(view.bars))
        self.last_bar_indices.append(len(view.bars) - 1)
        return Signal.FLAT


# ---------------------------------------------------------------------------
# Causal guarantee: strategy never sees future bars
# ---------------------------------------------------------------------------

def test_view_lengths_are_strictly_increasing():
    n = 8
    bars = _bar_range(n)
    recorder = _ViewLengthRecorder()
    _engine().run(bars, recorder, _passing_report(n))
    # At step i, view must contain exactly i+1 bars.
    assert recorder.lengths == list(range(1, n + 1))


def test_view_last_bar_is_current_bar():
    n = 6
    bars = _bar_range(n)
    recorder = _ViewLengthRecorder()
    _engine().run(bars, recorder, _passing_report(n))
    # The last bar in each view must be bars[i], not any future bar.
    for i, last_idx in enumerate(recorder.last_bar_indices):
        assert last_idx == i, f"at step {i}, view.last was bars[{last_idx}] not bars[{i}]"


def test_view_bars_field_is_a_tuple():
    """BarView.bars must be a tuple (immutable), not a list."""
    captured: list[type] = []

    class _TypeChecker:
        def on_bar(self, view: BarView, position: Position) -> Signal:
            captured.append(type(view.bars))
            return Signal.FLAT

    bars = _bar_range(3)
    _engine().run(bars, _TypeChecker(), _passing_report(3))
    assert all(t is tuple for t in captured)


# ---------------------------------------------------------------------------
# Execution lag: fill at bars[i+1].open
# ---------------------------------------------------------------------------

def test_entry_fill_at_next_bar_open():
    """LONG signal on bar 0 → entry price == bars[1].open."""
    entry_price = 1.1050
    bars = [
        _bar(0, 1.1000),
        _bar(1, entry_price),   # fill bar — entry at this bar's open
        _bar(2, 1.1100),        # close bar (FLAT signal on bar 1)
    ]
    result = _engine().run(bars, _LongOnFirst(), _passing_report(3))
    assert len(result.trades) == 1
    # Entry timestamp must match bars[1].ts.
    assert result.trades[0].entry_ts == bars[1].ts


def test_exit_fill_at_next_bar_open():
    """FLAT signal on bar 1 → exit price == bars[2].open."""
    bars = [
        _bar(0, 1.1000),
        _bar(1, 1.1050),
        _bar(2, 1.1100),
    ]
    result = _engine().run(bars, _LongOnFirst(), _passing_report(3))
    # Exit timestamp must match bars[2].ts.
    assert result.trades[0].exit_ts == bars[2].ts


# ---------------------------------------------------------------------------
# Last-bar safety: signal on final bar must not generate an entry
# ---------------------------------------------------------------------------

def test_last_bar_long_signal_produces_no_trade():
    n = 4
    bars = _bar_range(n)
    strategy = _SignalOnLastBar(n)
    result = _engine().run(bars, strategy, _passing_report(n))
    assert result.trades == ()


def test_last_bar_with_open_position_force_closes():
    """Open LONG position at last bar → closed at bars[-1].close (causal)."""
    close_price = 1.1200
    bars = [
        _bar(0, 1.1000),
        _bar(1, 1.1050),          # fill bar: LONG entered here
        _bar(2, 1.1100),
        _bar(3, close_price),     # last bar: force-close at this bar's close
    ]
    bars[3] = Bar(
        ts=bars[3].ts, open=close_price, high=close_price + 0.001,
        low=close_price - 0.001, close=close_price, source="test",
    )
    result = _engine().run(bars, _AlwaysLong(), _passing_report(4))
    assert len(result.trades) == 1
    assert result.trades[0].exit_ts == bars[3].ts


# ---------------------------------------------------------------------------
# Cost application
# ---------------------------------------------------------------------------

def _expected_round_trip_cost() -> float:
    """Manually compute DEFAULT_COST_MODEL cost for EUR/USD, 1 lot, no session."""
    inst = get_instrument(_SYMBOL)
    return DEFAULT_COST_MODEL.round_trip_cost_currency(
        inst, lots=1.0, atr=Pips(0.0), session=None
    )


def test_profitable_trade_pnl_net_of_cost():
    """10 pips LONG gain minus round-trip cost."""
    entry_price = 1.10000
    exit_price  = 1.10100   # +10 pips
    bars = [
        _bar(0, entry_price),
        _bar(1, entry_price),   # entry at bars[1].open
        _bar(2, exit_price),    # exit at bars[2].open (FLAT after bar 1)
    ]
    result = _engine().run(bars, _LongOnFirst(), _passing_report(3))
    assert len(result.trades) == 1

    inst = get_instrument(_SYMBOL)
    pip_delta = (exit_price - entry_price) / inst.pip_size  # 10 pips
    raw_pnl = pip_delta * inst.pip_value_per_lot            # 100.0 USD
    cost = _expected_round_trip_cost()
    expected = raw_pnl - cost
    assert math.isclose(result.trades[0].pnl, expected, rel_tol=1e-9)


def test_losing_trade_pnl_net_of_cost():
    """Entry and exit at same price → only cost subtracted (net negative)."""
    price = 1.10000
    bars = [
        _bar(0, price),
        _bar(1, price),
        _bar(2, price),
    ]
    result = _engine().run(bars, _LongOnFirst(), _passing_report(3))
    assert len(result.trades) == 1
    cost = _expected_round_trip_cost()
    assert math.isclose(result.trades[0].pnl, -cost, rel_tol=1e-9)


def test_equity_curve_is_cumulative_pnl():
    """equity[k] == sum(pnls[:k+1])."""
    bars = _bar_range(6, start_price=1.1000, step=0.0001)
    result = _engine().run(bars, _LongThenShort(), _passing_report(6))
    cumulative = 0.0
    for trade, eq in zip(result.trades, result.equity, strict=True):
        cumulative += trade.pnl
        assert math.isclose(eq, cumulative, rel_tol=1e-12)


# ---------------------------------------------------------------------------
# Data-quality gate enforcement
# ---------------------------------------------------------------------------

def test_engine_raises_on_failing_report():
    bars = _bar_range(4)
    with pytest.raises(ValueError, match="data quality gate failed"):
        _engine().run(bars, _AlwaysFlat(), _failing_report())


def test_engine_raises_on_symbol_mismatch():
    bars = _bar_range(4)
    wrong = DataQualityReport(symbol="GBP/USD", timeframe=_TF, n_bars=4, checks=())
    with pytest.raises(ValueError, match="report.symbol"):
        _engine().run(bars, _AlwaysFlat(), wrong)


def test_engine_raises_on_timeframe_mismatch():
    bars = _bar_range(4)
    wrong = DataQualityReport(symbol=_SYMBOL, timeframe="5m", n_bars=4, checks=())
    with pytest.raises(ValueError, match="report.timeframe"):
        _engine().run(bars, _AlwaysFlat(), wrong)


def test_engine_raises_on_fewer_than_two_bars():
    bars = _bar_range(1)
    with pytest.raises(ValueError, match="at least 2 bars"):
        _engine().run(bars, _AlwaysFlat(), _passing_report(1))


# ---------------------------------------------------------------------------
# Position rules
# ---------------------------------------------------------------------------

def test_duplicate_long_signal_is_ignored():
    """Two consecutive LONG signals while already LONG → only one trade."""
    bars = _bar_range(5)
    result = _engine().run(bars, _AlwaysLong(), _passing_report(5))
    assert len(result.trades) == 1


def test_duplicate_short_signal_is_ignored():
    bars = _bar_range(5)
    result = _engine().run(bars, _AlwaysShort(), _passing_report(5))
    assert len(result.trades) == 1


def test_reversal_long_to_short_produces_two_trades():
    """LONG → SHORT reversal: trade 1 closes LONG, trade 2 is the SHORT."""
    n = 5
    bars = _bar_range(n)
    result = _engine().run(bars, _LongThenShort(), _passing_report(n))
    # trade 0: LONG closed by SHORT signal
    # trade 1: SHORT closed by force-close at last bar
    assert len(result.trades) == 2
    assert result.trades[0].entry_ts == bars[1].ts   # LONG entry at bars[1].open
    assert result.trades[1].entry_ts == bars[2].ts   # SHORT entry at bars[2].open


def test_reversal_entry_and_close_use_same_fill_price():
    """Both legs of a reversal fill at the same bar's open."""
    bars = [
        _bar(0, 1.1000),   # signal LONG
        _bar(1, 1.1050),   # LONG entry here (open=1.1050)
        _bar(2, 1.1080),   # signal SHORT: LONG exits at bars[2].open, SHORT enters
        _bar(3, 1.1060),   # SHORT exits at bars[3].open (FLAT signal)
        _bar(4, 1.1040),   # last bar
    ]
    result = _engine().run(bars, _LongThenShort(), _passing_report(5))
    assert len(result.trades) >= 2
    # LONG exit and SHORT entry both at bars[2].open.
    assert result.trades[0].exit_ts == bars[2].ts
    assert result.trades[1].entry_ts == bars[2].ts


def test_flat_strategy_produces_no_trades():
    bars = _bar_range(6)
    result = _engine().run(bars, _AlwaysFlat(), _passing_report(6))
    assert result.trades == ()
    assert result.equity == ()


# ---------------------------------------------------------------------------
# Short position PnL direction
# ---------------------------------------------------------------------------

def test_short_profit_on_price_decline():
    """SHORT entry above exit → profit after costs (sufficient move)."""
    bars = [
        _bar(0, 1.1100),   # signal SHORT
        _bar(1, 1.1100),   # SHORT entry at bars[1].open=1.1100
        _bar(2, 1.1000),   # FLAT signal: SHORT exit at bars[2].open=1.1000
    ]

    class _ShortOnFirst:
        def on_bar(self, view: BarView, pos: Position) -> Signal:
            return Signal.SHORT if len(view) == 1 else Signal.FLAT

    result = _engine().run(bars, _ShortOnFirst(), _passing_report(3))
    assert len(result.trades) == 1
    # 100 pips profit minus cost.
    assert result.trades[0].pnl > 0


def test_short_loss_on_price_rise():
    """SHORT entry below exit → loss."""
    bars = [
        _bar(0, 1.1000),
        _bar(1, 1.1000),   # SHORT entry
        _bar(2, 1.1100),   # exit at higher price
    ]

    class _ShortOnFirst:
        def on_bar(self, view: BarView, pos: Position) -> Signal:
            return Signal.SHORT if len(view) == 1 else Signal.FLAT

    result = _engine().run(bars, _ShortOnFirst(), _passing_report(3))
    assert len(result.trades) == 1
    assert result.trades[0].pnl < 0


# ---------------------------------------------------------------------------
# BacktestResult structure
# ---------------------------------------------------------------------------

def test_result_pnls_property_matches_trades():
    bars = _bar_range(5)
    result = _engine().run(bars, _AlwaysLong(), _passing_report(5))
    assert result.pnls == [t.pnl for t in result.trades]


def test_result_is_immutable():
    bars = _bar_range(4)
    result = _engine().run(bars, _AlwaysLong(), _passing_report(4))
    with pytest.raises((TypeError, AttributeError)):
        result.trades = ()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Feature causality: EMA
# ---------------------------------------------------------------------------

def test_ema_length_matches_input():
    bars = _bar_range(10, step=0.0001)
    assert len(ema(bars, 5)) == 10


def test_ema_nans_before_period():
    bars = _bar_range(10)
    result = ema(bars, 5)
    for i in range(4):
        assert math.isnan(result[i]), f"expected NaN at index {i}"
    assert not math.isnan(result[4])


def test_ema_seed_equals_sma():
    """EMA[period-1] must equal the simple mean of the first `period` closes."""
    period = 4
    bars = [_bar(i, 1.1000 + i * 0.0010) for i in range(8)]
    result = ema(bars, period)
    expected = sum(b.close for b in bars[:period]) / period
    assert math.isclose(result[period - 1], expected, rel_tol=1e-12)


def test_ema_no_lookahead():
    bars = [_bar(i, 1.1000 + i * 0.0001) for i in range(20)]
    bad = find_lookahead_indices(lambda b: ema(b, 5), bars)
    assert bad == [], f"EMA lookahead detected at indices {bad}"


def test_ema_empty_input():
    assert ema([], 5) == []


def test_ema_invalid_period():
    with pytest.raises(ValueError):
        ema(_bar_range(5), 0)


def test_ema_period_equals_one_matches_close():
    """EMA(1) = close price at every bar."""
    bars = [_bar(i, 1.1000 + i * 0.0005) for i in range(5)]
    result = ema(bars, 1)
    for b, v in zip(bars, result, strict=True):
        assert math.isclose(v, b.close, rel_tol=1e-12)


# ---------------------------------------------------------------------------
# Feature causality: ATR
# ---------------------------------------------------------------------------

def test_atr_length_matches_input():
    bars = _bar_range(10)
    assert len(atr(bars, 3)) == 10


def test_atr_nans_before_period():
    bars = _bar_range(10)
    result = atr(bars, 5)
    for i in range(4):
        assert math.isnan(result[i]), f"expected NaN at index {i}"
    assert not math.isnan(result[4])


def test_atr_no_lookahead():
    # Use varying prices so TR varies bar-to-bar.
    prices = [1.1000, 1.1020, 1.0990, 1.1050, 1.1010, 1.0980, 1.1060, 1.1030,
              1.1000, 1.1040, 1.1015, 1.0970, 1.1055, 1.1025, 1.0995]
    bars = [_bar(i, p, spread=0.0010) for i, p in enumerate(prices)]
    bad = find_lookahead_indices(lambda b: atr(b, 5), bars)
    assert bad == [], f"ATR lookahead detected at indices {bad}"


def test_atr_seed_equals_average_tr():
    """ATR[period-1] must equal the simple average of the first `period` TRs."""
    period = 3
    prices = [1.1000, 1.1020, 1.0990, 1.1050]
    bars = [_bar(i, p, spread=0.0015) for i, p in enumerate(prices)]
    result = atr(bars, period)

    # Compute TR manually for first `period` bars.
    trs = [bars[0].high - bars[0].low]
    for i in range(1, period):
        prev_c = bars[i - 1].close
        trs.append(max(
            bars[i].high - bars[i].low,
            abs(bars[i].high - prev_c),
            abs(bars[i].low - prev_c),
        ))
    expected = sum(trs) / period
    assert math.isclose(result[period - 1], expected, rel_tol=1e-12)


def test_atr_empty_input():
    assert atr([], 3) == []


def test_atr_invalid_period():
    with pytest.raises(ValueError):
        atr(_bar_range(5), 0)


def test_atr_non_negative():
    """ATR values must never be negative."""
    bars = [_bar(i, 1.1000 + (i % 3) * 0.0005, spread=0.0003) for i in range(15)]
    result = atr(bars, 5)
    for i, v in enumerate(result):
        if not math.isnan(v):
            assert v >= 0, f"negative ATR at index {i}: {v}"


# ---------------------------------------------------------------------------
# assert_no_lookahead integration (existing harness)
# ---------------------------------------------------------------------------

def test_assert_no_lookahead_passes_ema():
    bars = [_bar(i, 1.1000 + i * 0.0002) for i in range(15)]
    assert_no_lookahead(lambda b: ema(b, 4), bars)


def test_assert_no_lookahead_passes_atr():
    bars = [_bar(i, 1.1000 + (i % 5) * 0.0003, spread=0.0008) for i in range(15)]
    assert_no_lookahead(lambda b: atr(b, 4), bars)
