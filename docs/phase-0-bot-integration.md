# Phase 0 · A1 — Bot skeleton: integration guide

Drop-in for `github.com/vahidelahi777/NovaxFX`. Adds an interactive, multi-user
Telegram product bot **alongside** the existing broadcast daemon. No existing
file is modified except two small additive edits (below).

## New files (copy as-is)
```
# A1 — bot skeleton
src/novax/bot/__init__.py     # package; pure exports, no telegram/psycopg import
src/novax/bot/config.py       # BotConfig + load_bot_config; token redacted in repr
src/novax/bot/messages.py     # pure reply text + single-source DISCLAIMER
src/novax/bot/app.py          # python-telegram-bot wiring (only file importing telegram)
scripts/run_bot.py            # entry point: python scripts/run_bot.py
tests/test_bot.py             # 10 tests, no network / no PTB needed

# A2 — user registry
src/novax/bot/models.py       # User, UserPrefs, SubscriptionTier (pure, immutable)
src/novax/bot/registry.py     # UserRepository protocol + InMemoryUserRepository + ensure_user
src/novax/bot/db_postgres.py  # PostgresUserRepository + SCHEMA_SQL (only file importing psycopg)
tests/test_user_registry.py   # 10 tests, no DB needed (in-memory covers the contract)
```

## Validation (already run, all green on Python 3.12+)
- `ruff check` — passed · `ruff format --check` — passed
- `mypy src/novax/bot` (strict) — **Success: no issues**
- `pytest tests/test_bot.py` — **10 passed**
- `build_application(...)` wires 3 CommandHandlers + 1 fallback MessageHandler

> Note: the module uses only stdlib features compatible with the repo's 3.12+ target.

## Two additive edits to existing files

**1. `pyproject.toml` — add the optional `bot` dependency group** under
`[project.optional-dependencies]`:
```toml
bot = [
    "python-telegram-bot>=21,<23",
    "psycopg[binary]>=3.1",
]
```
(hatch already packages all of `src/novax`, so no packaging change is needed.)

If CI runs `mypy` without installing the `bot` extra, add these overrides so the
`telegram`/`psycopg` imports don't break the strict run:
```toml
[[tool.mypy.overrides]]
module = ["telegram", "telegram.*", "psycopg", "psycopg.*"]
ignore_missing_imports = true
```
(Both ship `py.typed`, so when the extra *is* installed mypy type-checks them
fully — as it did here: `Success: no issues found in 7 source files`.)

## Database (A2)
Apply the schema once against your Postgres, then use the repository:
```python
import psycopg
from novax.bot.db_postgres import PostgresUserRepository, apply_schema

conn = psycopg.connect("postgresql://user:pass@host/novax")
apply_schema(conn)                       # creates bot_users if absent
repo = PostgresUserRepository(conn)      # same interface as InMemoryUserRepository
```
For tests/local dev use `InMemoryUserRepository()` — no database required.

**2. `.env.example` — add the optional admin list** (token line already exists):
```
# Optional: comma-separated Telegram user IDs with admin rights
TELEGRAM_ADMIN_IDS=
```

## Run it
```bash
pip install -e ".[bot]"
export TELEGRAM_TOKEN=...          # from @BotFather — never commit or log
export TELEGRAM_ADMIN_IDS=123456   # optional
python scripts/run_bot.py
```
Then message the bot: `/start`, `/help`, `/disclaimer`. Any other command hits
the fallback. It long-polls, so it is safe to run next to `prod_daemon_xauusd.py`.

## Design notes (why it's built this way)
- **Pure/wiring split** — all reply text lives in `messages.py` (deterministic,
  fully tested); `app.py` is the only telegram-touching module. Matches the
  repo's "pure, tested, no lookahead" philosophy.
- **Token safety** — `BotConfig.__repr__` redacts the token; never logged.
- **Single-source DISCLAIMER** — task G1 will reuse `messages.DISCLAIMER` across
  every surface.

## Next tasks unblocked
A2 (user registry / Postgres) → A3 (onboarding) → B1 (signal fan-out). See
`phase-0-task-board.md`.
