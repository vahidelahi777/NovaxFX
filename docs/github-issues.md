# Phase 0 — GitHub Issues (ready to file)

Each item is a fileable issue: title + description + acceptance criteria. Labels suggested in brackets. Keep PRs small and green in CI before merge.

---

## Repository setup

### `repo: scaffold monorepo (apps/libs/research/infra/docs)` [infra]
Create the base layout per the architecture blueprint: `apps/`, `libs/`, `research/`, `infra/`, `docs/`, `pyproject.toml`, Python 3.12.
- [ ] Directory tree created with package markers.
- [ ] `pyproject.toml` with ruff + black + mypy configured.
- [ ] `libs/` importable from `apps/` and `research/`; `research/` never imported by prod.

### `ci: GitHub Actions lint + type + test on PR` [infra]
Block merge on red.
- [ ] Workflow runs ruff, black --check, mypy, pytest.
- [ ] Required status check on `main`.

### `repo: pre-commit hooks (ruff, black, mypy, trailing-ws)` [infra]
- [ ] `.pre-commit-config.yaml` committed; documented in README.

---

## Data ingestion

### `data: OANDA v20 candle puller with 5000/req paging + backoff` [data]
Pull bid/ask + mid candles for EUR_USD, GBP_USD, USD_JPY, XAU_USD.
- [ ] Pages with from/to loop, ≤ 5000 candles/req.
- [ ] Stores bid, ask, mid; UTC timestamps; tick volume labeled as such.
- [ ] Retry/backoff on transient errors.
- [ ] Note in code: candle = base-price group, ≠ live pricing.

### `data: Dukascopy tick downloader → resampled bars (incl. XAU/USD)` [data]
Wrap `duka`/`dukascopy-node`; pull ticks, resample to 1m + 5m in Polars.
- [ ] 4 instruments, ≥ 5y, bid/ask.
- [ ] Raw ticks cached immutably (Parquet, source + fetch_ts).
- [ ] Resampling deterministic and unit-tested.

### `data: TwelveData secondary fetcher with rate-limit guard` [data]
- [ ] Catches HTTP 429 and backs off (8/min, 800/day free tier).
- [ ] Unit test simulates 429 → no silent skip.

### `data: raw landing writer (immutable Parquet, source + fetch_ts)` [data]
- [ ] Never overwrites raw; append-only landing.
- [ ] Records source, fetch_ts, instrument, tf.

---

## Data validation

### `data: coverage/gap report (>=99.5% gate)` [data]
- [ ] Per instrument/tf coverage %.
- [ ] Enumerates every gap with cause; fails build if < 99.5% in trading hours.

### `data: cross-source sanity check (OANDA vs Dukascopy)` [data]
- [ ] Close-price deltas within documented tolerance; divergences logged.

### `data: spread series extraction + sanity bounds` [data]
- [ ] No zero/negative spreads; distribution within per-instrument bounds.

---

## Session calendar

### `lib: ship sessions.py (DST-correct) + tests` [lib] ✅ done
- [x] `SessionWindow`, bounds, membership, overlap, weekend gate.
- [x] 13 tests pass incl. DST-mismatch-week 4h overlap + naive-datetime reject.

### `lib: bar tagging (session + overlap + active_sessions)` [lib]
- [ ] Every bar tagged with session, overlap flag, active_sessions.
- [ ] Uses `sessions.py`; no hardcoded UTC offsets anywhere.

---

## Research / features

### `research: feature primitives (Asian H/L, ATR, sweep, BOS, OR)` [quant]
- [ ] Each primitive unit-tested.
- [ ] **No-lookahead property tests** (feature at t uses only data ≤ t).
- [ ] BOS/sweep detection deterministic (same input → same output).

### `research: strategy notebooks for the 3 hypotheses` [quant]
- [ ] One per strategy; imports `libs/`.
- [ ] References the hypothesis docs; records params tested.

---

## Cost model

### `lib: cost model (spread/slippage/commission, session+news scaling, XAU profile)` [lib]
- [ ] Per-instrument profiles; XAU/USD block distinct from FX.
- [ ] Adverse slippage on stops; session multipliers via `sessions.py`.
- [ ] `stress_factor` sweeps {1.0, 1.25, 1.5}.
- [ ] Unit tests: XAU ≠ FX profile; pip conventions (JPY 0.01, XAU 0.1) correct.

---

## Backtest runner

### `backtest: VectorBT screening runner (reproducible)` [quant]
- [ ] Fast vectorized triage; logs commit + data_hash + params.
- [ ] Output reproducible bit-for-bit.

### `backtest: walk-forward + lockbox + Monte Carlo + deflated Sharpe` [quant]
- [ ] WF with per-window reporting.
- [ ] Lockbox access counter (warn/fail on second open).
- [ ] MC trade-sequence (p50/p95 DD).
- [ ] DSR from logged trial count.

### `backtest: cost-sensitivity sweep + reject rule` [quant]
- [ ] Runs {1.0, 1.25, 1.5}×.
- [ ] Flags any strategy negative at 1.5× as REJECTED.

---

## Reporting

### `report: go/no-go report template wired to results` [quant]
- [ ] Template populated from experiment log.
- [ ] All sections present per `go-no-go-report-template.md`.

### `report: experiment log (MLflow or sqlite run table)` [infra]
- [ ] Every backtest/validation run recorded with full repro tuple.

---

## Test suite

### `test: no-lookahead property tests for features` [test]
- [ ] Feature values unchanged when future bars are removed.

### `test: cost-model unit tests (XAU vs FX)` [test]
- [ ] Correct pip math; adverse slippage on stops; XAU distinct.

### `test: reproducibility test (same inputs -> same metrics)` [test]
- [ ] Two runs from identical repro tuple produce identical metrics.

---

## Milestone

All issues above = **Phase 0 complete** when the [`go-no-go-report`](./go-no-go-report-template.md) is filled and returns a verdict. No Phase 1 issues are filed until that verdict is **GO**.
