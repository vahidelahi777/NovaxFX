#!/usr/bin/env python
"""Run the NovaxFX product bot (Phase 0 · A1).

Usage:
    pip install -e ".[bot]"
    export TELEGRAM_TOKEN=...        # from @BotFather; never commit or log
    python scripts/run_bot.py

Reads TELEGRAM_TOKEN (required) and TELEGRAM_ADMIN_IDS (optional, comma-sep)
from the environment. Long-polls Telegram; safe to run alongside the existing
production daemon.
"""

from __future__ import annotations

from novax.bot.app import run

if __name__ == "__main__":
    run()
