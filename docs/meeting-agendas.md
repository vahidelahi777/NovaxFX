# Novax FX — Meeting Agendas
**July 2026**

---

## Meeting 1 — CTO/CEO Quarterly Project Review

**Title:** Novax FX — Q3 2026 Research Platform Review
**Suggested date:** Week of July 14, 2026
**Duration:** 45 minutes
**Attendees:** CEO, CTO, Lead Engineer
**Format:** Screen share + walk through `docs/cto-ceo-review.md`

### Agenda

| # | Topic | Time | Owner |
|---|---|---|---|
| 1 | Platform status overview — what's shipped | 5 min | Engineer |
| 2 | Live demo — CI/CD pipeline, daemon, Telegram alerts | 10 min | Engineer |
| 3 | Research integrity layer — why this matters | 5 min | Engineer |
| 4 | Current limitations (honest assessment) | 5 min | Engineer |
| 5 | Roadmap review — P2 through P5 | 5 min | All |
| 6 | Resource asks — data budget, Hetzner upgrade | 5 min | CEO/CTO decision |
| 7 | Q&A and next steps | 10 min | All |

### Pre-meeting materials (share 24h before)
- [README.md](../README.md) — current state
- [docs/cto-ceo-review.md](cto-ceo-review.md) — executive brief
- GitHub Actions: show last CI run result

### Expected decisions
- [ ] Approve TwelveData data budget (~$50/month)
- [ ] Confirm Hetzner upgrade timeline for paper trading phase
- [ ] Set target date for walk-forward go/no-go review

### Calendar invite template
```
Subject: Novax FX — Q3 2026 Project Review (45 min)
Location: Zoom / Google Meet
Description:
  Quarterly review of the Novax FX research platform.
  We'll cover: what's shipped (491 tests, live daemon, CI/CD),
  current limitations, roadmap to paper trading, and resource asks.

  Pre-read: README.md and docs/cto-ceo-review.md (shared separately)

  Agenda attached.
```

---

## Meeting 2 — Technical Team Demo Day

**Title:** Novax FX — V2 Live Daemon Demo
**Suggested date:** Week of July 14, 2026
**Duration:** 60 minutes
**Attendees:** Full engineering team
**Format:** Live code walkthrough + terminal demo

### Agenda

| # | Topic | Time | Owner |
|---|---|---|---|
| 1 | What changed in V2 (vs V1 daemon) | 5 min | Lead Engineer |
| 2 | Live demo — backtest engine + walk-forward | 10 min | Engineer |
| 3 | Live demo — EventScheduler + calendar events | 10 min | Engineer |
| 4 | Live demo — multi-TF scanner + Telegram alert | 10 min | Engineer |
| 5 | Live demo — Dukascopy pipeline + Parquet layout | 8 min | Engineer |
| 6 | Live demo — CI/CD pipeline in GitHub Actions | 7 min | Engineer |
| 7 | Feature discussion — what we build next | 10 min | All |

### Demo checklist (engineer runs this before the meeting)
- [ ] `git pull` — latest commit on screen
- [ ] `pytest -q` — 491 passing, < 20s
- [ ] GitHub Actions tab — show green CI pipeline
- [ ] Hetzner: `docker ps` — prod-daemon running
- [ ] Telegram: at least one real alert this week
- [ ] `python scripts/run_weekly_bos_retest.py` — show output

### Discussion topics (Feature round)
Use `docs/competitive-analysis.md` as the starting point:
1. Which feature should we build next? (F1/F2/F3 are recommended)
2. Is the signal score (F3) the right way to approach P2?
3. Any gaps in the current test coverage?

### Calendar invite template
```
Subject: Novax FX — V2 Live Daemon Demo + Team Feature Discussion (60 min)
Location: Zoom / Google Meet / in-person
Description:
  Demo of everything shipped in the V2 daemon:
  - Multi-event scheduler (market open/close, London/NY, daily, weekly)
  - Multi-timeframe confluence scanner
  - Telegram alerts (UTC + Tehran time)
  - Dukascopy data pipeline
  - CI/CD auto-deploy to Hetzner

  Second half: decide which features we build in Q3.

  Pre-read: docs/competitive-analysis.md (feature tier list)
```

---

## Meeting 3 — Q3 Sprint Planning

