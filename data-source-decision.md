# Data Source Decision

**Status:** decided · **Owner:** Data Engineer · **Reviewers:** Quant Lead, Senior Trader

## Decision

For Phase 0, ingest from **two primary free sources** and one secondary:

1. **Dukascopy** — PRIMARY for deep historical depth (incl. XAU/USD).
2. **OANDA v20 (practice)** — PRIMARY for execution-aligned reference + streaming.
3. **TwelveData** — SECONDARY for cross-checks/convenience.

**Defer** all paid/institutional feeds (Databento, Polygon, Refinitiv, Bloomberg) until an edge is validated. Buying high-end data before proving an edge exists is spending money to postpone the real question.

## Comparison

| Source | Pros | Cons | Cost | Quality concern | Phase 0 fit |
|---|---|---|---|---|---|
| OANDA v20 practice | REST + streaming, bid/ask candles, execution-aligned, free demo | candle endpoint = base-price group (≠ account live pricing); 5000 candles/req; tick volume only | Free | historical candles differ from your live pricing group | **Primary** (reference) |
| Dukascopy | free deep tick history (bid/ask), ECN-sourced, covers XAU | not our execution broker; weekend/holiday gaps; downloader effort | Free | ECN feed ≠ retail fills | **Primary** (depth) |
| TwelveData | simple REST, FX + metals, already in use | free tier 8 req/min · 800/day; **silent 429s**; shallow free history | Free → ~$29/mo | aggregated; thin free depth | **Secondary** |
| Databento / Polygon / Refinitiv | high quality, depth | cost; overkill pre-validation | $$$ | — | **Deferred** |

## Implementation constraints (engineer-ready)

### OANDA v20 (practice)
- Endpoint: `GET /v3/instruments/{instrument}/candles`. **Max 5000 candles/request** → page with `from`/`to` loop (or the `InstrumentsCandlesFactory` pattern).
- Request `price=BA` (bid+ask) **and** mid; store all three.
- Symbols use underscores: `EUR_USD`, `GBP_USD`, `USD_JPY`, `XAU_USD`.
- **Do not** treat candle data as your live pricing — OANDA historical candles are base-price group and can differ from an account's live pricing group.
- `volume` is **tick volume**, not real volume.
- Token from the demo HUB → "Manage API Access". Practice base URL differs from live; default the SDK to demo.

### Dukascopy
- Use a maintained open-source downloader (Python `duka`, or `dukascopy-node` CLI). Pull **ticks** per instrument/day, resample to 1m/5m in Polars.
- Expect per-day file granularity and slow downloads for multi-year tick ranges — parallelize politely, do not hammer the endpoint.
- Cache raw downloads immutably as Parquet (`source=dukascopy`, `fetch_ts`).
- Caveat: not our execution broker — spreads/fills are a reference, not a promise. Flag weekend/holiday gaps.

### TwelveData
- Free tier: **8 credits/min, 800/day**. `time_series` endpoint; symbols like `EUR/USD`, `XAU/USD`.
- **The fetcher MUST catch HTTP 429 and back off.** Silent skip-and-continue produces invisible data gaps. Treat any uncaught 429 as a build-blocking bug.
- Deep historical depth is limited on free; only use for spot cross-checks, not as a backtest base.

## Ingestion plan

1. Backfill **≥ 5y** M1 (resampled to 5m where used) for EUR/USD, GBP/USD, USD/JPY, XAU/USD from **Dukascopy**.
2. Pull OANDA bid/ask candles over the same range as the **execution-aligned reference**.
3. Use TwelveData only to spot-check divergences.
4. Land everything immutably as Parquet with `source` + `fetch_ts`; never overwrite raw.
5. Build curated UTC OHLCV + spread in DuckDB.
6. **Gate** on the data-quality checklist before any backtest.

## Acceptance criteria

- [ ] All 4 instruments pulled from Dukascopy, ≥ 5y, resampled to 1m + 5m.
- [ ] OANDA bid/ask candles pulled for the same range; symbol mapping verified.
- [ ] TwelveData fetcher handles 429 (unit test simulating rate limit).
- [ ] Raw landing is immutable Parquet with `source` + `fetch_ts`.
- [ ] Curated UTC OHLCV + spread table queryable in DuckDB.
- [ ] Cross-source sanity check: OANDA vs Dukascopy close deltas within a documented tolerance; divergences logged.

## Data-quality checklist (gate before backtests)

- [ ] Coverage ≥ 99.5% of expected bars within trading hours, per instrument/tf.
- [ ] All gaps enumerated with cause (weekend/holiday/missing) — none silently dropped.
- [ ] No zero/negative spreads; spread distribution within sane bounds per instrument.
- [ ] Timestamps tz-aware UTC; no duplicates; monotonic per instrument/tf.
- [ ] Resampling verified deterministic (same input → same bars).
- [ ] XAU/USD precision/pip convention matches [`instrument-universe.md`](./instrument-universe.md).
