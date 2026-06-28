"""
Novax FX — Session Calendar (DST-correct).

Design rules (locked, Phase 0):
  * ALL instants are timezone-aware and reasoned about in UTC.
  * Sessions are DEFINED in their local exchange timezone and converted to UTC
    per-day via zoneinfo, so DST is handled automatically and the London/New-York
    DST-mismatch weeks (when the overlap window shifts/lengthens) are correct
    *by construction* rather than by hardcoded offsets.
  * No naive datetimes are ever accepted. Passing a naive datetime raises.

These session boundaries are a documented, configurable convention — not a law of
nature. What must be correct is the *conversion*, not the exact local hours. Adjust
START/END per your data vendor's convention; the correctness tests still hold.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

__all__ = [
    "SessionWindow",
    "SESSIONS",
    "session_bounds_utc",
    "is_in_session",
    "overlap_bounds_utc",
    "is_in_overlap",
    "active_sessions",
    "primary_session",
    "is_fx_market_open",
]


@dataclass(frozen=True)
class SessionWindow:
    """A trading session defined in LOCAL exchange time. end is exclusive."""
    name: str
    tz: str           # IANA tz name, e.g. "Europe/London"
    start: time       # local start (inclusive)
    end: time         # local end (exclusive)

    def __post_init__(self) -> None:
        if self.start >= self.end:
            # These FX session conventions never cross local midnight.
            raise ValueError(f"{self.name}: start must be < end (no midnight cross)")


# Convention used here (override per vendor as needed):
#   ASIA    : Tokyo 09:00–18:00 JST   (Japan has NO DST -> always 00:00–09:00 UTC)
#   LONDON  : 08:00–16:00 local       (GMT in winter, BST in summer)
#   NEWYORK : 08:00–17:00 local       (EST in winter, EDT in summer)
SESSIONS: dict[str, SessionWindow] = {
    "ASIA": SessionWindow("ASIA", "Asia/Tokyo", time(9, 0), time(18, 0)),
    "LONDON": SessionWindow("LONDON", "Europe/London", time(8, 0), time(16, 0)),
    "NEWYORK": SessionWindow("NEWYORK", "America/New_York", time(8, 0), time(17, 0)),
}


def _require_aware_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("naive datetime rejected: all instants must be tz-aware UTC")
    return dt.astimezone(timezone.utc)


def _local_to_utc(tz: str, d: date, t: time) -> datetime:
    """Localize (d, t) in tz and return the UTC instant. zoneinfo applies DST for d."""
    return datetime.combine(d, t, tzinfo=ZoneInfo(tz)).astimezone(timezone.utc)


def session_bounds_utc(name: str, local_day: date) -> tuple[datetime, datetime]:
    """UTC [start, end) of `name` for the given LOCAL calendar day."""
    sw = SESSIONS[name]
    start = _local_to_utc(sw.tz, local_day, sw.start)
    end = _local_to_utc(sw.tz, local_day, sw.end)
    return start, end


def is_in_session(name: str, dt_utc: datetime) -> bool:
    """Is the UTC instant inside `name`'s local [start, end)?"""
    dt_utc = _require_aware_utc(dt_utc)
    sw = SESSIONS[name]
    local = dt_utc.astimezone(ZoneInfo(sw.tz))
    return sw.start <= local.time() < sw.end


def overlap_bounds_utc(local_day: date) -> tuple[datetime, datetime] | None:
    """
    UTC [start, end) of the London/New-York overlap for the given day, or None.
    Computed as the intersection of the two sessions' UTC bounds — so the window
    automatically lengthens during DST-mismatch weeks.
    """
    ls, le = session_bounds_utc("LONDON", local_day)
    ns, ne = session_bounds_utc("NEWYORK", local_day)
    start, end = max(ls, ns), min(le, ne)
    return (start, end) if start < end else None


def is_in_overlap(dt_utc: datetime) -> bool:
    dt_utc = _require_aware_utc(dt_utc)
    return is_in_session("LONDON", dt_utc) and is_in_session("NEWYORK", dt_utc)


def active_sessions(dt_utc: datetime) -> list[str]:
    """All sessions active at the UTC instant; includes 'OVERLAP' when London and NY overlap."""
    dt_utc = _require_aware_utc(dt_utc)
    result = [name for name in SESSIONS if is_in_session(name, dt_utc)]
    if "LONDON" in result and "NEWYORK" in result:
        result.append("OVERLAP")
    return result


_SESSION_PRIORITY = ("OVERLAP", "LONDON", "NEWYORK", "ASIA")


def primary_session(dt_utc: datetime) -> str | None:
    """Highest-priority active session: OVERLAP > LONDON > NEWYORK > ASIA, or None."""
    active = active_sessions(dt_utc)
    for s in _SESSION_PRIORITY:
        if s in active:
            return s
    return None


def is_fx_market_open(dt_utc: datetime) -> bool:
    """
    Coarse FX open check: closed from Fri 21:00 UTC to Sun 21:00 UTC.
    (21:00 UTC ~= NY close; refine with a real holiday calendar in Phase 1.)
    """
    dt_utc = _require_aware_utc(dt_utc)
    wd, t = dt_utc.weekday(), dt_utc.time()  # Mon=0 .. Sun=6
    if wd == 5:  # Saturday
        return False
    if wd == 4 and t >= time(21, 0):  # Friday after 21:00 UTC
        return False
    if wd == 6 and t < time(21, 0):   # Sunday before 21:00 UTC
        return False
    return True
