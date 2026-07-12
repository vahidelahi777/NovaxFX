# Novax FX — Competitive Analysis & Feature Roadmap
**Date:** July 2026 · **Author:** Engineering

---

## Comparable Projects

### 1. QuantConnect (LEAN Engine)
**Website:** quantconnect.com · **Open source:** Yes (LEAN) · **Cloud platform:** Yes

| Dimension | QuantConnect | Novax FX |
|---|---|---|
| Backtest engine | Event-driven, multi-asset | Bar-by-bar, FX/gold focused |
| Research integrity | None enforced | Deflated Sharpe + lockbox + artifact trail |
| Multi-testing correction | Manual — user's responsibility | Built-in: DSR penalises every trial |
| Live trading | Brokerage integrations (IBKR, Alpaca, etc.) | Planned (OANDA v20 target) |
| Data | Cloud-hosted (Quandl, alternative datasets) | Dukascopy (self-hosted Parquet) |
| Cost model | Commission configurable | Pessimistic: spread floor + slippage + commission |
| Language | C# (LEAN) / Python API | Python 3.12+ |
| Deployment | Cloud (QuantConnect servers) | Self-hosted Docker (Hetzner) |
| Customisability | Medium (cloud constraints) | Full (own infra) |
| Price | Free tier + $8–$20/mo | Infrastructure cost only |

**Novax advantages:**
- Research integrity is structural, not optional — you cannot bypass the lockbox
- Full stack ownership: no vendor lock-in, no data privacy concerns
- Pessimistic cost model: results are conservative by design
- Custom Tehran timezone, XAU/USD-first design

**QuantConnect advantages:**
- Massive data library (years of tick data, alternative data)
- Live broker connections out of the box
- Large community, strategy forum, research notebooks

---

### 2. NautilusTrader
**Website:** nautilustrader.io · **Open source:** Yes · **Language:** Python + Rust

| Dimension | NautilusTrader | Novax FX |
|---|---|---|
| Backtest engine | Production-identical (same code runs live) | Custom causal engine; NautilusTrader planned |
| Performance | Rust core, nanosecond events | Python, bar-by-bar (research focus) |
| Research integrity | None enforced | Full (DSR, lockbox, artifact trail) |
| Live trading | FTX, Binance, IBKR, OKX adapters | Planned (OANDA) |
| Strategy reuse | Same object live + backtest | Planned alignment |
| Learning curve | Very high (Rust concepts, actor model) | Low (pure Python) |
| Documentation | Good but complex | Internal specs + test coverage |

**Novax advantages:**
- Research integrity layer (NautilusTrader has none)
- Simpler mental model for the research loop
- Validated data quality gate before any engine run

**NautilusTrader advantages:**
- Production-grade performance (Rust core)
- True backtest-to-live parity (same strategy object)
- More broker adapters

---

### 3. Freqtrade (crypto, but design reference)
**Website:** freqtrade.io · **Language:** Python · **Focus:** Crypto

| Dimension | Freqtrade | Novax FX |
|---|---|---|
| Domain | Crypto (Binance, KuCoin, etc.) | FX + Gold |
| Research workflow | Hyperopt (grid search over parameters) | Walk-forward + deflated Sharpe |
| Overfitting protection | None — Hyperopt actively encourages it | Structural: artifact trail + lockbox |
| Live trading | Yes (crypto exchanges via ccxt) | Planned |
| Dashboard | Integrated FreqUI | Planned (Next.js) |
| Community | Very large | Internal |

**Key observation:** Freqtrade's Hyperopt is the exact failure mode Novax is designed to prevent.
Running 10,000 parameter combinations and picking the best one is not research — it is
noise discovery with a professional UI.

---

### 4. Jesse (crypto, Python)
**Website:** jesse.trade · **Language:** Python · **Focus:** Crypto

A clean, well-designed backtester with a good research loop. No live FX support, no
research integrity layer, no multi-testing correction.

---

## Where Novax Stands Out

**The three things no competitor enforces:**

1. **Deflated Sharpe by default** — every trial is counted and penalises your reported Sharpe.
   QuantConnect, Freqtrade, Jesse: none of them do this.

2. **One-shot lockbox** — you cannot access the out-of-sample window until all decisions
   are frozen, by code. You physically cannot cheat even by accident.

