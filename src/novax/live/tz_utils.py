"""Tehran (IRST) timezone display helpers.

Iran Standard Time is always UTC+3:30. Iran does not observe DST.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

__all__ = ["TEHRAN", "fmt_both", "fmt_tehran", "fmt_utc"]

TEHRAN = ZoneInfo("Asia/Tehran")
_UTC = ZoneInfo("UTC")


def fmt_tehran(dt: datetime) -> str:
    """Return *dt* formatted as Tehran local time.

    Example: '2026-07-14 03:45 IRST'
    """
    teh = dt.astimezone(TEHRAN)
    return teh.strftime("%Y-%m-%d %H:%M IRST")


def fmt_utc(dt: datetime) -> str:
    """Return *dt* formatted as UTC.

    Example: '2026-07-14 00:15 UTC'
    """
    return dt.astimezone(_UTC).strftime("%Y-%m-%d %H:%M UTC")


def fmt_both(dt: datetime) -> str:
    """Return *dt* as 'YYYY-MM-DD HH:MM UTC / HH:MM IRST'.

    Example: '2026-07-14 00:15 UTC / 03:45 IRST'
    """
    utc_str = dt.astimezone(_UTC).strftime("%Y-%m-%d %H:%M UTC")
    teh_str = dt.astimezone(TEHRAN).strftime("%H:%M IRST")
    return f"{utc_str} / {teh_str}"
