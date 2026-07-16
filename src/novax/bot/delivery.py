"""Async delivery wiring for per-user signal fan-out (Phase 0 · B1).

Transport is injected via the ``send`` callable so this module never imports
python-telegram-bot — that coupling lives in the daemon or a thin adapter.

B2 seam — how the live daemon will plug in::

    from novax.bot.fanout import select_recipients, format_signal_message
    from novax.bot.delivery import deliver

    # Inside the daemon's 15M scan callback, after inserting the signal:
    users = repo.list_all()
    recipients = select_recipients(stored_signal, users, primary_session)
    if recipients:
        asyncio.create_task(
            deliver(stored_signal, recipients, app.bot.send_message)
        )

    # app.bot.send_message(chat_id, text) already satisfies
    # Callable[[int, str], Awaitable[None]].
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from .fanout import Recipient, SignalInfo, format_signal_message

__all__ = ["deliver"]


async def deliver(
    signal: SignalInfo,
    recipients: list[Recipient],
    send: Callable[[int, str], Awaitable[None]],
    *,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> None:
    """Send the signal to all recipients, honouring their individual delays.

    PREMIUM / PRO recipients (delay_seconds == 0) send immediately.
    FREE-tier recipients wait for their delay_seconds before receiving the
    same message — this is the commercial hook for the free tier.

    All sends are driven by ``asyncio.gather`` so the coroutines run
    concurrently; the delayed ones simply await ``sleep`` first.

    Args:
        signal: the signal to format and deliver.
        recipients: output of ``select_recipients``.
        send: ``async (telegram_id, text) -> None``; injected so this
            module never imports python-telegram-bot.
        sleep: injectable for tests (default: ``asyncio.sleep``).
    """
    if not recipients:
        return

    text = format_signal_message(signal)

    async def _send_after(r: Recipient) -> None:
        if r.delay_seconds > 0:
            await sleep(float(r.delay_seconds))
        await send(r.user.telegram_id, text)

    await asyncio.gather(*(_send_after(r) for r in recipients))
