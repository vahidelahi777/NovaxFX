"""Append-only JSONL trade journal for paper trading.

Each completed trade (entry ↔ exit pair) is written as one JSON line.
The file is safe to tail, grep, or import into pandas for analysis.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .paper_trader import PaperEvent

__all__ = ["CompletedTrade", "TradeJournal"]


@dataclass(frozen=True)
class CompletedTrade:
    symbol: str
    direction: str          # "LONG" | "SHORT"
    entry_ts: datetime      # tz-aware UTC
    exit_ts: datetime       # tz-aware UTC
    entry_price: float
    exit_price: float
    sl_at_entry: float | None
    tp_at_entry: float | None
    exit_kind: str          # "EXIT_TP" | "EXIT_SL" | "EXIT_SIGNAL"
    pnl: float
    n_bars_held: int        # round((exit_ts - entry_ts).total_seconds() / 14400)


def _to_dict(trade: CompletedTrade) -> dict[str, Any]:
    return {
        "symbol": trade.symbol,
        "direction": trade.direction,
        "entry_ts": trade.entry_ts.isoformat(),
        "exit_ts": trade.exit_ts.isoformat(),
        "entry_price": trade.entry_price,
        "exit_price": trade.exit_price,
        "sl_at_entry": trade.sl_at_entry,
        "tp_at_entry": trade.tp_at_entry,
        "exit_kind": trade.exit_kind,
        "pnl": trade.pnl,
        "n_bars_held": trade.n_bars_held,
    }


def _from_dict(d: dict[str, Any]) -> CompletedTrade:
    return CompletedTrade(
        symbol=str(d["symbol"]),
        direction=str(d["direction"]),
        entry_ts=datetime.fromisoformat(str(d["entry_ts"])).astimezone(UTC),
        exit_ts=datetime.fromisoformat(str(d["exit_ts"])).astimezone(UTC),
        entry_price=float(d["entry_price"]),
        exit_price=float(d["exit_price"]),
        sl_at_entry=float(d["sl_at_entry"]) if d["sl_at_entry"] is not None else None,
        tp_at_entry=float(d["tp_at_entry"]) if d["tp_at_entry"] is not None else None,
        exit_kind=str(d["exit_kind"]),
        pnl=float(d["pnl"]),
        n_bars_held=int(d["n_bars_held"]),
    )


class TradeJournal:
    """Append-only JSONL trade log.

    Each call to record_exit() appends exactly one JSON line. The file can be
    read safely at any time — partial writes are not possible because each line
    is a single write call whose size is well below PIPE_BUF (4 KiB on Linux).
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def record_exit(
        self,
        *,
        symbol: str,
        direction: str,
        entry_price: float,
        entry_ts: str,
        sl_at_entry: float | None,
        tp_at_entry: float | None,
        exit_event: PaperEvent,
    ) -> CompletedTrade:
        """Append one completed trade and return the record."""
        entry_dt = datetime.fromisoformat(entry_ts).astimezone(UTC)
        exit_dt = exit_event.ts
        n_bars = round((exit_dt - entry_dt).total_seconds() / 14400)
        pnl = exit_event.pnl if exit_event.pnl is not None else 0.0

        trade = CompletedTrade(
            symbol=symbol,
            direction=direction,
            entry_ts=entry_dt,
            exit_ts=exit_dt,
            entry_price=entry_price,
            exit_price=exit_event.price,
            sl_at_entry=sl_at_entry,
            tp_at_entry=tp_at_entry,
            exit_kind=exit_event.kind.value,
            pnl=pnl,
            n_bars_held=n_bars,
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(_to_dict(trade)) + "\n")
        return trade

    def load(self) -> list[CompletedTrade]:
        """Read all records. Returns [] if the file is absent or empty."""
        if not self._path.exists():
            return []
        trades: list[CompletedTrade] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                trades.append(_from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
        return trades
