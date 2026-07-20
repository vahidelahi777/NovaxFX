"""HTTP retry helper — pure, no network imports, injectable sleep for tests."""

from __future__ import annotations

import logging
import time
import urllib.error
from collections.abc import Callable

__all__ = ["FETCH_RETRIES", "FETCH_RETRY_DELAYS", "retry_fetch"]

FETCH_RETRIES: int = 3
FETCH_RETRY_DELAYS: tuple[int, ...] = (15, 45, 120)


def retry_fetch[T](
    fetcher: Callable[[], T],
    *,
    retries: int = FETCH_RETRIES,
    delays: tuple[int, ...] = FETCH_RETRY_DELAYS,
    sleep_fn: Callable[[float], None] = time.sleep,
    log: logging.Logger | None = None,
) -> T:
    """Run *fetcher* with retry / back-off.  Raises the last exception on exhaustion."""
    last_exc: Exception | None = None
    for attempt in range(retries):
        if attempt > 0:
            delay = delays[attempt - 1]
            if log is not None:
                log.warning(
                    "Fetch attempt %d/%d failed — retrying in %ds: %s",
                    attempt,
                    retries,
                    delay,
                    last_exc,
                )
            sleep_fn(delay)
        try:
            return fetcher()
        except (urllib.error.URLError, OSError) as exc:
            last_exc = exc
    raise last_exc  # type: ignore[misc]
