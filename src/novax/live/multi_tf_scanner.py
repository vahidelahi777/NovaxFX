"""Multi-timeframe signal scanner: 4H WeeklyBOSRetest + 1H GoldPullback + 15M EMACross."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..data_sources import Bar
from ..engine import BarView, Position, Signal
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
    sl: float | None  # SL price — only set by WeeklyBOSRetest on 4H
    tp: float | None  # TP price — only set by WeeklyBOSRetest on 4H
    n_bars_used: int


@dataclass(frozen=True)
class MultiTFScanResult:
    symbol: str
    h4: TFSignal
    h1: TFSignal
    m15: TFSignal
    confluence: bool  # h4 != FLAT and h1.signal == h4.signal
    direction: Signal  # h4.signal when confluence else FLAT
    entry_price: float | None  # h4 last_close when confluence else None
    sl: float | None  # from h4 (WeeklyBOSRetest internal)
    tp: float | None  # from h4 (WeeklyBOSRetest internal)
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
        sl=None,
        tp=None,
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

    4H  — WeeklyBOSRetest (institutional BOS bias + SL/TP)
    1H  — GoldPullback    (trend confirmation)
    15M — EMACross        (entry timing; default fast=9, slow=21)

    Confluence fires when 4H is non-FLAT and 1H agrees on the same direction.
    15M is informational and does not gate the alert.
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
        h1 = _replay_h1(bars_h1, self._h1_params)
        m15 = _replay_m15(bars_m15, self._m15_params)

        confluence = h4.signal != Signal.FLAT and h1.signal == h4.signal
        direction = h4.signal if confluence else Signal.FLAT
        entry_price = bars_h4[-1].close if confluence else None
        sl = h4.sl if confluence else None
        tp = h4.tp if confluence else None

        return MultiTFScanResult(
            symbol=self._symbol,
            h4=h4,
            h1=h1,
            m15=m15,
            confluence=confluence,
            direction=direction,
            entry_price=entry_price,
            sl=sl,
            tp=tp,
            scanned_at=datetime.now(tz=UTC),
        )
