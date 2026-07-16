"""Bot configuration loaded from the environment.

Security: the Telegram token is read from the environment and is *never* logged
or printed. ``BotConfig.__repr__`` redacts it so it cannot leak via debug output
or tracebacks — mirroring the existing daemon's "never log the token" rule.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

__all__ = ["BotConfig", "MissingTokenError", "load_bot_config"]


class MissingTokenError(RuntimeError):
    """Raised when ``TELEGRAM_TOKEN`` is absent from the environment."""


@dataclass(frozen=True)
class BotConfig:
    """Immutable runtime configuration for the product bot."""

    token: str
    admin_ids: frozenset[int]

    def __repr__(self) -> str:
        # Redact the token so it never appears in logs or tracebacks.
        return f"BotConfig(token=***redacted***, admin_ids={sorted(self.admin_ids)})"


def _parse_admin_ids(raw: str) -> frozenset[int]:
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError as exc:
            raise ValueError(f"Invalid admin id {part!r} in TELEGRAM_ADMIN_IDS") from exc
    return frozenset(ids)


def load_bot_config(env: Mapping[str, str] | None = None) -> BotConfig:
    """Build a :class:`BotConfig` from ``env`` (defaults to ``os.environ``).

    Raises :class:`MissingTokenError` if ``TELEGRAM_TOKEN`` is not set.
    """
    source: Mapping[str, str] = os.environ if env is None else env
    token = source.get("TELEGRAM_TOKEN", "").strip()
    if not token:
        raise MissingTokenError(
            "TELEGRAM_TOKEN is not set. Copy .env.example to .env and fill it in."
        )
    admin_ids = _parse_admin_ids(source.get("TELEGRAM_ADMIN_IDS", ""))
    return BotConfig(token=token, admin_ids=admin_ids)
