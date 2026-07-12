"""Persistent paper trader — detects signal transitions and tracks virtual P&L.

One call to update() per H4 bar close. State is atomically persisted to a JSON
file so the process can be restarted without losing position context.
"""

from __future__ import annotations

import dataclasses
import json
import os
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from ..data_sources import Bar
from ..engine import Signal
from .signal_scanner import ScanResult

__all__ = ["EventKind", "PaperEvent", "PaperPosition", "PaperTrader"]


class EventKind(StrEnum):
    ENTRY_LONG = "ENTRY_LONG"
    ENTRY_SHORT = "ENTRY_SHORT"
    EXIT_TP = "EXIT_TP"
    EXIT_SL = "EXIT_SL"
    EXIT_SIGNAL = "EXIT_SIGNAL"
    HOLD = "HOLD"
    NO_CHANGE = "NO_CHANGE"


@dataclass(frozen=True)
class PaperEvent:
    kind: EventKind
    ts: datetime
    symbol: str
    signal: Signal
    price: float
    sl: float | None
    tp: float | None
    pnl: float | None
    cumulative_pnl: float


@dataclass
class PaperPosition:
    direction: str = "FLAT"
    entry_price: float | None = None
    entry_ts: str | None = None
    sl: float | None = None
    tp: float | None = None
    cumulative_pnl: float = 0.0
    trade_count: int = 0


