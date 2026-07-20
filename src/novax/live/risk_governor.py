"""RiskGovernor — hard, persisted, latching daily loss limit.

Trading day rolls at 17:00 America/New_York (standard NYSE close).
State is atomically written to JSON (tmp + os.replace pattern).

Fail-safe: a corrupt / unreadable ledger file loads as halted=True
so the daemon blocks new trades until a human resets the file.
"""

from __future__ import annotations

import dataclasses
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo

__all__ = ["RiskGovernor", "RiskLedger", "trading_day"]

_NY: tzinfo = ZoneInfo("America/New_York")
_ROLL_HOUR: int = 17  # 17:00 NY = trading-day boundary


def trading_day(now: datetime) -> str:
    """Return the current trading-day label as 'YYYY-MM-DD'.

    The day rolls at 17:00 America/New_York; times before that
    still belong to the previous calendar date's session.
    """
    ny = now.astimezone(_NY)
    if ny.hour < _ROLL_HOUR:
        # Before 17:00 NY — still the same trading day as yesterday
        from datetime import timedelta

        ny = ny - timedelta(days=1)
    return ny.strftime("%Y-%m-%d")


@dataclass
class RiskLedger:
    day: str = ""
    realized_r: float = 0.0
    trades: int = 0
    halted: bool = False
    halted_at: str | None = None
    halt_reason: str | None = None
    history: dict[str, float] = field(default_factory=dict)


_CORRUPT_LEDGER = RiskLedger(
    halted=True,
    halt_reason="ledger corrupt — manual reset required",
)


class RiskGovernor:
    """Enforce a daily loss limit in R-multiples.

    Args:
        state_path:       JSON file for ledger persistence.
        max_daily_loss_r: Halt when realized_r <= -max_daily_loss_r (default 3.0).
        max_daily_trades: Halt when trades >= max_daily_trades (default 6).
    """

    def __init__(
        self,
        state_path: Path,
        max_daily_loss_r: float = 3.0,
        max_daily_trades: int = 6,
    ) -> None:
        self._path = state_path
        self._max_loss_r = max_daily_loss_r
        self._max_trades = max_daily_trades
        self._ledger: RiskLedger = self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_halted(self, now: datetime | None = None) -> bool:
        """Roll the day if needed, then return whether trading is halted."""
        if now is None:
            now = datetime.now(tz=UTC)
        self._maybe_roll(now)
        return self._ledger.halted

    def record_fill(self, pnl_r: float, now: datetime | None = None) -> bool:
        """Record a closed trade's P&L in R-multiples.

        Returns True if this fill tripped the halt (first trip only).
        """
        if now is None:
            now = datetime.now(tz=UTC)
        self._maybe_roll(now)
        led = self._ledger
        if led.halted:
            return False

        led.realized_r += pnl_r
        led.trades += 1

        tripped = False
        if led.realized_r <= -self._max_loss_r:
            led.halted = True
            led.halted_at = now.isoformat()
            led.halt_reason = (
                f"daily loss limit hit: realized_r={led.realized_r:.2f}R <= -{self._max_loss_r}R"
            )
            tripped = True
        elif led.trades >= self._max_trades:
            led.halted = True
            led.halted_at = now.isoformat()
            led.halt_reason = f"max daily trades hit: {led.trades} >= {self._max_trades}"
            tripped = True

        self._save()
        return tripped

    @property
    def ledger(self) -> RiskLedger:
        return self._ledger

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _maybe_roll(self, now: datetime) -> None:
        today = trading_day(now)
        led = self._ledger
        if led.day == today:
            return
        # Corrupt ledger requires manual reset — never auto-roll it.
        if led.halt_reason and "corrupt" in led.halt_reason:
            return
        # New trading day — persist the closed day's R into history, then reset.
        if led.day:
            led.history[led.day] = led.realized_r
        led.day = today
        led.realized_r = 0.0
        led.trades = 0
        led.halted = False
        led.halted_at = None
        led.halt_reason = None
        self._save()

    def _load(self) -> RiskLedger:
        if not self._path.exists():
            return RiskLedger()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return RiskLedger(**raw)
        except Exception:  # noqa: BLE001
            return _CORRUPT_LEDGER

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(dataclasses.asdict(self._ledger), indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, self._path)
