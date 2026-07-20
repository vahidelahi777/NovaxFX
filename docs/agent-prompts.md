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
wiring: /start /help /disclaimer /settings + ConversationHandler onboarding),
`models.py` (User, UserPrefs, SubscriptionTier), `registry.py` (UserRepository
protocol + InMemoryUserRepository + ensure_user), `db_postgres.py`
(PostgresUserRepository), `onboarding.py` (pure keyboard builders + state
reducer), `dispatch.py` (per-user fan-out; killswitch seam at H5),
`fanout.py` (select_recipients, format_signal_message).

Current live package (`src/novax/live/`): `multi_tf_scanner.py` (EMA50
confluence gate — v2; WeeklyBOSRetest kept as bonus-indicator), `messages.py`
(all Telegram formatters incl. `fmt_sweep_alert`), `london_sweep_scanner.py`
(LondonSweepScanner wrapping `LondonOpenSweep`), `paper_trader.py`
(PaperTrader, PaperPosition — JSON-persisted), `signal_store.py` (DuckDB store
+ score weights), `risk_governor.py` (RiskGovernor — P1.2), `recovery.py`
(reconcile_on_boot — P1.3), `event_scheduler.py`, `news_gate.py`, etc.

Production daemon (`scripts/prod_daemon_xauusd.py`): `_retry_fetch` (testable
retry helper — P1.1), all async handlers use `asyncio.to_thread` for fetches
(P1.1), `RiskGovernor` wired (P1.2), `PaperTrader.entry_signal_id` persisted
(P1.3), `--stream` flag for `ResilientStream` (P1.5), heartbeat file touched
each scheduler iteration (P1.6).

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

---

# Production roadmap prompts (from the 2026-07-20 production review)

Three phases. Within a phase, do the tasks in order — later tasks build on
earlier ones. Each prompt is one session / one PR. Tasks marked **[daemon]**
explicitly authorize modifying `scripts/prod_daemon_xauusd.py` (overriding the
"additive only" rule for that file only).

---

## P1.1 — [daemon] Unblock the event loop: async-safe fetching + retry-wrapped report handlers

Fix a production bug in `scripts/prod_daemon_xauusd.py`: `_fetch_all` uses
blocking `time.sleep()` and synchronous `urllib` (via
`novax.data.ingest.twelvedata.fetch_bars`) but is called from async handlers.
During the retry ladder (15+45+120 s) the entire asyncio event loop — PTB
polling, `/signal`, `/stats`, the scheduler — freezes.

Requirements:
1. In every async handler (`_handle_15m`, `_handle_market_update_4h`,
   `_handle_london_sweep`, `_handle_market_open`, `_handle_market_close`,
   `_handle_weekly_report`, `_handle_session_open`, `_handle_daily_report`),
   run all `_fetch_all` / `fetch_bars` calls via `await asyncio.to_thread(...)`.
   `_fetch_all` itself stays synchronous (it runs inside the thread).
2. `_handle_market_open`, `_handle_market_close`, `_handle_weekly_report`, and
   `_handle_session_open` currently call `fetch_bars` bare, with no retries —
   one transient blip kills the report. Route them through `_fetch_all`-style
   retry logic (extract a single-interval retry helper if cleaner).
3. Error notifications sent to Telegram must not interpolate raw exception text
   into `parse_mode="Markdown"` (unescaped `_ * \`` can 400 the alert itself).
   Send error/maintenance notifications as plain text (no parse_mode).
4. Tests in `tests/test_daemon_fetch_async.py` (no network): the retry helper
   retries on `URLError`/`OSError` with the configured delays (inject a fake
   sleep), gives up after `_FETCH_RETRIES`, and returns on first success.
   Extract the retry logic into a testable function if needed.

Before finishing, run and report: `ruff check scripts tests` ·
`ruff format --check scripts tests` · `mypy src/novax` · `pytest`. All green.

---

## P1.2 — [daemon] RiskGovernor: hard, persisted, latching daily loss limit

Create `src/novax/live/risk_governor.py` — a pure module (no telegram, no
network) enforcing a global daily loss limit in R-multiples, persisted to JSON
with the same atomic write pattern as `PaperTrader._save()` (tmp +
`os.replace`).

Requirements:
1. `trading_day(now)` helper: the gold trading day rolls at **17:00
   America/New_York** (use `zoneinfo`), not midnight UTC.
