# Novax FX Intelligence Platform — Founding-Team Blueprint

*A senior founding-team design for an institutional-grade Forex research, signal, and (eventually) execution platform.*

> **Framing & disclaimer.** This is a technology and research design document, not financial advice and not a promise of profit. The central, uncomfortable truth that shapes every decision below: **the hard part is not the engineering — it is finding and validating a real, cost-surviving edge.** Most retail automated FX systems lose money after spread, slippage, and overfitting. This architecture is therefore optimized first for *fast, honest, rigorous research*, and treats live trading and SaaS as downstream privileges that must be *earned* through validation gates.

---

## 1. Executive Summary

**What we are building, in one sentence:** a research-first FX intelligence platform that ingests high-quality market + macro data, runs a library of session-aware strategies through a realistic backtesting/validation engine, scores signals with transparent (and later ML-assisted) logic under a strict risk layer, and graduates — only after proof — from research → paper → semi-auto → fully automated, with a SaaS product as the eventual commercial layer.

**The founding team's three load-bearing convictions:**

1. **Edge before infrastructure.** A beautiful Kafka/Kubernetes/feature-store stack with no validated edge is an expensive way to lose money. The MVP is a research loop, not a trading bot. We will deliberately *under-build* the plumbing until an edge justifies it.
2. **Research–live parity is the #1 risk control.** The largest source of "it worked in backtest, lost in live" is divergence between research code and execution code. We pick a stack (NautilusTrader) where the *same strategy object* runs in backtest, paper, and live. This single choice eliminates a whole class of failure.
3. **Statistical honesty is non-negotiable.** We will test dozens of strategy/parameter/regime combinations. Without multiple-testing correction (deflated Sharpe, purged CV, walk-forward, out-of-sample lockboxes), we *will* fool ourselves. Most of our engineering rigor goes into *not lying to ourselves*.

**MVP target (first ~90 days):** clean data foundation for 3–4 instruments, 2–3 strategies fully specified and implemented, a realistic event-driven backtester with spread/slippage/session/DST correctness, proper walk-forward validation with multiple-testing correction, a transparent rule-based signal score, and a thin read-only dashboard + Telegram alerts. **No live capital. No ML beyond simple baselines. No marketplace.**

---

## 2. Product Vision

A platform that progresses through clearly gated maturity stages, each unlocking the next only on validation:

- **Tier 0 — Research lab:** strategy R&D, backtesting, walk-forward, regime/session analytics. (Internal.)
- **Tier 1 — Signal intelligence:** scored, explainable signals delivered to a dashboard + alerts; full audit trail.
- **Tier 2 — Paper trading:** live data, simulated fills, real-time tracking of signal→outcome.
- **Tier 3 — Semi-automated:** human-in-the-loop confirmation before execution via broker API.
- **Tier 4 — Fully automated:** autonomous execution under a hard risk engine + kill switch.
- **Tier 5 — Commercial SaaS:** multi-tenant signal/analytics/risk products, API access, eventual marketplace.

The product's durable moat is **trustworthy, auditable, explainable intelligence + risk discipline**, not a black-box "money printer." That positioning is also the safest one legally and commercially.

---

## 3. Market & Forex Session Analysis

**Instrument focus.** Majors (EUR/USD, GBP/USD, USD/JPY, USD/CHF, AUD/USD, NZD/USD, USD/CAD) plus the high-vol crosses (EUR/JPY, GBP/JPY, EUR/GBP). Include **XAU/USD (gold)** explicitly — technically a metal, not an FX major, but it trades on FX-style flow, is hugely liquid, and is the most popular retail "FX" instrument; it deserves first-class treatment alongside the majors.

**Sessions (all logic stored in UTC, displayed in session tz, DST-aware):**

| Session | Typical character | Strategy fit |
|---|---|---|
| **Asian (Tokyo)** | Lower volatility, range-bound, JPY/AUD/NZD most active | Range definition, accumulation, liquidity build-up |
| **London** | Volatility expansion, trend initiation, EUR/GBP focus | Breakouts, liquidity sweeps of Asian range, trend starts |
| **London–NY overlap** | Highest liquidity & volatility of the day | Continuation, reversal at extremes, biggest moves |
| **New York** | Driven by US data/news; afternoon fade common | News momentum/fade, ORB, reversal after overlap |

