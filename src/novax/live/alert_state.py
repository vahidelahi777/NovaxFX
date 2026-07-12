"""Persistent alert de-duplication state."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

__all__ = ["AlertState", "AlertStateStore"]


@dataclass
class AlertState:
    """Last-sent alert direction and the H4 bar that triggered it."""

    direction: str = "FLAT"  # "LONG" | "SHORT" | "FLAT"
    h4_bar_ts: str = ""      # ISO8601 of the H4 bar ts

    def is_duplicate(self, direction: str, h4_bar_ts: datetime) -> bool:
        """Return True if this exact alert was already sent."""
        return self.direction == direction and self.h4_bar_ts == h4_bar_ts.isoformat()

    def update(self, direction: str, h4_bar_ts: datetime) -> None:
        self.direction = direction
        self.h4_bar_ts = h4_bar_ts.isoformat()


class AlertStateStore:
    """Read/write AlertState as a JSON file with atomic saves."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> AlertState:
        """Read state from disk; return a blank AlertState on missing or corrupt file."""
        if not self._path.exists():
            return AlertState()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return AlertState(
                direction=str(data.get("direction", "FLAT")),
                h4_bar_ts=str(data.get("h4_bar_ts", "")),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return AlertState()

    def save(self, state: AlertState) -> None:
        """Write state to disk atomically via a .tmp file and os.replace."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
        os.replace(tmp, self._path)
