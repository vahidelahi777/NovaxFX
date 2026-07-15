"""MultiTFTSI — 1H bias + 15M TSI crossover entry for XAU/USD.

Signal hierarchy (three tiers, evaluated in priority order)
-----------------------------------------------------------
1. EXHAUSTION  — 15M TSI was at extreme (±ob_extreme, default 75), now
                 crosses back. Overrides H1 bias. Strongest signal.

2. OB/OS REVERSAL — 15M TSI was at moderate level (±ob_moderate, default 40),
                    now crosses back, AND H1 bias agrees.

3. STANDARD CROSSOVER — 15M TSI crosses signal line, H1 bias agrees,
                        and 15M TSI is NOT already in the OB/OS zone.

H1 Bias
-------
  BULL : H1 TSI > 0  AND  H1 TSI > H1 signal  AND  H1 close > EMA50
  BEAR : H1 TSI < 0  AND  H1 TSI < H1 signal  AND  H1 close < EMA50
  FLAT : otherwise — no new standard/reversal entries (exhaustion still fires)

H1 reconstruction
-----------------
  Accepts 15M bars. H1 candles assembled internally: when bar hour changes,
  the prior H1 close is fed into 1H TSI and EMA50 to update the bias.

Exit
----
  SL/TP : ATR-based (Wilder RMA, 14-period on 15M bars)
  Reversal : opposite 15M TSI crossover before SL/TP is reached

Session filter
--------------
  Entries: London 07–12 UTC, NY 13–20 UTC.
  Position management (SL/TP/reversal exit): every bar regardless of session.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..engine import BarView, Position, Signal
from ..indicators import ATRIndicator, EMAIndicator, TSIIndicator

__all__ = ["MultiTFTSI"]

_LONDON_HOURS: frozenset[int] = frozenset(range(7, 13))
_NY_HOURS: frozenset[int] = frozenset(range(13, 21))


@dataclass
class MultiTFTSI:
    """1H-biased TSI momentum strategy entered on 15M crossover signals.

    Args:
        tsi_long: TSI long smoothing period (default 25).
        tsi_short: TSI short smoothing period (default 13).
        tsi_signal: TSI signal-line EMA period (default 13).
        ema_period: EMA period for H1 trend regime filter (default 50).
        atr_period: ATR period for SL/TP sizing on 15M bars (default 14).
        sl_atr_mult: SL distance = ATR × sl_atr_mult (default 1.5).
        tp_atr_mult: TP distance = ATR × tp_atr_mult; must exceed sl_atr_mult (default 3.0).
        ob_moderate: Moderate OB/OS threshold; reversal crossover here requires
            H1 bias confirmation (default 40).
        ob_extreme: Extreme OB/OS threshold; reversal crossover here overrides
            H1 bias entirely — exhaustion signal (default 75).
        london: Allow entries in London session 07–12 UTC (default True).
        ny: Allow entries in NY session 13–20 UTC (default True).
    """

    tsi_long: int = 25
    tsi_short: int = 13
    tsi_signal: int = 13
    ema_period: int = 50
    atr_period: int = 14
    sl_atr_mult: float = 1.5
    tp_atr_mult: float = 3.0
    ob_moderate: float = 40.0
    ob_extreme: float = 75.0
    london: bool = True
    ny: bool = True

    # 1H internal state
    _tsi_1h: TSIIndicator = field(init=False, repr=False)
    _ema_1h: EMAIndicator = field(init=False, repr=False)
    _h1_bias: str = field(init=False, repr=False, default="FLAT")
    _cur_hour: int | None = field(init=False, repr=False, default=None)
    _h1_high: float = field(init=False, repr=False, default=0.0)
    _h1_low: float = field(init=False, repr=False, default=float("inf"))
    _h1_close: float = field(init=False, repr=False, default=0.0)

    # 15M internal state
    _tsi_15m: TSIIndicator = field(init=False, repr=False)
    _atr_15m: ATRIndicator = field(init=False, repr=False)
    _prev_tsi: float | None = field(init=False, repr=False, default=None)
    _prev_sig: float | None = field(init=False, repr=False, default=None)

    # Trade state
    _sl: float | None = field(init=False, repr=False, default=None)
    _tp: float | None = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        if self.ob_extreme <= self.ob_moderate:
            raise ValueError(
                f"ob_extreme ({self.ob_extreme}) must exceed ob_moderate ({self.ob_moderate})"
            )
        if self.tp_atr_mult <= self.sl_atr_mult:
            raise ValueError(
                f"tp_atr_mult ({self.tp_atr_mult}) must exceed sl_atr_mult ({self.sl_atr_mult})"
            )
        self._tsi_1h  = TSIIndicator(self.tsi_long, self.tsi_short, self.tsi_signal)
        self._ema_1h  = EMAIndicator(self.ema_period)
        self._tsi_15m = TSIIndicator(self.tsi_long, self.tsi_short, self.tsi_signal)
        self._atr_15m = ATRIndicator(self.atr_period)
        self._h1_bias  = "FLAT"
        self._cur_hour = None
        self._h1_high  = 0.0
        self._h1_low   = float("inf")
        self._h1_close = 0.0
        self._prev_tsi = None
        self._prev_sig = None
        self._sl = None
        self._tp = None

    # ------------------------------------------------------------------
    def _in_session(self, hour: int) -> bool:
        return (self.london and hour in _LONDON_HOURS) or (self.ny and hour in _NY_HOURS)

    def _tick_h1(self, bar: object) -> None:
        """Aggregate a 15M bar into the running H1 candle.

        When the hour changes, close the prior H1 and update 1H indicators.
        """
        hour = bar.ts.hour  # type: ignore[attr-defined]

        if self._cur_hour is None:
            self._cur_hour = hour
            self._h1_high  = bar.high   # type: ignore[attr-defined]
            self._h1_low   = bar.low    # type: ignore[attr-defined]
            self._h1_close = bar.close  # type: ignore[attr-defined]
            return

        if hour != self._cur_hour:
            # H1 candle for _cur_hour is complete — feed its close into 1H indicators
            tsi_r = self._tsi_1h.update(self._h1_close)
            ema_v = self._ema_1h.update(self._h1_close)
            if tsi_r is not None and ema_v is not None:
                t, s = tsi_r.tsi, tsi_r.signal
                if t > 0 and t > s and self._h1_close > ema_v:
                    self._h1_bias = "BULL"
                elif t < 0 and t < s and self._h1_close < ema_v:
                    self._h1_bias = "BEAR"
                else:
                    self._h1_bias = "FLAT"

            self._cur_hour = hour
            self._h1_high  = bar.high   # type: ignore[attr-defined]
            self._h1_low   = bar.low    # type: ignore[attr-defined]
            self._h1_close = bar.close  # type: ignore[attr-defined]
        else:
            self._h1_high  = max(self._h1_high, bar.high)   # type: ignore[attr-defined]
            self._h1_low   = min(self._h1_low,  bar.low)    # type: ignore[attr-defined]
            self._h1_close = bar.close                       # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    def on_bar(self, view: BarView, position: Position) -> Signal:
        bar = view.last

        self._tick_h1(bar)

        tsi_r = self._tsi_15m.update(bar.close)
        atr   = self._atr_15m.update(bar.high, bar.low, bar.close)
        if tsi_r is None or atr is None:
            return Signal.FLAT

        tsi = tsi_r.tsi
        sig = tsi_r.signal

        # Snapshot prev-bar values before overwriting
        prev_tsi = self._prev_tsi
        prev_sig = self._prev_sig

        crossed_up = (
            prev_tsi is not None
            and prev_sig is not None
            and prev_tsi <= prev_sig
            and tsi > sig
        )
        crossed_down = (
            prev_tsi is not None
            and prev_sig is not None
            and prev_tsi >= prev_sig
            and tsi < sig
        )

        # OB/OS classification of the bar that just produced the crossover
        was_ob_extreme  = prev_tsi is not None and prev_tsi >  self.ob_extreme
        was_os_extreme  = prev_tsi is not None and prev_tsi < -self.ob_extreme
        was_ob_moderate = prev_tsi is not None and prev_tsi >  self.ob_moderate
        was_os_moderate = prev_tsi is not None and prev_tsi < -self.ob_moderate

        self._prev_tsi = tsi
        self._prev_sig = sig

        # ------------------------------------------------------------------
        # Manage open position (no session gate)
        # ------------------------------------------------------------------
        if position.is_long:
            if self._sl is not None and bar.low <= self._sl:
                self._sl = self._tp = None
                return Signal.FLAT
            if self._tp is not None and bar.high >= self._tp:
                self._sl = self._tp = None
                return Signal.FLAT
            if crossed_down:                       # momentum reversal → exit
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
            if crossed_up:                         # momentum reversal → exit
                self._sl = self._tp = None
                return Signal.FLAT
            return Signal.SHORT

        # ------------------------------------------------------------------
        # FLAT: look for new entry (session-gated)
        # ------------------------------------------------------------------
        if not self._in_session(bar.ts.hour):
            return Signal.FLAT

        entry = bar.close

        # ── Tier 1: Exhaustion reversal (±ob_extreme) — overrides H1 bias ─
        if crossed_up and was_os_extreme:
            self._sl = entry - atr * self.sl_atr_mult
            self._tp = entry + atr * self.tp_atr_mult
            return Signal.LONG

        if crossed_down and was_ob_extreme:
            self._sl = entry + atr * self.sl_atr_mult
            self._tp = entry - atr * self.tp_atr_mult
            return Signal.SHORT

        # ── Tier 2: Moderate OB/OS reversal (±ob_moderate + H1 bias) ──────
        if crossed_up and was_os_moderate and self._h1_bias == "BULL":
            self._sl = entry - atr * self.sl_atr_mult
            self._tp = entry + atr * self.tp_atr_mult
            return Signal.LONG

        if crossed_down and was_ob_moderate and self._h1_bias == "BEAR":
            self._sl = entry + atr * self.sl_atr_mult
            self._tp = entry - atr * self.tp_atr_mult
            return Signal.SHORT

        # ── Tier 3: Standard crossover (H1 bias, not in OB/OS zone) ───────
        if crossed_up and self._h1_bias == "BULL" and tsi < self.ob_moderate:
            self._sl = entry - atr * self.sl_atr_mult
            self._tp = entry + atr * self.tp_atr_mult
            return Signal.LONG

        if crossed_down and self._h1_bias == "BEAR" and tsi > -self.ob_moderate:
            self._sl = entry + atr * self.sl_atr_mult
            self._tp = entry - atr * self.tp_atr_mult
            return Signal.SHORT

        return Signal.FLAT
