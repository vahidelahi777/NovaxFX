# Session Calendar Specification

**Status:** implemented + tested · **Owner:** Backend + Data Engineer · **Module:** `libs/data/sessions.py`

## Principle

Store and reason about every instant in **UTC**. **Define** sessions in local exchange time and convert via `zoneinfo`, so DST — including the London/New-York mismatch weeks — is correct **by construction**, not by hardcoded offsets.

This closes the single most common silent backtesting bug. A hardcoded UTC overlap window silently mislabels ~an hour of bars twice a year. That same class of error produces nonsense regime labels (e.g. "RANGING 100% of windows").

## Session definitions (convention — configurable per vendor)

| Session | Local window | Timezone | DST behavior |
|---|---|---|---|
| ASIA (Tokyo) | 09:00–18:00 | Asia/Tokyo | **No DST** → always 00:00–09:00 UTC |
| LONDON | 08:00–16:00 | Europe/London | GMT ↔ BST |
| NEW YORK | 08:00–17:00 | America/New_York | EST ↔ EDT |
| LONDON–NY OVERLAP | LONDON ∩ NEWYORK | — | shifts/lengthens with DST |

> These local hours are a documented convention, not a law. What must be correct is the **conversion**, not the exact local boundaries. Override per data-vendor convention; the correctness tests still hold.

## Verified overlap windows (computed by the module)

| Regime | Example date | ASIA (UTC) | LONDON (UTC) | NEW YORK (UTC) | Overlap (UTC) |
|---|---|---|---|---|---|
| Winter (both standard) | 2025-01-15 | 00:00–09:00 | 08:00–16:00 | 13:00–22:00 | **13:00–16:00 (3h)** |
| Spring mismatch (US EDT, UK GMT) | 2025-03-12 | 00:00–09:00 | 08:00–16:00 | 12:00–21:00 | **12:00–16:00 (4h)** |
| Summer (both DST) | 2025-07-15 | 00:00–09:00 | 07:00–15:00 | 12:00–21:00 | **12:00–15:00 (3h)** |
| Autumn mismatch (UK GMT, US EDT) | 2025-10-29 | 00:00–09:00 | 08:00–16:00 | 12:00–21:00 | **12:00–16:00 (4h)** |

**Why the mismatch weeks matter:** the UK and US change DST on different Sundays (UK: last Sun Mar / last Sun Oct; US: 2nd Sun Mar / 1st Sun Nov). During the gaps the overlap is **4 hours, not 3**. Any code that assumes a fixed UTC overlap is wrong for ~4 weeks every year.

## Representation in code

- Sessions are immutable `SessionWindow(name, tz, start, end)` records (`end` exclusive).
- Membership/bounds computed by converting via `zoneinfo`.
- **Naive datetimes are rejected** — forces tz-aware UTC discipline everywhere.
- Coarse FX weekend gating: closed Fri 21:00 → Sun 21:00 UTC (refine with a holiday calendar in Phase 1).

### Public API

```python
session_bounds_utc(name: str, local_day: date) -> tuple[datetime, datetime]
is_in_session(name: str, dt_utc: datetime) -> bool
overlap_bounds_utc(local_day: date) -> tuple[datetime, datetime] | None
is_in_overlap(dt_utc: datetime) -> bool
active_sessions(dt_utc: datetime) -> list[str]
is_fx_market_open(dt_utc: datetime) -> bool
```

## Test requirements (shipped: 13 tests passing)

- [ ] ASIA bounds constant at 00:00–09:00 UTC year-round (Japan no DST).
- [ ] Winter and summer overlaps are exactly 3h.
- [ ] **Both DST-mismatch weeks are exactly 4h** (spring + autumn).
- [ ] `is_in_overlap` agrees with `overlap_bounds_utc`; end boundary is exclusive.
- [ ] Naive datetime raises `ValueError`.
- [ ] Non-UTC aware input is normalized (not mishandled).
- [ ] Weekend gating: closed Saturday, open midweek.

Run: `pytest -q libs/data/test_sessions.py`

## Acceptance criteria

- [ ] `sessions.py` committed under `libs/data/`.
- [ ] All session-correctness tests pass in CI.
- [ ] Bar-tagging utility assigns session + overlap + `active_sessions` to every bar.
- [ ] No module anywhere computes sessions from hardcoded UTC offsets.

## Phase 1 follow-ups (not now)

- Real exchange holiday calendar (replace coarse weekend gate).
- Per-instrument session relevance weighting.
- Half-day / early-close handling around major holidays.
