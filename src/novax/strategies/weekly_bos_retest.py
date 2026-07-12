"""Weekly BOS Retest strategy — institutional H4 setup.

Entry logic (causal, one trade at a time):
  LONG  — BOS_UP this week + OB retest + EMA bull + TSI bull + no bearish CHoCH
  SHORT — BOS_DOWN this week + OB retest + EMA bear + TSI bear + no bullish CHoCH

Exit logic (internal SL/TP tracking):
  SL: ob_buffer_pips beyond the OB edge (below ob_low for LONG, above ob_high for SHORT)
  TP: entry ± risk × risk_reward

SL/TP breach is detected by bar.low/bar.high (intrabar approximation, suitable for H4).
Actual fill price is the engine's job (bars[i+1].open).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..engine import BarView, Position, Signal
from ..indicators import BOSDetector, BOSState, EMAIndicator, TSIIndicator, WeeklyLevelTracker

__all__ = ["WeeklyBOSRetest"]


@dataclass
class WeeklyBOSRetest:
    """Weekly BOS Retest strategy for H4 XAU/USD (and FX majors).

    Args:
        ema_fast: Fast EMA period for directional bias (must be < ema_slow).
        ema_slow: Slow EMA period.
        tsi_long: Long smoothing period for TSI double-smoothed momentum.
        tsi_short: Short smoothing period for TSI.
        tsi_signal: Signal-line EMA period for TSI.
        pip_size: One pip in price units (XAU/USD default 0.1).
        ob_buffer_pips: SL placed this many pips beyond the OB edge.
        max_risk_pips: Skip trade if SL distance exceeds this many pips.
        risk_reward: TP = entry ± risk × risk_reward.
    """

    ema_fast: int = 20
    ema_slow: int = 50
    tsi_long: int = 25
    tsi_short: int = 13
    tsi_signal: int = 13
    pip_size: float = 0.1
    ob_buffer_pips: float = 5.0
    max_risk_pips: float = 80.0
    risk_reward: float = 2.0

    _ema_fast_ind: EMAIndicator = field(init=False, repr=False)
    _ema_slow_ind: EMAIndicator = field(init=False, repr=False)
    _tsi: TSIIndicator = field(init=False, repr=False)
    _weekly: WeeklyLevelTracker = field(init=False, repr=False)
    _bos: BOSDetector = field(init=False, repr=False)
    _sl: float | None = field(init=False, repr=False, default=None)
    _tp: float | None = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        if self.ema_fast >= self.ema_slow:
            raise ValueError(f"ema_fast ({self.ema_fast}) must be < ema_slow ({self.ema_slow})")
        if self.ob_buffer_pips <= 0:
            raise ValueError(f"ob_buffer_pips must be > 0, got {self.ob_buffer_pips}")
        if self.max_risk_pips <= 0:
            raise ValueError(f"max_risk_pips must be > 0, got {self.max_risk_pips}")
        if self.risk_reward <= 0:
            raise ValueError(f"risk_reward must be > 0, got {self.risk_reward}")
        self._ema_fast_ind = EMAIndicator(self.ema_fast)
        self._ema_slow_ind = EMAIndicator(self.ema_slow)
        self._tsi = TSIIndicator(self.tsi_long, self.tsi_short, self.tsi_signal)
        self._weekly = WeeklyLevelTracker()
        self._bos = BOSDetector()
        self._sl = None
        self._tp = None

    def on_bar(self, view: BarView, position: Position) -> Signal:
        bar = view.last

        # All indicators must receive every bar — missing one corrupts state.
        fast_val = self._ema_fast_ind.update(bar.close)
        slow_val = self._ema_slow_ind.update(bar.close)
        tsi_r = self._tsi.update(bar.close)
        levels = self._weekly.update(bar)
        bos = self._bos.update(bar, levels)

        if fast_val is None or slow_val is None or tsi_r is None or bos is None:
            return Signal.FLAT

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

        # FLAT — look for entry
        ema_bull = fast_val > slow_val
        ema_bear = fast_val < slow_val
        tsi_bull = tsi_r.tsi > 0 and tsi_r.tsi > tsi_r.signal
        tsi_bear = tsi_r.tsi < 0 and tsi_r.tsi < tsi_r.signal

        if bos.state == BOSState.BOS_UP and bos.has_ob and not bos.choch_bearish:
            # OB retest: bar dips into OB zone but close holds above ob_low
            ob_retested = bar.low <= bos.ob_high and bar.close >= bos.ob_low
            if ob_retested and ema_bull and tsi_bull:
                entry = bar.close
                sl = bos.ob_low - self.ob_buffer_pips * self.pip_size
                risk = entry - sl
                if 0 < risk <= self.max_risk_pips * self.pip_size:
                    self._sl = sl
                    self._tp = entry + risk * self.risk_reward
                    return Signal.LONG

        if bos.state == BOSState.BOS_DOWN and bos.has_ob and not bos.choch_bullish:
            # OB retest: bar rallies into OB zone but close holds below ob_high
            ob_retested = bar.high >= bos.ob_low and bar.close <= bos.ob_high
            if ob_retested and ema_bear and tsi_bear:
                entry = bar.close
                sl = bos.ob_high + self.ob_buffer_pips * self.pip_size
                risk = sl - entry
                if 0 < risk <= self.max_risk_pips * self.pip_size:
                    self._sl = sl
                    self._tp = entry - risk * self.risk_reward
                    return Signal.SHORT

        return Signal.FLAT
