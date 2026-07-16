"""Postgres implementation of the user registry (Phase 0 · A2).

Honours the :class:`novax.bot.registry.UserRepository` protocol. Requires the
optional ``bot`` dependency group (``psycopg[binary]``). Kept in its own module
so the pure logic in ``registry.py`` stays import-light and fully testable
without a live database.

Integration-tested against a real Postgres (not in the unit CI matrix); the
in-memory repository covers the behavioural contract in unit tests.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import psycopg

from .models import SubscriptionTier, User, UserPrefs

__all__ = ["PostgresUserRepository", "SCHEMA_SQL", "apply_schema", "connect_and_prepare"]

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS bot_users (
    telegram_id  BIGINT PRIMARY KEY,
    first_name   TEXT,
    username     TEXT,
    tier         TEXT        NOT NULL DEFAULT 'free',
    prefs        JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_COLUMNS = "telegram_id, first_name, username, tier, prefs, created_at, updated_at"


def apply_schema(conn: psycopg.Connection[Any]) -> None:
    """Create the ``bot_users`` table if it does not exist."""
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    conn.commit()


def connect_and_prepare(database_url: str) -> PostgresUserRepository:
    """Open a psycopg connection, apply the schema, and return the repo.

    Called lazily from ``app.run()`` so psycopg is never imported unless
    ``DATABASE_URL`` is set.
    """
    conn: psycopg.Connection[Any] = psycopg.connect(database_url)
    apply_schema(conn)
    return PostgresUserRepository(conn)


def _row_to_user(row: tuple[Any, ...]) -> User:
    telegram_id, first_name, username, tier, prefs, created_at, updated_at = row
    prefs_dict = prefs if isinstance(prefs, dict) else json.loads(prefs)
    return User(
        telegram_id=int(telegram_id),
        first_name=first_name,
        username=username,
        tier=SubscriptionTier(tier),
        prefs=UserPrefs.from_dict(prefs_dict),
        created_at=created_at if isinstance(created_at, datetime) else None,
        updated_at=updated_at if isinstance(updated_at, datetime) else None,
    )


class PostgresUserRepository:
    """Postgres-backed user registry. Pass an open ``psycopg`` connection."""

    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self._conn = conn

    def get(self, telegram_id: int) -> User | None:
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT {_COLUMNS} FROM bot_users WHERE telegram_id = %s", (telegram_id,))
            row = cur.fetchone()
        return _row_to_user(row) if row is not None else None

    def create_or_get(
        self, telegram_id: int, first_name: str | None = None, username: str | None = None
    ) -> User:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO bot_users (telegram_id, first_name, username)
                VALUES (%s, %s, %s)
                ON CONFLICT (telegram_id) DO NOTHING
                RETURNING {_COLUMNS}
                """,
                (telegram_id, first_name, username),
            )
            row = cur.fetchone()
            if row is None:  # already existed
                cur.execute(
                    f"SELECT {_COLUMNS} FROM bot_users WHERE telegram_id = %s", (telegram_id,)
                )
                row = cur.fetchone()
        self._conn.commit()
        assert row is not None
        return _row_to_user(row)

    def set_tier(self, telegram_id: int, tier: SubscriptionTier) -> User:
        return self._update("tier = %s", (tier.value,), telegram_id)

    def set_prefs(self, telegram_id: int, prefs: UserPrefs) -> User:
        return self._update("prefs = %s::jsonb", (json.dumps(prefs.to_dict()),), telegram_id)

    def _update(self, set_clause: str, params: tuple[Any, ...], telegram_id: int) -> User:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE bot_users SET {set_clause}, updated_at = now()
                WHERE telegram_id = %s
                RETURNING {_COLUMNS}
                """,
                (*params, telegram_id),
            )
            row = cur.fetchone()
        self._conn.commit()
        if row is None:
            from .registry import UserNotFoundError

            raise UserNotFoundError(telegram_id)
        return _row_to_user(row)

    def list_by_tier(self, tier: SubscriptionTier) -> list[User]:
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLUMNS} FROM bot_users WHERE tier = %s ORDER BY telegram_id",
                (tier.value,),
            )
            rows = cur.fetchall()
        return [_row_to_user(r) for r in rows]

    def list_all(self) -> list[User]:
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT {_COLUMNS} FROM bot_users ORDER BY telegram_id")
            rows = cur.fetchall()
        return [_row_to_user(r) for r in rows]

    def count(self) -> int:
        with self._conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM bot_users")
            row = cur.fetchone()
        return int(row[0]) if row is not None else 0
