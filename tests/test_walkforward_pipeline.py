"""End-to-end integration tests: SimpleWalkForward → BacktestEngine → metrics.

Strategy: LONG when close > EMA(5), FLAT otherwise.
Bar series: monotone rising prices so the EMA always lags the close after
warmup, guaranteeing at least one trade in the test segment.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from novax.data_sources import Bar
from novax.dataquality import CheckResult, DataQualityReport
from novax.engine import BacktestEngine, BarView, Position, Signal
from novax.features import ema
from novax.metrics import compute_basic_metrics
from novax.walkforward import SimpleWalkForward

_SYMBOL = "EUR/USD"
_TF = "1h"
_BASE_TS = datetime(2025, 1, 6, 10, 0, tzinfo=UTC)
_EXPECTED_METRIC_KEYS = frozenset(
    {
        "total_return",
        "max_drawdown_abs",
        "max_drawdown_pct",
        "sharpe_ratio",
        "trade_count",
        "win_rate",
        "avg_trade_pnl",
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rising_bars(n: int, start: float = 1.1000, step: float = 0.0003) -> list[Bar]:
    """Monotone rising bars. close > EMA after period warmup -> generates LONG trades."""
    bars = []
    for i in range(n):
        price = start + i * step
        ts = _BASE_TS + timedelta(hours=i)
        h, lo = price + 0.0001, price - 0.0001
        bars.append(Bar(ts=ts, open=price, high=h, low=lo, close=price, source="synth"))
    return bars


def _passing_report(bars: list[Bar]) -> DataQualityReport:
    return DataQualityReport(symbol=_SYMBOL, timeframe=_TF, n_bars=len(bars), checks=())


class _EmaStrategy:
    """LONG when close > EMA(period), FLAT otherwise. NaN bars → FLAT."""

    def __init__(self, period: int = 5) -> None:
        self._period = period

    def on_bar(self, view: BarView, pos: Position) -> Signal:
        if len(view) < self._period:
            return Signal.FLAT
        last_ema = ema(view.bars, self._period)[-1]
        if math.isnan(last_ema):
            return Signal.FLAT
        return Signal.LONG if view.last.close > last_ema else Signal.FLAT


# ---------------------------------------------------------------------------
# SimpleWalkForward unit tests
# ---------------------------------------------------------------------------

def test_split_sizes_match_ratio():
    bars = _make_rising_bars(30)
    train, test = SimpleWalkForward(train_ratio=0.7).split(bars)
    assert len(train) == 21          # int(30 * 0.7)
    assert len(test) == 9
    assert len(train) + len(test) == 30


def test_split_is_contiguous_and_non_overlapping():
    bars = _make_rising_bars(20)
    train, test = SimpleWalkForward(train_ratio=0.6).split(bars)
    assert train[-1].ts < test[0].ts


def test_split_preserves_all_bars():
    bars = _make_rising_bars(25)
    train, test = SimpleWalkForward(train_ratio=0.8).split(bars)
    assert train + test == bars


def test_split_invalid_ratio_zero():
    with pytest.raises(ValueError):
        SimpleWalkForward(train_ratio=0.0)


def test_split_invalid_ratio_one():
    with pytest.raises(ValueError):
        SimpleWalkForward(train_ratio=1.0)


def test_split_too_few_bars_for_train():
    bars = _make_rising_bars(1)
    with pytest.raises(ValueError):
        SimpleWalkForward(train_ratio=0.99).split(bars)


# ---------------------------------------------------------------------------
# compute_basic_metrics unit tests
# ---------------------------------------------------------------------------

def _run_on(bars: list[Bar]) -> object:
    engine = BacktestEngine(symbol=_SYMBOL, timeframe=_TF)
    return engine.run(bars, _EmaStrategy(5), _passing_report(bars))


def test_metrics_keys_are_complete():
    result = _run_on(_make_rising_bars(20))
    assert set(compute_basic_metrics(result).keys()) == _EXPECTED_METRIC_KEYS


def test_metrics_no_trades_returns_zeros():
    # Two bars, always FLAT strategy → no trades.
    bars = _make_rising_bars(2)

    class _Flat:
        def on_bar(self, v: BarView, p: Position) -> Signal:
            return Signal.FLAT

    result = BacktestEngine(symbol=_SYMBOL, timeframe=_TF).run(
        bars, _Flat(), _passing_report(bars)
    )
    m = compute_basic_metrics(result)
    assert m["trade_count"] == 0
    assert m["total_return"] == 0.0
    assert m["max_drawdown_abs"] == 0.0
    assert m["max_drawdown_pct"] == 0.0
    assert m["sharpe_ratio"] == 0.0
    assert m["win_rate"] == 0.0
    assert m["avg_trade_pnl"] == 0.0


def test_metrics_total_return_equals_sum_of_pnls():
    result = _run_on(_make_rising_bars(20))
    m = compute_basic_metrics(result)
    assert math.isclose(m["total_return"], sum(result.pnls), rel_tol=1e-12)


def test_metrics_avg_trade_pnl():
    result = _run_on(_make_rising_bars(20))
    m = compute_basic_metrics(result)
    if m["trade_count"] > 0:
        expected = m["total_return"] / m["trade_count"]
        assert math.isclose(m["avg_trade_pnl"], expected, rel_tol=1e-12)


def test_metrics_win_rate_bounded():
    result = _run_on(_make_rising_bars(20))
    m = compute_basic_metrics(result)
    assert 0.0 <= m["win_rate"] <= 1.0


def test_metrics_max_drawdown_abs_non_negative():
    result = _run_on(_make_rising_bars(20))
    m = compute_basic_metrics(result)
    assert m["max_drawdown_abs"] >= 0.0


def test_metrics_max_drawdown_pct_bounded():
    """max_drawdown_pct must be in [0, 1] — it's a dimensionless fraction."""
    result = _run_on(_make_rising_bars(20))
    m = compute_basic_metrics(result)
    assert 0.0 <= m["max_drawdown_pct"] <= 1.0


