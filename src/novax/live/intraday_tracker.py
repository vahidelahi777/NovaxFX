"""Compute intraday and weekly high/low levels from a bar series."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ..data_sources import Bar

__all__ = ["BarLevels", "compute_day_levels", "compute_week_levels", "current_week_start"]


@dataclass(frozen=True)
class BarLevels:
    """Highest high and lowest low across a set of bars."""

    label: str  # e.g. "2026-07-14" or "2026-07-07/2026-07-11"
    high: float
    low: float
    bar_count: int


def compute_day_levels(bars: list[Bar], date_utc: datetime | None = None) -> BarLevels | None:
    """Return H/L for bars whose ts falls on *date_utc* (UTC).

    *date_utc* defaults to today UTC.  Returns None when no bars match.
    """
    ref = (date_utc or datetime.now(tz=UTC)).astimezone(UTC)
    date_str = ref.strftime("%Y-%m-%d")
    day_bars = [b for b in bars if b.ts.astimezone(UTC).strftime("%Y-%m-%d") == date_str]
    if not day_bars:
        return None
    return BarLevels(
        label=date_str,
        high=max(b.high for b in day_bars),
        low=min(b.low for b in day_bars),
        bar_count=len(day_bars),
    )


def current_week_start(now: datetime) -> datetime:
    """Return Monday 00:00:00 UTC of the week containing *now*."""
    now_utc = now.astimezone(UTC)
    days_since_monday = now_utc.weekday()  # 0=Mon … 6=Sun
    monday = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    monday -= timedelta(days=days_since_monday)
    return monday


def compute_week_levels(bars: list[Bar], week_start: datetime) -> BarLevels | None:
    """Return H/L for bars whose ts >= *week_start* UTC.

    *week_start* is typically the Monday 00:00 UTC returned by
    ``current_week_start()``.  Returns None when no bars match.
    """
    ws = week_start.astimezone(UTC)
    week_bars = [b for b in bars if b.ts.astimezone(UTC) >= ws]
    if not week_bars:
        return None
    label = ws.strftime("%Y-%m-%d")
    return BarLevels(
        label=label,
        high=max(b.high for b in week_bars),
        low=min(b.low for b in week_bars),
        bar_count=len(week_bars),
    )