2. `RiskLedger` dataclass: `day`, `realized_r`, `trades`, `halted`,
   `halted_at`, `halt_reason`, and `history: dict[str, float]` (day → realized
   R, appended on rollover).
3. `RiskGovernor(state_path, max_daily_loss_r=3.0, max_daily_trades=6)` with:
   - `is_halted(now) -> bool` — rolls the day first; halted state **latches**
     until the trading day rolls over.
   - `record_fill(pnl_r, now) -> bool` — accumulates realized R and trade
     count; trips the halt when `realized_r <= -max_daily_loss_r` or
     `trades >= max_daily_trades`; returns True iff this fill tripped it.
   - **Fail safe:** a corrupt/unreadable ledger file loads as
     `halted=True, halt_reason="ledger corrupt — manual reset required"`.
4. Wire into `scripts/prod_daemon_xauusd.py`:
   - construct `RiskGovernor(state_dir / f"risk_ledger_{symbol}.json")` in
     `main()`, store on `_State`;
   - in `_handle_15m`, before the confluence/alert section: if
     `is_halted()`, log and return (no alert, no fan-out);
   - pass `killswitch=state.risk_governor.is_halted` to the existing
     `dispatch_signal(...)` call (the seam already exists in
     `novax/bot/dispatch.py`);
   - in the PaperTrader EXIT branch, convert pnl to R using the entry's
     `sl_pips` (R = pnl / (sl_pips * pip)) and call `record_fill`; if it
     trips, send a plain-text 🛑 halt notification to the notif channel.
5. Tests in `tests/test_risk_governor.py` (no network, use tmp_path and
   injected `now`): day rollover at 17:00 NY; loss-limit trip; trade-count
   trip; latch persists across reload; corrupt file loads halted; history
   accumulates on rollover.

Before finishing: `ruff check src tests scripts` · `ruff format --check` ·
`mypy src/novax` · `pytest`. All green.

---

## P1.3 — [daemon] Persistent state recovery: entry_signal_id + boot reconciliation

The daemon keeps `state.paper_entry_id` (the link between the open paper
position and its `SignalStore` row) in memory only. After a restart, that
signal stays `ACTIVE` forever and corrupts the win-rate/P&L stats shown by
`/stats`.

Requirements:
1. Add `entry_signal_id: str | None = None` to `PaperPosition` in
   `src/novax/live/paper_trader.py` (it round-trips through the existing JSON
   persistence automatically). Add a small `set_entry_link(sig_id)` /
   `clear_entry_link()` API on `PaperTrader` that saves state.
2. In `scripts/prod_daemon_xauusd.py`, replace every read/write of
   `state.paper_entry_id` with the persisted field; delete the `_State`
   attribute.
3. Add a pure function `reconcile_on_boot(trader, store, log)` (put it in
   `paper_trader.py` or a new `src/novax/live/recovery.py`):
   - every `SignalStore` row with status ACTIVE whose id != the open
     position's `entry_signal_id` → set status EXPIRED, log a warning;
   - if `entry_signal_id` is set but the position is FLAT → clear the link,
     log a warning.
   Add whatever minimal query method `SignalStore` needs (e.g.
   `ids_by_status(status) -> list[str]`).
4. Call `reconcile_on_boot` once in `post_init` before the scheduler starts.
5. Tests in `tests/test_state_recovery.py` (no network): entry link survives a
   save/load round-trip; orphaned ACTIVE rows get EXPIRED; stale link on FLAT
   position gets cleared; a matched ACTIVE row is left untouched.

Before finishing: `ruff check` · `ruff format --check` · `mypy src/novax` ·
`pytest`. All green.

---

## P1.4 — ResilientStream: websocket reconnect, gap backfill, stalled-bar watchdog

`src/novax/data/stream/twelvedata_ws.py` has no reconnect logic (a dropped WS
only logs a heartbeat warning and the stream silently dies), no gap backfill,
and `BarBuilder` only emits a bar when the first tick of the *next* interval
arrives — a stalled feed means the last bar never closes. This task is
additive: do not rewrite `TwelveDataStream`, wrap it.

Requirements:
1. In `twelvedata_ws.py`, fix the timestamp fallback in `BarBuilder.push`:
   a tick with neither `timestamp` nor `last_trade_time` must be **rejected
   with a warning**, never defaulted to 0 (epoch-0 bars poison ordering).
