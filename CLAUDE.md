# CLAUDE.md — NovaxFX project context

Read this first. It is the grounding for any agent (VSCode Claude plugin, or
Cowork) that thinks about or writes prompts for this repo. **Before writing a
prompt or a plan, review the actual code and the docs referenced here — do not
rely on memory.**

## What this is
NovaxFX — a research-grade FX intelligence platform (EUR/USD, GBP/USD, USD/JPY,
XAU/USD). Posture: **education + validated signals + analysis**. Bots run only on
the user's own broker account, own keys — no custody, no pooled funds, no
personalized advice, no profit promises. Not financial advice.

The moat is **structural research integrity**: causal backtest engine, deflated
Sharpe, out-of-sample lockbox, tamper-proof artifact/trial registry, go/no-go
gate. Do not weaken these guarantees.

## Tech & conventions (enforced by CI — match them exactly)
- Python **3.12+**. `from __future__ import annotations`; explicit `__all__`;
  full type hints; UTC-aware datetimes (`datetime.now(UTC)`); `StrEnum` for
  string enums.
- **ruff** (line 100; rules E,F,I,UP,B,SIM) — `ruff check` and
  `ruff format --check` must be clean.
- **mypy** strict — must report success.
- **pytest** — tests must not need network or a live DB. 31 test files today.
- **Pure/wiring split:** deterministic logic in its own module (no telegram, no
  psycopg, no network); side-effecting I/O isolated. Only `bot/app.py` imports
  `telegram`; only `bot/db_postgres.py` imports `psycopg`. Follow this pattern.
- Never log or print secrets (Telegram token, broker keys).
- Additive changes only unless a task explicitly says to modify the engine,
  the live daemon, or existing tests.

## Layout (source of truth is the code, not this list)
- `src/novax/` — research core: sessions, instruments, costs, engine, features,
  walkforward, metrics, validation, gate, artifacts, trial_registry, harness.
- `src/novax/strategies/` — WeeklyBOSRetest, GoldPullback, EMACross, TSI, etc.
- `src/novax/indicators/` — EMA, ATR, BOS, SuperTrend, TSI, weekly levels, pivots.
- `src/novax/live/` — event scheduler, multi-TF scanner, Telegram broadcast
  messages, signal store/score, paper trader, news gate.
- `src/novax/bot/` — **customer-facing product bot (Phase 0)**:
  `config.py` (BotConfig, load_bot_config; token redacted),
  `messages.py` (pure reply text + single-source `DISCLAIMER`),
  `app.py` (python-telegram-bot wiring: /start /help /disclaimer + fallback),
  `models.py` (User, UserPrefs, SubscriptionTier),
  `registry.py` (UserRepository protocol + InMemoryUserRepository + ensure_user),
  `db_postgres.py` (PostgresUserRepository + SCHEMA_SQL).
- `scripts/` — `prod_daemon_xauusd.py` (live broadcast daemon), `run_bot.py`
  (product bot entry point), ingest + research scripts.
- `docs/` — see planning docs below.

## Product plan & operating model (docs/)
- `NovaxFX-Company-Strategy-and-Roadmap.md` — full strategy, four pillars
  (Learn / Analyze / Signals / Bot-trading), phased roadmap.
- `phase-0-task-board.md` — the backlog. Status now: **A1, A2, A5 done;
  A3 next**, then B1. Product layer = Phase 0 Telegram bot → Phase 1 website.
- `decision-log.md` — append-only decisions (posture, framework, broker, etc.).
- `team-charter.md` — the AI "team" roles → how to invoke them.
- `agent-prompts.md` — **ready-to-paste task prompts for the VSCode plugin.**
- `phase-0-bot-integration.md` — how the bot package integrates.

## How to work here (prompt-writing workflow)
1. Review the relevant code + the docs above (especially the task board and
   `agent-prompts.md`) so the prompt is grounded in what actually exists.
2. Scope one task from the board. Keep to the conventions above.
3. Require green `ruff` + `mypy src/novax/bot` + `pytest` before "done", with
   unit tests that need no network/DB.
4. Reuse `novax.bot.messages.DISCLAIMER` on every user-facing surface.

## Phase 0 status snapshot (keep updated)
- A1 bot skeleton — done · A2 user registry — done · A5 daemon guard — done
- A3 onboarding (inline keyboards, register on /start, capture prefs) — **next**
- B1 per-user signal fan-out — pending · G1 disclaimer everywhere — pending
