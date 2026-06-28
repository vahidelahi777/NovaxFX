# Novax FX — Research Platform

A research-first FX intelligence platform built to validate systematic trading edges with
rigorous statistical discipline before any capital is risked. The architecture is optimised for
a fast, honest, auditable research loop — live trading is a downstream privilege earned through
validation, not a starting assumption.

> **Not financial advice. No promise of profit.** This is trading technology and research
> infrastructure. Every result must survive realistic cost modelling, walk-forward validation,
> and deflated-Sharpe multiple-testing correction before it is considered real.

---

## Current Status

**Phase 1 · Batch 2 complete** — the core research stack is fully operational.

| Phase | Scope | Status |
|---|---|---|
| Phase 0 | Sessions, instruments, cost model, deflated Sharpe, lockbox, go/no-go gate | ✅ Complete |
| Phase 0.5–0.7 | Enforcement layer: artifact registry, trial registry, experiment runner, CI guards | ✅ Complete |
| Phase 1 · Batch 1 | Causal backtest engine, EMA/ATR feature library, full engine test suite | ✅ Complete |
| Phase 1 · Batch 2 | Walk-forward split, basic performance metrics, end-to-end integration tests | ✅ Complete |
| Phase 2+ | Signal scoring, risk engine, paper trading, ML layer, dashboard | Planned |

All 87 tests pass. No live capital. No external broker connections.

---

## What Is Built

### Core modules (`src/novax/`)

| Module | Purpose |
|---|---|
| `sessions.py` | DST-correct session calendar — Asia / London / NY / Overlap, all in UTC via `zoneinfo` |
| `instruments.py` | EUR/USD, GBP/USD, USD/JPY, XAU/USD — pip conventions, pip-value math |
| `costs.py` | Conservative cost model: spread + entry/exit slippage + commission, XAU distinct from FX |
| `data_sources.py` | `Bar` dataclass (UTC-enforced); local/in-memory only — provider adapters are deferred seams |
| `dataquality.py` | `DataQualityReport` — required pre-condition before the engine accepts a bar series |
| `features.py` | Causal EMA and ATR; NaN before warmup; structurally verified no-lookahead |
| `engine.py` | Bar-by-bar backtest engine: next-bar fill, force-close at last bar, strategy returns `Signal` only |
| `walkforward.py` | `SimpleWalkForward` — deterministic train/test split by ratio |
| `metrics.py` | `compute_basic_metrics` — total return, drawdown (abs + %), Sharpe, trade count, win rate, avg PnL |
| `validation.py` | Deflated Sharpe, `Lockbox` guard, `evaluate_go_no_go` — never returns GO on any failure |
| `artifacts.py` | Immutable artifact registry — every result hash-addressed |
| `trial_registry.py` | JSONL-backed trial log — append-only, one line per experiment |
| `runner.py` | `ExperimentRunner` context manager — logs the trial before the body runs |
| `gate.py` | Artifact-driven go/no-go evaluation — no caller trust, no shortcut path |
| `harness.py` | `find_lookahead_indices` — mechanically verifies causal correctness of any indicator |
| `config.py` | `SETTINGS` — go/no-go thresholds, single source of truth |
| `battery.py` | CI battery of invariant checks |

### Key guarantees

**Causality is structural.**  
The engine creates `bars_t: tuple[Bar, ...]` (immutable) and passes `BarView(bars_t[:i+1])`
at each step. The strategy sees only past bars — this cannot be bypassed by mistake.

**Signals, not PnL.**  
Strategies return `Signal.LONG | SHORT | FLAT`. PnL computation lives entirely inside
`_close()` in the engine; the strategy has no access to cost logic.

**Execution lag.**  
A signal declared at bar `i` is filled at bar `i+1` open. Last-bar signals are silently
dropped. Positions are force-closed at `bars[-1].close`.

