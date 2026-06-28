"""Data-source seams for Phase 0 — local/in-memory only, no network.

Real OANDA / Dukascopy / TwelveData adapters are deferred (see
docs/phase-0/data-source-decision.md). The provider classes here exist only to
mark the integration seam; they raise NotImplementedError so nothing accidentally
depends on a service in Phase 0.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

UTC = UTC

__all__ = [
    "Bar",
    "DataSource",
    "InMemoryDataSource",
    "OandaDataSource",
    "DukascopyDataSource",
    "TwelveDataSource",
]


@dataclass(frozen=True, slots=True)
class Bar:
    """A single OHLC bar. `ts` is the bar-open instant, tz-aware UTC.

    `volume` is TICK volume (FX has no central volume). `spread` is in price units
    (ask - bid) where available.
    """

    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    bid: float | None = None
    ask: float | None = None
    spread: float | None = None
    source: str = "unknown"

    def __post_init__(self) -> None:
        if self.ts.tzinfo is None:
            raise ValueError("Bar.ts must be tz-aware UTC (naive rejected)")
        # Normalize to UTC on a frozen dataclass.
        object.__setattr__(self, "ts", self.ts.astimezone(UTC))
        if not (self.low <= self.open <= self.high and self.low <= self.close <= self.high):
            raise ValueError(f"OHLC inconsistent at {self.ts.isoformat()}")
        if self.bid is not None and self.ask is not None and self.ask < self.bid:
            raise ValueError(f"ask < bid at {self.ts.isoformat()}")


@runtime_checkable
class DataSource(Protocol):
    """Minimal read interface every provider must satisfy."""

    name: str

    def get_bars(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> list[Bar]:
        """Return bars with ts in [start, end), ascending. Inputs must be UTC-aware."""
        ...


@dataclass(slots=True)
class InMemoryDataSource:
    """Backtest/dev source backed by a preloaded dict of bars. No I/O."""

    name: str = "memory"
    _bars: dict[tuple[str, str], list[Bar]] = field(default_factory=dict)

    def load(self, symbol: str, timeframe: str, bars: list[Bar]) -> None:
        ordered = sorted(bars, key=lambda b: b.ts)
        self._bars[(symbol, timeframe)] = ordered

    def get_bars(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> list[Bar]:
        for label, dt in (("start", start), ("end", end)):
            if dt.tzinfo is None:
                raise ValueError(f"{label} must be tz-aware UTC")
        s, e = start.astimezone(UTC), end.astimezone(UTC)
        return [b for b in self._bars.get((symbol, timeframe), []) if s <= b.ts < e]


class _DeferredProvider:
    """Base for not-yet-implemented network providers."""

    name = "deferred"

    def get_bars(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> list[Bar]:
        raise NotImplementedError(
            f"{type(self).__name__} is deferred in Phase 0 — no external services. "
            "See docs/phase-0/data-source-decision.md."
        )


class OandaDataSource(_DeferredProvider):
    name = "oanda"


class DukascopyDataSource(_DeferredProvider):
    name = "dukascopy"


class TwelveDataSource(_DeferredProvider):
    name = "twelvedata"
