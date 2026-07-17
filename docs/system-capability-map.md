# NovaxFX — System Capability Map & Build Plan

Your full application vision mapped to what exists in the repo today. Status:
✅ done · 🟡 partial · 🔴 to build. Grounded in a repo scan (Jul 2026).

| #   | Capability                                                    | Status | What exists today                                                                                                           | Gap → epic                                                                                 |
| --- | ------------------------------------------------------------- | ------ | --------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| 1   | **Realtime WS data (XAUUSD): price, candle…**                 | 🟡     | `data/stream/twelvedata_ws.py` (WS adapter), `data/ingest/{dukascopy,twelvedata}.py` (historical/REST)                      | Wire WS → live bar aggregation → persist continuously (daemon currently polls). **Epic R** |
| 2   | **Store on DB**                                               | 🟡     | Parquet (`data/storage`), DuckDB `SignalStore`, Postgres (users)                                                            | No time-series store for live prices/candles (TimescaleDB or DuckDB rollup). **Epic R**    |
| 3   | **Strategies + indicators + money mgmt + all trading params** | 🟡     | 6 strategies, 7 indicators (EMA/ATR/BOS/SuperTrend/TSI/…), `costs.py`, `instruments.py`                                     | **No money-management / position-sizing / risk module.** **Epic K**                        |
| 4   | **Signal generator + scoring**                                | ✅      | `multi_tf_scanner`, `signal_scanner`, `signal_score` (0–100), `signal_store`                                                | Fan-out done (B1); live wiring in flight (B5)                                              |
| 5   | **Daily & weekly reports**                                    | ✅      | `fmt_daily_report`, `fmt_weekly_report` in the live daemon                                                                  | —                                                                                          |
| 6   | **Semi & auto bot trading**                                   | 🟡     | `paper_trader`, `trade_journal` (simulated)                                                                                 | No broker execution, no pre-trade risk gate, no semi/auto executor. **Epic K + Epic X**    |
| 7   | **Fetch news + LLM on price & news**                          | 🟡     | `news_gate` (economic-calendar blackout), `channel_aggregator` (Telethon + Anthropic summarize)                             | No news→feature pipeline; no LLM analysis/RAG over price+news. **Epic N**                  |
| 8   | **Web platform (technical + fundamental)**                    | 🔴     | none yet (admin H1 starts the FastAPI stack)                                                                                | Full FastAPI API + Next.js trading UI. **Epic W (Phase 1)**                                |
| 9   | **Research engine (backtest + forward test)**                 | ✅      | `engine`, `walkforward`, `validation` (deflated Sharpe + lockbox), `gate`, `harness`, `trial_registry`, `metrics`, `runner` | Backtest ✅; walk-forward ✅; live-paper = forward test. Monte-Carlo/regime = later          |

**Headline:** signals, scoring, reports, and the validated research engine are done. The
missing pieces cluster into five new epics: **R** (realtime data), **K** (risk/money
mgmt), **X** (broker execution), **N** (news + LLM), **W** (web trading platform).

---

## New epics & tasks

### Epic R — Realtime data & storage
- **R1** Wire `twelvedata_ws` into a continuous stream → 1m/15m bar aggregation → persist (append to the store the engine already reads). Reconnect/backfill on gaps.
- **R2** Choose the live time-series store: TimescaleDB (per blueprint) or DuckDB rollups. Schema for `prices`/`candles`; retention + backups.

### Epic K — Money management & risk engine (safety-critical)
- **K1** Position-sizing / money-management module: risk-per-trade %, ATR-based sizing, pip-value from `instruments`, max exposure. Pure + fully tested.
- **K2** Pre-trade **risk gate + kill switch** (repo P3): limits, max drawdown circuit-breaker, hard stop. **Must ship before any live execution (decision D-001).** Admin H5 wires the UI toggle to this.

### Epic X — Broker execution (on the user's own account)
- **X1** OANDA v20 broker adapter: auth with the user's own encrypted keys (A4), place/modify/close orders with TP/SL. No pooled funds, no custody.
- **X2** **Semi-auto** executor: bot proposes → human confirms → order sent through the K2 risk gate. (Recommended default.)
- **X3** **Fully-auto** executor: autonomous, hard risk gate + kill switch, small capital only. Gated behind K2 + validation + legal review.

### Epic N — News + LLM analysis
- **N1** News ingestion pipeline (economic calendar + headlines) → stored, timestamped, linked to instruments.
- **N2** LLM analysis (**RAG, not training**): ground a model on retrieved price context + news to produce **fundamental commentary** and an explainable read. *Note: literally training a foundation model is out of scope/expensive; best practice is RAG + small ML models (LightGBM) for price features, per the blueprint.*
- **N3** (optional) ML/LLM-derived signal features fed into the score — only if they beat the baseline out-of-sample (respect the deflated-Sharpe gate).

### Epic W — Web trading platform (Phase 1)
- **W1** FastAPI API exposing signals, analytics, track record, prices (builds on the admin FastAPI stack from Epic H).
- **W2** Next.js + TradingView Lightweight-Charts UI: **technical** (charts, indicators, signals) + **fundamental** (news, calendar, LLM commentary).
- **W3** Accounts, subscriptions, broker-connect UI, unified Telegram↔web identity.

---

## Recommended sequence (respecting dependencies & safety)
1. **Finish Phase 0 loop:** B5 (wire fan-out) → admin H1→H7 → G1 + payments. *(monetizable bot)*
2. **Epic R** (realtime data) + **Epic N1/N2** (news + LLM commentary) — feed better analysis into signals and the `/analyze` surface.
3. **Epic K** (money mgmt + **risk engine/kill switch**) — the hard gate.
4. **Epic X** (broker): X1 → **X2 semi-auto** (stop here for a good while) → X3 fully-auto *(small capital, gated)*.
5. **Epic W** (web platform) — Phase 1, in parallel once the API from H exists.

**Non-negotiables:** no live-money execution before K2 + validated strategy + legal
review; auto-trading always on the user's own account/keys; no profit promises.