3. **Artifact trail before execution** — the trial is logged before the backtest runs.
   If you crash mid-run, the log still shows you attempted it. No hidden experiments.

---

## Feature Suggestions (Prioritised)

### Tier 1 — High value, close to current capabilities

**F1 — Regime detection gate**
- Classify market as trending / ranging / volatile using ATR percentile + ADX
- Gate strategies: WeeklyBOSRetest only runs in trending regimes
- Prevents trading a breakout strategy in a choppy market
- Implementation: `src/novax/indicators/regime.py` + gate in `EventScheduler`

**F2 — Monte Carlo drawdown simulator**
- Given a trade series, simulate 10,000 random orderings to bound worst-case drawdown
- Required for P3 risk engine: "what is the 95th-percentile max drawdown?"
- Implementation: `src/novax/validation/monte_carlo.py`

**F3 — Signal score (0–100)**
- Decompose confluence into components: structure (0–30), momentum (0–30), session (0–20), spread (0–20)
- Store each component in the `SignalRecord` for ML features later
- Makes every alert self-explanatory: "Score 74/100 — strong structure, good session"

**F4 — Parameter sensitivity surface**
- For any strategy parameter, plot Sharpe vs parameter value across the walk-forward window
- Rejects strategies with a single over-fit peak; requires a plateau
- Already conceptually required by the go/no-go gate; add the visualisation

### Tier 2 — Medium-term, significant value

**F5 — Correlation-aware position sizing**
- If XAU/USD and EUR/USD are both LONG with >0.7 correlation, treat them as one position
- Prevents doubling up on the same risk factor
- Implementation: real-time correlation matrix in `src/novax/risk/correlation.py`

**F6 — News sentiment gate**
- Suppress trading alerts during high-impact news windows (NFP, FOMC, CPI)
- Use an economic calendar API (e.g. ForexFactory, Investing.com) for event times
- Implementation: `src/novax/calendar/news_gate.py`

**F7 — Read-only dashboard (FastAPI + Next.js)**
- Show: live price, current signal, last 10 alerts, weekly levels, paper trade P&L
- No trading controls — read-only enforced at API layer
- TradingView Lightweight-Charts for the chart panel

**F8 — Walk-forward reporting PDF**
- Auto-generate a PDF report for every completed walk-forward run
- Includes: equity curve, drawdown chart, parameter sensitivity, Sharpe waterfall
- Shareable with CTO/CEO without needing code access

### Tier 3 — Longer horizon, strategic value

**F9 — Multi-strategy ensemble**
- Combine WeeklyBOSRetest + GoldPullback + EMACross signals into a single score
- Weight by out-of-sample Sharpe (not in-sample — that is the whole point)
- Requires P2 signal scoring to be complete first

**F10 — Institutional signal API**
- FastAPI endpoint: `GET /signals/latest?symbol=XAUUSD`
- Rate-limited, API-key authenticated
- Enables white-label signal distribution as a revenue stream (P8 target)

**F11 — Adaptive walk-forward (expanding window)**
- Instead of fixed 70/30 split, use expanding window validation
- Each month's test window uses all prior months as training
- More data-efficient, better for shorter history instruments

**F12 — Multi-asset correlation matrix dashboard**
- Real-time heatmap: XAU/USD, EUR/USD, GBP/USD, USD/JPY pairwise correlations
- Regime-coloured: green = trending, amber = choppy, red = news event
- Flagship visual for the P4 dashboard

---

## Recommended Next 3 Features (for Q3 2026)

| Priority | Feature | Effort | Why Now |
|---|---|---|---|
| 1 | F3 — Signal score (0–100) | 2 weeks | Enables P2 and ML features; low risk |
| 2 | F1 — Regime detection gate | 1 week | Prevents bad trades in choppy markets immediately |
| 3 | F2 — Monte Carlo drawdown | 1 week | Required for P3 risk engine; validates position sizing |

These three together complete the path from "research" to "validated, risk-gated paper trading."

---

## Market Positioning

```
Research integrity  ←  Novax  →  Live trading
        ↑                              ↑
  (our strength)              (competitors' strength)
```

The gap to close is live trading infrastructure (P5–P7). The moat to widen is research
integrity — no competitor enforces it structurally. This is the right long-term advantage
because overfitting is the industry's core failure mode, and we are the platform that
makes it impossible.

---

*Internal analysis — not for distribution.*
