"""GoldPullback — H4 pullback strategy for XAU/USD.

Signal logic (single timeframe):
  LONG  when EMA20 > EMA50  AND  Supertrend bullish  AND  TSI > 0 & above signal
        AND  close is within zone_entry_pips of a fresh support zone
  SHORT when EMA20 < EMA50  AND  Supertrend bearish  AND  TSI < 0 & below signal
        AND  close is within zone_entry_pips of a fresh resistance zone
  HOLD  (repeat current direction) when the two primary trend filters still agree
  FLAT  otherwise / during warm-up

Zone condition gates entry only. Once in a trade, only EMA + Supertrend
disagreement causes an exit. This prevents whipsawing on brief TSI dips
inside a running trend.

SL/TP sizing
------------
  SL = entry ± ATR × sl_atr_mult   (Wilder's RMA, 14-period)
  TP = entry ± ATR × tp_atr_mult
  Both are exposed as _sl / _tp for the multi-TF scanner to read.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..engine import BarView, Position, Signal
from ..indicators import (
    ATRIndicator,
    EMAIndicator,
    PivotZoneDetector,
    SupertrendIndicator,
    TSIIndicator,
)

__all__ = ["GoldPullback"]

XAU_PIP_SIZE: float = 0.1  # one pip for gold = $0.10


@dataclass
class GoldPullback:
    """H4 pullback strategy: EMA bias + Supertrend + TSI + S/D zones.

    Args:
        ema_fast: Fast EMA period for directional bias.
        ema_slow: Slow EMA period. Must be > ema_fast.
        st_period: ATR period for Supertrend (uses Wilder's RMA internally).
        st_multiplier: Band multiplier for Supertrend.
        tsi_long: Long smoothing period for TSI double-smoothed momentum.
        tsi_short: Short smoothing period for TSI.
        tsi_signal: Signal-line EMA period for TSI.
        atr_period: ATR period for SL/TP sizing (Wilder's RMA, default 14).
        sl_atr_mult: SL distance = ATR × sl_atr_mult (default 1.5).
        tp_atr_mult: TP distance = ATR × tp_atr_mult (default 3.0).
        pivot_left: Left-side bars required to confirm a pivot.
        pivot_right: Right-side bars lag before a pivot is confirmed.
        zone_merge_pips: Pivots within this distance are merged into one zone.
        max_zone_touches: Zone is exhausted after this many tests.
        zone_entry_pips: Max distance from close to zone price to trigger entry.
    """

    ema_fast: int = 20
    ema_slow: int = 50
    st_period: int = 10
    st_multiplier: float = 3.0
    tsi_long: int = 25
    tsi_short: int = 13
    tsi_signal: int = 13
    atr_period: int = 14
    sl_atr_mult: float = 1.5
    tp_atr_mult: float = 2.25  # RR=1.5 — tighter TP for higher win rate
    pivot_left: int = 5
    pivot_right: int = 5
    # XAU/USD pip_size=0.1, so 1 pip = $0.10.
    # zone_merge_pips=50 → $5.0 cluster radius; zone_entry_pips=150 → $15.0 proximity
    # gate (~0.6% of a $2500 quote), large enough to catch wicks testing a zone.
    zone_merge_pips: float = 50.0
    max_zone_touches: int = 3
    zone_entry_pips: float = 150.0

    _ema_fast_ind: EMAIndicator = field(init=False, repr=False)
    _ema_slow_ind: EMAIndicator = field(init=False, repr=False)
    _supertrend: SupertrendIndicator = field(init=False, repr=False)
    _tsi: TSIIndicator = field(init=False, repr=False)
    _atr: ATRIndicator = field(init=False, repr=False)
    _zones: PivotZoneDetector = field(init=False, repr=False)
    _sl: float | None = field(init=False, repr=False, default=None)
    _tp: float | None = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        if self.ema_fast >= self.ema_slow:
            raise ValueError(f"ema_fast ({self.ema_fast}) must be < ema_slow ({self.ema_slow})")
        if self.zone_entry_pips <= 0:
            raise ValueError(f"zone_entry_pips must be > 0, got {self.zone_entry_pips}")
        if self.tp_atr_mult <= self.sl_atr_mult:
            raise ValueError(
                f"tp_atr_mult ({self.tp_atr_mult}) must be > sl_atr_mult ({self.sl_atr_mult})"
            )
        self._ema_fast_ind = EMAIndicator(self.ema_fast)
        self._ema_slow_ind = EMAIndicator(self.ema_slow)
        self._supertrend = SupertrendIndicator(self.st_period, self.st_multiplier)
        self._tsi = TSIIndicator(self.tsi_long, self.tsi_short, self.tsi_signal)
        self._atr = ATRIndicator(self.atr_period)
        self._zones = PivotZoneDetector(
            pip_size=XAU_PIP_SIZE,
            left_bars=self.pivot_left,
            right_bars=self.pivot_right,
            zone_merge_pips=self.zone_merge_pips,
            max_touches=self.max_zone_touches,
        )
        self._sl = None
        self._tp = None

    def on_bar(self, view: BarView, position: Position) -> Signal:
        bar = view.last

        ema_fast_val = self._ema_fast_ind.update(bar.close)
        ema_slow_val = self._ema_slow_ind.update(bar.close)
        st_result = self._supertrend.update(bar.high, bar.low, bar.close)
        tsi_result = self._tsi.update(bar.close)
        atr_val = self._atr.update(bar.high, bar.low, bar.close)
        active_zones = self._zones.update(bar)

        if any(v is None for v in (ema_fast_val, ema_slow_val, st_result, tsi_result, atr_val)):
            return Signal.FLAT

        # mypy narrowing — values are non-None past the guard above
        assert ema_fast_val is not None
        assert ema_slow_val is not None
        assert st_result is not None
        assert tsi_result is not None
        assert atr_val is not None

        ema_bull = ema_fast_val > ema_slow_val
        ema_bear = ema_fast_val < ema_slow_val
        st_bull = st_result.direction == 1
        st_bear = st_result.direction == -1
        tsi_bull = tsi_result.tsi > 0 and tsi_result.tsi > tsi_result.signal
        tsi_bear = tsi_result.tsi < 0 and tsi_result.tsi < tsi_result.signal

        gate = self.zone_entry_pips * XAU_PIP_SIZE
        near_support = any(
            bar.close - gate <= z.price <= bar.close + gate
            for z in active_zones
            if z.kind == "support"
        )
        near_resistance = any(
            bar.close - gate <= z.price <= bar.close + gate
            for z in active_zones
            if z.kind == "resistance"
        )

        if position.is_flat:
            if ema_bull and st_bull and tsi_bull and near_support:
                entry = bar.close
                self._sl = entry - atr_val * self.sl_atr_mult
                self._tp = entry + atr_val * self.tp_atr_mult
                return Signal.LONG
            if ema_bear and st_bear and tsi_bear and near_resistance:
                entry = bar.close
                self._sl = entry + atr_val * self.sl_atr_mult
                self._tp = entry - atr_val * self.tp_atr_mult
                return Signal.SHORT
            return Signal.FLAT

        if position.is_long:
            if not (ema_bull and st_bull):
                self._sl = self._tp = None
                return Signal.FLAT
            return Signal.LONG

        if position.is_short:
            if not (ema_bear and st_bear):
                self._sl = self._tp = None
                return Signal.FLAT
            return Signal.SHORT

        return Signal.FLAT
