"""Tests for BotConfig — database_url parsing and secret redaction (DZ2).

No live DB required; these cover the pure config loading logic only.
PostgresUserRepository is integration-tested separately.
"""

from __future__ import annotations

import pytest

from novax.bot import MissingTokenError, load_bot_config


def test_database_url_absent_gives_none() -> None:
    cfg = load_bot_config({"TELEGRAM_TOKEN": "tok"})
    assert cfg.database_url is None


def test_database_url_empty_string_gives_none() -> None:
    cfg = load_bot_config({"TELEGRAM_TOKEN": "tok", "DATABASE_URL": ""})
    assert cfg.database_url is None


def test_database_url_whitespace_only_gives_none() -> None:
    cfg = load_bot_config({"TELEGRAM_TOKEN": "tok", "DATABASE_URL": "   "})
    assert cfg.database_url is None


def test_database_url_parsed_when_present() -> None:
    url = "postgresql://novax:s3cret@postgres:5432/novax"
    cfg = load_bot_config({"TELEGRAM_TOKEN": "tok", "DATABASE_URL": url})
    assert cfg.database_url == url


def test_repr_redacts_token() -> None:
    cfg = load_bot_config({"TELEGRAM_TOKEN": "supersecret-token"})
    assert "supersecret-token" not in repr(cfg)
    assert "redacted" in repr(cfg)


def test_repr_redacts_database_url_when_set() -> None:
    url = "postgresql://novax:hunter2@postgres:5432/novax"
    cfg = load_bot_config({"TELEGRAM_TOKEN": "tok", "DATABASE_URL": url})
    r = repr(cfg)
    assert "hunter2" not in r
    assert "postgresql" not in r
    assert "redacted" in r


def test_repr_shows_none_for_database_url_when_absent() -> None:
    cfg = load_bot_config({"TELEGRAM_TOKEN": "tok"})
    assert "database_url=None" in repr(cfg)


def test_missing_token_still_raises() -> None:
    with pytest.raises(MissingTokenError):
        load_bot_config({"DATABASE_URL": "postgresql://u:p@h/db"})


def test_botconfig_is_immutable() -> None:
    import dataclasses

    cfg = load_bot_config({"TELEGRAM_TOKEN": "tok", "DATABASE_URL": "postgresql://u:p@h/db"})
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.database_url = "other"