**Critical correctness note:** London and New York observe DST on **different calendars**, so the overlap window *shifts several times a year*. Hardcoding UTC session boundaries is a classic, silent backtest bug. Sessions must be defined in their local exchange timezone with a DST-aware library (`zoneinfo`/`pytz`) and converted to UTC per-day. (This is exactly the kind of subtle error that quietly inflates backtest results.)

**FX-specific data caveat:** there is no central exchange, so **"volume" is tick volume / broker volume only** — a proxy, not true traded volume. Spread and liquidity are *broker-specific*. Any strategy depending on volume or spread must be validated against the *same* data source you will trade on.

---

## 4. Strategy Library Design

We treat every strategy as a **falsifiable hypothesis**, specified to a common template, version-controlled, and only promoted after validation. Your existing SMC/ICT work (liquidity sweeps, break-of-structure, order blocks) maps directly onto several of these.

### 4.1 Reusable strategy specification template

Every strategy file documents: `id/version`, `thesis` (why an edge should exist — the economic/behavioral rationale), `best_session`, `best_pairs`, `required_data`, `entry_logic`, `exit_logic`, `stop_loss`, `take_profit`, `invalidation`, `regime_filter`, `news_filter`, `risk_rules`, `expected_weaknesses`, `backtest_requirements`, `ml_features`, `scoring`, `decay_signals`.

> **Founding-team rule:** if you can't write a one-paragraph economic/behavioral *reason an edge should exist*, do not build it. "The indicators line up" is not a thesis. Liquidity grabs, session open positioning, stop-hunt mechanics, and news repricing *are* theses.

### 4.2 Concrete specs (highest-priority strategies)

**S1 — Asian Range Breakout**
- *Thesis:* range built in low-liquidity Asian session is broken on London volatility expansion.
- *Session/pairs:* enter at London open; EUR/USD, GBP/USD, EUR/JPY, GBP/JPY, XAU/USD.
- *Entry:* break of Asian high/low (with buffer to filter noise) confirmed by expansion (ATR/range thrust).
- *Exit/TP:* measured move (range height ×k) or overlap extreme; *SL:* opposite side of range / structural swing; *invalidation:* fakeout back inside range within N bars.
- *Regime filter:* require non-ranging London regime; *news filter:* skip if high-impact EUR/GBP/USD print inside window.
- *Weaknesses:* false breakouts, choppy days, holidays. *Decay:* rising fakeout rate, shrinking measured-move capture.

**S2 — London / Asian-Liquidity Sweep (SMC)**
- *Thesis:* price sweeps Asian high/low (stop run) then reverses — the classic ICT liquidity grab + break of structure.
- *Entry:* sweep of prior session liquidity → displacement/BOS in opposite direction → entry on order block / FVG retest.
- *SL:* beyond sweep extreme; *TP:* opposing liquidity pool / prior day high-low; *invalidation:* close beyond sweep extreme without BOS.
- *Note:* this is the production-grade version of your current Novax SMC logic — and exactly where `detect_bos()` correctness matters. Build BOS/sweep detection as tested, reusable primitives.

**S3 — New York Opening Range Breakout (ORB)**
- *Thesis:* first X minutes of NY define a range; break signals directional intent driven by US flow.
- *Pairs:* USD majors, XAU/USD; *news filter:* mandatory around 8:30 ET data.

**S4 — Overlap Continuation** and **S5 — Overlap Reversal** — mirror strategies for the London–NY overlap; continuation when trend + regime align, reversal at session extreme + exhaustion + opposing liquidity.

**S6 — Trend-Continuation Pullback** — multi-timeframe: HTF trend, LTF pullback to value (MA/FVG/OB), enter on resumption. Regime filter = trending.

**S7 — VWAP / Mean Reversion** — session-anchored VWAP; fade stretched deviations *only* in ranging/mean-revert regime. Strictly regime-gated.

**S8 — Volatility-Expansion Breakout** — squeeze detection (Bollinger/Keltner compression, low ATR percentile) → trade the expansion.