2. New module `src/novax/data/stream/resilient_stream.py`:
   `ResilientStream(api_key, symbol, interval_seconds, bar_queue)` with an
   async `run()` supervisor that loops forever until cancelled:
   - starts a `TwelveDataStream` via `asyncio.to_thread` (the SDK blocks);
   - the `on_bar` callback (called from the SDK thread) hands the bar to the
     asyncio queue via `loop.call_soon_threadsafe` — no work in the callback;
   - a watchdog coroutine: if no tick/bar for `1.5 × interval`, treat as a
     disconnect (return → supervisor tears down and reconnects);
   - reconnect with capped exponential backoff `(1, 2, 5, 15, 30, 60)` s;
   - after every reconnect, backfill the gap via REST
     (`novax.data.ingest.twelvedata.fetch_bars` in a thread) from
     `last_bar_ts + interval` to now, pushing only bars newer than
     `last_bar_ts` into the queue in order.
3. Keep it pure enough to test: the backoff sequence, gap-window computation,
   and "only newer bars" filter live in small pure functions.
4. Tests in `tests/test_resilient_stream.py` (no network, no twelvedata SDK
   import): timestamp-rejection in BarBuilder; backoff progression and cap;
   backfill window math; dedup/ordering of backfilled bars pushed to the
   queue; watchdog stall detection with injected clock.

Before finishing: `ruff check` · `ruff format --check` · `mypy src/novax` ·
`pytest`. All green. Do NOT wire into the daemon yet — that is P1.5.

---

## P1.5 — [daemon] Migrate the 15M path to the bar queue (flag-gated)

Wire `ResilientStream` (P1.4) into `scripts/prod_daemon_xauusd.py` behind a
flag, keeping REST polling as the default until the stream is proven.

Requirements:
1. Add `--stream` (default off). When off, behavior is byte-for-byte today's.
2. When on: start `ResilientStream` as an asyncio task in `post_init`; a
   consumer task awaits the bar queue and, on each completed 15M bar, runs the
   existing `_handle_15m` logic. The scheduler loop keeps firing all
   *non*-15M events (reports, session opens) unchanged; suppress only
   `BAR_CLOSE_15M` scheduling in stream mode.
3. The 15M handler still needs H4/H1 context — keep fetching those via the
   (now threaded, P1.1) REST path; only the 15M trigger moves to the stream.
4. On stream-task crash (should be unreachable given the supervisor, but
   belt-and-braces): log, notify the notif channel in plain text, and fall
   back to scheduler-driven 15M events until restart.
5. Tests: extract the "which events does the scheduler fire in stream mode"
   decision into a pure function and test it; test the fallback switch logic.

Before finishing: `ruff check` · `ruff format --check` · `mypy src/novax` ·
`pytest`. All green. Report a manual test plan for a supervised prod trial.

---

## P1.6 — Ops hardening: heartbeat file, Docker healthcheck, log rotation caps

1. In `scripts/prod_daemon_xauusd.py` `_scheduler_loop`, touch
   `state.state_dir / "heartbeat"` once per loop iteration (and once at
   startup).
2. In `docker-compose.yml`, on `prod-daemon`: a healthcheck that fails when
   the heartbeat file is older than 20 minutes
   (`find /app/data/heartbeat -mmin -20 | grep -q heartbeat`), `interval: 60s`,
   `retries: 3`, `start_period: 120s`; a memory limit (768M); json-file log
   driver capped at `max-size: 20m`, `max-file: 5`. Add the same log caps to
   `product-bot`.
3. Add `deploy/README` note (or extend existing deploy docs): how to alert on
   an unhealthy container (autoheal container or host cron posting to the
   notif channel) — a silent daemon is indistinguishable from "no setups
   today" for users, so unhealthy must page someone.
4. Test: none required for compose; add a unit test that the scheduler-loop
   heartbeat helper writes/updates the file (pure function + tmp_path).

Before finishing: `ruff check` · `mypy src/novax` · `pytest` green, and
`docker compose config` parses.

---

## P2.1 — ApprovalGate: pure HITL policy + persisted pending queue

Create the human-in-the-loop approval layer as a pure module + store, no
telegram imports (the daemon injects senders, same pattern as
`bot/dispatch.py`).

