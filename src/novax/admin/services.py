"""Admin service layer — pure query functions, no FastAPI or DB imports.

All I/O is injected via callables so every function is unit-testable
without a live database or running server.
"""

from __future__ import annotations

import importlib.metadata
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TypedDict

__all__ = ["HealthSnapshot", "health_snapshot"]


class HealthSnapshot(TypedDict):
    version: str
    time_utc: str
    db_ok: bool


def health_snapshot(check_db: Callable[[], bool]) -> HealthSnapshot:
    """Return app version, current UTC time, and DB reachability.

    Args:
        check_db: Zero-argument callable that returns True when the DB is
                  reachable and False (or raises) otherwise.
    """
    try:
        version = importlib.metadata.version("novax")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"

    try:
        db_ok = check_db()
    except Exception:  # noqa: BLE001
        db_ok = False

    return HealthSnapshot(
        version=version,
        time_utc=datetime.now(UTC).isoformat(timespec="seconds"),
        db_ok=db_ok,
    )
