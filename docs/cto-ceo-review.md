# Novax FX — Executive Project Review
**Date:** July 2026 · **Audience:** CTO / CEO · **Author:** Engineering

---

## One-Line Summary

Novax FX is a systematic FX and gold (XAU/USD) research platform with a live monitoring
daemon, a rigorous anti-overfitting validation pipeline, and a fully automated CI/CD
deployment — currently in pre-live research mode with zero capital at risk.

---

## Why We Built This

Most retail algorithmic trading projects fail for the same reason: they confuse
in-sample Sharpe ratios with real edge. A strategy that works on the data you used to
develop it is not a strategy — it is memorisation. Our platform is engineered around
making that mistake structurally impossible:

- **No lookahead by construction** — the backtest engine cannot see future bars
- **Deflated Sharpe** penalises every trial you ran, not just the one you're reporting
- **Lockbox** prevents touching out-of-sample data until all decisions are frozen
- **Artifact trail** records every run, hash-addressed, before it executes

Capital will not be risked until these gates pass. That is a hard rule, not a guideline.

---

## What Has Been Delivered

### Phase 0 — Research Scaffold (Complete)
- Sessions calendar (Asia / London / NY), all DST-correct via `zoneinfo`
- Instrument registry: EUR/USD, GBP/USD, USD/JPY, XAU/USD
- Conservative cost model (spread + slippage + commission, stress-tested at 1.0×, 1.25×, 1.5×)
- Go/no-go gate with deflated Sharpe and out-of-sample lockbox

### Phase 0.7 — Enforcement Layer (Complete)
- Immutable artifact registry (content-addressed, hash-stored)
- Append-only trial registry (JSONL, one line per experiment)
- `ExperimentRunner` context manager: logs the trial before the body runs
- CI guards: invariant checks run in every push

### Phase 1 — Backtest Engine (Complete)
- Causal bar-by-bar engine: signal at bar `i` fills at bar `i+1` open
- EMA and ATR indicators with mechanical lookahead verification
- Walk-forward split (deterministic, ratio-based)
- 7 scalar metrics: return, drawdown (abs + %), Sharpe, trade count, win rate, avg PnL

### Phase 1.5 — Live Daemon V2 (Complete)
- Multi-timeframe scanner (4H WeeklyBOSRetest → 1H GoldPullback → 15M EMACross)
- 7 event types: 15M bar-close, market open/close, London open, NY open, daily report, weekly report
- Tehran timezone support: always IRST (UTC+3:30), no DST
- JSONL persistent storage for weekly levels and signal records
- Dukascopy tick data ingestion (bi5 binary, 1M bars, async)
- Dockerised production daemon on Hetzner with fully automated SSH deploy

### CI/CD Pipeline (Complete)
```
lint (ruff + mypy)  →  test (3.12 + 3.13)  →  docker build  →  SSH auto-deploy
```
Every push to `main` that passes all gates automatically updates the live server.

---

## Test Coverage

| Area | Tests | Status |
|---|---|---|
| Research core (engine, metrics, validation) | ~250 | ✅ Pass |
| Live module (scheduler, scanner, messages, store) | ~150 | ✅ Pass |
| Indicators (BOS, EMA, ATR, SuperTrend, TSI) | ~60 | ✅ Pass |
| Data pipeline (parquet, ingest) | ~31 | ✅ Pass |
| **Total** | **491** | **✅ All pass** |

---

## Current Limitations (Honest Assessment)

| Limitation | Impact | Plan |
|---|---|---|
| No validated strategy yet | Cannot move to paper trading | Ongoing — completing walk-forward on WeeklyBOSRetest |
| Single instrument focus (XAU/USD) | Limited diversification | EUR/USD next once XAU/USD passes gates |
| No risk engine | Cannot safely automate entries | P3 — ships before paper trading starts |
| No dashboard | Manual Telegram monitoring only | P4 — FastAPI + Next.js |
| Historical data from Dukascopy only | No real-time feed yet | TwelveData adapter ready as seam |

---

## Risk Management Philosophy

**The hard gates (cannot be bypassed by code):**
1. Strategy must show positive expectancy after full cost model
2. Must pass deflated Sharpe (penalised by number of trials tested)
3. Out-of-sample lockbox must never be opened before all decisions are frozen
4. No capital deployment without passing all three

**Infrastructure risks:**
- SSH key rotation required if `DEPLOY_KEY` is ever suspected compromised
- Telegram Bot API token must never be logged or committed (enforced by env-var-only access)
- Hetzner server is single point of failure — acceptable for research phase; HA deferred to P5

---

## KPIs to Track (Next 90 Days)

| KPI | Target | Current |
|---|---|---|
| CI pass rate | >95% | Establishing baseline |
| Walk-forward Sharpe (XAU/USD) | >1.5 net-of-costs | In progress |
| Deflated Sharpe pass | YES | In progress |
| Test count | Growing | 491 |
| Deploy frequency | Weekly | Established |

---

## Team Asks

1. **Data budget** — TwelveData premium plan for real-time 1M bars (~$50/month)
2. **Hetzner resources** — current CAX11 sufficient; upgrade to CAX21 when paper trading starts
3. **GitHub environment approval** — Production environment gate in GitHub Settings for deploy step
4. **Decision** — Target date for first walk-forward go/no-go review meeting

---

## Roadmap (High Level)

| Phase | Target | Gate |
|---|---|---|
| P2 — Signal scoring | Q3 2026 | Decomposable 0–100 score |
| P3 — Risk engine | Q3 2026 | Kill switch, position limits |
| P4 — Thin API + dashboard | Q4 2026 | Read-only, audit log |
| P5 — Paper trading | Q4 2026 | Strategy passes all validation gates |
| P6 — Semi-auto | Q1 2027 | Human-confirm → OANDA |
| P7 — Fully auto | Q2 2027 | Small capital only |
| P8 — Commercial SaaS | TBD | Multi-tenant signal / analytics |

---

## Bottom Line

The platform is in good shape technically. The research integrity layer is stronger than
anything typical retail traders use. The live daemon is running, the CI/CD pipeline is
green, and the code quality bar is high (strict mypy, ruff lint, 491 tests).

The honest next milestone: **a strategy that passes all validation gates on real historical
data**. Until that happens, everything else is infrastructure. The infrastructure is ready.

---

*Not financial advice. Research infrastructure only.*
