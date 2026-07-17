"""Uvicorn entry point for the NovaxFX admin panel (H1).

Bind to 127.0.0.1 by default — the panel sits behind a TLS reverse proxy
(Caddy) and must never be exposed directly to the internet.

Required env vars:
  ADMIN_PASSWORD_HASH   argon2id hash; generate with:
                        python -c "from novax.admin.auth import hash_password; \\
                                   print(hash_password('your-password'))"
  SESSION_SECRET        Long random secret for itsdangerous signing.

Optional env vars:
  DATABASE_URL          Passed to the DB health check.
  ADMIN_HOST            Bind address (default: 127.0.0.1).
  ADMIN_PORT            Bind port    (default: 8001).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable

import uvicorn

from novax.admin.app import create_app


def _make_db_check(database_url: str) -> Callable[[], bool]:
    """Return a callable that tests whether *database_url* is reachable."""

    def _check() -> bool:
        try:
            import psycopg  # noqa: PLC0415

            conn = psycopg.connect(database_url, connect_timeout=3)
            conn.close()
            return True
        except Exception:  # noqa: BLE001
            return False

    return _check


def main() -> None:
    password_hash = os.environ.get("ADMIN_PASSWORD_HASH", "").strip()
    session_secret = os.environ.get("SESSION_SECRET", "").strip()

    if not password_hash:
        sys.exit("ADMIN_PASSWORD_HASH is not set. See script docstring.")
    if not session_secret:
        sys.exit("SESSION_SECRET is not set. See script docstring.")

    database_url = os.environ.get("DATABASE_URL", "").strip() or None
    check_db: Callable[[], bool] | None = (
        _make_db_check(database_url) if database_url else None
    )

    app = create_app(
        password_hash=password_hash,
        session_secret=session_secret,
        check_db=check_db,
    )

    host = os.environ.get("ADMIN_HOST", "127.0.0.1")
    port = int(os.environ.get("ADMIN_PORT", "8001"))
    uvicorn.run(app, host=host, port=port, access_log=True)


if __name__ == "__main__":
    main()