**Title:** Novax FX — Q3 2026 Sprint Planning
**Suggested date:** Week of July 21, 2026 (after CTO/CEO review)
**Duration:** 90 minutes
**Attendees:** Engineering team
**Format:** Whiteboard / Miro + GitHub Issues

### Agenda

| # | Topic | Time | Owner |
|---|---|---|---|
| 1 | Review Q2 retrospective — what went well / what didn't | 10 min | All |
| 2 | Confirm P2 signal scoring scope | 15 min | Lead Engineer |
| 3 | Confirm P3 risk engine scope | 15 min | Lead Engineer |
| 4 | Break into tasks — GitHub Issues for each story | 25 min | All |
| 5 | Assign owners + estimate weeks | 15 min | All |
| 6 | Set sprint cadence — weekly standups? bi-weekly? | 10 min | All |

### Input documents
- `docs/competitive-analysis.md` — feature prioritisation (Tier 1 is scope)
- `docs/cto-ceo-review.md` — KPIs and resource constraints
- `docs/Novax-FX-Implementation-Blueprint.md` — architectural guidance

### Proposed Q3 scope
| Story | Owner | Target |
|---|---|---|
| F3 — Signal score (0–100) | TBD | End of July |
| F1 — Regime detection gate | TBD | Early August |
| F2 — Monte Carlo drawdown | TBD | Mid August |
| Walk-forward go/no-go run (XAU/USD) | Lead Engineer | End of August |
| P3 risk engine spec | Lead Engineer | End of September |

### Calendar invite template
```
Subject: Novax FX — Q3 Sprint Planning (90 min)
Location: Zoom / Google Meet / in-person
Description:
  Q3 planning session. We'll scope and assign:
  - P2 Signal scoring (F3)
  - Regime detection gate (F1)
  - Monte Carlo drawdown (F2)
  - Walk-forward go/no-go run on XAU/USD

  Bring: your capacity estimate for the next 10 weeks.
  Pre-read: docs/competitive-analysis.md → Tier 1 features
```

---

## Meeting 4 — Walk-Forward Go/No-Go Review

**Title:** Novax FX — WeeklyBOSRetest Walk-Forward Go/No-Go Decision
**Suggested date:** End of August 2026 (when walk-forward run is complete)
**Duration:** 60 minutes
**Attendees:** CEO, CTO, Lead Engineer
**Format:** Report walkthrough + go/no-go vote

### Agenda

| # | Topic | Time | Owner |
|---|---|---|---|
| 1 | Walk-forward methodology recap (what we did, what we didn't touch) | 5 min | Engineer |
| 2 | Training window results: Sharpe, drawdown, trade count | 10 min | Engineer |
| 3 | Out-of-sample (lockbox) results: same metrics | 10 min | Engineer |
| 4 | Deflated Sharpe calculation: how many trials were run | 10 min | Engineer |
| 5 | Go/No-Go vote — formal decision | 10 min | CEO + CTO |
| 6 | If GO: paper trading timeline and budget | 10 min | All |
| 7 | If NO-GO: what to investigate next | 5 min | All |

### Decision gate (all must pass for GO)
- [ ] Net-of-costs Sharpe on out-of-sample window > 1.5
- [ ] Deflated Sharpe (corrected for trial count) > 1.0
- [ ] Max drawdown < 20% on out-of-sample window
- [ ] Parameter sensitivity shows plateau (not a single peak)
- [ ] Monte Carlo 95th-percentile drawdown acceptable

### Calendar invite template
```
Subject: Novax FX — WeeklyBOSRetest Go/No-Go Decision Meeting (60 min)
Location: Zoom / in-person (important decision — prefer in-person)
Description:
  Formal go/no-go review for the WeeklyBOSRetest strategy on XAU/USD.
  The lockbox will be opened for the first time in this meeting.
  Outcome: GO (paper trading approved) or NO-GO (back to research).

  This is a gated decision — please read the walk-forward report
  (shared the day before) carefully before the meeting.
```

---

## Standing Meetings (Recommended)

### Weekly Engineering Standup — 15 minutes
- What shipped since last week
- Blockers
- CI status (green or investigation needed)
- Format: async Telegram message if all is green; sync call only if blocked

### Bi-weekly Strategy Research Review — 30 minutes
- Signal quality review: how are 15M alerts performing?
- Data quality review: any gaps in Dukascopy history?
- Walk-forward progress update

---

*Meeting agendas — internal use only.*
