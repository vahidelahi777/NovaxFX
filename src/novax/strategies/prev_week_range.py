"""Previous-Week High/Low Range strategy — London/NY session setup.

Levels
------
  PWH = previous week's high  (Friday close → locked for the whole next week)
  PWL = previous week's low

Entry logic
-----------
  PULLBACK  — price tags the level but holds inside the range:
    LONG  : bar.low  <= PWL + touch_buf  AND bar.close >= PWL
            + EMA bullish + TSI bullish
    SHORT : bar.high >= PWH - touch_buf  AND bar.close <= PWH
            + EMA bearish + TSI bearish

  BREAKOUT  — price closes convincingly outside the range:
    LONG  : bar.close > PWH + break_buf  + EMA bull + TSI bull
    SHORT : bar.close < PWL - break_buf  + EMA bear + TSI bear

Session filter
--------------
  Only enter new positions during London (07–12 UTC) or NY (13–20 UTC).
  Open positions are managed (SL/TP) on every bar regardless of session.

SL / TP
-------
  Pullback LONG  — SL = PWL - sl_buf       | TP = entry + risk × RR
  Pullback SHORT — SL = PWH + sl_buf       | TP = entry - risk × RR
  Breakout LONG  — SL = PWH - sl_buf       | TP = entry + risk × RR
  Breakout SHORT — SL = PWL + sl_buf       | TP = entry - risk × RR
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..engine import BarView, Position, Signal
from ..indicators import ATRIndicator, EMAIndicator, TSIIndicator, WeeklyLevelTracker

__all__ = ["PrevWeekRange"]

_LONDON_HOURS: frozenset[int] = frozenset(range(7, 13))   # 07:00–12:59 UTC
_NY_HOURS: frozenset[int] = frozenset(range(13, 21))       # 13:00–20:59 UTC


@dataclass
class PrevWeekRange:
    """Weekly H/L range strategy for XAU/USD (and FX majors).

    Args:
        ema_fast: Fast EMA period.
        ema_slow: Slow EMA period (must be > ema_fast).
        tsi_long: TSI long smoothing period.
        tsi_short: TSI short smoothing period.
        tsi_signal: TSI signal-line EMA period.
        pip_size: One pip in price units (XAU/USD default 0.1).
        touch_buf_pips: Price must come within this many pips of PWH/PWL
            for a pullback to register.
        break_buf_pips: Price must close this many pips beyond PWH/PWL
            for a breakout to register.
        sl_buf_pips: SL placed this many pips beyond the level.
        max_risk_pips: Skip trade if SL distance exceeds this.
        risk_reward: TP = entry ± risk × risk_reward.
        london: Allow entries during London session (07–12 UTC).
        ny: Allow entries during NY session (13–20 UTC).
    """

    ema_fast: int = 20
    ema_slow: int = 50
    tsi_long: int = 25
    tsi_short: int = 13
    tsi_signal: int = 13
    pip_size: float = 0.1
    touch_buf_pips: float = 3.0
    break_buf_pips: float = 2.0
    sl_atr_mult: float = 1.0
    """SL = level ± sl_atr_mult × ATR(atr_period).  Replaces fixed pip SL."""
    atr_period: int = 14
    max_risk_pips: float = 150.0
    risk_reward: float = 2.0
    london: bool = True
    ny: bool = True

    _ema_fast_ind: EMAIndicator = field(init=False, repr=False)
    _ema_slow_ind: EMAIndicator = field(init=False, repr=False)
    _tsi: TSIIndicator = field(init=False, repr=False)
    _atr: ATRIndicator = field(init=False, repr=False)
    _weekly: WeeklyLevelTracker = field(init=False, repr=False)
    _sl: float | None = field(init=False, repr=False, default=None)
    _tp: float | None = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        if self.ema_fast >= self.ema_slow:
            raise ValueError(f"ema_fast ({self.ema_fast}) must be < ema_slow ({self.ema_slow})")
        self._ema_fast_ind = EMAIndicator(self.ema_fast)
        self._ema_slow_ind = EMAIndicator(self.ema_slow)
        self._tsi = TSIIndicator(self.tsi_long, self.tsi_short, self.tsi_signal)
        self._atr = ATRIndicator(self.atr_period)
        self._weekly = WeeklyLevelTracker()
        self._sl = None
        self._tp = None

    def _in_session(self, hour: int) -> bool:
        return (self.london and hour in _LONDON_HOURS) or (self.ny and hour in _NY_HOURS)

    def on_bar(self, view: BarView, position: Position) -> Signal:
        bar = view.last

        fast = self._ema_fast_ind.update(bar.close)
        slow = self._ema_slow_ind.update(bar.close)
        tsi_r = self._tsi.update(bar.close)
        atr_val = self._atr.update(bar.high, bar.low, bar.close)
        levels = self._weekly.update(bar)

        if fast is None or slow is None or tsi_r is None or atr_val is None or levels is None:
            return Signal.FLAT

        # --- Manage open position (SL/TP checked on every bar) ---
        if position.is_long:
            if self._sl is not None and bar.low <= self._sl:
                self._sl = self._tp = None
                return Signal.FLAT
            if self._tp is not None and bar.high >= self._tp:
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
            return Signal.SHORT

        # --- FLAT: look for new entry (session-gated) ---
        if not self._in_session(bar.ts.hour):
            return Signal.FLAT

        pwh = levels.prev_high
        pwl = levels.prev_low
        touch_buf = self.touch_buf_pips * self.pip_size
        break_buf = self.break_buf_pips * self.pip_size
        # SL buffer = ATR-based (adapts to current volatility)
        sl_buf = self.sl_atr_mult * atr_val
        max_risk = self.max_risk_pips * self.pip_size

        ema_bull = fast > slow
        ema_bear = fast < slow
        tsi_bull = tsi_r.tsi > 0 and tsi_r.tsi > tsi_r.signal
        tsi_bear = tsi_r.tsi < 0 and tsi_r.tsi < tsi_r.signal

        # --- Pullback: buy at PWL support ---
        if bar.low <= pwl + touch_buf and bar.close >= pwl and ema_bull and tsi_bull:
            entry = bar.close
            sl = pwl - sl_buf
            risk = entry - sl
            if 0 < risk <= max_risk:
                self._sl = sl
                self._tp = entry + risk * self.risk_reward
                return Signal.LONG

        # --- Pullback: sell at PWH resistance ---
        if bar.high >= pwh - touch_buf and bar.close <= pwh and ema_bear and tsi_bear:
            entry = bar.close
            sl = pwh + sl_buf
            risk = sl - entry
            if 0 < risk <= max_risk:
                self._sl = sl
                self._tp = entry - risk * self.risk_reward
                return Signal.SHORT

        # --- Breakout: buy above PWH ---
        if bar.close > pwh + break_buf and ema_bull and tsi_bull:
            entry = bar.close
            sl = pwh - sl_buf
            risk = entry - sl
            if 0 < risk <= max_risk:
                self._sl = sl
                self._tp = entry + risk * self.risk_reward
                return Signal.LONG

        # --- Breakout: sell below PWL ---
        if bar.close < pwl - break_buf and ema_bear and tsi_bear:
            entry = bar.close
            sl = pwl + sl_buf
            risk = sl - entry
            if 0 < risk <= max_risk:
                self._sl = sl
                self._tp = entry - risk * self.risk_reward
                return Signal.SHORT

        return Signal.FLAT
