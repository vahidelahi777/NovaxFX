# Novax FX Platform — Phase 0 Scaffold

Research-only foundation for the Novax FX platform. **No live capital, no broker
execution, no external services.** Everything reasons in timezone-aware UTC.

This scaffold exists to make the Phase 0 question answerable honestly: *is there a
realistic, cost-aware edge worth building around?* See `docs/phase-0/` for the
full plan; this repo is the code under those specs.

## Requirements

- Python **3.12+**
- (dev) `pytest`, `ruff`, `mypy`

## Layout

```
src/novax/
  __init__.py        # public re-exports
  config.py          # Settings + Phase 0 go/no-go thresholds (single source of truth)
  sessions.py        # DST-correct session calendar (Asia/London/NY/overlap)
  instruments.py     # EUR/USD, GBP/USD, USD/JPY, XAU/USD + pip math
  data_sources.py    # local/in-memory only; provider adapters are deferred seams
  costs.py           # conservative cost model (spread/slippage/commission, XAU distinct)
  validation.py      # metrics, deflated Sharpe, lockbox guard, go/no-go evaluation
tests/
  test_sessions.py   # boundaries, DST mismatch weeks, naive-datetime rejection
  test_instruments.py# pip conventions (JPY 0.01, XAU 0.1), registry
  test_costs.py      # conservatism, XAU > FX, stress scaling, adverse stop slippage
```

## Setup & test

```bash
# editable install (optional)
pip install -e ".[dev]"

# run tests (pytest is configured with pythonpath=src, so install is optional)
pytest

# lint / types
ruff check src tests
mypy
```

## Design rules (enforced in code)

- **UTC everywhere.** Naive datetimes are rejected at the boundary (`sessions`, `Bar`,
  `TradeRecord`). No silent local-time assumptions.
- **DST by construction.** Sessions are defined in local exchange time and converted via
  `zoneinfo`. The London/NY overlap is computed as an intersection, so it correctly
  lengthens to **4h** during DST-mismatch weeks (tested). A hardcoded UTC overlap would
  mislabel ~an hour of bars twice a year.
- **Pip conventions are explicit.** USD/JPY pip = 0.01, XAU/USD pip = 0.1. PnL math reads
  `pip_size` from the registry; never hardcode it.
- **Costs are pessimistic.** Spread floors, slippage (fixed + ATR-scaled), adverse stop
  slippage, session multipliers (Asia thinner), and a `stress_factor` swept over
  {1.0, 1.25, 1.5}. XAU/USD has its own profile — FX assumptions are never reused for gold.
- **Anti-self-deception.** `validation.py` implements deflated Sharpe (penalizes the number
  of trials), a one-shot `Lockbox` guard, and a strict `evaluate_go_no_go` that returns
  NO_GO on any failed criterion.

## Quick example

```python
from datetime import date, datetime, UTC
from novax import overlap_bounds_utc, get_instrument, pips, DEFAULT_COST_MODEL

# DST-correct overlap (spring mismatch week -> 4 hours)
print(overlap_bounds_utc(date(2025, 3, 12)))   # (12:00Z, 16:00Z)

# pip math respects conventions
print(pips(get_instrument("USD/JPY"), 0.10))   # 10.0

# conservative round-trip cost, stressed
cm = DEFAULT_COST_MODEL.with_stress(1.5)
print(cm.round_trip_cost_pips("XAU/USD", atr_pips=30, session="ASIA", exit_on_stop=True))
```

## Calibration TODO (before any result is trusted)

- [ ] Replace placeholder cost floors in `costs.py` with values calibrated to realized feed spreads.
- [ ] Replace nominal `pip_value_per_lot` in `instruments.py` with rate-accurate values for PnL.
- [ ] Implement real data adapters (deferred seams in `data_sources.py`) per `docs/phase-0/data-source-decision.md`.

## Scope guardrails

Not in this scaffold (deferred per the architecture decision): live trading, broker
execution, dashboards, ML, SaaS, Kubernetes, Kafka, microservices, feature store.