**Dimensional consistency.**  
`max_drawdown_abs` is in currency units (e.g. USD). `max_drawdown_pct` is a dimensionless
fraction in `[0, 1]` — use this one when comparing against fractional gate thresholds.

**Research integrity layer.**  
`ArtifactRegistry`, `ExperimentRunner`, and `evaluate_gate` form a tamper-resistant pipeline.
Trials are logged before they run; gates read from artifacts, not from caller-supplied values.

---

## Architecture

```
research loop (this repo)
├── data layer          Bar dataclass + DataQualityReport (gateway)
├── feature layer       EMA, ATR — causal, NaN-before-warmup, harness-verified
├── engine              BacktestEngine → BacktestResult (trades + equity)
├── walk-forward        SimpleWalkForward → (train_bars, test_bars)
├── metrics             compute_basic_metrics → 7 scalar metrics
├── validation          deflated Sharpe + Lockbox + go/no-go
└── enforcement         ArtifactRegistry + TrialRegistry + ExperimentRunner + gate
```

Full platform vision (modular monolith + worker processes, not microservices):

```
Ingestion (OANDA / Dukascopy / TwelveData)
        ↓
Raw Parquet → TimescaleDB (normalised bars)
        ↓
Feature engine (point-in-time)
        ↓
Strategy engine (Nautilus)  ←→  Backtest / walk-forward / Monte Carlo
        ↓
Signal scoring (decomposable 0–100)
        ↓
Risk engine (pre-trade gate — ships in MVP)
        ↓
Paper → Semi-auto → Fully auto (gated by validation)
        ↓
FastAPI + Next.js dashboard + Telegram alerts
```

See [`docs/Novax-FX-Implementation-Blueprint.md`](docs/Novax-FX-Implementation-Blueprint.md)
and [`docs/Novax-FX-Platform-Founding-Blueprint.md`](docs/Novax-FX-Platform-Founding-Blueprint.md)
for the full architecture, database schema, API design, sprint plan, and roadmap.

---

## Instruments & Sessions

**Instruments:** EUR/USD, GBP/USD, USD/JPY, XAU/USD (gold, first-class — not an afterthought).

**Sessions (UTC, DST-correct):**

| Session | Character |
|---|---|
| Asia | Low volatility, range-bound; JPY / AUD / NZD most active |
| London | Volatility expansion; liquidity sweep of Asian range |
| London–NY Overlap | Highest liquidity; biggest daily moves |
| New York | US data-driven; afternoon fade common |

London and New York observe DST on different calendars. The overlap window shifts several
times a year. Sessions are defined in local exchange timezone via `zoneinfo` and converted
to UTC per-day — hardcoding UTC times is a silent, well-known backtest bug.

---

## Strategy Library (Planned / In Research)

Each strategy is a falsifiable hypothesis with an explicit economic rationale:

- **S1** Asian Range Breakout — London volatility breaks the low-liquidity Asian range
- **S2** London / Asian Liquidity Sweep (SMC) — stop-run + BOS reversal entry
- **S3** NY Opening Range Breakout (ORB) — first-X-minutes directional intent
- **S4/S5** Overlap Continuation / Reversal
- **S6** Multi-Timeframe Trend Pullback
- **S7** VWAP Mean Reversion (regime-gated: ranging only)
- **S8** Volatility-Expansion Breakout
- **S9/S10** News Momentum / Fade
- **S11–S14** MTF Structure, S/R Liquidity, Correlation-Aware Overlay, Macro Gate

---

## Tech Stack

| Layer | Choice |
|---|---|
| Language | Python 3.12 |
| Data wrangling | Polars + DuckDB + Parquet (Pandas where libs require) |
| Time-series DB | PostgreSQL + TimescaleDB |
| Backtest / exec core | NautilusTrader (same strategy object in backtest + paper + live) |
| Fast research screen | VectorBT |
| ML tracking | MLflow |
| ML | scikit-learn + LightGBM; PyTorch only when it beats baselines OOS |
| Orchestration | Prefect |
| API | FastAPI |
| Frontend | Next.js + TypeScript + TradingView Lightweight-Charts |
| Observability | Prometheus + Grafana + OpenTelemetry |
| Deploy | Docker + docker-compose (MVP); K8s deferred |
| Broker | OANDA v20 (paper → semi-auto), IBKR later |