**S9 — News Momentum** and **S10 — News Fade** — momentum rides the initial repricing on a surprise vs. consensus; fade plays the overreaction retrace. Both require the economic-calendar + surprise data and tight spread/slippage modeling (spreads blow out around news).

**S11 — Multi-Timeframe Structure**, **S12 — S/R Liquidity**, **S13 — Correlation-Aware overlay** (don't double-up correlated USD bets; use DXY/cross confirmation), **S14 — Macro filter** (yield/DXY regime as a *gate*, not a standalone signal).

### 4.3 How to score & detect decay (applies to all)
- **Score:** base historical expectancy *conditioned on session+regime* × confidence modifiers (see §10).
- **Decay detection:** rolling expectancy/Sharpe vs. backtest baseline (CUSUM / control charts), rising stop-out rate, falling win-rate, parameter-stability drift. Auto-flag and auto-demote a decaying strategy to "monitor only."

---

## 5. Data Architecture

**Layered, point-in-time-correct, reproducible.**

- **Raw landing (immutable):** every fetch stored as raw Parquet/JSON with source + fetch timestamp. Never overwrite — reproducibility depends on it.
- **Normalized/curated:** cleaned OHLCV + bid/ask/spread, UTC-indexed, gap-flagged, in TimescaleDB (hot/recent) + Parquet on disk/object store (cold/research).
- **Feature layer:** engineered features with **point-in-time correctness** (no value available before its real-world timestamp — this is how you prevent lookahead).
- **Outputs:** signals, predictions, model outputs, trades, results — all persisted and versioned.

**Data needed:** tick + 1m OHLCV (resample up), bid/ask + spread, tick volume (as proxy, clearly labeled), economic calendar (with consensus + actual + surprise), central-bank events, news headlines/body, sentiment, and macro context: **DXY, US/DE/JP yields, equity indices, gold & oil, volatility measures (realized + VIX/MOVE proxies)**.

**Providers (tiers — verify current pricing yourself before committing):**

| Tier | Examples | Use for |
|---|---|---|
| Free / cheap | **OANDA v20** (practice acct: REST + streaming, decent history), **Dukascopy** (free historical tick), TwelveData (you already use this) | MVP, research, paper |
| Mid | Polygon.io, Tiingo, Finnhub; ForexFactory/Investing-derived calendars | better breadth, news/calendar |
| Pro | **Databento**, Refinitiv, Bloomberg, institutional FIX feeds | scale / institutional only |

> **Verdict:** build the MVP on **OANDA v20 (practice) for clean execution-aligned data + streaming**, **Dukascopy for free deep history**, and your existing **TwelveData** as a secondary. Do **not** pay for pro data until an approach is validated. Critically: backtest on the *same broker's* spread/data you intend to trade on, or your costs are fiction.

---

## 6. Technical Architecture

**MVP = a modular monolith + a few workers, not microservices.** Resist premature distribution.

```
            ┌─────────────── Data Ingestion ───────────────┐
            │  market (OANDA/Dukascopy/TwelveData) | news   │
            │  economic calendar | macro (DXY/yields/etc.)  │
            └───────────────┬───────────────────────────────┘
                            ▼
        Raw landing (Parquet/object store)  ──►  Normalization/cleaning
                            ▼
   TimescaleDB (hot)   +   Parquet/DuckDB (research, columnar)
                            ▼
                  Feature engineering (point-in-time)
                            ▼
   ┌──────────────┬───────────────┬────────────────┬──────────────┐
   │ Strategy      │ Backtest /     │ Signal scoring │ ML training  │
   │ engine        │ walk-forward   │ engine         │ + registry   │
   │ (Nautilus)    │ (Nautilus+VBT) │                │ (MLflow)     │
   └──────┬────────┴───────┬────────┴───────┬────────┴──────┬───────┘
          ▼                ▼                ▼               ▼
            ┌──────────── RISK ENGINE (pre-trade gate) ───────────┐
            │ limits | exposure | news blackout | kill switch     │
            └──────────────────────┬──────────────────────────────┘
                                    ▼
        Paper engine ──► Semi-auto ──► Live execution (OANDA/IBKR)
                                    ▼
   FastAPI backend ─ WebSocket ─► Next.js dashboard | Telegram/email alerts
                                    ▼
        Postgres (signals/trades/audit) | Prometheus+Grafana | OTel
```

**Strict separation of research / paper / live** as distinct deployments with distinct credentials and distinct databases. Live config never bleeds into research.

**Scale later, not now:** Kafka/Redpanda for streaming, Kubernetes, and a dedicated feature store are **deferred** until volume/throughput/tenancy actually demand them. For a single-instrument research loop and paper trading, a well-built docker-compose stack on one VPS is correct.

---

## 7. Recommended Tech Stack

| Layer | MVP choice | Why / when to upgrade |
|---|---|---|
| Language | **Python 3.12** | ecosystem; Polars/DuckDB give C-speed where needed |
| Data wrangling | **Polars + DuckDB + Parquet** (Pandas where libs require) | columnar, fast, cheap, memory-frugal vs Pandas |
| Time-series DB | **PostgreSQL + TimescaleDB** | hypertables, continuous aggregates, SQL familiarity |
| Research store | **DuckDB over Parquet** | zero-server analytical queries on history |
| Backtest/exec core | **NautilusTrader** | event-driven, realistic, **same code research→live** |
| Fast research screen | **VectorBT** (open-source) | vectorized parameter sweeps for idea triage |
| Orchestration | **Prefect** (MVP) → **Dagster** if asset-lineage matters | Python-native; skip Airflow |
| Task/async | asyncio + Prefect; add **Dramatiq** if a real queue is needed | avoid Celery's weight early |
| ML | **scikit-learn + LightGBM/XGBoost**; PyTorch only when justified | baselines first |
| ML tracking/registry | **MLflow** | experiments, params, models, lineage |
| Drift/monitoring | **Evidently** + custom metrics → Grafana | ML drift + data quality |
| API | **FastAPI** | async, typed, fast |
| Frontend | **Next.js + TypeScript** | (matches your web-platform stack) |
| Charting | **TradingView Lightweight-Charts** (free, OSS) | the obvious TradingView-quality OSS pick; Plotly/ECharts for analytics |
| Realtime | **WebSocket** (FastAPI) + Redis pub/sub | Redis Streams before Kafka |
| Cache/locks | **Redis** | ratelimits, locks, ephemeral state |
| Observability | **Prometheus + Grafana + OpenTelemetry** | metrics/traces from day 1 |
| Packaging/deploy | **Docker + docker-compose** (MVP) → K8s at growth | you already run K8s on the web side; don't force it here yet |
| Broker | **OANDA v20** (paper→semi-auto), **IBKR** (`ib-async`) later, cTrader Open API alt | MT5 only if a strategy needs it; FIX at institutional scale |

---

## 8. Open-Source Tools to Use or Evaluate

- **Use now:** NautilusTrader, VectorBT, Polars, DuckDB, TimescaleDB, MLflow, scikit-learn, LightGBM/XGBoost, FastAPI, Next.js, Lightweight-Charts, Prometheus/Grafana, OpenTelemetry, Evidently, Prefect, Redis, `zoneinfo`.
- **Evaluate later:** Dagster (vs Prefect), Feast (only if multi-model/online serving justifies it), Redpanda/Kafka (streaming scale), Qlib (Microsoft's quant research toolkit — good ideas, heavier), `mlfinlab`-style implementations of triple-barrier/purged-CV (or implement from López de Prado directly).
- **Avoid / deprioritize:** **Zipline** (effectively unmaintained; the `zipline-reloaded` fork is equities-centric and dated), **Backtrader** (single-threaded, stale, no research-live parity), **Lean/QuantConnect** (C#, cloud-coupled, heavyweight for a Python team). NautilusTrader supersedes these for your needs.

---

## 9. Database Design Overview

Core entities (PostgreSQL/TimescaleDB; research mirrors in Parquet):

- **`instruments`** — symbol, type (fx/metal), pip size, session profile.
- **`ohlcv`** (hypertable) — instrument, tf, ts(UTC), o/h/l/c, bid, ask, spread, tick_vol, source.
- **`economic_events`** — ts, currency, name, impact, consensus, actual, surprise.
- **`news`** — ts, source, headline, body, entities, sentiment.
- **`features`** — instrument, ts, feature_set_version, payload (point-in-time correct).
- **`strategies`** — id, version, spec hash, status (research/paper/live/retired).
- **`signals`** — strategy_id+ver, instrument, ts, direction, entry, sl, tp, score, score_components(JSON), regime, session, news_state.
- **`backtests`** — run_id, strategy_ver, data_range, params, costs_model, metrics, equity_curve_ref, code_commit, data_hash (full reproducibility).
- **`paper_trades` / `live_trades`** — separate tables; link to originating signal; fills, slippage, costs, pnl.
- **`models`** — MLflow run ref, version, training_data_hash, metrics, status.
- **`audit_log`** — append-only: every signal, decision, risk-gate verdict, override, config change, with actor + timestamp.

**Principles:** everything versioned (code commit + data hash + params on every result), append-only audit, no destructive overwrites in raw/audit, reproducibility as a schema-level requirement.

---

## 10. Signal Scoring Framework

A **transparent, decomposable 0–100 score** — explainability is a product feature and a compliance asset.

```
score = base_expectancy_score        # strategy's historical edge, conditioned on (session, regime)
      × regime_fit_modifier          # does current regime match strategy's home regime?
      × volatility_filter            # within tradable vol band?
      × spread_slippage_penalty      # penalize wide spreads / illiquid windows
      × news_risk_modifier           # blackout → 0; elevated risk → discount
      × correlation_penalty          # discount if it stacks correlated USD exposure
      × (optional) ml_prob_modifier  # ML probability-of-success, ONLY once validated
```

Every signal stores **all components** so a user (or auditor) sees *why* it scored what it did. ML enters as a *modifier*, never a black-box override — and only after it demonstrably improves out-of-sample expectancy. A signal that fails any hard gate (news blackout, spread cap, regime mismatch) is suppressed regardless of base score.

---

## 11. ML / AI Framework

**Realistic stance:** in FX, well-constructed *rules* are often hard to beat, data is non-stationary and limited, and ML mostly earns its keep as a **filter/scorer**, not an oracle. Build baselines first; add complexity only when it beats them out-of-sample.

| Task | Start (baseline) | Later |
|---|---|---|
| Regime classification | rules + rolling stats; HMM/GMM | supervised classifier on engineered features |
| Strategy selection | rule table (regime→strategy) | meta-model ranking strategies by context |
| Signal quality / prob-of-success | LightGBM on engineered features | calibrated ensembles |
| Volatility forecast | EWMA/GARCH | LSTM/Temporal models (only if they win) |
| Spread/slippage risk | empirical by session/news | regression model |
| News sentiment | lexicon / small transformer | fine-tuned finance LLM |
| Event-impact prediction | historical surprise→move stats | supervised model |
| Anomaly detection | z-score / Isolation Forest | autoencoders |
| Strategy-decay detection | CUSUM/control charts | change-point models |

**Anti-self-deception rules (mandatory):**
- **Labeling:** triple-barrier method (López de Prado) — label by which of profit-target / stop / time-limit hits first. Avoids naive fixed-horizon labels.
- **No lookahead:** all features point-in-time; resample/lag carefully; sessions in UTC with DST.
- **No leakage:** purged k-fold CV **with embargo** (drop train samples whose labels overlap test windows). Standard k-fold leaks in time series.
- **Evaluation:** walk-forward + a never-touched out-of-sample **lockbox**; report calibration (Brier/reliability), not just accuracy; economic metrics (expectancy, Sharpe, max DD) over ML metrics.
- **Non-stationarity:** rolling/expanding retrain schedules; monitor feature & prediction drift (Evidently); demote on drift.
- **Multiple testing:** every model/feature search inflates false discovery — apply deflated Sharpe / Bonferroni-style discounting (see §13).

---

## 12. News & Macro Analysis Framework

- **Calendar pipeline:** ingest events with consensus + actual; compute **surprise = (actual − consensus)/σ**; map surprise→historical instrument reaction.
- **News blackout windows:** hard rule — no entries N minutes before/after high-impact events for affected currencies; spreads and slippage spike here.
- **Sentiment:** start lexicon/simple classifier on headlines; upgrade to a finance-tuned model later; treat sentiment as a *modifier/gate*, not a primary signal.
- **Macro regime gate:** DXY trend, yield direction, risk-on/off proxies as context that *enables/disables* strategies (e.g., suppress JPY mean-reversion during aggressive carry-unwind regimes).
- **Central-bank events:** treat as their own high-severity blackout + post-event regime-shift watch.

---

## 13. Backtesting & Validation Framework

This is where most retail systems quietly cheat. Ours won't.

**Realism (cost & mechanics):** model spread (time-of-day + news-dependent), slippage, commission, partial fills where relevant, realistic SL/TP execution (intrabar ambiguity handled conservatively), session-specific liquidity, and **UTC + DST correctness** for all sessions.

**Statistical rigor:**
- **Walk-forward** (rolling optimize→test) as the default, not a single in-sample fit.
- **Out-of-sample lockbox** never touched until final go/no-go.
- **Monte Carlo** on trade-sequence (resample order/returns) → distribution of outcomes, not a single equity curve; report drawdown distribution.
- **Parameter robustness:** prefer broad plateaus over sharp single-peak optima (sharp peaks = curve-fit).
- **Multiple-testing correction:** **Deflated Sharpe Ratio** / accounting for the number of trials. If you test 200 variants, the best one looks great by luck alone — discount for it. This single discipline separates real research from backtest theater.
- **Portfolio-level:** correlation between pairs (USD legs co-move), aggregate exposure, portfolio drawdown — not just per-strategy.

**Reproducibility:** every backtest stores code commit + data hash + params + cost model. Re-running must reproduce the result bit-for-bit.

**Validation gates (a strategy is promoted only if):** positive, stable expectancy *after realistic costs*, robust across the parameter plateau, survives walk-forward + lockbox, survives deflated-Sharpe discounting, and behaves sanely in Monte Carlo drawdown.

---

## 14. Risk Management System

A **pre-trade risk engine** that every signal must pass — research, paper, and live alike. The risk layer can always say no.

- Max risk per trade (fixed-fractional or volatility-targeted sizing).
- Max daily / weekly loss; max drawdown → auto-halt.
- Max correlated exposure (aggregate USD/JPY/etc. legs); max open positions; per-pair exposure caps.
- Session-level risk budgets; **news blackout windows**; spread filter; volatility band filter.
- **Kill switch** (instant flatten + halt) and **manual override**, both audit-logged with actor + reason.
- Append-only audit of every risk verdict.
- **Disclaimers/compliance** surfaced in product (signals are information, not advice).

> **Verdict:** the risk engine ships in the **MVP**, even though there's no live capital — because paper trading must run through the *same* gate it will use live. Parity again.

---

## 15. Execution & Broker Integration Plan

- **Paper → semi-auto:** **OANDA v20** — clean REST + streaming, practice accounts, retail-algo friendly, data aligns with execution.
- **Scale / breadth:** **Interactive Brokers** via `ib-async` (broad instruments, better fills at size).
- **Alt:** **cTrader Open API**; **MT5** Python API only if a specific strategy ecosystem demands it (clunky for production); **FIX** only at institutional scale.
- **Execution abstraction:** a thin broker-adapter interface so strategies are broker-agnostic; NautilusTrader already models this well (its backtest and live adapters share the strategy layer).
- **Progression:** paper (sim fills) → semi-auto (signal → human confirm → API order) → full-auto (autonomous, hard risk gate + kill switch), each gated by validation.

---

## 16. Frontend / Dashboard Product Design

- **Signal feed:** scored signals with decomposed score components ("why"), entry/SL/TP, session, regime, news state.
- **Strategy performance:** equity curves, expectancy/Sharpe/DD by **session × regime × pair**, decay flags.
- **Session & pair analytics:** behavior heatmaps, volatility-by-session, overlap windows (DST-correct).
- **Backtest UI:** launch/compare runs, walk-forward views, Monte Carlo drawdown fans, parameter-robustness surfaces.
- **Paper-trading monitor → live monitor** (later): open positions, risk-budget utilization, kill switch.
- **Risk dashboard:** exposure, correlation, limit utilization, blackout status.
- **Model dashboard:** drift, calibration, feature importance, version status.
- **Alerts:** Telegram (you already use it), email, push.
- **Charts:** TradingView Lightweight-Charts for price; Plotly/ECharts for analytics.

---

## 17. Team Structure

**MVP (1–3 people; you likely wear several hats):** founding engineer/CTO (data + backend + DevOps), quant researcher (strategy + validation — *the* critical hire/skill), part-time frontend. Quant rigor is the scarce ingredient; protect it.

**Seed (5–8):** + ML engineer, dedicated data engineer, full-time frontend/product, fractional risk/compliance advisor, part-time product strategist.

**Growth (12+):** + MLOps/DevOps, multiple quants, backend team, QA/SRE, in-house compliance/legal, sales/CS for SaaS, design.

**Hiring priority order:** validation-capable quant → data/backend → ML → frontend → DevOps/SRE → compliance → GTM.

---

## 18. Startup Business Model

Layered, each tier unlocked by the prior:

1. **Signal-intelligence SaaS** (subscription tiers by pairs/strategies/latency) — primary early revenue.
2. **Pro trader tools** (backtesting, analytics, risk) — higher tier.
3. **Risk-analytics platform** (sell the risk/exposure engine to traders/desks).
4. **Prop-firm analytics** (evaluation/monitoring tooling — a hot niche).
5. **API access** (programmatic signals/analytics).
6. **Strategy marketplace** (later; needs trust, track record, and heavy compliance).
7. **Broker partnerships / white-label** (distribution at scale).

> **Compliance reality (not legal advice — engage a qualified lawyer early):** selling signals or analytics ("information/education") is very different from *managing money* or giving *personalized investment advice*, which is regulated in most jurisdictions. Your bilingual / cross-border (Iran ↔ international) context adds **payments and sanctions complexity** (Stripe/international rails, KYC, sanctions screening) that must be designed for, not discovered. Keep clear disclaimers; position as intelligence/tooling, not advice; get jurisdiction-specific counsel before charging cross-border or touching client funds.

---

## 19. Roadmap by Phase

For each: **goal · deliverables · team · timeline · risks · validation · don't-build-yet.**

- **P0 Research & validation (2–4 wk):** prove data access + one strategy hypothesis is *worth* building. *Deliver:* data spike, one strategy backtested honestly. *Validate:* any sign of cost-surviving edge. *Don't build:* anything else.
- **P1 Data foundation (3–5 wk):** ingestion + normalization + TimescaleDB/Parquet + point-in-time features for 3–4 instruments. *Risk:* data quality, DST/timezone. *Validate:* reproducible, gap-flagged, correct sessions.
- **P2 Backtesting & strategy engine (4–6 wk):** NautilusTrader integration, realistic costs, walk-forward, 2–3 strategies. *Validate:* deflated-Sharpe-survivor on lockbox. *Don't:* ML, live, microservices.
- **P3 Signal scoring & dashboard (3–4 wk):** transparent score + read-only dashboard + Telegram alerts + audit log. *Validate:* signals reproducible & explainable.
- **P4 ML & news intelligence (4–8 wk):** baselines (regime, prob-of-success), calendar/news pipeline, MLflow, drift monitoring. *Validate:* ML *beats* rules out-of-sample, else drop it.
- **P5 Paper trading (4–6 wk):** live data → sim fills → through the real risk engine; track signal→outcome. *Validate:* paper expectancy ≈ backtest after costs.
- **P6 Semi-automated (4–6 wk):** human-confirm execution via OANDA. *Validate:* live fills match paper assumptions; slippage within budget.
- **P7 Fully automated (gated, open-ended):** autonomous + hard risk + kill switch, **small real capital only after sustained paper/semi-auto proof.**
- **P8 Commercial SaaS (ongoing):** multi-tenant, billing, API, compliance hardening, then marketplace.

---

## 20. MVP Scope

**In:** OANDA/Dukascopy/TwelveData ingestion for ~3–4 instruments (incl. EUR/USD, GBP/USD, XAU/USD); TimescaleDB + Parquet; point-in-time features; NautilusTrader backtester with realistic costs + DST-correct sessions; walk-forward + lockbox + deflated Sharpe; 2–3 fully-specified strategies (incl. your SMC liquidity-sweep); transparent rule-based signal score; pre-trade risk engine; read-only dashboard + Telegram alerts; full audit + reproducibility.

**Out (deliberately):** live capital, full ML stack, feature store, Kafka/Redpanda, Kubernetes, marketplace, multi-tenant SaaS, broker breadth beyond OANDA, fancy frontend.

---

## 21. What to Avoid

- Live capital before validation gates pass. **Hard rule.**
- Curve-fitting: sharp parameter peaks, no out-of-sample, ignoring multiple-testing. (This is the #1 way to ship a losing system that backtests beautifully.)
- Backtesting on data/spreads that don't match your execution broker.
- Hardcoded UTC session times (DST drift) and treating FX tick-volume as real volume.
- Premature infra: K8s, Kafka, feature store, microservices before they're justified.
- ML theater: complex models that don't beat baselines out-of-sample.
- Building the marketplace/SaaS before a single validated edge exists.
- Secrets in compose files / repos (rotate any exposed keys; use a secrets manager). *(You already flagged a hardcoded key on the existing Novax system — same discipline applies here from day one.)*
- Marketing it as guaranteed profit — false and a legal/compliance liability.

---

## 22. Key Technical Risks

1. **No edge / edge doesn't survive costs.** The dominant risk. Mitigation: ruthless validation gates, honest cost modeling.
2. **Overfitting / multiple-testing self-deception.** Mitigation: walk-forward, lockbox, deflated Sharpe, parameter plateaus.
3. **Data quality / FX volume fiction / broker-specific spread.** Mitigation: same-source backtest+execution, gap flagging, point-in-time.
4. **Non-stationarity & strategy decay.** Mitigation: regime conditioning, decay monitors, auto-demotion, retrain schedules.
5. **Backtest↔live divergence.** Mitigation: research-live parity (NautilusTrader), paper-before-live, slippage budgets.
6. **Timezone/DST correctness bugs.** Mitigation: UTC storage, DST-aware session logic, tests.
7. **Execution/slippage in live.** Mitigation: conservative fill modeling, semi-auto stage, small initial size.
8. **Regulatory / payments / sanctions (cross-border).** Mitigation: early counsel, clear positioning as tooling, KYC/sanctions design.
9. **Operational/security** (secrets, key rotation, audit). Mitigation: secrets manager, least privilege, append-only audit.

---

## 23. Final Recommended First 90 Days Plan

**Weeks 1–2 — Validation spike.** Stand up OANDA practice + Dukascopy history for EUR/USD + XAU/USD. Implement *one* strategy (your SMC Asian-liquidity-sweep) in a quick VectorBT screen. Brutally honest first look at whether *any* cost-surviving edge exists. Kill or continue.

**Weeks 3–5 — Data foundation.** Ingestion → normalization → TimescaleDB + Parquet for 3–4 instruments; point-in-time features; UTC + DST-correct session engine with tests. Reproducibility (data hashing) baked in.

**Weeks 6–9 — Serious backtesting.** Integrate NautilusTrader; realistic spread/slippage/commission; implement 2–3 strategies as tested strategy objects; walk-forward + out-of-sample lockbox; **deflated Sharpe** discounting; Monte Carlo drawdown.

**Weeks 10–11 — Signal score + risk engine + thin UI.** Transparent decomposable score; pre-trade risk gate (same one paper/live will use); read-only Next.js dashboard + Telegram alerts; full audit log.

**Week 12 — Go/no-go review.** Against validation gates (§13). If a strategy survives honestly → proceed to paper (P5). If not → iterate on research; **do not** advance toward live. Document findings either way.

**The one rule that governs all 90 days:** *no real capital, and no building of downstream tiers, until a strategy survives honest validation.* Everything here is designed to make that judgment trustworthy — including the judgment that an idea should be abandoned.

---

*Built as a coordinated founding-team design (CTO, Quant Lead, Senior FX Trader, ML Lead, Data/Backend/Frontend Eng, DevOps/MLOps, Risk, Product, Compliance). This is engineering and research guidance, not financial advice, and makes no promise of profit. Validate everything; respect the risk layer; verify provider pricing and legal/regulatory requirements for your jurisdictions before commercial or live-capital steps.*