Requirements:
1. `src/novax/live/approval_gate.py`:
   - `ApprovalPolicy(StrEnum)`: BROADCAST, SEMI_AUTO, AUTO.
   - `ApprovalStatus(StrEnum)`: PENDING, APPROVED, REJECTED, EXPIRED,
     AUTO_APPROVED.
   - `PendingApproval` frozen dataclass: id, signal_id, created_at,
     expires_at, status, decided_by (telegram admin id | None), decided_at,
     reason.
   - `ApprovalGate(store, policy, ttl=timedelta(minutes=10), auto_envelope,
     on_decision)`:
     `submit(signal_id, signal, now)` — BROADCAST and (AUTO within envelope)
     → AUTO_APPROVED, else PENDING;
     `async decide(approval_id, approve, admin_id, now)` — **idempotent**:
     only a PENDING, unexpired row transitions; a late click transitions to
     EXPIRED; double-clicks return None;
     `expire_stale(now)` — batch-expire, returns the expired rows.
2. `ApprovalStore` — persisted table in the existing DuckDB pattern (follow
   `src/novax/live/signal_store.py`): insert, get, transition (guarded:
   only from PENDING), expire_before, plus stats queries
   `counts_by_status(since)` and `decision_latency_seconds(since)` (for the
   Phase-3 dashboard and the semi→auto promotion review).
3. The audit trail is **append-only in spirit**: transitions never overwrite
   decided_by/decided_at once set; no delete API.
4. Tests in `tests/test_approval_gate.py` (no network, injected now):
   submit policy matrix (BROADCAST/SEMI_AUTO/AUTO in+out of envelope);
   idempotent decide; TTL expiry on late decide; expire_stale batch;
   transition guard (cannot decide an APPROVED row); stats queries.

Before finishing: `ruff check` · `ruff format --check` · `mypy src/novax` ·
`pytest`. All green.

---

## P2.2 — [daemon] Wire the approval gate: admin cards, callbacks, expiry sweep

Wire P2.1 into `scripts/prod_daemon_xauusd.py`.

Requirements:
1. `--approval-mode {broadcast,semi,auto}` (default `broadcast` — current
   behavior unchanged) and env `TELEGRAM_ADMIN_IDS` (already in
   `.env.example`) parsed into a set of ints; refuse to start in `semi`/`auto`
   with no admin ids.
2. In `_handle_15m`, after all existing gates (score, news, dedupe, and the
   P1.2 RiskGovernor): `pa = gate.submit(sig.id, sig, now)`.
   - AUTO_APPROVED → existing broadcast + fan-out path, unchanged.
   - PENDING → send an approval card to the **notif channel** with
     `InlineKeyboardMarkup`: `✅ Approve` / `❌ Reject`
     (`callback_data=f"appr:{pa.id}:1|0"`), plus a plain summary line
     (direction, entry, SL, TP, score, TTL). Card text via a new pure
     `fmt_approval_card(...)` in `src/novax/live/messages.py`.
3. `CallbackQueryHandler` for `^appr:`: **authz first** (`from_user.id` in
   admin ids, else answer "not authorized" and do nothing); route to
   `gate.decide(...)`; answer the callback with the resulting status; remove
   the inline keyboard; on APPROVED, run the broadcast + fan-out path for
   that stored signal.
4. In the scheduler loop, call `gate.expire_stale(now)` each iteration; for
   each newly expired card, edit the message to strike the buttons (best
   effort, ignore edit failures).
5. `auto_envelope` for AUTO mode (pure function, unit-tested): score ≥
   threshold AND news gate clear AND RiskGovernor not halted AND session in
   {LONDON, NY}. AUTO must be a strict subset of what SEMI_AUTO sees.
6. Tests in `tests/test_approval_wiring.py` (no network): callback-data
   parse/roundtrip; authz rejection; the auto_envelope predicate matrix;
   "which path runs per status" as a pure dispatch function.

Before finishing: `ruff check` · `ruff format --check` · `mypy src/novax` ·
`pytest`. All green.

---

## P2.3 — Promotion criteria: append to decision-log.md

