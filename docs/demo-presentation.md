# Novax FX — Demo Presentation Script
**Audience:** CTO, CEO, team · **Duration:** 30–45 min · **Date:** July 2026

---

## Opening (2 min)

> "Most algorithmic trading platforms are built to look impressive in backtests.
> Novax is built to be honest. Every component exists to catch us when we're fooling
> ourselves — and we've built 491 automated tests to prove it."

**Key message:** Research integrity first. Capital later. That is the competitive advantage.

---

## Section 1 — The Problem We Solve (3 min)

**The overfitting trap:**
- Retail traders run 100 backtests and pick the one that worked
- That "best" strategy is just curve-fitted noise
- Live performance always disappoints because the edge was never real

**Our answer:**
1. Deflated Sharpe: penalise every trial you ran (not just the one you report)
2. Lockbox: you cannot touch out-of-sample data until all decisions are frozen
3. Artifact trail: every backtest is hash-addressed and logged before it runs

**Live demo step:** `git log --oneline -5` — show that every commit triggers CI/CD

---

## Section 2 — The Research Core (8 min)

### 2a. The backtest engine

**Show:** `src/novax/engine.py`

Key points:
- `BarView(bars[:i+1])` — strategy sees only past bars, enforced by immutable tuple
- Signal at bar `i` → fill at bar `i+1` open (execution lag is real)
- Cost model is always applied: spread + slippage (entry + exit) + commission

**Run live:**
```bash
python scripts/run_weekly_bos_retest.py
```
Show the output: total return, drawdown, Sharpe — after costs.

### 2b. Walk-forward split

**Explain:** Train on 70% of data. Test on 30%. Never touch test set during development.

**Show:** `src/novax/walkforward.py` — 15 lines, deterministic, no randomness.

### 2c. Validation gates

**Show the go/no-go call:**
```python
result = evaluate_go_no_go(artifact_id, registry)
# result.verdict is GO only if ALL conditions are met
```

Point to the deflated Sharpe calculation — "this is why a 3.0 Sharpe on training becomes
0.8 Sharpe after correcting for the 47 trials we ran."

---

## Section 3 — Live Daemon (8 min)

### 3a. Event scheduler

**Show:** `src/novax/live/event_scheduler.py`

Seven event types fire at the right market times:
- 15M bar-close: real-time confluence scanning
- Sunday 22:00 UTC: market open report (previous week H/L)
- Friday 21:00 UTC: market close + weekly report (simultaneous)
- London 08:00 / NY 13:00: session open alerts
- 20:00 UTC daily: daily report

**Key design point:** `next_events()` returns a list — Friday 21:00 fires BOTH
`MARKET_CLOSE` and `WEEKLY_REPORT` at the same time. No missed events, no duplicate waits.

### 3b. Multi-timeframe confluence

**Show:** `src/novax/live/multi_tf_scanner.py`

Architecture:
```
4H  WeeklyBOSRetest   →  LONG / SHORT / FLAT  (lead signal)
1H  GoldPullback      →  LONG / SHORT / FLAT  (confirmation)
15M EMACross          →  LONG / SHORT / FLAT  (informational)

Confluence = 4H and 1H agree → alert fires
```

### 3c. Telegram alert example

Show a real alert format:
```
🟢 XAUUSD Confluence Signal
Time:  2026-07-14 08:15 UTC / 11:45 IRST
4H:    LONG  (WeeklyBOSRetest — BOS confirmed, retest entry)
1H:    LONG  (GoldPullback — above EMA50, pullback to support)
15M:   FLAT  (EMACross — informational)
Entry: 2725.50  |  SL: 2700.00  |  TP: 2751.00
Risk:  1R = 25.5 pips
```

### 3d. Tehran timezone

- Iran Standard Time is always UTC+3:30
- Iran does NOT observe DST — ever
- All alerts show both UTC and IRST
- Enforced in `tz_utils.py` — always "IRST", never "IRDT"

---

## Section 4 — Data Pipeline (5 min)

### 4a. Dukascopy ingestion

**Show:** `scripts/ingest_dukascopy.py`

- Downloads tick data in Dukascopy bi5 binary format (LZMA-compressed)
- Resamples ticks to 1M OHLCV bars + bid/ask spread
- Stores in monthly Parquet files (snappy compression, ~1MB/month/instrument)

**Run live (dry run):**
```bash
python scripts/ingest_dukascopy.py --symbol XAUUSD --year 2025 --month 1 --dry-run
```

### 4b. Parquet storage layout

```
data/
  xau/usd/
    1m/
      2025/01.parquet
      2025/02.parquet
      ...
```

DuckDB can query across months with a single SQL statement — no Pandas required.

---

## Section 5 — CI/CD Pipeline (5 min)

**Show:** `.github/workflows/ci.yml` and `deploy.yml`

```
push to main
    ↓
lint:   ruff format --check  +  ruff check  +  mypy (strict)  +  ci_guards.py
    ↓
test:   pytest on Python 3.12 and 3.13 in parallel
    ↓
docker: docker build (smoke test, no push)
    ↓
deploy: SSH → Hetzner
        git pull --ff-only
        docker compose build prod-daemon
        docker compose up -d prod-daemon
```

**Point out:** Deploy never cancels mid-flight (`cancel-in-progress: false`).
CI cancels stale runs on new push (`cancel-in-progress: true` — saves minutes).

---

## Section 6 — Roadmap Q&A (5 min)

**Next milestone (P2 — Signal Scoring):**
- Decomposable 0–100 score: every component stored separately
- Enables ensemble strategies and ML features without data leakage

**After that (P3 — Risk Engine):**
- Pre-trade kill switch
- Position limits by instrument + total exposure
- This ships *before* any paper trading starts

**When does real money enter?**
- After a strategy passes deflated Sharpe + lockbox
- After P3 risk engine is in place
- After P5 paper trading period validates live fills

---

## Demo Checklist (Before Presenting)

- [ ] `git pull` — ensure latest commit is on screen
- [ ] `pytest -q` — show 491 passing in < 20s
- [ ] GitHub Actions tab open — show green CI pipeline
- [ ] Hetzner server: `docker ps` — show daemon running
- [ ] Telegram: show at least one real alert received this week
- [ ] `scripts/run_weekly_bos_retest.py` — show output (no live data needed)

---

## Common Questions & Answers

**Q: How is this different from QuantConnect?**
A: QuantConnect is a hosted cloud backtester for retail traders. Novax is a research
platform with a research integrity layer — deflated Sharpe, lockbox, artifact trail —
that QuantConnect doesn't enforce. We also own our execution stack end-to-end.

**Q: Why XAU/USD first?**
A: Gold has the highest pip value, cleanest daily structure, and the most predictable
weekly levels. It is the best instrument to develop and validate a multi-TF BOS strategy
on before scaling to FX pairs.

**Q: What is the Sharpe target?**
A: Net-of-costs deflated Sharpe > 1.5 on the out-of-sample window. Any lower and we
cannot be confident the edge is real after correcting for multiple testing.

**Q: When is paper trading?**
A: After the risk engine (P3) ships and after at least one strategy passes all gates.
We will not paper trade with a strategy that hasn't passed the lockbox.

**Q: What's the commercial model?**
A: Research phase → internal capital → subscription signal product for institutions.
See `docs/Novax-FX-Platform-Founding-Blueprint.md` for the full model.

---

*Demo script — internal use only. Not for distribution.*
