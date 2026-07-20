"""LondonOpenSweep — Asian-range sweep-and-reject strategy for XAU/USD.

Signal logic (1H bars, UTC timestamps):
  Asian session  : bars whose ts.hour is in 0–6 UTC.
                   Track daily high / low across these bars.
  London window  : bars whose ts.hour is in 7–11 UTC.
  SHORT signal   : bar.high > asian_high AND bar.close < asian_high
                   (price swept above the range then rejected → bearish)
  LONG  signal   : bar.low  < asian_low  AND bar.close > asian_low
                   (price swept below the range then rejected → bullish)
  Reset          : at midnight UTC (new day) and after 12:00 UTC.

Only one signal fires per calendar day.  Subsequent London bars on the same
day after a signal return the same direction (preserving the signal for the
scanner to read) until reset.

Volatility filter
-----------------
Maintain a running list of the last 20 ATR values.  If the current bar's ATR
exceeds 1.5× the mean of the previous 19 values the signal is suppressed
(returns FLAT) regardless of sweep pattern.  This avoids the April-2025-style
tariff-shock whipsaw clusters.

SL / TP sizing
--------------
  SHORT : SL = sweep_high + atr * sl_atr_mult
          TP = entry   - (SL - entry) * rr
  LONG  : SL = sweep_low  - atr * sl_atr_mult
          TP = entry   + (entry - SL) * rr
Both exposed as _sl / _tp for the scanner to read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from ..engine import BarView, Position, Signal
from ..indicators import ATRIndicator

__all__ = ["LondonOpenSweep"]

_ASIAN_HOURS: frozenset[int] = frozenset(range(0, 7))  # 00–06 UTC inclusive
_LONDON_HOURS: frozenset[int] = frozenset(range(7, 12))  # 07–11 UTC inclusive
_LONDON_CLOSE_HOUR: int = 12  # reset at or after this hour

_MIN_ASIAN_BARS: int = 5  # warmup: need at least this many Asian bars before signalling


@dataclass
class LondonOpenSweep:
    """London open sweep-and-reject strategy.

    Args:
        sl_atr_mult: ATR multiplier for stop-loss distance (default 1.0).
        rr:          Reward-to-risk ratio for take-profit (default 2.0).
        atr_period:  ATR period (Wilder's RMA, default 14).
        vol_window:  Number of recent ATR values used for vol filter (default 20).
        vol_mult:    If current ATR > vol_mult × mean(last vol_window-1), skip (default 1.5).
    """

    sl_atr_mult: float = 1.0
    rr: float = 2.0
    atr_period: int = 14
    vol_window: int = 20
    vol_mult: float = 1.5

    # Internal ATR indicator
    _atr_ind: ATRIndicator = field(init=False, repr=False)
    # Rolling ATR history for vol filter
    _atr_history: list[float] = field(init=False, repr=False)

    # Current-day Asian range
    _today: date | None = field(init=False, repr=False, default=None)
    _asian_high: float | None = field(init=False, repr=False, default=None)
    _asian_low: float | None = field(init=False, repr=False, default=None)
    _asian_bar_count: int = field(init=False, repr=False, default=0)

    # Sweep high / low for SL computation
    _sweep_extreme: float | None = field(init=False, repr=False, default=None)

    # Today's signal state
    _signal_today: Signal = field(init=False, repr=False, default=Signal.FLAT)
    _signal_fired: bool = field(init=False, repr=False, default=False)

    # Exposed for scanner
    _sl: float | None = field(init=False, repr=False, default=None)
    _tp: float | None = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        if self.sl_atr_mult <= 0:
            raise ValueError(f"sl_atr_mult must be > 0, got {self.sl_atr_mult}")
        if self.rr <= 0:
            raise ValueError(f"rr must be > 0, got {self.rr}")
        self._atr_ind = ATRIndicator(self.atr_period)
        self._atr_history = []

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def on_bar(self, view: BarView, position: Position) -> Signal:  # noqa: ARG002
        bar = view.last
        ts: datetime = bar.ts if bar.ts.tzinfo is not None else bar.ts.replace(tzinfo=UTC)
        bar_date: date = ts.date()
        hour: int = ts.hour

        # --- 1. Update ATR -------------------------------------------------
        atr_val = self._atr_ind.update(bar.high, bar.low, bar.close)
        if atr_val is not None:
            self._atr_history.append(atr_val)
            if len(self._atr_history) > self.vol_window:
                self._atr_history.pop(0)

        # --- 2. Day reset ---------------------------------------------------
        if self._today != bar_date:
            self._today = bar_date
            self._asian_high = None
            self._asian_low = None
            self._asian_bar_count = 0
            self._sweep_extreme = None
            self._signal_today = Signal.FLAT
            self._signal_fired = False
            self._sl = None
            self._tp = None

        # --- 3. Track Asian range -------------------------------------------
        if hour in _ASIAN_HOURS:
            if self._asian_high is None or bar.high > self._asian_high:
                self._asian_high = bar.high
            if self._asian_low is None or bar.low < self._asian_low:
                self._asian_low = bar.low
            self._asian_bar_count += 1
            return Signal.FLAT

        # --- 4. Past London close — FLAT ------------------------------------
        if hour >= _LONDON_CLOSE_HOUR:
            return Signal.FLAT

        # --- 5. London window — only proceed if in 7–11 UTC ----------------
        if hour not in _LONDON_HOURS:
            return Signal.FLAT

        # --- 6. Warmup guard ------------------------------------------------
        if (
            self._asian_bar_count < _MIN_ASIAN_BARS
            or self._asian_high is None
            or self._asian_low is None
        ):
            return Signal.FLAT

        # --- 7. If already fired today, preserve direction ------------------
        if self._signal_fired:
            return self._signal_today

        # --- 8. Volatility filter -------------------------------------------
        if atr_val is not None and len(self._atr_history) >= 2:
            prev = self._atr_history[:-1]
            mean_prev = sum(prev) / len(prev)
            if mean_prev > 0 and atr_val > self.vol_mult * mean_prev:
                return Signal.FLAT

        # --- 9. Sweep detection --------------------------------------------
        asian_high = self._asian_high
        asian_low = self._asian_low

        if bar.high > asian_high and bar.close < asian_high:
            # Bearish sweep: wicked above Asian high, closed below it
            if atr_val is not None:
                entry = bar.close
                sweep_hi = bar.high
                sl_price = sweep_hi + atr_val * self.sl_atr_mult
                tp_price = entry - (sl_price - entry) * self.rr
                self._sl = sl_price
                self._tp = tp_price
                self._sweep_extreme = sweep_hi
            self._signal_today = Signal.SHORT
            self._signal_fired = True
            return Signal.SHORT

        if bar.low < asian_low and bar.close > asian_low:
            # Bullish sweep: wicked below Asian low, closed above it
            if atr_val is not None:
                entry = bar.close
                sweep_lo = bar.low
                sl_price = sweep_lo - atr_val * self.sl_atr_mult
                tp_price = entry + (entry - sl_price) * self.rr
                self._sl = sl_price
                self._tp = tp_price
                self._sweep_extreme = sweep_lo
            self._signal_today = Signal.LONG
            self._signal_fired = True
            return Signal.LONG

        return Signal.FLAT
