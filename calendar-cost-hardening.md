# Calendar & ATR/Cost Hardening (Phase 0.7, High 1–3)

**Status:** implemented + tested (`src/novax/market_calendar.py`, `src/novax/units.py`,
`src/novax/costs.py`, `tests/test_costs.py`, `tests/test_enforcement.py`).

## 1. Market calendar

### Problem
The Phase 0.6 calendar was a hardcoded ~7-date stub: mid-week holidays (Thanksgiving,
Good Friday, July 4) were treated as normal trading days, so holiday-contaminated bars
passed silently.

### Design — computed, provider-based, fail-closed
```python
class CalendarProvider(Protocol):
    def full_closures(self, year: int) -> set[date]: ...
    def half_days(self, year: int) -> set[date]: ...

@dataclass(frozen=True, slots=True)
class ComputedHolidayProvider:  # default
    def full_closures(self, year): ...   # computed for ANY year
    def half_days(self, year): ...
```
`ComputedHolidayProvider` computes, per year:
- **New Year's Day**, **Christmas (25)**, **Boxing Day (26)**;
- **Good Friday** via the Anonymous-Gregorian Easter algorithm (`easter(year) - 2d`);
- **US Independence Day** with the observed Sat→Fri / Sun→Mon rule;
- **Thanksgiving** (4th Thursday of November) and other US market holidays
  (MLK, Presidents', Memorial = last Monday of May, Labor);
- **half-days:** Black Friday (day after Thanksgiving), Christmas Eve.

`MarketCalendar` (NY-17:00 anchored, DST-correct) consults the provider for full
closures and half-days; `is_fx_market_open(dt)` is the public entry.

### XAU/USD note
Gold follows a metals calendar close to the FX one for the major closures handled here;
an instrument-specific provider can be injected (`MarketCalendar(provider=...)`) without
touching call sites. Per-instrument metals/holiday nuances are a Phase 1 refinement.

### Fail-closed behavior
A naive (tz-less) datetime is rejected. Closures are computed (not looked up), so there
is no "year not in table" gap; an injected provider that returns nothing for a year is a
provider bug surfaced by the known-date tests, not a silent pass.

### Tests
- [x] Thanksgiving 2025-11-27 is closed (`test_thanksgiving_2025_handled`).
- [x] Good Friday 2025-04-18 and Christmas are closed (`test_holiday_closes_market`).
- [x] Weekend boundary is DST-correct (existing session tests).

## 2. ATR / Pip unit types

### Problem
Raw-float ATR was ambiguous: `0.0010` could be 10 pips (EUR/USD) or price units passed
by mistake. The Phase 0.6 magnitude guard only caught implausibly *large* values, so
small wrong-unit values passed silently.

### Design — explicit unit types at the boundary
```python
@dataclass(frozen=True, slots=True)
class Pips:        value: float   # finite, >= 0
@dataclass(frozen=True, slots=True)
class PriceUnits:  value: float
def to_pips(instrument, price: PriceUnits) -> Pips: ...
def require_pips(value) -> Pips:   # raises on raw float or PriceUnits
```
Every public CostModel boundary takes `atr: Pips` (default `_ZERO_PIPS`) and runs it
through `require_pips`. A raw float or a `PriceUnits` at that boundary is a `TypeError`,
not a quietly-wrong number.

### Migration
`round_trip_cost_pips(sym, atr_pips=10.0)` → `round_trip_cost_pips(sym, atr=Pips(10.0))`,
or convert: `to_pips(get_instrument("EUR/USD"), PriceUnits(0.0010))`.

### Tests
- [x] `PriceUnits` and raw float are rejected where pips are required; converted value
  works (`test_atr_price_units_rejected`).

## 3. Cost model stress separation

### Problem / fix
Stress scaling must hit spread + slippage, **not** the fixed commission (a per-lot fee
does not widen under volatility). `with_stress(factor)` scales spread/slippage only;
commission is added afterward, unscaled.

### Tests
- [x] `(cost_1.5x − commission) == 1.5 × (cost_1x − commission)`
  (`test_commission_not_stress_multiplied`).

### Specced for Phase 1
- **Realized spread path:** when ingested data carries quoted spread, use it instead of
  the conservative floor.
- **Volatility/session/news spread curve:** widen modeled spread as a function of
  realized volatility and session/news state (floors remain the fail-closed fallback).

## CI enforcement (this area)
`scripts/ci_guards.py` statically forbids re-introducing a raw-float ATR at a CostModel
public boundary (`no-raw-float-atr`) — any `atr` param not annotated `Pips` fails CI.
