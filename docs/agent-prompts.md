# NovaxFX — Agent prompts for the VSCode Claude plugin

Paste these into the Claude plugin, one task at a time. The **Project rules**
block can be pasted once at the top of a session (or kept in `CLAUDE.md`); each
task prompt below assumes it.

---

## Project rules (paste once per session)

You are working in the NovaxFX repo (research-grade FX platform, Python 3.12+).
Follow these rules for every change:

- Match existing conventions: `from __future__ import annotations`, an explicit
  `__all__`, full type hints, `datetime` is UTC-aware (`datetime.now(UTC)`),
  `StrEnum` for string enums.
- Keep the **pure/wiring split**: pure, deterministic logic in its own module
  (no network, no DB, no telegram import); side-effecting I/O isolated. Only
  `bot/app.py` imports `telegram`; only `bot/db_postgres.py` imports `psycopg`.
- Everything must pass, with zero new warnings:
  `ruff check src tests` · `ruff format --check src tests` ·
  `mypy src/novax/bot` (strict) · `pytest`.
- Write unit tests that need no network and no live DB (use
  `InMemoryUserRepository`, not Postgres).
- Never log or print the Telegram token or any secret.
- Every user-facing surface reuses `novax.bot.messages.DISCLAIMER` (task G1).
- Do not modify the research engine, the live daemon, or existing tests unless
  the task explicitly says so. Additive changes only.

Current bot package (`src/novax/bot/`): `config.py` (BotConfig, load_bot_config),
`messages.py` (pure reply text + DISCLAIMER), `app.py` (python-telegram-bot
wiring: /start /help /disclaimer + unknown fallback), `models.py` (User,
UserPrefs, SubscriptionTier), `registry.py` (UserRepository protocol +
InMemoryUserRepository + ensure_user), `db_postgres.py` (PostgresUserRepository).

---

## A3 — Onboarding flow (inline keyboards) that registers users and captures prefs

Implement task A3 of Phase 0. Goal: when a new user runs `/start`, register them
via the user registry, then walk them through an inline-keyboard onboarding that
captures their signal preferences (pairs, sessions, minimum score) and saves them.

Requirements:
1. **Wire `/start` to the registry.** In `app.py`, the app must hold a
   `UserRepository` instance (default `InMemoryUserRepository`; allow injecting a
   `PostgresUserRepository`). On `/start`, call `ensure_user(repo, telegram_id,
   first_name, username)` before replying. Do not break the existing `/start`
   welcome text or the other commands.
2. **Onboarding conversation.** Add an inline-keyboard flow (use
   `InlineKeyboardMarkup` / `CallbackQueryHandler`, or PTB `ConversationHandler`)
   that lets the user:
   - pick one or more pairs from {EURUSD, GBPUSD, USDJPY, XAUUSD} (multi-select,
     toggle on tap, a "Done" button),
   - pick one or more sessions from {ASIA, LONDON, NY, OVERLAP},
   - pick a minimum signal score from {50, 60, 70, 80, 90},
   then persist them with `repo.set_prefs(...)` as a `UserPrefs`.
   Add a `/settings` command that re-opens the same flow to edit prefs.
3. **Keep logic testable.** Put the pure pieces — keyboard builders, the
   toggle/selection-state reducer, and the "selection → UserPrefs" mapping — in a
   new pure module `src/novax/bot/onboarding.py` (no telegram import). `app.py`
   only wires PTB callbacks to these pure functions. Follow the pattern already
   used by `messages.py` vs `app.py`.
4. **Defaults & validation.** Selecting nothing keeps `UserPrefs` defaults
   (XAUUSD; LONDON+NY; min_score 70). Reuse `UserPrefs` validation (min_score in
   0–100). Reuse `messages.DISCLAIMER` at the end of onboarding.
5. **Tests** in `tests/test_onboarding.py` (no network, no DB): keyboard state
   toggling, multi-select accumulation, selection→UserPrefs mapping, and that a
   fresh `/start`-style `ensure_user` + `set_prefs` round-trips through
   `InMemoryUserRepository`. Also assert `onboarding.py` imports without
   `python-telegram-bot` installed (pure module).

Before finishing, run and report:
`ruff check src/novax/bot tests` · `ruff format --check src/novax/bot tests` ·
`mypy src/novax/bot` · `pytest tests/test_bot.py tests/test_user_registry.py tests/test_onboarding.py`.
All must be green. Then summarize the diff and the new commands/handlers added.

---

## Next prompts (ask NovaxFX-in-Cowork to generate these when ready)

- **A4** — encrypted per-user broker-secret storage (`/connect` groundwork).
- **B1** — per-user signal fan-out: read from the existing `signal_store` /
  `signal_score` and deliver to subscribed users honoring their `UserPrefs`
  filters (pair, session, min_score); free tier delayed, premium real-time.
- **G1** — enforce `DISCLAIMER` on every outbound message centrally.