Docs-only task. Append an entry to `docs/decision-log.md` (append-only file —
never edit existing entries) titled "Semi→Auto promotion criteria (pre-
committed)" with today's date, stating: auto-execution may launch only after
≥60 trading sessions in SEMI_AUTO with approval rate ≥90% on the score band
to be automated, expiry rate <10%, zero RiskGovernor halts caused by approved
signals, and live-vs-backtest tracking error within the OOS confidence
interval; and that AUTO launches with RiskGovernor limits at half the
SEMI_AUTO values for the first month. Note that the metrics come from
`ApprovalStore` stats queries (P2.1) so the review is mechanical, not
judgment-based.

---

## P3.1 — R-multiple performance stats (replace pips-only reporting)

The stats surfaced by `/stats` and the weekly report are in raw pips with no
risk normalization — misleading across ATR regimes and account sizes.

Requirements:
1. `SignalStore` already persists `sl_pips` per signal. Add
   `pnl_r` (REAL, nullable) to the schema with a migration path for existing
   DBs (ALTER TABLE if column missing, same pattern as any existing schema
   evolution in `signal_store.py`). When `update_status` records `pnl_pips`
   and the row has `sl_pips > 0`, also store `pnl_r = pnl_pips / sl_pips`.
2. New pure module `src/novax/live/performance.py`: given closed-signal rows,
   compute `expectancy_r`, `profit_factor`, `win_rate`, `max_drawdown_r`
   (peak-to-trough on cumulative R), `longest_losing_streak`. Reuse/align
   with the definitions in `src/novax/metrics.py` where they exist — do not
   fork the drawdown definition.
3. Update `fmt_cmd_stats` and `fmt_weekly_performance` in
   `src/novax/live/messages.py` to lead with expectancy (R) and show win rate
   alongside it, never alone. Keep pips as a secondary line. Reuse
   `DISCLAIMER`.
4. Tests in `tests/test_performance.py`: each metric against hand-computed
   fixtures (include an all-loss streak, a zero-trade case, and a case where
   win_rate < 50% but expectancy_r > 0); migration adds the column
   idempotently.

Before finishing: `ruff check` · `ruff format --check` · `mypy src/novax` ·
`pytest`. All green.

---

## P3.2 — Transparency scorecard: query layer + monthly Telegram post + admin page

Build the monthly transparency scorecard on top of P3.1 and the P2.1 audit
store. One query layer; two renderers.

Requirements:
1. `src/novax/live/scorecard.py` (pure over injected stores): for a given
   month, assemble: signals emitted (all statuses, including expired and
   rejected — nothing hidden), win rate, expectancy (R), profit factor, max
   drawdown (R), longest losing streak, daily halts triggered (from
   `RiskLedger.history` / halt events), approval rate + expiry rate (from
   `ApprovalStore`), and live-vs-backtest tracking error (live expectancy
   minus the OOS backtest expectancy, the latter passed in as a constant from
   the gated artifact).
2. `fmt_monthly_scorecard(...)` in `live/messages.py`: a Telegram-ready
   monthly post. Losses shown at full size; every number traceable to the
   stores; ends with `DISCLAIMER`.
3. Daemon: on the first `DAILY_REPORT` of each month (the existing
   archival branch in `_handle_daily_report` already detects `now.day == 1`),
   also send the scorecard for the previous month to the main channel.
4. Admin panel: add a read-only "Scorecard" view to `src/novax/admin/`
   (follow the existing app.py/services.py/views split and auth) rendering
   the same struct — the admin page and the Telegram post must come from the
   same `scorecard.py` output, never parallel computations.
5. Tests in `tests/test_scorecard.py`: scorecard assembly against fixture
   stores (including a month with zero signals); formatter includes every
   metric and the disclaimer; admin service returns the same numbers as the
   formatter input.

Before finishing: `ruff check` · `ruff format --check` · `mypy src/novax` ·
`pytest`. All green.

---

## T1 — [daemon] Signal lifecycle tracking: broadcast outcomes for every alerted signal

Today an alerted signal is fire-and-forget from the channel's point of view:
the PaperTrader tracks one internal position and `SignalStore` statuses are
updated silently, but subscribers never see "signal hit TP" or "signal
stopped out." Build public, per-signal outcome tracking for **every alerted
signal**, independent of the single paper position.

