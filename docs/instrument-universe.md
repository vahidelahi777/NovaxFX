# Instrument Universe

**Status:** locked · **Owner:** Quant Lead + Senior Trader

## Locked Phase 0 universe (4)

EUR/USD · GBP/USD · USD/JPY · XAU/USD

Chosen for liquidity, regime diversity, and direct relevance to the 3 priority strategies. XAU/USD is included because it is the existing system's actual focus and behaves distinctly — it is a **metal, not an FX major**, and must use its own cost/vol assumptions.

## Specs

| Instrument | Class | pip_size | price_precision | Typical character | Best-fit sessions | Cost/vol notes |
|---|---|---|---|---|---|---|
| EUR/USD | FX major | 0.0001 | 5 | tightest spread, deepest liquidity, cleaner ranges | London, NY, overlap | benchmark; tightest costs |
| GBP/USD | FX major | 0.0001 | 5 | more volatile, sharp London moves | London, overlap | wider than EUR/USD; good sweep candidate |
| USD/JPY | FX major | 0.01 | 3 | Asian sensitivity, BoJ/rate-driven | Asia, NY | **pip math = 0.01**; watch intervention/news |
| XAU/USD | Metal | 0.1 (define & document) | 2 | high ATR, gappy, risk-driven | London, NY, overlap | **wider spread, larger pip value, bigger ATR — never reuse FX defaults** |

> **pip convention warning:** USD/JPY pip = 0.01, not 0.0001. XAU/USD conventions vary by broker; we **define pip_size = 0.1 with price_precision = 2** and use it consistently in every cost and PnL calculation. Mixing conventions silently corrupts expectancy math. Encode these in a single config, referenced everywhere.

## Per-instrument requirements

- [ ] Store exact `pip_size` and `price_precision` per instrument in one config block.
- [ ] Attach DST-correct session profile (from `sessions.py`) to each instrument.
- [ ] XAU/USD gets its **own** cost profile (spread floor, slippage, pip value) — a separate block, not FX defaults. See [`cost-model-spec.md`](./cost-model-spec.md).
- [ ] PnL and risk math read pip_size from config, never hardcoded.

## Validation rule

A strategy must pass on **≥ 3 of 4** instruments to advance. A strategy that only works on one instrument is treated as a likely fluke and **rejected**, not "kept for later."

## Out of scope for Phase 0

USD/CHF, AUD/USD, NZD/USD, USD/CAD, EUR/JPY, GBP/JPY, EUR/GBP. Add only after the core 4 show signal. Adding instruments before validation just multiplies the testing surface and the multiple-testing penalty.

## Acceptance criteria

- [ ] Config block exists with pip_size + price_precision for all 4 instruments.
- [ ] Unit test asserts USD/JPY pip = 0.01 and XAU/USD pip = 0.1 are applied in PnL math.
- [ ] Session profile attaches correctly to each instrument.
- [ ] XAU/USD cost profile is distinct from FX-major profile (asserted in test).
