"""Multi-timeframe signal scanner: 4H EMA trend + 1H GoldPullback + 15M EMACross.

Confluence definition (v2)
--------------------------
  OLD (too strict): h4.signal != FLAT AND h1.signal == h4.signal
    → required WeeklyBOSRetest (4H) to fire; fires 0-2x per week

  NEW (practical): h4_trend != FLAT AND h1.signal == h4_trend
    → uses EMA50 direction on 4H as trend bias; fires whenever 1H
      GoldPullback agrees with the 4H trend; multiple times per day

  WeeklyBOSRetest is still replayed on 4H and its signal/BOS state
  is preserved in the result for logging and bonus-alert purposes.

SL/TP priority
--------------
  1. h4 WeeklyBOSRetest sl/tp — if BOS fired (high conviction)
  2. h1 GoldPullback sl/tp    — fallback (ATR-based, always present)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..data_sources import Bar
from ..engine import BarView, Position, Signal
from ..indicators import EMAIndicator
from ..strategies.ema_cross import EMACross
from ..strategies.gold_pullback import GoldPullback
from ..strategies.weekly_bos_retest import WeeklyBOSRetest

__all__ = ["MultiTFScanResult", "MultiTFScanner", "TFSignal"]

_FLAT_POS = Position(direction="FLAT")
_M15_DEFAULTS: dict[str, Any] = {"fast": 9, "slow": 21}


@dataclass(frozen=True)
class TFSignal:
    timeframe: str  # "4h" | "1h" | "15min"
    signal: Signal  # LONG | SHORT | FLAT
    last_bar_ts: datetime  # ts of the last bar used
    last_close: float  # close price of the last bar
    sl: float | None  # SL price
    tp: float | None  # TP price
    n_bars_used: int


@dataclass(frozen=True)
class MultiTFScanResult:
    symbol: str
    h4: TFSignal          # WeeklyBOSRetest signal (kept for logging / bonus)
    h4_trend: Signal      # 4H EMA50 trend direction — gates confluence
    h1: TFSignal          # GoldPullback signal
    m15: TFSignal         # EMACross signal (informational)
    confluence: bool      # h4_trend != FLAT and h1.signal == h4_trend
    direction: Signal     # h4_trend when confluence else FLAT
    entry_price: float | None  # h1 last_close when confluence else None
    sl: float | None      # h4 BOS sl if available, else h1 ATR sl
    tp: float | None      # h4 BOS tp if available, else h1 ATR tp
    scanned_at: datetime  # UTC timestamp of the scan


def _flat_signal(timeframe: str, ts: datetime, close: float) -> TFSignal:
    return TFSignal(
        timeframe=timeframe,
        signal=Signal.FLAT,
        last_bar_ts=ts,
        last_close=close,
        sl=None,
        tp=None,
        n_bars_used=0,
    )


def _flat_result(symbol: str) -> MultiTFScanResult:
    sentinel_ts = datetime.fromtimestamp(0, tz=UTC)
    empty = _flat_signal("", sentinel_ts, 0.0)
    return MultiTFScanResult(
        symbol=symbol,
        h4=empty,
        h4_trend=Signal.FLAT,
        h1=empty,
        m15=empty,
        confluence=False,
        direction=Signal.FLAT,
        entry_price=None,
        sl=None,
        tp=None,
        scanned_at=datetime.now(tz=UTC),
    )


def _replay_h4(bars: list[Bar], params: dict[str, Any]) -> TFSignal:
    strat = WeeklyBOSRetest(**params)
    last_signal = Signal.FLAT
    for i in range(len(bars)):
        view = BarView(bars=tuple(bars[: i + 1]))
        last_signal = strat.on_bar(view, _FLAT_POS)
    return TFSignal(
        timeframe="4h",
        signal=last_signal,
        last_bar_ts=bars[-1].ts,
        last_close=bars[-1].close,
        sl=strat._sl,  # noqa: SLF001
        tp=strat._tp,  # noqa: SLF001
        n_bars_used=len(bars),
    )


def _h4_ema_trend(bars: list[Bar]) -> Signal:
    """Compute 4H EMA50 trend direction with slope confirmation.

    Requires both price > EMA50 AND EMA50 sloping upward (or vice versa).
    A rising price above a flat EMA = choppy market → FLAT.
    Slope is measured over the last 5 bars (20H on 4H chart).
    Minimum slope: 0.5 pip per bar to filter ranging markets.
    """
    ind = EMAIndicator(50)
    ema_history: list[float] = []
    for b in bars:
        val = ind.update(b.close)
        if val is not None:
            ema_history.append(val)

    if len(ema_history) < 6:
        return Signal.FLAT

    ema_now = ema_history[-1]
    ema_5ago = ema_history[-6]
    slope_per_bar = (ema_now - ema_5ago) / 5   # pips per 4H bar

    last_close = bars[-1].close
    _MIN_SLOPE = 0.5   # 0.5 pip/bar minimum slope (gold pip = $0.10)

    if last_close > ema_now and slope_per_bar > _MIN_SLOPE:
        return Signal.LONG
    if last_close < ema_now and slope_per_bar < -_MIN_SLOPE:
        return Signal.SHORT
    return Signal.FLAT


def _replay_h1(bars: list[Bar], params: dict[str, Any]) -> TFSignal:
    strat = GoldPullback(**params)
    last_signal = Signal.FLAT
    for i in range(len(bars)):
        view = BarView(bars=tuple(bars[: i + 1]))
        last_signal = strat.on_bar(view, _FLAT_POS)
    return TFSignal(
        timeframe="1h",
        signal=last_signal,
        last_bar_ts=bars[-1].ts,
        last_close=bars[-1].close,
        sl=strat._sl,  # noqa: SLF001
        tp=strat._tp,  # noqa: SLF001
        n_bars_used=len(bars),
    )


def _replay_m15(bars: list[Bar], params: dict[str, Any]) -> TFSignal:
    merged = {**_M15_DEFAULTS, **params}
    strat = EMACross(**merged)
    last_signal = Signal.FLAT
    for i in range(len(bars)):
        view = BarView(bars=tuple(bars[: i + 1]))
        last_signal = strat.on_bar(view, _FLAT_POS)
    return TFSignal(
        timeframe="15min",
        signal=last_signal,
        last_bar_ts=bars[-1].ts,
        last_close=bars[-1].close,
        sl=None,
        tp=None,
        n_bars_used=len(bars),
    )


class MultiTFScanner:
    """Run three strategies on their respective bar series and return a confluent signal.

    4H  — WeeklyBOSRetest (institutional BOS signal, kept for bonus logging)
          EMA50 direction used for the actual confluence gate
    1H  — GoldPullback    (trend confirmation + ATR SL/TP)
    15M — EMACross        (entry timing; default fast=9, slow=21; informational)

    Confluence fires when 4H EMA50 trend is non-FLAT and 1H agrees on direction.
    """

    def __init__(
        self,
        symbol: str,
        h4_params: dict[str, Any] | None = None,
        h1_params: dict[str, Any] | None = None,
        m15_params: dict[str, Any] | None = None,
    ) -> None:
        self._symbol = symbol
        self._h4_params: dict[str, Any] = h4_params or {}
        self._h1_params: dict[str, Any] = h1_params or {}
        self._m15_params: dict[str, Any] = m15_params or {}

    def scan(
        self,
        bars_h4: list[Bar],
        bars_h1: list[Bar],
        bars_m15: list[Bar],
    ) -> MultiTFScanResult:
        """Replay each bar series through its strategy and return a MultiTFScanResult.

        Returns a fully-FLAT result immediately if any TF has fewer than 2 bars.
        """
        if len(bars_h4) < 2 or len(bars_h1) < 2 or len(bars_m15) < 2:
            return _flat_result(self._symbol)

        h4 = _replay_h4(bars_h4, self._h4_params)
        h4_trend = _h4_ema_trend(bars_h4)
        h1 = _replay_h1(bars_h1, self._h1_params)
        m15 = _replay_m15(bars_m15, self._m15_params)

        # Confluence: 4H EMA trend + 1H GoldPullback agree on direction
        confluence = h4_trend != Signal.FLAT and h1.signal == h4_trend
        direction = h4_trend if confluence else Signal.FLAT
        entry_price = bars_h1[-1].close if confluence else None

        # SL/TP: use BOS levels only when BOS signal agrees with EMA trend direction
        # (prevents a stale SHORT BOS SL/TP being applied to a LONG EMA-trend trade)
        bos_agrees = h4.signal == h4_trend
        sl = (h4.sl if bos_agrees and h4.sl is not None else h1.sl) if confluence else None
        tp = (h4.tp if bos_agrees and h4.tp is not None else h1.tp) if confluence else None

        return MultiTFScanResult(
            symbol=self._symbol,
            h4=h4,
            h4_trend=h4_trend,
            h1=h1,
            m15=m15,
            confluence=confluence,
            direction=direction,
            entry_price=entry_price,
            sl=sl,
            tp=tp,
            scanned_at=datetime.now(tz=UTC),
        )