---

## Requirements

- Python **3.12+**
- No external services required to run the research core

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Run tests

```bash
pytest
```

## Lint & type-check

```bash
ruff check src tests
mypy
```

---

## Design Rules

**UTC everywhere.** Naive datetimes are rejected at the boundary (`sessions`, `Bar`,
`TradeRecord`). No silent local-time assumptions anywhere.

**Pip conventions are explicit.** USD/JPY pip = 0.01, XAU/USD pip = 0.1. PnL math reads
`pip_size` from the registry — never hardcoded.

**Costs are pessimistic.** Spread floor + entry slippage + exit slippage + commission.
XAU/USD has its own cost profile; FX assumptions are never reused for gold. A `stress_factor`
sweeps `{1.0, 1.25, 1.5}` to bound downside estimates.

**No lookahead by construction.** `BarView` is a frozen tuple of past bars. Indicators return
NaN before warmup. `find_lookahead_indices` mechanically verifies causality.

**Anti-self-deception.** Deflated Sharpe penalises the number of trials tested. A one-shot
`Lockbox` prevents touching the out-of-sample data before the final go/no-go. Gates are
artifact-driven — no value passed by the caller is trusted.

**Immutable audit trail.** Artifacts are content-addressed. Trials are logged before they run.
Every backtest stores code commit + data hash + params + cost model for bit-for-bit
reproducibility.

---

## Validation Gates

A strategy is promoted only when it:

1. Shows positive expectancy **after realistic costs** across a walk-forward window
2. Survives the out-of-sample **lockbox**
3. Passes **deflated Sharpe** discounting (corrected for the number of trials tested)
4. Shows a broad parameter plateau (not a single over-fit peak)
5. Behaves sanely in **Monte Carlo drawdown** simulation

No real capital. No downstream tier. Until these gates are passed.

---

## Repository Layout

```
src/novax/           core research platform (stdlib-only)
tests/               87 tests — unit, integration, end-to-end pipeline
docs/
  Novax-FX-Implementation-Blueprint.md   concrete services, schemas, API, sprint plan
  Novax-FX-Platform-Founding-Blueprint.md  strategy, vision, team, business model
  phase-0.7/         Phase 0.7 design docs
  specs/             module-level specs (cost model, artifact registry, sessions, …)
scripts/
  ci_guards.py       CI invariant checks
pyproject.toml       build, dev dependencies, ruff + mypy config
```

---

## Roadmap

```
P0  ✅  Research scaffold — sessions, instruments, costs, validation
P0.7 ✅  Enforcement layer — artifact registry, trial log, gate, CI guards
P1  ✅  Backtest engine — causal fills, features, walk-forward, metrics
P2      Signal scoring — decomposable 0–100 score with all components stored
P3      Risk engine — pre-trade gate, limits, kill switch (ships before paper)
P4      Thin API + dashboard — read-only, Telegram alerts, full audit log
P5      Paper trading — live data, sim fills, through the real risk engine
P6      Semi-auto — human-confirm → OANDA v20 API
P7      Fully auto — autonomous, hard risk gate + kill switch (small capital only)
P8      Commercial SaaS — multi-tenant signal / analytics / risk products
```

The governing rule: **no real capital and no downstream tier until a strategy survives
honest, gated validation.** Everything here is engineered to make that judgment trustworthy —
including the judgment to walk away from an idea that doesn't work.

---

*Engineering and research guidance only — not financial advice, no promise of profit.
Validate everything; respect the risk layer; verify provider pricing and jurisdiction-specific
legal/regulatory requirements before any commercial or live-capital step.*
