"""DuckDB-based bar loading: query Parquet files and return list[Bar].

DuckDB is used for its glob-pattern SQL interface over multiple Parquet files,
enabling efficient date-range queries without loading entire months into memory.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from ...data_sources import Bar

__all__ = ["load_bars"]


def load_bars(
    root: Path,
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
) -> list[Bar]:
    """Load bars within [start, end] from Parquet files via DuckDB.

    Args:
        root: Root directory passed to ParquetStore (parent of the symbol folder).
        symbol: Instrument symbol, e.g. "EURUSD".
        timeframe: Timeframe label, e.g. "1m".
        start: Inclusive lower bound (UTC-aware).
        end: Inclusive upper bound (UTC-aware).

    Returns:
        List of Bar objects sorted by timestamp ascending. Empty if no files exist
        or no bars fall within the requested range.

    Raises:
        ValueError: If start or end is not tz-aware.
    """
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be tz-aware UTC")

    data_dir = root / symbol.lower() / timeframe
    parquet_files = list(data_dir.glob("*/*.parquet"))
    if not parquet_files:
        return []

    # DuckDB glob: {data_dir}/*/*.parquet covers {year}/{month:02d}.parquet
    pattern = str(data_dir / "*" / "*.parquet").replace("\\", "/")

    # ts column is stored as plain TIMESTAMP (no tz) to avoid pytz dependency in DuckDB.
    # All stored values are UTC; bounds are compared as naive UTC strings.
    start_s = start.strftime("%Y-%m-%d %H:%M:%S")
    end_s = end.strftime("%Y-%m-%d %H:%M:%S")
    conn: Any = duckdb.connect(":memory:")
    try:
        query = f"""
            SELECT ts, open, high, low, close, volume, bid, ask, spread, source
            FROM read_parquet('{pattern}')
            WHERE ts >= '{start_s}'::TIMESTAMP AND ts <= '{end_s}'::TIMESTAMP
            ORDER BY ts
        """
        rows: list[Any] = conn.execute(query).fetchall()
    finally:
        conn.close()

    bars: list[Bar] = []
    for row in rows:
        raw_ts: Any = row[0]
        ts: datetime = (
            raw_ts
            if isinstance(raw_ts, datetime) and raw_ts.tzinfo is not None
            else (
                raw_ts.replace(tzinfo=UTC)
                if isinstance(raw_ts, datetime)
                else datetime.fromisoformat(str(raw_ts)).replace(tzinfo=UTC)
            )
        )
        bid_v: float | None = float(row[6]) if row[6] is not None else None
        ask_v: float | None = float(row[7]) if row[7] is not None else None
        spr_v: float | None = float(row[8]) if row[8] is not None else None
        src: str = str(row[9]) if row[9] is not None else "dukascopy"
        bars.append(
            Bar(
                ts=ts,
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]) if row[5] is not None else 0.0,
                bid=bid_v,
                ask=ask_v,
                spread=spr_v,
                source=src,
            )
        )
    return bars