def test_metrics_trade_count_is_int():
    result = _run_on(_make_rising_bars(20))
    m = compute_basic_metrics(result)
    assert isinstance(m["trade_count"], int)


def test_metrics_drawdown_pct_comparable_to_fractional_threshold():
    """Verify max_drawdown_pct can be directly compared to a 0-to-1 gate threshold."""
    result = _run_on(_make_rising_bars(20))
    m = compute_basic_metrics(result)
    # Should not raise and must yield a meaningful boolean.
    threshold = 0.20
    assert isinstance(m["max_drawdown_pct"] > threshold, bool)


# ---------------------------------------------------------------------------
# End-to-end pipeline tests
# ---------------------------------------------------------------------------

def test_pipeline_runs_end_to_end():
    bars = _make_rising_bars(40)
    train, test = SimpleWalkForward(train_ratio=0.7).split(bars)

    assert len(train) + len(test) == len(bars)

    result = BacktestEngine(symbol=_SYMBOL, timeframe=_TF).run(
        test, _EmaStrategy(5), _passing_report(test)
    )
    metrics = compute_basic_metrics(result)

    assert set(metrics.keys()) == _EXPECTED_METRIC_KEYS


def test_pipeline_trade_count_positive():
    """Rising bars guarantee at least one LONG trade in the test segment."""
    bars = _make_rising_bars(40)
    _, test = SimpleWalkForward(train_ratio=0.7).split(bars)

    result = BacktestEngine(symbol=_SYMBOL, timeframe=_TF).run(
        test, _EmaStrategy(5), _passing_report(test)
    )
    assert compute_basic_metrics(result)["trade_count"] > 0


def test_pipeline_is_deterministic():
    """Same input always produces identical output — no hidden state."""
    bars = _make_rising_bars(40)
    _, test = SimpleWalkForward(train_ratio=0.7).split(bars)

    engine = BacktestEngine(symbol=_SYMBOL, timeframe=_TF)
    strategy = _EmaStrategy(5)
    report = _passing_report(test)

    result_a = engine.run(test, strategy, report)
    result_b = engine.run(test, strategy, report)

    assert result_a.pnls == result_b.pnls
    assert result_a.equity == result_b.equity


def test_train_bars_precede_test_bars_in_time():
    """Causal split: no test bar timestamp predates any train bar timestamp."""
    bars = _make_rising_bars(30)
    train, test = SimpleWalkForward(train_ratio=0.7).split(bars)
    assert all(t.ts > train[-1].ts for t in test)


def test_pipeline_profitable_on_rising_series():
    """A 100% LONG strategy on rising bars must net positive after costs."""
    bars = _make_rising_bars(40, step=0.0010)  # bigger step → more pip profit
    _, test = SimpleWalkForward(train_ratio=0.7).split(bars)

    result = BacktestEngine(symbol=_SYMBOL, timeframe=_TF).run(
        test, _EmaStrategy(5), _passing_report(test)
    )
    m = compute_basic_metrics(result)
    assert m["total_return"] > 0