class PaperTrader:
    """Persistent paper trader. One call to update() per scanner run."""

    def __init__(self, state_path: Path) -> None:
        self._path = state_path
        self._pos: PaperPosition = self._load()

    def _load(self) -> PaperPosition:
        if not self._path.exists():
            return PaperPosition()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return PaperPosition(**data)
        except (json.JSONDecodeError, TypeError, KeyError):
            return PaperPosition()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(dataclasses.asdict(self._pos), indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, self._path)

    @property
    def position(self) -> PaperPosition:
        return self._pos

    def update(self, result: ScanResult, last_bar: Bar) -> PaperEvent:
        """Advance paper state by one scanner snapshot.

        Args:
            result:   Latest ScanResult from SignalScanner.scan().
            last_bar: The most recent Bar the scanner evaluated last.
                      Used to detect SL/TP breach via bar.low/bar.high.

        Returns a PaperEvent describing what changed. Always saves state.
        """
        pos = self._pos
        cur_dir = pos.direction
        new_sig = result.signal
        ts = last_bar.ts
        price = last_bar.close

        # --- SL/TP pre-check: detect breach on every bar, even during HOLD ---
        if cur_dir == "LONG":
            if pos.sl is not None and last_bar.low <= pos.sl:
                return self._close_long(pos, result, last_bar, ts, price)
            if pos.tp is not None and last_bar.high >= pos.tp:
                return self._close_long(pos, result, last_bar, ts, price)
        elif cur_dir == "SHORT":
            if pos.sl is not None and last_bar.high >= pos.sl:
                return self._close_short(pos, result, last_bar, ts, price)
            if pos.tp is not None and last_bar.low <= pos.tp:
                return self._close_short(pos, result, last_bar, ts, price)

        # --- FLAT cases ---
        if cur_dir == "FLAT":
            if new_sig == Signal.FLAT:
                self._save()
                return PaperEvent(
                    kind=EventKind.NO_CHANGE,
                    ts=ts,
                    symbol=result.symbol,
                    signal=Signal.FLAT,
                    price=price,
                    sl=None,
                    tp=None,
                    pnl=None,
                    cumulative_pnl=pos.cumulative_pnl,
                )
            if new_sig == Signal.LONG:
                pos.direction = "LONG"
                pos.entry_price = price
                pos.entry_ts = ts.isoformat()
                pos.sl = result.sl
                pos.tp = result.tp
                self._save()
                return PaperEvent(
                    kind=EventKind.ENTRY_LONG,
                    ts=ts,
                    symbol=result.symbol,
                    signal=Signal.LONG,
                    price=price,
                    sl=result.sl,
                    tp=result.tp,
                    pnl=None,
                    cumulative_pnl=pos.cumulative_pnl,
                )
            # new_sig == Signal.SHORT
            pos.direction = "SHORT"
            pos.entry_price = price
            pos.entry_ts = ts.isoformat()
            pos.sl = result.sl
            pos.tp = result.tp
            self._save()
            return PaperEvent(
                kind=EventKind.ENTRY_SHORT,
                ts=ts,
                symbol=result.symbol,
                signal=Signal.SHORT,
                price=price,
                sl=result.sl,
                tp=result.tp,
                pnl=None,
                cumulative_pnl=pos.cumulative_pnl,
            )

        # --- HOLD cases ---
        if cur_dir == "LONG" and new_sig == Signal.LONG:
            self._save()
            return PaperEvent(
                kind=EventKind.HOLD,
                ts=ts,
                symbol=result.symbol,
                signal=Signal.LONG,
                price=price,
                sl=pos.sl,
                tp=pos.tp,
                pnl=None,
                cumulative_pnl=pos.cumulative_pnl,
            )

        if cur_dir == "SHORT" and new_sig == Signal.SHORT:
            self._save()
            return PaperEvent(
                kind=EventKind.HOLD,
                ts=ts,
                symbol=result.symbol,
                signal=Signal.SHORT,
                price=price,
                sl=pos.sl,
                tp=pos.tp,
                pnl=None,
                cumulative_pnl=pos.cumulative_pnl,
            )

        # --- Exit cases (LONG→FLAT/SHORT, SHORT→FLAT/LONG, direction flips) ---
        # Direction flip is treated as exit-first; caller sees FLAT on next update().
        if cur_dir == "LONG":
            return self._close_long(pos, result, last_bar, ts, price)
        return self._close_short(pos, result, last_bar, ts, price)

    def _close_long(
        self,
        pos: PaperPosition,
        result: ScanResult,
        last_bar: Bar,
        ts: datetime,
        price: float,
    ) -> PaperEvent:
        entry_price = pos.entry_price if pos.entry_price is not None else price
        pnl = price - entry_price
        if pos.sl is not None and last_bar.low <= pos.sl:
            kind = EventKind.EXIT_SL
        elif pos.tp is not None and last_bar.high >= pos.tp:
            kind = EventKind.EXIT_TP
        else:
            kind = EventKind.EXIT_SIGNAL
        pos.cumulative_pnl += pnl
        pos.trade_count += 1
        pos.direction = "FLAT"
        pos.entry_price = None
        pos.entry_ts = None
        pos.sl = None
        pos.tp = None
        self._save()
        return PaperEvent(
            kind=kind,
            ts=ts,
            symbol=result.symbol,
            signal=Signal.FLAT,
            price=price,
            sl=None,
            tp=None,
            pnl=pnl,
            cumulative_pnl=pos.cumulative_pnl,
        )

    def _close_short(
        self,
        pos: PaperPosition,
        result: ScanResult,
        last_bar: Bar,
        ts: datetime,
        price: float,
    ) -> PaperEvent:
        entry_price = pos.entry_price if pos.entry_price is not None else price
        pnl = entry_price - price
        if pos.sl is not None and last_bar.high >= pos.sl:
            kind = EventKind.EXIT_SL
        elif pos.tp is not None and last_bar.low <= pos.tp:
            kind = EventKind.EXIT_TP
        else:
            kind = EventKind.EXIT_SIGNAL
        pos.cumulative_pnl += pnl
        pos.trade_count += 1
        pos.direction = "FLAT"
        pos.entry_price = None
        pos.entry_ts = None
        pos.sl = None
        pos.tp = None
        self._save()
        return PaperEvent(
            kind=kind,
            ts=ts,
            symbol=result.symbol,
            signal=Signal.FLAT,
            price=price,
            sl=None,
            tp=None,
            pnl=pnl,
            cumulative_pnl=pos.cumulative_pnl,
        )
