"""Tests for the Phase 0 product bot skeleton (A1).

These cover the pure logic only (config + messages) — no network, no
python-telegram-bot dependency required, so they run in the standard CI matrix.
"""

from __future__ import annotations

import pytest

from novax.bot import (
    DISCLAIMER,
    BotConfig,
    MissingTokenError,
    disclaimer_text,
    help_text,
    load_bot_config,
    render_command,
    start_text,
    unknown_text,
)


def test_start_text_greets_by_name_and_includes_disclaimer() -> None:
    text = start_text("Vahid")
    assert "Vahid" in text
    assert "NovaxFX" in text
    assert DISCLAIMER in text


def test_start_text_without_name_is_generic() -> None:
    text = start_text(None)
    assert "Welcome!" in text
    assert DISCLAIMER in text


def test_help_lists_core_commands() -> None:
    text = help_text()
    for cmd in ("/start", "/help", "/disclaimer"):
        assert cmd in text


def test_disclaimer_is_not_financial_advice() -> None:
    text = disclaimer_text()
    assert "not personalized financial advice" in text
    assert "No profit is promised" in text


def test_render_command_routes_known_commands() -> None:
    assert render_command("start", "Vahid") == start_text("Vahid")
    assert render_command("/help") == help_text()
    assert render_command("DISCLAIMER") == disclaimer_text()


def test_render_command_unknown_falls_back() -> None:
    assert render_command("wat") == unknown_text()


def test_load_bot_config_reads_token_and_admins() -> None:
    cfg = load_bot_config({"TELEGRAM_TOKEN": "abc123", "TELEGRAM_ADMIN_IDS": "1, 2 ,3"})
    assert isinstance(cfg, BotConfig)
    assert cfg.token == "abc123"
    assert cfg.admin_ids == frozenset({1, 2, 3})


def test_load_bot_config_missing_token_raises() -> None:
    with pytest.raises(MissingTokenError):
        load_bot_config({})


def test_config_repr_redacts_token() -> None:
    cfg = load_bot_config({"TELEGRAM_TOKEN": "supersecret-token"})
    assert "supersecret-token" not in repr(cfg)
    assert "redacted" in repr(cfg)


def test_invalid_admin_id_raises() -> None:
    with pytest.raises(ValueError):
        load_bot_config({"TELEGRAM_TOKEN": "x", "TELEGRAM_ADMIN_IDS": "1,notanint"})
