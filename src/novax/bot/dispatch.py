"""Fan-out wiring: pulls recipients from the user repo and drives delivery (B5).

This is the thin bridge between the live daemon and the per-user delivery layer.
It never imports python-telegram-bot or psycopg directly — those are injected
via the ``send`` callable and the ``repo`` argument respectively.

H5 seam: pass a ``killswitch`` callable; when it returns True the fan-out is
skipped entirely without touching delivery or the repo.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from .delivery import deliver
from .fanout import SignalInfo, select_recipients
from .registry import UserRepository

__all__ = ["dispatch_signal"]

log = logging.getLogger(__name__)


async def dispatch_signal(
    signal: SignalInfo,
    repo: UserRepository,
    send: Callable[[int, str], Awaitable[None]],
    session_of: Callable[[datetime], str | None],
    *,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    killswitch: Callable[[], bool] | None = None,
) -> int:
    """Fan the signal out to all eligible registered users.

    Returns the number of recipients selected.  A fan-out failure in
    ``deliver`` is the caller's responsibility to catch.

    Args:
        signal: emitted signal (any object satisfying ``SignalInfo``).
        repo: user registry; ``list_all()`` is called synchronously.
        send: ``async (telegram_id, text) -> None``; injected so this
            module never imports python-telegram-bot.
        session_of: maps a UTC datetime to a session name or None.
        sleep: injectable for tests (default: ``asyncio.sleep``).
        killswitch: H5 hook — if provided and returns True, fan-out is
            skipped and 0 is returned.
    """
    if killswitch is not None and killswitch():
        log.info("Fan-out killswitch active — signal not delivered to users")
        return 0
    users = repo.list_all()
    recipients = select_recipients(signal, users, session_of)
    if recipients:
        await deliver(signal, recipients, send, sleep=sleep)
    log.info(
        "Fan-out: %d recipient(s) for %s %s",
        len(recipients),
        signal.symbol,
        signal.direction,
    )
    return len(recipients)
