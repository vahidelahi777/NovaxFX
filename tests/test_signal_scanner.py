"""Tests for SignalScanner and ScanResult."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from novax.data_sources import Bar
from novax.engine import Signal
from novax.indicators.bos import BOSState
from novax.live import ScanResult, SignalScanner

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)  # Monday W1 2024


def _bar(
    ts: datetime,
    open_: float,
    high: float,
    low: float,
    close: float,
) -> Bar:
    return Bar(ts=ts, open=open_, high=high, low=low, close=close, source="test")


def _h4_bars(closes: list[float], *, week_offset: int = 0) -> list[Bar]:
    """Build H4 bars for a single week starting at _BASE + week_offset weeks.
    Each close becomes a flat OHLC bar (open=close-1, high=close+1, low=close-1).
    """
    week_start = _BASE + timedelta(weeks=week_offset)
    bars = []
    for i, c in enumerate(closes):
        ts = week_start + timedelta(hours=4 * i)
        bars.append(
            _bar(ts, open_=c - 1.0, high=c + 1.0, low=c - 1.0, close=c)
        )
    return bars


# ---------------------------------------------------------------------------
# Unit tests — ScanResult structure
# ---------------------------------------------------------------------------


class TestScanResultFields:
    def test_is_frozen(self) -> None:
        result = ScanResult(
            ts=_BASE,
            symbol="XAUUSD",
            timeframe="4h",
            signal=Signal.FLAT,
            bos_state="idle",
            has_ob=False,
            ob_high=None,
            ob_low=None,
            prev_week_high=None,
            prev_week_low=None,
            sl=None,
            tp=None,
            n_bars_used=0,
        )
        with pytest.raises((AttributeError, TypeError)):
            result.signal = Signal.LONG  # type: ignore[misc]

    def test_default_flat_result(self) -> None:
        result = ScanResult(
            ts=_BASE,
            symbol="TEST",
            timeframe="4h",
            signal=Signal.FLAT,
            bos_state="idle",
            has_ob=False,
            ob_high=None,
            ob_low=None,
            prev_week_high=None,
            prev_week_low=None,
            sl=None,
            tp=None,
            n_bars_used=0,
        )
        assert result.signal == Signal.FLAT
        assert result.sl is None
        assert result.tp is None


# ---------------------------------------------------------------------------
# Unit tests — SignalScanner
# ---------------------------------------------------------------------------


class TestSignalScannerEmpty:
    def test_empty_bars_returns_flat(self) -> None:
        scanner = SignalScanner("XAUUSD")
        result = scanner.scan([])
        assert result.signal == Signal.FLAT
        assert result.n_bars_used == 0

    def test_single_bar_returns_flat(self) -> None:
        scanner = SignalScanner("XAUUSD")
        bars = _h4_bars([2600.0], week_offset=0)
        result = scanner.scan(bars)
        assert result.signal == Signal.FLAT
        assert result.n_bars_used == 1

    def test_metadata_propagated(self) -> None:
        scanner = SignalScanner("EURUSD", timeframe="1h")
        bars = _h4_bars([1.1, 1.2], week_offset=0)
        result = scanner.scan(bars)
        assert result.symbol == "EURUSD"
        assert result.timeframe == "1h"
        assert result.n_bars_used == 2

    def test_ts_is_last_bar_ts(self) -> None:
        scanner = SignalScanner("XAUUSD")
        bars = _h4_bars([2600.0, 2601.0, 2602.0], week_offset=0)
        result = scanner.scan(bars)
        assert result.ts == bars[-1].ts


class TestSignalScannerNoSignal:
    def test_warmup_only_returns_flat(self) -> None:
        """Bars in a single week → WeeklyLevelTracker returns None → BOS idle."""
        scanner = SignalScanner("XAUUSD")
        closes = [2600.0 + i for i in range(10)]
        bars = _h4_bars(closes, week_offset=0)
        result = scanner.scan(bars)
        assert result.signal == Signal.FLAT
        assert result.bos_state == BOSState.IDLE.value

    def test_strategy_params_accepted(self) -> None:
        scanner = SignalScanner(
            "XAUUSD",
            strategy_params={"ema_fast": 5, "ema_slow": 20},
        )
        bars = _h4_bars([2600.0 + i for i in range(5)], week_offset=0)
        result = scanner.scan(bars)
        assert result.signal == Signal.FLAT

    def test_scan_is_stateless(self) -> None:
        """Two calls with the same bars must return the same result."""
        scanner = SignalScanner("XAUUSD")
        bars = _h4_bars([2600.0 + i for i in range(10)], week_offset=0)
        r1 = scanner.scan(bars)
        r2 = scanner.scan(bars)
        assert r1 == r2

    def test_scan_uses_fresh_strategy_each_call(self) -> None:
        """Adding bars to the second call must not corrupt the first result."""
        scanner = SignalScanner("XAUUSD")
        bars_short = _h4_bars([2600.0 + i for i in range(5)], week_offset=0)
        bars_long = _h4_bars([2600.0 + i for i in range(10)], week_offset=0)
        r_short = scanner.scan(bars_short)
        r_long = scanner.scan(bars_long)
        assert r_short.n_bars_used == 5
        assert r_long.n_bars_used == 10
        assert r_short.ts == bars_short[-1].ts
        assert r_long.ts == bars_long[-1].ts

    def test_ob_high_none_when_no_ob(self) -> None:
        scanner = SignalScanner("XAUUSD")
        bars = _h4_bars([2600.0] * 5, week_offset=0)
        result = scanner.scan(bars)
        assert result.ob_high is None
        assert result.ob_low is None


# ---------------------------------------------------------------------------
# Integration test — LONG signal from synthetic bars
#
# Design (verified mathematically in the prior session):
#
#   Week 1  (20 bars, 4h each):
#     bars 0–9  : downtrend, closes 2660, 2655, …, 2615  (mom = -5)
#     bars 10–19: uptrend,   closes 2618, 2621, …, 2645  (mom = +3)
#     bar 0:  open=2660.5, high=2660.5, low=2659, close=2660
#       → week1_high = max(highs) = 2660.5  (only bar 0 matters for BOS level)
#
#   TSI(long=5, short=3, signal=3) with ema_fast=3, ema_slow=5:
#     After the downtrend-then-uptrend pattern:
#       TSI crosses 0 around bar13, continues rising.
#       At the end of week 1: TSI > signal (verified ≈ TSI=88.9, signal=81.0).
#
#   Week 2 (10 bars):
#     bars 0–6: gentle +2 momentum, closes 2647..2659
#     bar 7 (OB): bearish candle — open=2660.5, high=2661, low=2658, close=2659.5
#     bar 8 (BOS): open=2659.5, high=2663, low=2659, close=2661.5
#       → close=2661.5 > prev_high=2660.5 → BOS_UP fires
#       → OB found (bar 7: last bearish before BOS bar) → ob_high=2661, ob_low=2658
#     bar 9 (retest): open=2661, high=2662.5, low=2659, close=2661.5
#       → low=2659 ≤ ob_high=2661 ✓  (touched OB)
#       → close=2661.5 ≥ ob_low=2658 ✓  (held above OB bottom)
#       → ema_bull: EMA(3)≈2660.7 > EMA(5)≈2659.4 ✓
#       → tsi_bull: TSI≈100.0 > signal≈99.8 > 0 ✓
#       → sl = 2658 - 5*0.1 = 2657.5, risk = 4.0, tp = 2661.5 + 8.0 = 2669.5
#       ⇒ Signal.LONG
# ---------------------------------------------------------------------------


def _build_integration_bars() -> list[Bar]:
    """30-bar synthetic sequence that ends with Signal.LONG."""
    bars: list[Bar] = []

    # Week 1: Monday 2024-01-01 00:00 UTC (ISO week 1)
    w1_start = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)

    # Downtrend bars 0–9
    downtrend_closes = [2660.0 - 5.0 * i for i in range(10)]
    for i, c in enumerate(downtrend_closes):
        ts = w1_start + timedelta(hours=4 * i)
        # Bar 0 gets a special high so prev_high=2660.5 after week 1 completes
        high = 2660.5 if i == 0 else c + 1.0
        low = c - 1.0
        open_ = c + 0.5 if i == 0 else c + 1.0
        bars.append(_bar(ts, open_=open_, high=high, low=low, close=c))

    # Uptrend bars 10–19
    uptrend_closes = [2618.0 + 3.0 * i for i in range(10)]
    for i, c in enumerate(uptrend_closes):
        ts = w1_start + timedelta(hours=4 * (10 + i))
        bars.append(_bar(ts, open_=c - 1.0, high=c + 1.0, low=c - 1.0, close=c))

    # Week 2: Monday 2024-01-08 00:00 UTC
    w2_start = datetime(2024, 1, 8, 0, 0, tzinfo=UTC)

    # W2 bars 0–6: gentle +2 momentum
    w2_gentle_closes = [2647.0 + 2.0 * i for i in range(7)]
    for i, c in enumerate(w2_gentle_closes):
        ts = w2_start + timedelta(hours=4 * i)
        bars.append(_bar(ts, open_=c - 0.5, high=c + 1.0, low=c - 1.0, close=c))

    # W2 bar 7: bearish OB — open > close
    ts_ob = w2_start + timedelta(hours=4 * 7)
    bars.append(_bar(ts_ob, open_=2660.5, high=2661.0, low=2658.0, close=2659.5))

    # W2 bar 8: BOS_UP — close crosses prev_high=2660.5
    ts_bos = w2_start + timedelta(hours=4 * 8)
    bars.append(_bar(ts_bos, open_=2659.5, high=2663.0, low=2659.0, close=2661.5))

    # W2 bar 9: retest — dips into OB but holds → LONG entry
    ts_retest = w2_start + timedelta(hours=4 * 9)
    bars.append(_bar(ts_retest, open_=2661.0, high=2662.5, low=2659.0, close=2661.5))

    return bars


class TestSignalScannerIntegration:
    _PARAMS = {"ema_fast": 3, "ema_slow": 5, "tsi_long": 5, "tsi_short": 3, "tsi_signal": 3}

    def test_long_signal_fires(self) -> None:
        bars = _build_integration_bars()
        scanner = SignalScanner("XAUUSD", strategy_params=self._PARAMS)
        result = scanner.scan(bars)
        assert result.signal == Signal.LONG, (
            f"Expected LONG, got {result.signal!r}. "
            f"bos_state={result.bos_state}, has_ob={result.has_ob}, "
            f"sl={result.sl}, tp={result.tp}"
        )

    def test_bos_up_state(self) -> None:
        bars = _build_integration_bars()
        scanner = SignalScanner("XAUUSD", strategy_params=self._PARAMS)
        result = scanner.scan(bars)
        assert result.bos_state == BOSState.BOS_UP.value

    def test_ob_detected(self) -> None:
        bars = _build_integration_bars()
        scanner = SignalScanner("XAUUSD", strategy_params=self._PARAMS)
        result = scanner.scan(bars)
        assert result.has_ob is True
        assert result.ob_high == pytest.approx(2661.0)
        assert result.ob_low == pytest.approx(2658.0)

    def test_sl_tp_populated(self) -> None:
        bars = _build_integration_bars()
        scanner = SignalScanner("XAUUSD", strategy_params=self._PARAMS)
        result = scanner.scan(bars)
        # sl = ob_low - ob_buffer_pips * pip_size = 2658.0 - 5.0 * 0.1 = 2657.5
        # risk = 2661.5 - 2657.5 = 4.0
        # tp = 2661.5 + 4.0 * 2.0 = 2669.5
        assert result.sl == pytest.approx(2657.5)
        assert result.tp == pytest.approx(2669.5)

    def test_metadata(self) -> None:
        bars = _build_integration_bars()
        scanner = SignalScanner("XAUUSD", strategy_params=self._PARAMS)
        result = scanner.scan(bars)
        assert result.symbol == "XAUUSD"
        assert result.timeframe == "4h"
        assert result.n_bars_used == 30
        assert result.ts == bars[-1].ts

    def test_prev_week_levels_populated(self) -> None:
        bars = _build_integration_bars()
        scanner = SignalScanner("XAUUSD", strategy_params=self._PARAMS)
        result = scanner.scan(bars)
        # prev_high is frozen after week 1 completes — bar 0 had high=2660.5
        assert result.prev_week_high == pytest.approx(2660.5)
        assert result.prev_week_low is not None

    def test_scan_stateless_across_calls(self) -> None:
        bars = _build_integration_bars()
        scanner = SignalScanner("XAUUSD", strategy_params=self._PARAMS)
        r1 = scanner.scan(bars)
        r2 = scanner.scan(bars)
        assert r1 == r2

    def test_truncated_bars_no_signal(self) -> None:
        """Without week 2, no BOS can fire — scanner returns FLAT."""
        bars = _build_integration_bars()[:20]  # week 1 only
        scanner = SignalScanner("XAUUSD", strategy_params=self._PARAMS)
        result = scanner.scan(bars)
        assert result.signal == Signal.FLAT