Requirements:
1. New pure module `src/novax/live/signal_tracker.py` (no telegram, no
   network): `SignalTracker(state_path, max_age=timedelta(hours=48))`
   maintaining a persisted set of open tracked signals (atomic JSON, same
   tmp + `os.replace` pattern as `PaperTrader`):
   - `track(signal_id, direction, entry, sl, tp, ts)` — called when an alert
     is broadcast;
   - `on_bar(bar) -> list[TrackerEvent]` — for each open signal, check
     `bar.low`/`bar.high` against SL/TP (SL checked **before** TP when a bar
     spans both — match `paper_trader.py`'s conservative ordering); breach →
     emit `TP_HIT`/`SL_HIT` event with pnl_pips and pnl_r (pnl / sl
     distance) and remove from open set; older than `max_age` → emit
     `EXPIRED` with market-price pnl;
   - `open_signals() -> list[...]` with floating pips at a given price
     (for T2 and `/signal`).
2. `TrackerEvent` frozen dataclass: signal_id, kind (StrEnum: TP_HIT,
   SL_HIT, EXPIRED), ts, entry, exit_price, pnl_pips, pnl_r.
3. Formatters in `src/novax/live/messages.py` (pure):
   `fmt_signal_outcome(event, running_record)` — e.g. "✅ TP HIT +90 pips
   (+2.0R)" / "🛑 SL HIT −45 pips (−1.0R)", entry→exit, duration, and a
   running-record line ("This month: 5W–8L · +2.1R") built from
   `SignalStore` counts. Wins and losses formatted with identical
   prominence. Reuse `DISCLAIMER` policy.
4. Wire into `scripts/prod_daemon_xauusd.py`:
   - after a confluence alert is broadcast, call `tracker.track(...)` with
     the stored signal's id/entry/SL/TP and set that row ACTIVE;
   - in `_handle_15m`, after fetching bars, call
     `tracker.on_bar(bars_m15[-1])`; for each event: update the
     `SignalStore` row (WIN/LOSS/EXPIRED with pnl_pips, pnl_r), broadcast
     `fmt_signal_outcome` to the main channel, and fan the outcome out via
     the existing `dispatch_signal` path so subscribed users get closure on
     signals they received;
   - feed `RiskGovernor.record_fill(pnl_r)` from tracker events instead of
     (or in addition to) the paper-trader branch — the tracker is now the
     authoritative public record; keep PaperTrader as internal bookkeeping.
   - boot: `reconcile_on_boot` (P1.3) extends to tracked signals — open
     tracked ids must exist as ACTIVE rows and vice versa.
5. Tests in `tests/test_signal_tracker.py` (no network, tmp_path, injected
   bars): TP breach, SL breach, both-in-one-bar → SL wins, expiry, multiple
   concurrent tracked signals resolving on different bars, persistence
   round-trip, floating-pips computation, running-record formatting.

Before finishing: `ruff check` · `ruff format --check` · `mypy src/novax` ·
`pytest`. All green.

---

## T2 — [daemon] Hourly market pulse (cadence without diluting the signal bar)

Give the channel an hourly heartbeat so it never looks dead between signals —
without lowering the score-70 signal threshold, which is what protects the
edge.

Requirements:
1. New `EventType.HOURLY_PULSE` in `src/novax/live/event_scheduler.py`,
   firing at the top of each hour Mon–Fri, **skipped** when it coincides with
   a 15M scan already producing a message, a 4H update, or a session-open
   event (pure precedence function, unit-tested).
2. `fmt_hourly_pulse(...)` in `live/messages.py` (pure): one compact message
   — current price, 4H trend arrow, 1H bias, distance to nearest key level
   (from `LevelStore`/day levels), and — if T1 has open tracked signals — a
   status line per open signal with floating pips ("📍 LONG 2410.50 · now
   +12.3 pips · TP 90 away"). No entry advice when there is no signal; it is
   a market read, not a call to action.
3. Daemon handler `_handle_hourly_pulse`: reuse the cached
   `state.last_result`/`last_price` when fresh (< 20 min), else fetch 1H
   bars via the P1.1 retry helper. Send to the main channel. `--pulse`
   flag (default on) to disable.
4. Rate safety: pulse must never send more than one message; failures log
   and skip (never retry-spam the channel).
5. Tests in `tests/test_hourly_pulse.py`: scheduler emits HOURLY_PULSE at
   hour marks and the precedence/skip logic; formatter with 0, 1, and 2 open
   tracked signals; stale-cache decision function.

Before finishing: `ruff check` · `ruff format --check` · `mypy src/novax` ·
`pytest`. All green.
