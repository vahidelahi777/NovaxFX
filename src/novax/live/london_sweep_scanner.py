"""LondonSweepScanner — replays LondonOpenSweep on a 1H bar slice.

A self-contained scanner parallel to MultiTFScanner. The daemon runs both;
each fires independently. LondonSweepScanner fires daily (London session);
MultiTFScanner fires on 4H/1H/15M confluence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..data_sources import Bar
from ..engine import Position, Signal
from ..strategies.london_sweep import LondonOpenSweep

__all__ = ["LondonSweepScanner", "SweepScanResult"]

_FLAT_POS = Position(direction="FLAT")


@dataclass(frozen=True)
class SweepScanResult:
    symbol: str
    signal: Signal           # LONG | SHORT | FLAT
    confluence: bool         # True when signal != FLAT
    direction: Signal        # same as signal
    entry_price: float | None
    sl: float | None
    tp: float | None
    asian_high: float | None
    asian_low: float | None
    high_vol_skip: bool      # True when vol filter suppressed a potential sweep
    scanned_at: datetime


def _flat_result(symbol: str) -> SweepScanResult:
    return SweepScanResult(
        symbol=symbol,
        signal=Signal.FLAT,
        confluence=False,
        direction=Signal.FLAT,
        entry_price=None,
        sl=None,
        tp=None,
        asian_high=None,
        asian_low=None,
        high_vol_skip=False,
        scanned_at=datetime.fromtimestamp(0, tz=UTC),
    )


class LondonSweepScanner:
    """Replay LondonOpenSweep bar-by-bar and return the last-bar result.

    Args:
        symbol:        Instrument name, e.g. "XAUUSD".
        strategy_params: Keyword args forwarded to LondonOpenSweep.__init__.
    """

    def __init__(
        self,
        symbol: str = "XAUUSD",
        strategy_params: dict[str, Any] | None = None,
    ) -> None:
        self._symbol = symbol
        self._params: dict[str, Any] = strategy_params or {}

    def scan(self, bars_1h: list[Bar]) -> SweepScanResult:
        """Replay the strategy on *bars_1h* and return the result for the last bar.

        Always creates a fresh strategy instance so the scanner is stateless
        across calls (the caller passes a rolling lookback window each time).
        """
        if len(bars_1h) < 2:
            return _flat_result(self._symbol)

        strat = LondonOpenSweep(**self._params)
        last_signal = Signal.FLAT

        for i, _bar in enumerate(bars_1h):
            from ..engine import BarView  # local to avoid circular at module level
            view = BarView(bars=tuple(bars_1h[: i + 1]))
            last_signal = strat.on_bar(view, _FLAT_POS)

        last_bar = bars_1h[-1]
        ts = last_bar.ts if last_bar.ts.tzinfo is not None else last_bar.ts.replace(tzinfo=UTC)

        return SweepScanResult(
            symbol=self._symbol,
            signal=last_signal,
            confluence=last_signal != Signal.FLAT,
            direction=last_signal,
            entry_price=last_bar.close if last_signal != Signal.FLAT else None,
            sl=strat._sl,   # noqa: SLF001
            tp=strat._tp,   # noqa: SLF001
            asian_high=strat._asian_high,  # noqa: SLF001
            asian_low=strat._asian_low,    # noqa: SLF001
            high_vol_skip=False,  # suppression is handled inside the strategy
            scanned_at=ts,
        )
