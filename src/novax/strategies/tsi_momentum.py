"""TSIMomentum — EMA50 trend filter + TSI crossover entry.

Signal logic
------------
  LONG  : close > EMA50  (bull regime)
          AND TSI crosses above signal line
          AND TSI > +tsi_threshold
  SHORT : close < EMA50  (bear regime)
          AND TSI crosses below signal line
          AND TSI < -tsi_threshold

Exit
----
  - SL hit  : bar.low  <= sl (long) / bar.high >= sl (short)
  - TP hit  : bar.high >= tp (long) / bar.low  <= tp (short)
  - Regime flip: price crosses EMA50 to the opposite side

Risk sizing
-----------
  SL = entry ± ATR × sl_atr_mult
  TP = entry ± ATR × tp_atr_mult

Session filter
--------------
  New entries gated to London (07–12 UTC) and/or NY (13–20 UTC).
  Open positions managed on every bar regardless of session.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..engine import BarView, Position, Signal
from ..indicators import ATRIndicator, EMAIndicator, TSIIndicator

__all__ = ["TSIMomentum"]

_LONDON_HOURS: frozenset[int] = frozenset(range(7, 13))
_NY_HOURS: frozenset[int] = frozenset(range(13, 21))


@dataclass
class TSIMomentum:
    """EMA50 regime filter + TSI crossover entry for XAU/USD intraday.

    Args:
        ema_period: EMA period for trend regime (default 50).
        tsi_long: TSI long smoothing period (default 25).
        tsi_short: TSI short smoothing period (default 13).
        tsi_signal: TSI signal-line EMA period (default 13).
        atr_period: ATR period for SL/TP sizing (Wilder's RMA, default 14).
        sl_atr_mult: SL distance = ATR × sl_atr_mult (default 1.5).
        tp_atr_mult: TP distance = ATR × tp_atr_mult (default 3.0).
        tsi_threshold: Minimum absolute TSI at crossover to accept entry.
            Filters near-zero weak signals (default 5.0).
        london: Allow new entries in London session 07–12 UTC (default True).
        ny: Allow new entries in NY session 13–20 UTC (default True).
    """

    ema_period: int = 50
    tsi_long: int = 25
    tsi_short: int = 13
    tsi_signal: int = 13
    atr_period: int = 14
    sl_atr_mult: float = 1.5
    tp_atr_mult: float = 3.0
    tsi_threshold: float = 5.0
    london: bool = True
    ny: bool = True

    _ema: EMAIndicator = field(init=False, repr=False)
    _tsi: TSIIndicator = field(init=False, repr=False)
    _atr: ATRIndicator = field(init=False, repr=False)
    _prev_tsi: float | None = field(init=False, repr=False, default=None)
    _prev_signal: float | None = field(init=False, repr=False, default=None)
    _sl: float | None = field(init=False, repr=False, default=None)
    _tp: float | None = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        if self.ema_period < 1:
            raise ValueError(f"ema_period must be >= 1, got {self.ema_period}")
        if self.sl_atr_mult <= 0:
            raise ValueError(f"sl_atr_mult must be > 0, got {self.sl_atr_mult}")
        if self.tp_atr_mult <= self.sl_atr_mult:
            raise ValueError(
                f"tp_atr_mult ({self.tp_atr_mult}) must be > sl_atr_mult ({self.sl_atr_mult})"
            )
        self._ema = EMAIndicator(self.ema_period)
        self._tsi = TSIIndicator(self.tsi_long, self.tsi_short, self.tsi_signal)
        self._atr = ATRIndicator(self.atr_period)
        self._prev_tsi = None
        self._prev_signal = None
        self._sl = None
        self._tp = None

    def _in_session(self, hour: int) -> bool:
        return (self.london and hour in _LONDON_HOURS) or (self.ny and hour in _NY_HOURS)

    def on_bar(self, view: BarView, position: Position) -> Signal:
        bar = view.last

        ema_val = self._ema.update(bar.close)
        tsi_r   = self._tsi.update(bar.close)
        atr     = self._atr.update(bar.high, bar.low, bar.close)

        if ema_val is None or tsi_r is None or atr is None:
            return Signal.FLAT

        tsi_now = tsi_r.tsi
        sig_now = tsi_r.signal

        crossed_up = (
            self._prev_tsi is not None
            and self._prev_signal is not None
            and self._prev_tsi <= self._prev_signal
            and tsi_now > sig_now
        )
        crossed_down = (
            self._prev_tsi is not None
            and self._prev_signal is not None
            and self._prev_tsi >= self._prev_signal
            and tsi_now < sig_now
        )

        self._prev_tsi    = tsi_now
        self._prev_signal = sig_now

        bull_regime = bar.close > ema_val
        bear_regime = bar.close < ema_val

        # --- Manage open positions on every bar ---
        # EMA50 gates ENTRY only — exits driven by SL/TP or opposite TSI crossover.
        if position.is_long:
            if self._sl is not None and bar.low <= self._sl:
                self._sl = self._tp = None
                return Signal.FLAT
            if self._tp is not None and bar.high >= self._tp:
                self._sl = self._tp = None
                return Signal.FLAT
            if crossed_down:               # TSI momentum reversal → exit
                self._sl = self._tp = None
                return Signal.FLAT
            return Signal.LONG

        if position.is_short:
            if self._sl is not None and bar.high >= self._sl:
                self._sl = self._tp = None
                return Signal.FLAT
            if self._tp is not None and bar.low <= self._tp:
                self._sl = self._tp = None
                return Signal.FLAT
            if crossed_up:                 # TSI momentum reversal → exit
                self._sl = self._tp = None
                return Signal.FLAT
            return Signal.SHORT

        # --- FLAT: look for new entry (session-gated) ---
        if not self._in_session(bar.ts.hour):
            return Signal.FLAT

        if crossed_up and tsi_now > self.tsi_threshold and bull_regime:
            entry = bar.close
            self._sl = entry - atr * self.sl_atr_mult
            self._tp = entry + atr * self.tp_atr_mult
            return Signal.LONG

        if crossed_down and tsi_now < -self.tsi_threshold and bear_regime:
            entry = bar.close
            self._sl = entry + atr * self.sl_atr_mult
            self._tp = entry - atr * self.tp_atr_mult
            return Signal.SHORT

        return Signal.FLAT
