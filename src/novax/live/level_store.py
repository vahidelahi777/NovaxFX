"""Append-only JSONL store for weekly price levels and signal records.

Each record is written as a single JSON line.  Reads scan the whole file;
writes use open("a") which is atomic for lines < PIPE_BUF on POSIX.
Single-writer only (the daemon is single-threaded within each process).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

__all__ = ["LevelStore", "SignalRecord", "WeeklyLevel"]


@dataclass
class WeeklyLevel:
    """High/low levels for one trading week."""

    week_start: str  # "YYYY-MM-DD" — Monday of the week
    symbol: str
    prev_high: float | None  # previous week's highest high
    prev_low: float | None  # previous week's lowest low
    week_high: float | None  # current week's highest high so far
    week_low: float | None  # current week's lowest low so far
    recorded_at: str  # ISO UTC datetime when this record was written


@dataclass
class SignalRecord:
    """One signal observation from the multi-TF scanner."""

    ts: str  # ISO UTC datetime of the scan
    symbol: str
    h4_signal: str  # LONG / SHORT / FLAT
    h1_signal: str
    m15_signal: str
    confluence: bool
    entry_price: float | None
    sl: float | None
    tp: float | None
    source: str  # "15m_scan" | "daily" | "weekly" | "market_open" …


class LevelStore:
    """Append-only JSONL store writing to *path*.

    Both ``WeeklyLevel`` and ``SignalRecord`` records are stored in the same
    file, distinguished by the ``"_type"`` field added on write.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def append_level(self, record: WeeklyLevel) -> None:
        self._append({"_type": "level", **asdict(record)})

    def append_signal(self, record: SignalRecord) -> None:
        self._append({"_type": "signal", **asdict(record)})

    def _append(self, obj: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(obj, ensure_ascii=False)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def load_levels(self) -> list[WeeklyLevel]:
        return [
            WeeklyLevel(**{k: v for k, v in rec.items() if k != "_type"})
            for rec in self._iter_type("level")
        ]

    def load_signals(self) -> list[SignalRecord]:
        return [
            SignalRecord(**{k: v for k, v in rec.items() if k != "_type"})
            for rec in self._iter_type("signal")
        ]

    def _iter_type(self, type_name: str) -> Iterator[dict[str, Any]]:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj: dict[str, Any] = json.loads(raw)
                    if obj.get("_type") == type_name:
                        yield obj
                except json.JSONDecodeError:
                    continue
