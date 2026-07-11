"""Parquet-based Bar storage using PyArrow.

Storage layout:
  {root}/{symbol}/{timeframe}/{year}/{month:02d}.parquet

Each file contains all bars for one calendar month, sorted by timestamp.
Compression: snappy. Schema: see _BAR_SCHEMA below.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from ...data_sources import Bar
from ...instruments import get_instrument

__all__ = ["ParquetStore"]

_BAR_SCHEMA: Any = pa.schema(
    [
        # Stored as plain TIMESTAMP (no tz) so DuckDB doesn't require pytz.
        # All values are UTC by invariant; UTC is reattached on read.
        pa.field("ts", pa.timestamp("us")),
        pa.field("open", pa.float64()),
        pa.field("high", pa.float64()),
        pa.field("low", pa.float64()),
        pa.field("close", pa.float64()),
        pa.field("volume", pa.float64()),
        pa.field("bid", pa.float64()),
        pa.field("ask", pa.float64()),
        pa.field("spread", pa.float64()),
        pa.field("source", pa.string()),
    ]
)


class ParquetStore:
    """Read/write bars as monthly Parquet files under a root directory."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def bar_path(self, symbol: str, timeframe: str, year: int, month: int) -> Path:
        canonical = get_instrument(symbol).symbol  # "EUR/USD", "XAU/USD", etc.
        return self.root / canonical.lower() / timeframe / str(year) / f"{month:02d}.parquet"

    def write_bars(self, symbol: str, timeframe: str, bars: Sequence[Bar]) -> None:
        """Write bars to monthly Parquet files.

        Bars are grouped by calendar month and each group is written to its own
        file. Existing monthly files are overwritten. Input need not be sorted.
        """
        sorted_bars = sorted(bars, key=lambda b: b.ts)
        for (year, month), group_iter in itertools.groupby(
            sorted_bars, key=lambda b: (b.ts.year, b.ts.month)
        ):
            group = list(group_iter)
            path = self.bar_path(symbol, timeframe, year, month)
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_parquet(group, path)

    def read_bars(self, symbol: str, timeframe: str, year: int, month: int) -> list[Bar]:
        """Read all bars from a single monthly Parquet file. Returns [] if absent."""
        path = self.bar_path(symbol, timeframe, year, month)
        if not path.exists():
            return []
        return _read_parquet(path)


def _write_parquet(bars: list[Bar], path: Path) -> None:
    table: Any = pa.table(
        {
            "ts": pa.array(
                # Strip timezone before storage; UTC is restored on read.
                [b.ts.replace(tzinfo=None) for b in bars],
                type=pa.timestamp("us"),
            ),
            "open": [b.open for b in bars],
            "high": [b.high for b in bars],
            "low": [b.low for b in bars],
            "close": [b.close for b in bars],
            "volume": [b.volume for b in bars],
            "bid": [b.bid for b in bars],
            "ask": [b.ask for b in bars],
            "spread": [b.spread for b in bars],
            "source": [b.source for b in bars],
        },
        schema=_BAR_SCHEMA,
    )
    pq.write_table(table, path, compression="snappy")  # type: ignore[no-untyped-call]


def _read_parquet(path: Path) -> list[Bar]:
    table: Any = pq.read_table(path, schema=_BAR_SCHEMA)  # type: ignore[no-untyped-call]
    ts_col: list[Any] = table.column("ts").to_pylist()
    open_col: list[Any] = table.column("open").to_pylist()
    high_col: list[Any] = table.column("high").to_pylist()
    low_col: list[Any] = table.column("low").to_pylist()
    close_col: list[Any] = table.column("close").to_pylist()
    volume_col: list[Any] = table.column("volume").to_pylist()
    bid_col: list[Any] = table.column("bid").to_pylist()
    ask_col: list[Any] = table.column("ask").to_pylist()
    spread_col: list[Any] = table.column("spread").to_pylist()
    source_col: list[Any] = table.column("source").to_pylist()

    bars: list[Bar] = []
    for i, raw_ts in enumerate(ts_col):
        ts: datetime = raw_ts if raw_ts.tzinfo is not None else raw_ts.replace(tzinfo=UTC)
        bid_v: float | None = float(bid_col[i]) if bid_col[i] is not None else None
        ask_v: float | None = float(ask_col[i]) if ask_col[i] is not None else None
        spr_v: float | None = float(spread_col[i]) if spread_col[i] is not None else None
        src: str = str(source_col[i]) if source_col[i] is not None else "dukascopy"
        bars.append(
            Bar(
                ts=ts,
                open=float(open_col[i]),
                high=float(high_col[i]),
                low=float(low_col[i]),
                close=float(close_col[i]),
                volume=float(volume_col[i]) if volume_col[i] is not None else 0.0,
                bid=bid_v,
                ask=ask_v,
                spread=spr_v,
                source=src,
            )
        )
    return bars
