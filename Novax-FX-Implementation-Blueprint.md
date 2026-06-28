# Novax FX Platform — Implementation-Ready Technical Blueprint

*Companion to the founding-team strategy blueprint. This document is the buildable layer: concrete services, schemas, APIs, event flows, sprints, and standards.*

> **Not financial advice; no promise of profit.** This is trading *technology* design. Every live-capital and commercial step is gated behind honest validation. The architecture below optimizes for a fast, rigorous, auditable research loop first.

---

# PART I — Sections 1–23 (Decision Recap)

The full reasoning is in the strategy blueprint; here are the locked decisions so this document stands alone.

**1. Executive Summary.** Research-first FX intelligence platform. Edge before infrastructure; research↔live code parity (NautilusTrader) as the #1 risk control; statistical honesty (deflated Sharpe, purged CV, walk-forward, lockbox) as the core discipline. MVP = research loop + paper, **no live capital, no premature ML/infra**.

**2. Product Vision.** Gated maturity: Research → Signal intelligence → Paper → Semi-auto → Full-auto → SaaS. Moat = trustworthy, explainable, auditable intelligence + risk discipline.

**3. Market & Sessions.** Majors + high-vol JPY/GBP crosses + **XAU/USD** first-class. Sessions stored in **UTC**, defined in exchange tz with **DST awareness** (London/NY DST calendars differ — overlap window shifts). FX "volume" = tick-volume proxy; spread is broker-specific.

**4. Strategy Library.** Common falsifiable-hypothesis template (thesis required). Priority strategies: Asian-range breakout, SMC liquidity-sweep+BOS, NY ORB, overlap continuation/reversal, trend-pullback (MTF), VWAP mean-reversion, vol-expansion, news momentum/fade, S/R liquidity, correlation-aware overlay, macro gate.

**5. Data Architecture.** Raw immutable landing (Parquet) → normalized/curated (TimescaleDB + Parquet) → point-in-time feature layer → outputs. Providers: OANDA v20 (practice) + Dukascopy (history) + TwelveData (secondary) for MVP; pay for pro data (Databento/Polygon) only post-validation.

**6. Technical Architecture.** Hybrid modular monolith + a few worker processes (detail in B). Strict research/paper/live separation. Defer Kafka, K8s, feature store, microservices.

**7. Tech Stack.** Python 3.12, Polars+DuckDB+Parquet, PostgreSQL+TimescaleDB, Redis, NautilusTrader (core), VectorBT (screening), MLflow, scikit-learn/LightGBM, FastAPI, Next.js+TS, Lightweight-Charts, Prometheus+Grafana+OpenTelemetry, Evidently, Prefect, Docker/compose, OANDA→IBKR brokers.

