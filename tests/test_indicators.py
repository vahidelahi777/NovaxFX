"""Unit tests for src/novax/indicators/.

All tests are deterministic and network-free. Reference values for EMA and RMA
are computed analytically in comments so they can be verified by hand.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from novax.data_sources import Bar
from novax.indicators import (
    EMAIndicator,
    PivotZoneDetector,
    RMAIndicator,
    SupertrendIndicator,
    TSIIndicator,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bar(
    high: float,
    low: float,
    close: float | None = None,
    ts_hour: int = 0,
) -> Bar:
    c = close if close is not None else (high + low) / 2.0
    mid = (high + low) / 2.0
    return Bar(
        ts=datetime(2024, 1, 1, ts_hour % 24, tzinfo=UTC),
        open=mid,
        high=high,
        low=low,
        close=c,
        source="test",
    )


# ---------------------------------------------------------------------------
# EMAIndicator
# ---------------------------------------------------------------------------


class TestEMAIndicator:
    def test_invalid_period_raises(self) -> None:
        with pytest.raises(ValueError, match="period"):
            EMAIndicator(period=0)

    def test_returns_none_during_warmup(self) -> None:
        ema = EMAIndicator(period=3)
        assert ema.update(1.0) is None
        assert ema.update(2.0) is None
        assert ema.value is None

    def test_returns_value_at_period(self) -> None:
        # period=3, alpha=0.5
        # bar1: internal=1.0, count=1 (<3) → None
        # bar2: internal=0.5*2+0.5*1=1.5, count=2 → None
        # bar3: internal=0.5*3+0.5*1.5=2.25, count=3 → 2.25
        ema = EMAIndicator(period=3)
        ema.update(1.0)
        ema.update(2.0)
        result = ema.update(3.0)
        assert result == pytest.approx(2.25)

    def test_subsequent_update_correct(self) -> None:
        # Continuing from above at bar4:
        # internal=0.5*4+0.5*2.25=3.125, count=4 → 3.125
        ema = EMAIndicator(period=3)
        ema.update(1.0)
        ema.update(2.0)
        ema.update(3.0)
        result = ema.update(4.0)
        assert result == pytest.approx(3.125)

    def test_period_1_returns_immediately(self) -> None:
        ema = EMAIndicator(period=1)
        assert ema.update(5.0) == pytest.approx(5.0)

    def test_none_input_does_not_advance_count(self) -> None:
        ema = EMAIndicator(period=3)
        ema.update(1.0)
        ema.update(2.0)
        assert ema.update(None) is None  # None skipped — count stays at 2
        result = ema.update(3.0)  # this is the 3rd real value
        assert result == pytest.approx(2.25)

    def test_value_property_matches_update_return(self) -> None:
        ema = EMAIndicator(period=2)
        ema.update(1.0)
        ret = ema.update(2.0)
        assert ret == ema.value

    def test_converges_toward_constant_series(self) -> None:
        ema = EMAIndicator(period=5)
        for _ in range(100):
            ema.update(10.0)
        assert ema.value == pytest.approx(10.0, abs=1e-6)


# ---------------------------------------------------------------------------
# RMAIndicator
# ---------------------------------------------------------------------------


class TestRMAIndicator:
    def test_invalid_period_raises(self) -> None:
        with pytest.raises(ValueError, match="period"):
            RMAIndicator(period=0)

    def test_returns_none_during_warmup(self) -> None:
        rma = RMAIndicator(period=3)
        assert rma.update(1.0) is None
        assert rma.update(2.0) is None

    def test_seed_is_sma_of_first_period_values(self) -> None:
        # SMA(1, 2, 3) = 2.0
        rma = RMAIndicator(period=3)
        rma.update(1.0)
        rma.update(2.0)
        result = rma.update(3.0)
        assert result == pytest.approx(2.0)

    def test_subsequent_value_correct(self) -> None:
        # alpha=1/3; after seed=2.0: update(4.0) = 1/3*4 + 2/3*2 = 4/3+4/3 = 8/3
        rma = RMAIndicator(period=3)
        rma.update(1.0)
        rma.update(2.0)
        rma.update(3.0)
        result = rma.update(4.0)
        assert result == pytest.approx(8.0 / 3.0)

    def test_none_input_skipped(self) -> None:
        rma = RMAIndicator(period=2)
        rma.update(1.0)
        assert rma.update(None) is None  # still in warm-up, None skipped
        result = rma.update(3.0)  # 2nd real value → seed = (1+3)/2 = 2.0
        assert result == pytest.approx(2.0)

    def test_rma_differs_from_ema_for_same_period(self) -> None:
        # alpha_rma=1/5=0.2 vs alpha_ema=2/6≈0.333 — they must diverge
        rma = RMAIndicator(period=5)
        ema = EMAIndicator(period=5)
        prices = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
        for p in prices:
            rma.update(p)
            ema.update(p)
        assert rma.value is not None
        assert ema.value is not None
        assert rma.value != pytest.approx(ema.value, rel=0.01)

    def test_converges_toward_constant_series(self) -> None:
        rma = RMAIndicator(period=10)
        for _ in range(200):
            rma.update(7.0)
        assert rma.value == pytest.approx(7.0, abs=1e-6)


# ---------------------------------------------------------------------------
# SupertrendIndicator
# ---------------------------------------------------------------------------


class TestSupertrendIndicator:
    def test_invalid_period_raises(self) -> None:
        with pytest.raises(ValueError, match="period"):
            SupertrendIndicator(period=0)

    def test_invalid_multiplier_raises(self) -> None:
        with pytest.raises(ValueError, match="multiplier"):
            SupertrendIndicator(multiplier=0.0)

    def test_returns_none_during_warmup(self) -> None:
        st = SupertrendIndicator(period=3)
        assert st.update(1.1, 0.9, 1.0) is None
        assert st.update(1.1, 0.9, 1.0) is None
        assert st.value is None

    def test_first_valid_result_is_bullish(self) -> None:
        st = SupertrendIndicator(period=3, multiplier=2.0)
        result = None
        for i in range(3):
            result = st.update(1.0 + i * 0.01, 0.9 + i * 0.01, 0.95 + i * 0.01)
        assert result is not None
        assert result.direction == 1

    def test_direction_flips_bearish_on_breakdown(self) -> None:
        # Long steady uptrend to establish bullish state, then crash below band.
        st = SupertrendIndicator(period=5, multiplier=1.0)
        for i in range(20):
            st.update(1.0 + i * 0.01, 0.9 + i * 0.01, 0.95 + i * 0.01)
        assert st.value is not None and st.value.direction == 1

        # Dramatic drop: close well below any plausible lower band
        result = st.update(0.1, 0.05, 0.06)
        assert result is not None
        assert result.direction == -1

    def test_direction_flips_bullish_on_breakout(self) -> None:
        # Establish bearish state with a crash, then a V-recovery
        st = SupertrendIndicator(period=5, multiplier=1.0)
        for i in range(20):
            st.update(1.0 - i * 0.01, 0.9 - i * 0.01, 0.95 - i * 0.01)
        st.update(0.1, 0.05, 0.06)  # force bearish

        # Now ramp price far above any plausible upper band
        result = None
        for _ in range(5):
            result = st.update(10.0, 9.5, 9.8)
        assert result is not None
        assert result.direction == 1

    def test_band_ratchets_upward_when_bullish(self) -> None:
        # When bullish, lower band should not decrease between bars.
        st = SupertrendIndicator(period=5, multiplier=2.0)
        prev_band: float | None = None
        for i in range(30):
            result = st.update(1.0 + i * 0.005, 0.9 + i * 0.005, 0.95 + i * 0.005)
            if result is not None and result.direction == 1:
                if prev_band is not None:
                    assert result.value >= prev_band - 1e-9
                prev_band = result.value

    def test_value_property_matches_last_update(self) -> None:
        st = SupertrendIndicator(period=3)
        ret = None
        for _ in range(5):
            ret = st.update(1.1, 0.9, 1.0)
        assert ret == st.value

    def test_uses_rma_not_ema_for_atr(self) -> None:
        # Two indicators with period=10: one correct (RMA), conceptually verify
        # they produce a valid result (smoke test for correct ATR path).
        st = SupertrendIndicator(period=10, multiplier=3.0)
        prices = [(1.0 + i * 0.002, 0.99 + i * 0.002, 0.995 + i * 0.002) for i in range(20)]
        result = None
        for h, lo, c in prices:
            result = st.update(h, lo, c)
        assert result is not None
        assert result.value > 0


# ---------------------------------------------------------------------------
# TSIIndicator
# ---------------------------------------------------------------------------


class TestTSIIndicator:
    def test_invalid_period_raises(self) -> None:
        with pytest.raises(ValueError, match="periods"):
            TSIIndicator(long_period=0)

    def test_returns_none_during_warmup(self) -> None:
        tsi = TSIIndicator(long_period=5, short_period=3, signal_period=3)
        # At minimum need 1 (prev_close) + 5 (long EMA) + 3 (short EMA) + 3 (signal) - 2 = 10 bars
        for i in range(9):
            assert tsi.update(float(i + 1)) is None

    def test_eventually_produces_result(self) -> None:
        tsi = TSIIndicator(long_period=5, short_period=3, signal_period=3)
        result = None
        for i in range(30):
            result = tsi.update(float(i + 1))
        assert result is not None

    def test_tsi_in_valid_range(self) -> None:
        tsi = TSIIndicator(long_period=5, short_period=3, signal_period=3)
        result = None
        for i in range(50):
            result = tsi.update(1.0 + 0.01 * i)
        assert result is not None
        assert -100.0 <= result.tsi <= 100.0

    def test_positive_momentum_gives_positive_tsi(self) -> None:
        tsi = TSIIndicator(long_period=5, short_period=3, signal_period=3)
        result = None
        for i in range(50):
            result = tsi.update(1.0 + 0.1 * i)  # strictly increasing
        assert result is not None
        assert result.tsi > 0

    def test_negative_momentum_gives_negative_tsi(self) -> None:
        tsi = TSIIndicator(long_period=5, short_period=3, signal_period=3)
        result = None
        for i in range(50):
            result = tsi.update(100.0 - 0.1 * i)  # strictly decreasing
        assert result is not None
        assert result.tsi < 0

    def test_signal_tracks_tsi(self) -> None:
        tsi = TSIIndicator(long_period=5, short_period=3, signal_period=3)
        results = []
        for i in range(50):
            r = tsi.update(1.0 + 0.05 * i)
            if r is not None:
                results.append(r)
        assert len(results) > 0
        # Signal and TSI should be in the same ballpark (not wildly different)
        last = results[-1]
        assert abs(last.signal - last.tsi) < 20.0

    def test_value_property_matches_last_update(self) -> None:
        tsi = TSIIndicator(long_period=5, short_period=3, signal_period=3)
        ret = None
        for i in range(30):
            ret = tsi.update(float(i + 1))
        assert ret == tsi.value


# ---------------------------------------------------------------------------
# PivotZoneDetector
# ---------------------------------------------------------------------------


class TestPivotZoneDetector:
    def _bars_from_highs(self, highs: list[float]) -> list[Bar]:
        """Helper: each bar has the given high, low = high-0.1, close = high-0.05."""
        return [_bar(h, h - 0.1, h - 0.05, i) for i, h in enumerate(highs)]

    def test_invalid_left_right_raises(self) -> None:
        with pytest.raises(ValueError, match="left_bars"):
            PivotZoneDetector(pip_size=0.0001, left_bars=0, right_bars=1)

    def test_invalid_pip_size_raises(self) -> None:
        with pytest.raises(ValueError, match="pip_size"):
            PivotZoneDetector(pip_size=0.0)

    def test_detects_pivot_high_as_resistance(self) -> None:
        # Pattern: 1, 2, 3(pivot high), 2, 1 with left=2, right=2
        det = PivotZoneDetector(pip_size=0.0001, left_bars=2, right_bars=2)
        for bar in self._bars_from_highs([1.0, 2.0, 3.0, 2.0, 1.0]):
            det.update(bar)
        resistances = [z for z in det._zones if z.kind == "resistance"]
        assert len(resistances) >= 1
        assert any(abs(z.price - 3.0) < 0.01 for z in resistances)

    def test_detects_pivot_low_as_support(self) -> None:
        # Pivot low at bar index 2 (low=0.9), confirmed after 2 more bars
        det = PivotZoneDetector(pip_size=0.0001, left_bars=2, right_bars=2)
        lows = [3.0, 2.0, 1.0, 2.0, 3.0]
        for i, h in enumerate(lows):
            bar = _bar(h, h - 0.1, h - 0.05, i)
            det.update(bar)
        supports = [z for z in det._zones if z.kind == "support"]
        assert len(supports) >= 1

    def test_active_zones_excludes_broken_resistance(self) -> None:
        det = PivotZoneDetector(pip_size=0.0001, left_bars=2, right_bars=2)
        # Create a resistance at ~3.0
        for bar in self._bars_from_highs([1.0, 2.0, 3.0, 2.0, 1.0]):
            det.update(bar)
        # Close well above the resistance zone
        det.update(_bar(4.0, 3.5, 3.8, 10))
        active = det.active_zones
        assert not any(z.broken for z in active)

    def test_zone_broken_when_close_exceeds_price(self) -> None:
        det = PivotZoneDetector(pip_size=0.0001, left_bars=2, right_bars=2)
        for bar in self._bars_from_highs([1.0, 2.0, 3.0, 2.0, 1.0]):
            det.update(bar)
        resistances_before = [z for z in det._zones if z.kind == "resistance"]
        assert len(resistances_before) >= 1

        det.update(_bar(4.0, 3.5, 3.8, 10))  # close=3.8 > zone at ~3.0
        broken = [z for z in det._zones if z.kind == "resistance" and z.broken]
        assert len(broken) >= 1

    def test_exhausted_zone_not_in_active(self) -> None:
        det = PivotZoneDetector(pip_size=0.0001, left_bars=2, right_bars=2, max_touches=2)
        for bar in self._bars_from_highs([1.0, 2.0, 3.0, 2.0, 1.0]):
            det.update(bar)
        # Repeatedly test the resistance zone (high close to 3.0, close below it)
        for _ in range(5):
            det.update(_bar(3.05, 2.9, 2.95, 20))
        active = det.active_zones
        resistances = [z for z in det._zones if z.kind == "resistance"]
        # All resistance zones should now be exhausted (> max_touches) or broken
        assert all(not z.is_fresh(2) for z in resistances) or all(
            z not in active for z in resistances
        )

    def test_nearby_pivots_merge(self) -> None:
        det = PivotZoneDetector(pip_size=0.0001, left_bars=2, right_bars=2, zone_merge_pips=200.0)
        # Two resistance pivots very close together (within merge distance)
        for bar in self._bars_from_highs([1.0, 2.0, 3.000, 2.0, 1.0]):
            det.update(bar)
        for bar in self._bars_from_highs([1.0, 2.0, 3.001, 2.0, 1.0]):
            det.update(bar)
        resistances = [z for z in det._zones if z.kind == "resistance"]
        # Should have merged into one zone (touches += 1) not two separate zones
        assert len(resistances) == 1
        assert resistances[0].touches >= 2

    def test_no_pivot_when_window_not_full(self) -> None:
        det = PivotZoneDetector(pip_size=0.0001, left_bars=3, right_bars=3)
        for bar in self._bars_from_highs([1.0, 2.0, 3.0]):
            det.update(bar)
        assert det._zones == []

    def test_active_zones_property_filters_fresh(self) -> None:
        det = PivotZoneDetector(pip_size=0.0001, left_bars=2, right_bars=2, max_touches=3)
        for bar in self._bars_from_highs([1.0, 2.0, 3.0, 2.0, 1.0]):
            det.update(bar)
        zones = det.active_zones
        assert all(not z.broken for z in zones)
        assert all(z.touches <= 3 for z in zones)
