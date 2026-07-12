"""Tests for WeeklyBOSRetest strategy."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from novax.data_sources import Bar
from novax.engine import BarView, Position, Signal
from novax.indicators.bos import BOSResult, BOSState
from novax.indicators.tsi import TSIResult
from novax.strategies.weekly_bos_retest import WeeklyBOSRetest

WEEK1_MON = datetime(2024, 1, 8, tzinfo=UTC)
WEEK2_MON = datetime(2024, 1, 15, tzinfo=UTC)
H4 = timedelta(hours=4)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_bar(ts: datetime, o: float, h: float, lo: float, c: float) -> Bar:
    return Bar(ts=ts, open=o, high=h, low=lo, close=c)


def flat_pos() -> Position:
    return Position(direction="FLAT")


def long_pos(entry: float = 2609.0) -> Position:
    return Position(direction="LONG", entry_price=entry)


def short_pos(entry: float = 2620.0) -> Position:
    return Position(direction="SHORT", entry_price=entry)


def make_view(bar: Bar) -> BarView:
    return BarView(bars=(bar,))


def _idle_bos() -> BOSResult:
    return BOSResult(
        state=BOSState.IDLE,
        bos_level=math.nan,
        ob_high=math.nan,
        ob_low=math.nan,
        choch_bearish=False,
        choch_bullish=False,
    )


def _bos_up(
    ob_high: float = 2620.0,
    ob_low: float = 2610.0,
    choch_bearish: bool = False,
    choch_bullish: bool = False,
) -> BOSResult:
    return BOSResult(
        state=BOSState.BOS_UP,
        bos_level=2600.0,
        ob_high=ob_high,
        ob_low=ob_low,
        choch_bearish=choch_bearish,
        choch_bullish=choch_bullish,
    )


def _bos_down(
    ob_high: float = 2630.0,
    ob_low: float = 2620.0,
    choch_bearish: bool = False,
    choch_bullish: bool = False,
) -> BOSResult:
    return BOSResult(
        state=BOSState.BOS_DOWN,
        bos_level=2640.0,
        ob_high=ob_high,
        ob_low=ob_low,
        choch_bearish=choch_bearish,
        choch_bullish=choch_bullish,
    )


# Mock indicator classes — allow injecting controlled values into the strategy.
class _ConstEMA:
    def __init__(self, val: float | None) -> None:
        self._val = val

    def update(self, price: float) -> float | None:
        return self._val


class _ConstTSI:
    def __init__(self, tsi: float, sig: float) -> None:
        self._r = TSIResult(tsi=tsi, signal=sig)

    def update(self, price: float) -> TSIResult:
        return self._r


class _ConstBOS:
    def __init__(self, result: BOSResult | None) -> None:
        self._result = result

    def update(self, bar: Bar, levels: object) -> BOSResult | None:
        return self._result


def _patch(
    strat: WeeklyBOSRetest,
    *,
    fast: float = 1.2,
    slow: float = 1.0,
    tsi: float = 50.0,
    tsi_sig: float = 10.0,
    bos: BOSResult | None,
) -> None:
    """Replace strategy internals with controllable mocks."""
    strat._ema_fast_ind = _ConstEMA(fast)  # type: ignore[assignment]
    strat._ema_slow_ind = _ConstEMA(slow)  # type: ignore[assignment]
    strat._tsi = _ConstTSI(tsi, tsi_sig)  # type: ignore[assignment]
    strat._bos = _ConstBOS(bos)  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_validation_ema_fast_gte_slow() -> None:
    with pytest.raises(ValueError, match="ema_fast"):
        WeeklyBOSRetest(ema_fast=50, ema_slow=20)


def test_validation_ob_buffer_zero() -> None:
    with pytest.raises(ValueError, match="ob_buffer_pips"):
        WeeklyBOSRetest(ob_buffer_pips=0)


def test_validation_max_risk_negative() -> None:
    with pytest.raises(ValueError, match="max_risk_pips"):
        WeeklyBOSRetest(max_risk_pips=-1.0)


def test_validation_risk_reward_zero() -> None:
    with pytest.raises(ValueError, match="risk_reward"):
        WeeklyBOSRetest(risk_reward=0.0)


# ---------------------------------------------------------------------------
# Warmup / None guard
# ---------------------------------------------------------------------------


def test_returns_flat_during_warmup() -> None:
    strat = WeeklyBOSRetest()
    bar = make_bar(WEEK1_MON, 2600.0, 2601.0, 2599.0, 2600.5)
    sig = strat.on_bar(make_view(bar), flat_pos())
    assert sig == Signal.FLAT


def test_returns_flat_when_ema_none() -> None:
    strat = WeeklyBOSRetest()
    _patch(strat, fast=None, slow=None, bos=_idle_bos())  # type: ignore[arg-type]
    bar = make_bar(WEEK1_MON, 2600.0, 2601.0, 2599.0, 2600.5)
    sig = strat.on_bar(make_view(bar), flat_pos())
    assert sig == Signal.FLAT


def test_returns_flat_when_bos_none() -> None:
    strat = WeeklyBOSRetest()
    _patch(strat, bos=None)
    bar = make_bar(WEEK1_MON, 2600.0, 2601.0, 2599.0, 2600.5)
    sig = strat.on_bar(make_view(bar), flat_pos())
    assert sig == Signal.FLAT


# ---------------------------------------------------------------------------
# BOS_UP entry — full conditions met → LONG
# ---------------------------------------------------------------------------


def test_bos_up_full_conditions_returns_long() -> None:
    strat = WeeklyBOSRetest()
    # OB zone: ob_high=2608, ob_low=2605.5
    _patch(strat, bos=_bos_up(ob_high=2608.0, ob_low=2605.5))
    # Bar dips into OB (low≤ob_high) and closes inside/above (close≥ob_low)
    bar = make_bar(WEEK1_MON, 2610.0, 2611.0, 2606.0, 2609.0)
    sig = strat.on_bar(make_view(bar), flat_pos())
    assert sig == Signal.LONG


def test_bos_up_sets_sl_and_tp() -> None:
    strat = WeeklyBOSRetest(ob_buffer_pips=5.0, risk_reward=2.0, pip_size=0.1)
    _patch(strat, bos=_bos_up(ob_high=2608.0, ob_low=2605.5))
    bar = make_bar(WEEK1_MON, 2610.0, 2611.0, 2606.0, 2609.0)
    strat.on_bar(make_view(bar), flat_pos())
    # sl = ob_low - buffer = 2605.5 - 0.5 = 2605.0; risk = 2609 - 2605 = 4; tp = 2609 + 8 = 2617
    assert strat._sl == pytest.approx(2605.0)
    assert strat._tp == pytest.approx(2617.0)


# ---------------------------------------------------------------------------
# BOS_UP entry — individual conditions blocking → FLAT
# ---------------------------------------------------------------------------


def test_bos_up_no_ob_returns_flat() -> None:
    strat = WeeklyBOSRetest()
    _patch(
        strat,
        bos=BOSResult(
            state=BOSState.BOS_UP,
            bos_level=2600.0,
            ob_high=math.nan,
            ob_low=math.nan,
            choch_bearish=False,
            choch_bullish=False,
        ),
    )
    bar = make_bar(WEEK1_MON, 2610.0, 2611.0, 2606.0, 2609.0)
    assert strat.on_bar(make_view(bar), flat_pos()) == Signal.FLAT


def test_bos_up_choch_bearish_disqualifies() -> None:
    strat = WeeklyBOSRetest()
    _patch(strat, bos=_bos_up(choch_bearish=True))
    bar = make_bar(WEEK1_MON, 2610.0, 2611.0, 2606.0, 2609.0)
    assert strat.on_bar(make_view(bar), flat_pos()) == Signal.FLAT


def test_bos_up_ema_bearish_blocks_entry() -> None:
    strat = WeeklyBOSRetest()
    _patch(strat, fast=0.9, slow=1.0, bos=_bos_up(ob_high=2608.0, ob_low=2605.5))
    bar = make_bar(WEEK1_MON, 2610.0, 2611.0, 2606.0, 2609.0)
    assert strat.on_bar(make_view(bar), flat_pos()) == Signal.FLAT


def test_bos_up_tsi_bearish_blocks_entry() -> None:
    strat = WeeklyBOSRetest()
    _patch(strat, tsi=-10.0, tsi_sig=-5.0, bos=_bos_up(ob_high=2608.0, ob_low=2605.5))
    bar = make_bar(WEEK1_MON, 2610.0, 2611.0, 2606.0, 2609.0)
    assert strat.on_bar(make_view(bar), flat_pos()) == Signal.FLAT


def test_bos_up_close_below_ob_low_blocks_entry() -> None:
    """Close blows through OB (close < ob_low) — retest condition fails."""
    strat = WeeklyBOSRetest()
    _patch(strat, bos=_bos_up(ob_high=2608.0, ob_low=2605.5))
    # close=2604.0 < ob_low=2605.5 → retest fails
    bar = make_bar(WEEK1_MON, 2607.0, 2608.5, 2603.5, 2604.0)
    assert strat.on_bar(make_view(bar), flat_pos()) == Signal.FLAT


def test_bos_up_low_above_ob_high_blocks_entry() -> None:
    """Bar never dips into OB (low > ob_high) — retest condition fails."""
    strat = WeeklyBOSRetest()
    _patch(strat, bos=_bos_up(ob_high=2608.0, ob_low=2605.5))
    # bar.low=2609.5 > ob_high=2608.0 → OB not touched
    bar = make_bar(WEEK1_MON, 2610.0, 2611.0, 2609.5, 2609.8)
    assert strat.on_bar(make_view(bar), flat_pos()) == Signal.FLAT


def test_bos_up_risk_too_wide_blocks_entry() -> None:
    strat = WeeklyBOSRetest(max_risk_pips=10.0, ob_buffer_pips=5.0, pip_size=0.1)
    # ob_low=2500.0 → sl=2499.5, entry=2609, risk=109.5 >> max_risk=1.0
    _patch(strat, bos=_bos_up(ob_high=2608.0, ob_low=2500.0))
    bar = make_bar(WEEK1_MON, 2610.0, 2611.0, 2501.0, 2609.0)
    assert strat.on_bar(make_view(bar), flat_pos()) == Signal.FLAT


# ---------------------------------------------------------------------------
# BOS_DOWN entry
# ---------------------------------------------------------------------------


def test_bos_down_full_conditions_returns_short() -> None:
    strat = WeeklyBOSRetest()
    _patch(
        strat,
        fast=0.9,
        slow=1.0,
        tsi=-30.0,
        tsi_sig=-10.0,
        bos=_bos_down(ob_high=2630.0, ob_low=2625.0),
    )
    # bar rallies into OB (high≥ob_low) but closes inside/below (close≤ob_high)
    bar = make_bar(WEEK1_MON, 2622.0, 2628.0, 2621.0, 2626.0)
    assert strat.on_bar(make_view(bar), flat_pos()) == Signal.SHORT


def test_bos_down_sets_sl_and_tp() -> None:
    strat = WeeklyBOSRetest(ob_buffer_pips=5.0, risk_reward=2.0, pip_size=0.1)
    _patch(
        strat,
        fast=0.9,
        slow=1.0,
        tsi=-30.0,
        tsi_sig=-10.0,
        bos=_bos_down(ob_high=2630.0, ob_low=2625.0),
    )
    bar = make_bar(WEEK1_MON, 2622.0, 2628.0, 2621.0, 2626.0)
    strat.on_bar(make_view(bar), flat_pos())
    # sl = ob_high + buffer = 2630 + 0.5 = 2630.5; risk = 2630.5 - 2626 = 4.5; tp = 2626 - 9 = 2617
    assert strat._sl == pytest.approx(2630.5)
    assert strat._tp == pytest.approx(2617.0)


def test_bos_down_choch_bullish_disqualifies() -> None:
    strat = WeeklyBOSRetest()
    _patch(strat, fast=0.9, slow=1.0, tsi=-30.0, tsi_sig=-10.0, bos=_bos_down(choch_bullish=True))
    bar = make_bar(WEEK1_MON, 2622.0, 2628.0, 2621.0, 2626.0)
    assert strat.on_bar(make_view(bar), flat_pos()) == Signal.FLAT


# ---------------------------------------------------------------------------
# SL/TP tracking — LONG position
# ---------------------------------------------------------------------------


def test_long_sl_hit_returns_flat() -> None:
    strat = WeeklyBOSRetest()
    _patch(strat, bos=_idle_bos())
    strat._sl = 2600.0
    strat._tp = 2640.0
    # bar.low=2599.5 < sl=2600.0 → SL hit
    bar = make_bar(WEEK1_MON, 2610.0, 2615.0, 2599.5, 2601.0)
    sig = strat.on_bar(make_view(bar), long_pos())
    assert sig == Signal.FLAT
    assert strat._sl is None
    assert strat._tp is None


def test_long_tp_hit_returns_flat() -> None:
    strat = WeeklyBOSRetest()
    _patch(strat, bos=_idle_bos())
    strat._sl = 2580.0
    strat._tp = 2640.0
    # bar.high=2641.0 ≥ tp=2640.0 → TP hit
    bar = make_bar(WEEK1_MON, 2630.0, 2641.0, 2629.0, 2638.0)
    sig = strat.on_bar(make_view(bar), long_pos())
    assert sig == Signal.FLAT
    assert strat._sl is None
    assert strat._tp is None


def test_long_holds_when_sl_not_hit() -> None:
    strat = WeeklyBOSRetest()
    _patch(strat, bos=_idle_bos())
    strat._sl = 2595.0
    strat._tp = 2640.0
    # bar.low=2605.0 > sl=2595.0 and bar.high=2620.0 < tp=2640.0 → hold
    bar = make_bar(WEEK1_MON, 2610.0, 2620.0, 2605.0, 2615.0)
    sig = strat.on_bar(make_view(bar), long_pos())
    assert sig == Signal.LONG
    assert strat._sl == pytest.approx(2595.0)
    assert strat._tp == pytest.approx(2640.0)


# ---------------------------------------------------------------------------
# SL/TP tracking — SHORT position
# ---------------------------------------------------------------------------


def test_short_sl_hit_returns_flat() -> None:
    strat = WeeklyBOSRetest()
    _patch(strat, bos=_idle_bos())
    strat._sl = 2635.0
    strat._tp = 2595.0
    # bar.high=2636.0 ≥ sl=2635.0 → SL hit
    bar = make_bar(WEEK1_MON, 2625.0, 2636.0, 2624.0, 2630.0)
    sig = strat.on_bar(make_view(bar), short_pos())
    assert sig == Signal.FLAT
    assert strat._sl is None
    assert strat._tp is None


def test_short_tp_hit_returns_flat() -> None:
    strat = WeeklyBOSRetest()
    _patch(strat, bos=_idle_bos())
    strat._sl = 2645.0
    strat._tp = 2595.0
    # bar.low=2594.0 ≤ tp=2595.0 → TP hit
    bar = make_bar(WEEK1_MON, 2610.0, 2615.0, 2594.0, 2596.0)
    sig = strat.on_bar(make_view(bar), short_pos())
    assert sig == Signal.FLAT
    assert strat._sl is None
    assert strat._tp is None


def test_short_holds_when_sl_not_hit() -> None:
    strat = WeeklyBOSRetest()
    _patch(strat, bos=_idle_bos())
    strat._sl = 2645.0
    strat._tp = 2590.0
    # bar.high=2632.0 < sl=2645.0 and bar.low=2618.0 > tp=2590.0 → hold
    bar = make_bar(WEEK1_MON, 2625.0, 2632.0, 2618.0, 2622.0)
    sig = strat.on_bar(make_view(bar), short_pos())
    assert sig == Signal.SHORT


# ---------------------------------------------------------------------------
# Integration — engine run produces at least one trade
# ---------------------------------------------------------------------------


def test_integration_engine_produces_trade() -> None:
    """Full engine run with real BOSDetector/WeeklyLevelTracker + mocked EMA/TSI.

    Bar design:
      Week 1 (10 bars): uptrend from 2600→2609, establishes prev_high=2609.5.
      Week 2: W2-0/1 bullish below prev_high, W2-2 bearish OB, W2-3 BOS_UP,
              W2-4 OB retest → LONG, W2-5 TP hit → FLAT, W2-6 fill bar.
    """
    from novax.dataquality import CheckResult, DataQualityReport
    from novax.engine import BacktestEngine

    strat = WeeklyBOSRetest(ema_fast=3, ema_slow=5, max_risk_pips=200.0)
    # Patch EMA and TSI so warmup isn't a constraint; keep real _weekly and _bos.
    strat._ema_fast_ind = _ConstEMA(1.2)  # type: ignore[assignment]
    strat._ema_slow_ind = _ConstEMA(1.0)  # type: ignore[assignment]
    strat._tsi = _ConstTSI(50.0, 10.0)  # type: ignore[assignment]

    bars: list[Bar] = []

    # ── Week 1 (2024-01-08): 10 H4 bars, uptrend 2600→2609 ─────────────────
    # prev_high = max(highs) = 2609 + 0.5 = 2609.5
    for i in range(10):
        ts = WEEK1_MON + i * H4
        c = 2600.0 + i
        bars.append(make_bar(ts, c - 0.2, c + 0.5, c - 0.5, c))

    # ── Week 2 (2024-01-15): BOS + OB retest ────────────────────────────────
    # W2-0: bullish (below prev_high=2609.5)
    bars.append(make_bar(WEEK2_MON, 2604.8, 2605.5, 2604.5, 2605.0))
    # W2-1: bullish
    bars.append(make_bar(WEEK2_MON + H4, 2605.8, 2606.5, 2605.5, 2606.0))
    # W2-2: bearish OB (open=2607.5 > close=2606.5)
    bars.append(make_bar(WEEK2_MON + 2 * H4, 2607.5, 2608.0, 2605.5, 2606.5))
    # W2-3: BOS_UP (close=2610.5 > prev_high=2609.5); OB=W2-2: ob_high=2608, ob_low=2605.5
    bars.append(make_bar(WEEK2_MON + 3 * H4, 2607.0, 2612.0, 2606.5, 2610.5))
    # W2-4: OB retest (low=2606 ≤ ob_high=2608, close=2609 ≥ ob_low=2605.5) → LONG
    #   entry=2609, sl=2605.5-0.5=2605.0, risk=4.0, tp=2609+8.0=2617.0
    bars.append(make_bar(WEEK2_MON + 4 * H4, 2610.0, 2611.0, 2606.0, 2609.0))
    # W2-5: TP hit (high=2618 ≥ tp=2617) → FLAT; fill at W2-6.open
    bars.append(make_bar(WEEK2_MON + 5 * H4, 2610.0, 2618.0, 2609.0, 2617.0))
    # W2-6: fill bar
    bars.append(make_bar(WEEK2_MON + 6 * H4, 2617.0, 2618.0, 2616.0, 2617.0))

    report = DataQualityReport(
        symbol="XAUUSD",
        timeframe="4h",
        n_bars=len(bars),
        checks=(CheckResult("test", True, "ok"),),
    )
    engine = BacktestEngine(symbol="XAUUSD", timeframe="4h")
    result = engine.run(bars, strat, report)
    assert len(result.trades) >= 1