**8. Open-Source.** Use: Nautilus, VectorBT, Polars, DuckDB, Timescale, MLflow, LightGBM, FastAPI, Next.js, Lightweight-Charts, Prometheus/Grafana/OTel, Evidently, Prefect. Evaluate later: Dagster, Feast, Redpanda, Qlib. Avoid: Zipline (unmaintained), Backtrader (stale, no research-live parity), Lean (C#, cloud-coupled).

**9. DB Overview.** PostgreSQL (relational/transactional + Timescale extension for time-series), Redis (cache/locks/pub-sub), object storage/MinIO (Parquet artifacts, model binaries, raw landing). Full schema in C.

**10. Signal Scoring.** Transparent decomposable 0–100: `base_expectancy(session,regime) × regime_fit × vol_filter × spread_penalty × news_modifier × correlation_penalty × [ml_prob_modifier]`. All components persisted; hard gates suppress regardless of score.

**11. ML/AI.** Baselines first (rules/LightGBM); PyTorch only when it beats them OOS. Triple-barrier labels, purged k-fold + embargo, walk-forward + lockbox, calibration metrics, drift monitoring, multiple-testing discounting. ML is a *modifier/filter*, not an oracle.

**12. News/Macro.** Calendar with consensus/actual/surprise; news blackout windows (hard gate); sentiment as modifier; macro regime gate (DXY/yields/risk-on-off).

**13. Backtesting.** Realistic costs (spread/slippage/commission, session liquidity, news vol), UTC+DST correctness, walk-forward, OOS lockbox, Monte Carlo on trade sequence, parameter-plateau robustness, **deflated Sharpe**, portfolio correlation, full reproducibility (commit + data hash + params).

**14. Risk.** Pre-trade gate for every signal (research/paper/live): per-trade/daily/weekly loss, max DD halt, correlated/USD exposure, max positions, session budgets, news blackout, spread/vol filters, kill switch, manual override, append-only audit. Ships in MVP.

**15. Execution.** OANDA v20 (paper→semi-auto), IBKR `ib-async` later, cTrader alt, MT5 only if needed, FIX at institutional scale. Broker-adapter abstraction; Nautilus shares strategy layer across backtest/live.

**16. Frontend.** Signal feed (with score breakdown), strategy perf by session×regime×pair, session/pair analytics, backtest UI, paper monitor → live monitor, risk dashboard, model dashboard, Telegram/email/push alerts. Lightweight-Charts + Plotly/ECharts.

**17. Team.** MVP 1–3 (founder-CTO + validation-capable quant + part-time FE). Seed 5–8 (+ML, data eng, FE, fractional risk/compliance). Growth 12+ (MLOps, quants, backend, SRE, compliance, GTM). Hire order: quant → data/backend → ML → FE → DevOps → compliance → GTM.

**18. Business.** Signal-intelligence SaaS → pro tools → risk analytics → prop-firm analytics → API → marketplace → white-label. Cross-border (Iran↔intl) payments/sanctions/compliance is a real design constraint — engage counsel early; position as tooling, not advice.

**19. Roadmap.** P0 validation → P1 data → P2 backtest/strategy → P3 scoring/dashboard → P4 ML/news → P5 paper → P6 semi-auto → P7 full-auto (gated) → P8 SaaS. (Sprint-level detail in G.)

**20. MVP Scope.** In: 3–4 instruments ingestion, Timescale+Parquet, point-in-time features, Nautilus backtester w/ realistic costs + DST, walk-forward+lockbox+deflated Sharpe, 2–3 strategies, transparent score, risk engine, read-only dashboard + Telegram, audit+reproducibility. Out: live capital, full ML, feature store, Kafka, K8s, marketplace, multi-tenant SaaS.

**21. Avoid.** Live before validation; curve-fitting/ignoring multiple-testing; backtesting on non-execution data; hardcoded UTC sessions; treating tick-volume as real volume; premature infra; ML theater; marketplace before one validated edge; secrets in repo; profit guarantees.

**22. Key Risks.** Edge may not survive costs (dominant); overfitting/self-deception; data quality/FX-volume fiction; non-stationarity/decay; backtest↔live divergence; DST bugs; live slippage; regulatory/payments; secrets/ops.

**23. First 90 Days.** Wk1–2 edge spike (EUR/USD+XAU/USD, one SMC strategy); Wk3–5 data foundation; Wk6–9 serious backtesting; Wk10–11 score+risk+thin UI; Wk12 go/no-go. Rule: no real capital and no downstream tiers until a strategy survives honest validation.

---

# PART II — Implementation Detail (A–J)

## A. System Decomposition

Each module specified as: **purpose · responsibilities · inputs · outputs · internal deps · external deps · MVP placement · scale/ops notes.**

### A1. `ingestion-market` (Market Data Ingestor)
- **Purpose:** pull/stream price data from brokers/providers.
- **Responsibilities:** REST backfill + WebSocket streaming; dedup; raw landing; emit `market.tick`/`market.bar.closed`.
- **Inputs:** OANDA/Dukascopy/TwelveData feeds.
- **Outputs:** raw Parquet, normalized rows → Timescale, Redis pub-sub events.
- **Internal deps:** normalization, audit. **External deps:** broker/provider APIs.
- **MVP placement:** **separate worker process** (long-running streaming loop must not block the API).
- **Scale/ops:** per-provider rate limits, reconnect/backoff, gap detection & backfill, idempotency keys.

### A2. `ingestion-news` & `ingestion-calendar`
- **Purpose:** ingest news headlines/bodies + economic calendar (consensus/actual/surprise) + central-bank events.
- **Outputs:** `news_articles`, `economic_events`; events `news.ingested`, `calendar.event.upcoming`.
- **MVP placement:** **scheduled jobs** (Prefect flows), not always-on.
- **Scale/ops:** source reliability, dedup, timezone normalization, entity tagging.

### A3. `normalization` (Data Normalizer)
- **Purpose:** clean → canonical schema, UTC, gap-flag, resample 1m→HTF.
- **MVP placement:** **library inside monolith** + invoked by ingestion workers.
- **Scale/ops:** point-in-time correctness; deterministic resampling.

### A4. `feature-engine` (Feature Engineering)
- **Purpose:** compute point-in-time features (ATR, ranges, session stats, structure/BOS, regime inputs).
- **Outputs:** `feature_snapshots`.
- **MVP placement:** **library in monolith**; heavy batch runs as worker tasks.
- **Scale/ops:** **no lookahead**; versioned feature sets; reproducible.

### A5. `strategy-engine`
- **Purpose:** evaluate strategy rules → candidate signals.
- **Internal deps:** feature-engine, regime, news state.
- **MVP placement:** **core library in monolith** (Nautilus strategy objects).
- **Scale/ops:** strategies versioned; same object used in backtest/paper/live.

### A6. `backtest-engine`
- **Purpose:** event-driven backtests + walk-forward + Monte Carlo with realistic costs.
- **Outputs:** `backtest_runs`, `backtest_trades`, artifacts to object storage.
- **MVP placement:** **worker pool** (CPU-heavy; async via Prefect/queue).
- **Scale/ops:** reproducibility (commit+data hash+params); parallel param sweeps.

### A7. `scoring-engine`
- **Purpose:** turn candidate signals into scored, gated signals.
- **MVP placement:** **library in monolith**.
- **Scale/ops:** store score components; deterministic and explainable.

### A8. `risk-engine`
- **Purpose:** pre-trade gate; portfolio exposure; kill switch; limits.
- **MVP placement:** **library in monolith** (called by scoring + paper + live).
- **Scale/ops:** must be synchronous + fast; append-only `risk_events`.

### A9. `ml-platform` (training + inference)
- **Purpose:** train baselines, register models, serve inference.
- **External deps:** MLflow.
- **MVP placement:** **training = worker/offline; inference = library** (small models in-process). Extract a serving service only later.
- **Scale/ops:** drift monitoring, retrain schedules, model registry.

### A10. `paper-engine`
- **Purpose:** simulate fills on live data through the *real* risk engine; track signal→outcome.
- **MVP placement:** **worker process** subscribing to market + signal events.
- **Scale/ops:** realistic fill model; reconcile vs backtest assumptions.

### A11. `execution-adapter` (broker layer) — *deferred to semi-auto stage*
- **Purpose:** broker-agnostic order placement (OANDA→IBKR).
- **MVP placement:** **stub interface only in MVP**; real impl at P6.

### A12. `api-gateway` (FastAPI)
- **Purpose:** REST + WebSocket surface; auth; orchestrates domain libs.
- **MVP placement:** **the monolith's HTTP front**.

### A13. `frontend` (Next.js)
- **MVP placement:** **separate app**, talks to api-gateway.

### A14. `alerting` & `audit`
- **Purpose:** Telegram/email/push; append-only audit of every signal/decision/override.
- **MVP placement:** **libraries/workers in monolith**; audit is non-negotiable from day 1.

---

## B. Recommended MVP Architecture

**Decision: Hybrid modular monolith + a small number of long-running worker processes.** Not microservices.

**The shape:**
- **One deployable monolith** (`apps/api`) containing all domain *logic* as clean internal libraries: normalization, feature-engine, strategy-engine, scoring, risk, ml-inference, audit, alerting — behind a FastAPI gateway.
- **A few separate processes** that genuinely need their own lifecycle: `ingestion-market` (always-on streaming), `paper-engine` (always-on consumer), and a `worker` pool for backtests/training/feature-batch (CPU-heavy, queued via Prefect).
- **Shared via:** one PostgreSQL (with TimescaleDB extension), Redis (pub-sub + cache + locks), object storage (MinIO/S3) for artifacts.

**Why this is correct for the MVP:**
- A pre-PMF, pre-edge research platform changes shape constantly. Microservices freeze module boundaries you haven't learned yet, and add network/ops tax that buys nothing while you're a 1–3 person team.
- The monolith keeps domain logic *colocated and refactorable*; clean internal module boundaries mean you can extract a true service later (model serving, execution) with low cost.
- Streaming ingestion and paper-engine genuinely can't live inside a request/response API process, so they're separate — but they're *processes*, not microservices with their own datastores.

**Stay together:** strategy/scoring/risk/feature logic (they co-evolve fast and are called in one synchronous decision path). **Separate:** anything always-on (ingestion, paper) and anything CPU-heavy/async (backtests, training). **Don't build yet:** service mesh, K8s, Kafka, Feast, multi-tenant SaaS plumbing, a model-serving microservice, execution adapter.

---

## C. Database Design

**Stores:**
- **PostgreSQL** — all relational/transactional state: users, instruments, strategies/versions, signals, scores, backtests, paper trades, orders/executions, models, regime labels, risk events, audit, alerts, jobs.
- **TimescaleDB (Postgres extension, same instance for MVP)** — hypertables for `market_ticks`, `market_bars`, `spreads` (high-volume time-series). One DB engine, two roles — simpler ops.
- **Redis** — pub-sub events, hot cache (latest bar/quote), locks, rate-limit counters, ephemeral realtime state.
- **Object storage (MinIO → S3)** — raw data landing (Parquet), backtest artifacts (equity curves, trade blotters), model binaries, large feature batches.

**Schema (key tables — fields abbreviated; all timestamps `TIMESTAMPTZ` in UTC):**

| Table | Purpose | Key fields | PK | FKs | Indexes | Partition |
|---|---|---|---|---|---|---|
| `users` | accounts | id, email, role, created_at | id | — | uniq(email) | — |
| `workspaces` | future multi-tenant | id, name, owner_id | id | owner_id→users | — | — |
| `instruments` | tradable symbols | id, symbol, type(fx/metal), pip_size, session_profile | id | — | uniq(symbol) | — |
| `market_ticks` | raw quotes | instrument_id, ts, bid, ask, source | (instrument_id,ts) | instrument_id | (instrument_id,ts desc) | **hypertable by ts** |
| `market_bars` | OHLCV | instrument_id, tf, ts, o,h,l,c, tick_vol, source | (instrument_id,tf,ts) | instrument_id | (instrument_id,tf,ts desc) | **hypertable by ts**, space by instrument |
| `spreads` | spread series | instrument_id, ts, spread, source | (instrument_id,ts) | instrument_id | (instrument_id,ts) | **hypertable by ts** |
| `economic_events` | calendar | id, ts, currency, name, impact, consensus, actual, surprise | id | — | (ts), (currency,ts) | by ts (range) |
| `news_articles` | headlines/body | id, ts, source, headline, body, entities(jsonb) | id | — | (ts), GIN(entities) | by ts |
| `news_sentiment` | scored news | id, article_id, model_ver, score, label | id | article_id→news_articles | (article_id) | — |
| `strategies` | strategy registry | id, key, name, status | id | — | uniq(key) | — |
| `strategy_versions` | immutable versions | id, strategy_id, version, spec(jsonb), spec_hash, code_commit, created_at | id | strategy_id→strategies | uniq(strategy_id,version) | — |
| `feature_snapshots` | point-in-time features | id, instrument_id, ts, feature_set_ver, payload(jsonb) | id | instrument_id | (instrument_id,ts,feature_set_ver) | by ts |
| `regime_labels` | regime per window | id, instrument_id, ts, tf, regime, method_ver | id | instrument_id | (instrument_id,ts) | by ts |
| `backtest_runs` | backtest metadata | id, strategy_ver_id, data_range, params(jsonb), cost_model(jsonb), metrics(jsonb), data_hash, code_commit, artifact_uri, created_at | id | strategy_ver_id→strategy_versions | (strategy_ver_id) | — |
| `backtest_trades` | per-trade results | id, run_id, instrument_id, entry_ts, exit_ts, side, entry, exit, sl, tp, pnl, costs | id | run_id→backtest_runs | (run_id) | by entry_ts |
| `signals` | generated signals | id, strategy_ver_id, instrument_id, ts, direction, entry, sl, tp, session, regime, news_state, status | id | strategy_ver_id, instrument_id | (instrument_id,ts), (status) | by ts |
| `signal_scores` | score breakdown | id, signal_id, score, components(jsonb), model_ver | id | signal_id→signals | uniq(signal_id) | — |
| `paper_positions` | sim positions | id, signal_id, instrument_id, qty, entry_ts, entry, sl, tp, status, pnl | id | signal_id, instrument_id | (status) | — |
| `orders` | order intents | id, signal_id, broker_account_id, type, side, qty, price, status, ts | id | signal_id, broker_account_id | (status,ts) | by ts |
| `executions` | fills | id, order_id, fill_price, fill_qty, slippage, commission, ts | id | order_id→orders | (order_id) | by ts |
| `broker_accounts` | broker creds ref | id, workspace_id, broker, account_ref, env(paper/live) | id | workspace_id | — | — |
| `model_registry` | logical models | id, name, task, status | id | — | uniq(name) | — |
| `model_runs` | training runs | id, model_id, version, mlflow_run, metrics(jsonb), train_data_hash, status, created_at | id | model_id→model_registry | (model_id,version) | — |
| `risk_events` | gate verdicts/limits | id, ts, type, severity, signal_id?, detail(jsonb) | id | signal_id? | (ts), (type) | by ts (append-only) |
| `audit_logs` | append-only audit | id, ts, actor, action, entity, entity_id, payload(jsonb) | id | — | (ts), (entity,entity_id) | by ts (append-only) |
| `alerts` | outbound alerts | id, ts, channel, target, payload, status | id | — | (status,ts) | by ts |
| `system_jobs` | job runs | id, name, status, started_at, finished_at, detail(jsonb) | id | — | (name,started_at) | by ts |

**Retention strategy.** Ticks: keep ~30–90d hot in Timescale, then compress + tier raw to Parquet/object storage (cheap, queryable via DuckDB). Bars: keep long (small). Use Timescale **compression policies** + **continuous aggregates** for HTF rollups. Audit/risk: never delete (append-only, compress old chunks).

**Time-series strategy.** Hypertables on ticks/bars/spreads; space-partition bars by `instrument_id`; continuous aggregates for 5m/15m/1h/4h/1d from 1m; compression after N days.

**Versioning strategy.** Strategies and models are **immutable-version tables** (`strategy_versions`, `model_runs`) — never mutate a version; create a new one. Every backtest/signal references the exact `strategy_ver_id` (+ code_commit + data_hash) and every prediction references `model_ver`. This guarantees reproducibility and a clean audit trail.

---

## D. Repository / Codebase Structure

**Decision: Monorepo.** A 1–3 person team sharing domain models, types, and the *same* strategy code across research/backtest/paper/live benefits enormously from atomic commits and one source of truth. Polyrepo's isolation buys nothing yet and fractures the shared domain. (Revisit only if separate teams/release cadences emerge.)

```
novax/
  apps/
    api/                 # FastAPI gateway (the monolith) — REST + WS, auth, orchestrates libs
    worker/              # Prefect/queue workers: backtests, training, feature batches
    ingestion-market/    # always-on streaming consumer
    paper-engine/        # always-on paper-trading consumer
  libs/
    domain/              # entities, enums, value objects (shared across apps)
    data/                # normalization, resampling, providers' adapters, point-in-time joins
    features/            # feature engineering (versioned feature sets)
    strategies/          # Nautilus strategy objects + strategy specs/registry
    backtest/            # backtest orchestration, walk-forward, monte carlo, cost models
    scoring/             # signal scoring + gates
    risk/                # risk engine (pre-trade checks, limits, kill switch)
    ml/                  # training pipelines, labeling (triple-barrier), CV (purged+embargo), inference
    execution/           # broker-adapter interface (stub in MVP) + OANDA/IBKR impls later
    alerting/            # Telegram/email/push
    audit/               # append-only audit helpers
    common/              # config, logging, OTel, db session, redis, object-store clients
  research/
    notebooks/           # exploratory; NOT in the production path
    experiments/         # tracked experiment scripts (MLflow-logged)
  frontend/              # Next.js + TS app
  infra/
    docker/              # Dockerfiles, docker-compose
    ci/                  # GitHub Actions workflows
    migrations/          # Alembic
    grafana/ prometheus/ # dashboards, scrape configs
    terraform/           # (later, growth stage)
  docs/
    adr/                 # architecture decision records
    runbooks/            # ops runbooks, incident playbooks
    api/                 # OpenAPI, event catalog
```

**What lives where:** all *logic* in `libs/` (pure, testable, framework-light); `apps/` are thin runtimes that wire libs to a transport (HTTP, queue, stream). `research/` is a sandbox that *imports* `libs/` but is never imported *by* production. This is the clean-architecture boundary: dependencies point inward toward `domain/`.

---

## E. API Design

Versioned under `/api/v1`. Auth via JWT (bearer); roles `research`, `trader`, `admin`, `operator`. Shapes abbreviated.

**Auth**
- `POST /auth/login` → `{token}` · public
- `POST /auth/refresh` → `{token}` · auth
- `GET /auth/me` → `{user}` · auth

**Instruments**
- `GET /instruments` → `[{id,symbol,type,pip_size}]` · auth
- `GET /instruments/{id}/sessions` → session windows (DST-correct) · auth

**Market data**
- `GET /market/bars?instrument=&tf=&from=&to=` → OHLCV array · auth
- `GET /market/spread?instrument=&from=&to=` → spread series · auth
- `WS /ws/market` → subscribe channels `bar.{instrument}.{tf}`, `quote.{instrument}` · auth

**Strategies**
- `GET /strategies` → list · auth
- `GET /strategies/{key}/versions` → versions · auth
- `POST /strategies/{key}/versions` `{spec}` → new immutable version · admin
- `GET /strategies/{key}/performance?by=session|regime|pair` → metrics · auth

**Backtests**
- `POST /backtests` `{strategy_ver_id, instruments, date_range, params, cost_model}` → `{run_id, status}` · research
- `GET /backtests/{run_id}` → metrics + artifact_uri · research
- `GET /backtests/{run_id}/trades` → blotter · research
- `POST /backtests/{run_id}/walk-forward` `{windows}` → wf result · research
- `WS /ws/jobs` → `job.{run_id}.progress` · research

**Signals & scoring**
- `GET /signals?instrument=&status=&from=&to=` → signals · auth
- `GET /signals/{id}` → signal + score breakdown · auth
- `GET /signals/{id}/score` → `{score, components}` · auth
- `WS /ws/signals` → `signal.generated` stream · auth

**News & calendar**
- `GET /news?from=&to=&currency=` → articles + sentiment · auth
- `GET /calendar?from=&to=&impact=` → economic events · auth
- `GET /calendar/blackouts?instrument=` → active/upcoming blackout windows · auth

**Paper trading**
- `GET /paper/positions?status=` → positions · trader
- `GET /paper/pnl?from=&to=` → pnl curve · trader
- `WS /ws/paper` → `paper.position.updated` · trader

**Risk**
- `GET /risk/status` → limits, exposure, utilization · trader
- `GET /risk/events?from=&to=` → risk_events · trader
- `POST /risk/kill-switch` `{reason}` → halt all · admin
- `POST /risk/override` `{scope, reason}` → override (audited) · admin

**Models**
- `GET /models` → registry · research
- `GET /models/{name}/runs` → versions + metrics · research
- `GET /models/{name}/drift` → drift report · research

**Admin / monitoring**
- `GET /admin/jobs` → system_jobs · admin
- `GET /admin/audit?entity=&from=&to=` → audit logs · admin
- `GET /health` `GET /ready` `GET /metrics` (Prometheus) · operator/public-internal

---

## F. Service-to-Service Interactions

**Synchronous (in-process or REST):** the decision path — `feature-engine → strategy-engine → scoring-engine → risk-engine` — runs synchronously within the monolith for one bar/signal (fast, deterministic, fully audited). Frontend ↔ api-gateway is REST + WS.

**Asynchronous (Redis Streams in MVP; Redpanda/Kafka later):** decoupled producers/consumers via a small event bus. Workers (backtest/training) are dispatched via Prefect/queue.

**Event catalog (channel names):**
- `market.tick`, `market.bar.closed`
- `news.ingested`, `calendar.event.upcoming`, `news.blackout.activated`
- `signal.generated`, `signal.scored`, `signal.suppressed`
- `backtest.started`, `backtest.completed`
- `model.training.started`, `model.retrained`, `model.drift.detected`
- `risk.limit.triggered`, `risk.killswitch.activated`
- `paper.position.opened`, `paper.position.updated`, `paper.position.closed`
- `alert.dispatched`, `audit.recorded`

**Scheduled jobs (Prefect flows):** calendar/news ingestion (cron), nightly feature batch, walk-forward refresh, drift checks, decay monitors, data-gap backfill, Timescale compression policies.

**Signal generation flow:**
`market.bar.closed` → feature-engine computes point-in-time features → regime + news-state attached → strategy-engine evaluates → candidate → scoring-engine scores (+optional ML modifier) → **risk-engine pre-trade gate** → if pass: persist `signals`+`signal_scores`, emit `signal.generated`+`signal.scored`, dispatch alert; if fail: persist suppressed + `risk_events`, emit `signal.suppressed`.

**Paper trading flow:**
`signal.generated` → paper-engine opens sim position (realistic fill model) → on each `market.bar.closed` updates MTM, checks SL/TP → emits `paper.position.updated` → on exit persists outcome, emits `paper.position.closed` → reconcile vs backtest expectancy (decay monitor input).

**Retraining pipeline:**
schedule/drift trigger → worker pulls point-in-time training set (data_hash) → triple-barrier labels → purged k-fold + embargo CV → register in MLflow (`model_runs`) → if beats incumbent OOS → mark candidate → manual promote → `model.retrained`.

---

## G. MVP Delivery Plan — 12 Weeks / 6 Sprints (2 wk each)

> Roles assume a small team; one person may cover several. "Quant" = validation-capable researcher.

### Sprint 1 (Wk 1–2) — Foundation & Market Ingestion
- **Goal:** repo, CI, observability skeleton, and trustworthy market data landing for 3–4 instruments.
- **Eng:** monorepo scaffold, `common` (config/logging/OTel/db/redis/object-store), `apps/api` health/ready/metrics, Docker compose (Postgres+Timescale, Redis, MinIO, Grafana, Prometheus).
- **Data:** `ingestion-market` (OANDA practice + Dukascopy backfill), raw Parquet landing, `market_bars`/`spreads` hypertables, gap detection.
- **Quant:** define instrument list, session profiles (DST-correct), data-quality checks.
- **DevOps:** GitHub Actions (lint/test/build → GHCR), compose deploy to VPS.
- **Testing:** data-quality unit tests, ingestion idempotency tests.
- **Deliverables:** reproducible data foundation; dashboards show ingestion health.
- **Dependencies:** broker/provider keys (in secrets manager). **Risks:** provider rate limits, gap handling, DST correctness.

### Sprint 2 (Wk 3–4) — Normalization, Features, Regime
- **Goal:** point-in-time feature layer + regime labels.
- **Eng:** `data` (normalization, resampling 1m→HTF, point-in-time joins), `features` (ATR, ranges, session stats, structure/BOS primitives), `feature_snapshots`.
- **Quant:** regime method v0 (rules + rolling stats), `regime_labels`; **fix the "RANGING 100%" class of bug** with real OHLCV.
- **Testing:** **no-lookahead** property tests; resampling determinism; BOS/sweep unit tests.
- **Deliverables:** versioned features + regime on real history. **Risks:** leakage, feature reproducibility.

### Sprint 3 (Wk 5–6) — Strategy Engine & Backtester
- **Goal:** event-driven backtests with realistic costs for 2–3 strategies.
- **Eng:** integrate **NautilusTrader**; `strategies` (Asian-range breakout, SMC liquidity-sweep+BOS, NY ORB); cost models (spread/slippage/commission, session liquidity).
- **Quant:** strategy specs filled from template; sanity backtests.
- **DevOps:** `apps/worker` + Prefect for backtest jobs; artifacts to MinIO.
- **Testing:** cost-model tests; SL/TP execution-edge cases; DST window tests.
- **Deliverables:** `backtest_runs`/`backtest_trades` + artifacts, reproducible (commit+data_hash). **Risks:** intrabar fill ambiguity, cost realism.

### Sprint 4 (Wk 7–8) — Validation & Signal Generation
- **Goal:** trustworthy validation + live candidate signals.
- **Eng:** walk-forward, OOS lockbox, Monte Carlo, **deflated Sharpe**; signal-generation path on `market.bar.closed`.
- **Quant:** parameter-robustness (plateau) analysis; decay monitors; go/no-go criteria.
- **ML:** *optional* baseline prob-of-success (LightGBM) — only if time; behind a flag.
- **Testing:** purged-CV correctness tests; reproducibility of walk-forward.
- **Deliverables:** validation report per strategy; `signals` emitted live. **Risks:** overfitting, multiple-testing self-deception.

### Sprint 5 (Wk 9–10) — Scoring, Risk Engine, API, Thin Dashboard
- **Goal:** scored+gated signals exposed via API and a read-only UI.
- **Eng:** `scoring` (decomposable score + components), `risk` (pre-trade gate, limits, exposure, kill switch, `risk_events`), api-gateway endpoints (E), WS channels.
- **Frontend:** Next.js signal feed (with score breakdown), strategy performance, session/pair analytics, risk status — Lightweight-Charts.
- **Eng/audit:** append-only `audit_logs` on every signal/decision/override.
- **Testing:** risk-gate unit tests (every limit), API contract tests, score determinism.
- **Deliverables:** explainable scored signals end-to-end; Telegram alerts. **Risks:** score explainability, gate correctness.

### Sprint 6 (Wk 11–12) — Paper Trading, Observability, Hardening
- **Goal:** paper trading through the real risk engine + production-grade observability/audit.
- **Eng:** `paper-engine` (realistic fills), reconcile paper vs backtest expectancy; alerting hardening.
- **DevOps:** Grafana dashboards (ingestion, signals, risk, drift), OTel traces across the decision path, backups, runbooks.
- **Testing:** end-to-end paper flow tests; chaos on reconnect/gap; security pass (secrets, authz).
- **Deliverables:** running paper-trading loop + **go/no-go review** vs validation gates. **Risks:** paper↔backtest divergence (the key signal of whether to proceed).

---

## H. MVP User Stories

**Research user**
- As a researcher, I want to launch a backtest with explicit cost models, so that results reflect realistic execution.
- As a researcher, I want walk-forward + deflated-Sharpe results, so that I'm not fooled by overfitting.
- As a researcher, I want every backtest tied to a commit + data hash, so that results are reproducible.
- As a researcher, I want regime/session breakdowns of performance, so that I know *where* a strategy works.

**Trader user**
- As a trader, I want a live signal feed with a transparent score breakdown, so that I understand *why* a signal fired.
- As a trader, I want news-blackout and spread/vol gates applied automatically, so that I avoid toxic conditions.
- As a trader, I want a paper-trading monitor with PnL and open positions, so that I can judge real-world behavior before risking capital.
- As a trader, I want Telegram alerts on high-score signals, so that I don't have to watch screens.

**Admin user**
- As an admin, I want to publish new immutable strategy versions, so that history stays auditable.
- As an admin, I want a kill switch and override (both audited), so that I can halt the system instantly and safely.
- As an admin, I want to inspect the audit log for any signal/decision, so that I can explain every action.

**System operator**
- As an operator, I want health/ready/metrics + Grafana dashboards, so that I can see ingestion/signal/risk health.
- As an operator, I want alerts on data gaps, drift, and risk triggers, so that I can respond before damage.
- As an operator, I want documented runbooks, so that incidents have a known response.

---

## I. Engineering Standards

- **Coding conventions.** Python: `ruff` + `black` + `mypy` (typed everywhere in `libs/`); pure logic in libs, thin runtimes in apps; dependencies point inward (clean architecture). TS: ESLint + Prettier + strict tsconfig.
- **Testing pyramid.** Many fast unit tests (logic in libs, esp. no-lookahead/cost-model/risk-gate), fewer integration tests (db/redis/ingestion), few end-to-end (signal→paper). **TDD where logic is subtle** (risk, scoring, labeling, resampling). Property-based tests for time/leakage invariants.
- **CI/CD.** GitHub Actions: lint → type-check → test → build → push GHCR → deploy (compose on VPS for MVP). PRs require green CI + review. No direct pushes to main.
- **Observability.** OpenTelemetry traces across the decision path; Prometheus metrics; Grafana dashboards; structured JSON logs with correlation IDs. SLOs for ingestion freshness and signal latency.
- **Security baseline.** JWT auth + role-based authz; least privilege; TLS; input validation; dependency scanning; separate creds for research/paper/live; no broker live creds in MVP.
- **Secrets management.** Never in repo. Use a secrets manager (Doppler/Vault/SOPS-encrypted). Rotate on exposure. *(Carry the discipline from the existing Novax cleanup — no keys in compose files.)*
- **Migration policy.** Alembic; forward-only, reviewed, reversible where feasible; migrations in CI; never edit applied migrations.
- **API versioning.** `/api/v1`; additive changes preferred; breaking changes → new version; OpenAPI generated and committed.
- **Experiment tracking.** MLflow for every training run (params, metrics, artifacts, data hash). Research scripts log to MLflow; notebooks never in the production path.
- **Model & strategy versioning.** Immutable `strategy_versions` / `model_runs`; every signal/prediction references the exact version + code commit + data hash.
- **Logging standards.** Structured, leveled, no secrets/PII in logs; decision-path events logged at INFO with IDs; errors with context.
- **Audit trail.** Append-only `audit_logs` + `risk_events`; every signal, score, gate verdict, override, kill switch, and config change recorded with actor + timestamp + payload. Non-negotiable from Sprint 1.

---

## J. Final Implementation Recommendation

- **Best MVP architecture:** **hybrid modular monolith** (one FastAPI monolith of clean domain libs) **+ three long-running processes** (market ingestion, paper-engine, worker pool). One Postgres+Timescale, Redis, MinIO. No microservices, no K8s, no Kafka, no feature store yet.
- **First module to build:** the **data foundation** (`ingestion-market` + normalized `market_bars` + DST-correct sessions + reproducibility). Nothing downstream can be trusted without trustworthy, point-in-time data — and your existing system's "RANGING 100% on synthetic data" problem is exactly the failure this fixes.
- **Highest-risk area:** **whether a cost-surviving edge exists**, and in engineering terms, **backtest realism + leakage/lookahead**. A subtle lookahead bug or optimistic cost model produces a beautiful backtest and a losing live system. Guard it with property tests, purged CV, walk-forward, lockbox, and deflated Sharpe.
- **Biggest overengineering risk:** building **microservices / Kubernetes / Kafka / a feature store / a model-serving service / the marketplace** before a single strategy has survived validation. Every one of these is deferred until something downstream demands it.
- **Best order of implementation:** **data → features/regime → strategy engine + realistic backtester → validation (walk-forward/lockbox/deflated Sharpe) → scoring + risk → thin API/dashboard → paper trading → GO/NO-GO gate → (only then) semi-auto → full-auto → SaaS.**

**The governing rule, restated:** no real capital and no downstream tier until a strategy survives honest validation. Everything above is engineered to make that one judgment trustworthy — including the judgment to walk away from an idea that doesn't work.

---

*Coordinated founding-team design (CTO, Quant Lead, Senior FX Trader, ML Lead, Data/Backend/Frontend Eng, DevOps/MLOps, Risk, Product, Compliance). Engineering and research guidance only — not financial advice, no promise of profit. Validate everything; respect the risk layer; verify provider pricing and jurisdiction-specific legal/regulatory requirements before any commercial or live-capital step.*
