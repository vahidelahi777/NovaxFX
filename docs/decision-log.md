# NovaxFX — Decision Log

> Append-only record of company/product/technical decisions. Newest at top.
> Format: date · decision · rationale · owner · status. Mirrors the repo's artifact-trail philosophy: every call is auditable.

---

## 2026-07-16

### D-007 · Set up the AI "team" as reusable Claude roles
**Decision:** Operate NovaxFX as an AI-run startup. Roles (CTO, forex-expert, QA, researcher, etc.) are Claude subagents/features, not persistent hires; company memory lives in the repo (`docs/`, decision log, task board).
**Rationale:** Subagents are stateless; auditable repo-based memory matches the existing artifact trail.
**Owner:** Vahid + Claude · **Status:** ✅ Adopted (see `team-charter.md`)

### D-006 · Product = wrap the existing engine, don't rebuild
**Decision:** The customer product is a thin product layer (interactive Telegram bot → website) over the existing research engine. No engine rewrite.
**Rationale:** Repo already has 491 tests, live daemon, signal scoring, paper trader. The missing piece is a multi-user product surface, not more engine.
**Owner:** Vahid · **Status:** ✅ Adopted

### D-005 · Product posture = Education + Signals + Analysis (no custody)
**Decision:** General (non-personalized) signals + education + analysis. Bot-trading hooks run **only** on the user's own broker account with their own keys. No pooled funds, no discretionary management, no profit promises.
**Rationale:** Keeps us out of heavy licensing lanes (FCA/CySEC/ASIC/CFTC); matches repo's existing "not financial advice" stance. Lawyer review required before charging or live execution.
**Owner:** Vahid · **Status:** ✅ Adopted

### D-004 · Go-to-market phasing: Phase 0 Telegram → Phase 1 website
**Decision:** Ship the interactive Telegram product first, website second. Maps onto the repo's internal P0–P8 engineering roadmap (product layer sits above it).
**Owner:** Vahid · **Status:** ✅ Adopted

### D-003 · Telegram framework = python-telegram-bot (v22.x)
**Decision:** Build the product bot on python-telegram-bot; aiogram is the fallback if we need fully-async from day one.
**Rationale:** Mature, large community, matches Python stack, coexists with the existing daemon.
**Owner:** Claude (CTO) · **Status:** ⏳ Proposed — awaiting Vahid confirm

### D-002 · Broker hooks = OANDA v20 first, MetaApi later
**Decision:** Start with OANDA v20 (clean REST, `oandapyV20`, repo already targets it); add MetaApi (any MT4/5 broker) once there's demand. Semi-auto (human-confirm) before any full automation.
**Owner:** Claude (CTO) · **Status:** ⏳ Proposed — awaiting Vahid confirm

### D-001 · Risk engine ships BEFORE any live-money execution
**Decision:** Pre-trade risk gate + position limits + kill switch (repo P3) must ship before broker hooks touch real money. Paper first.
**Rationale:** Non-negotiable safety + the LLM instruction-hierarchy failure mode (model must never override hard limits).
**Owner:** Vahid · **Status:** ✅ Adopted

---

## Recent engineering state (as of last commit 6e71bdd, 2026-07-15)
Last ~4 days were internal engine work, not product:
- New strategies: TSI momentum, Multi-TF TSI, PrevWeekRange
- PaperTrader wired into live daemon; SL/TP on HOLD bars fixed
- DuckDB signal store, weighted score + confidence engine, NewsGate, heartbeat
- WebSocket stream adapter; unified confluence + scoring gate on `h4_trend`; GoldPullback ATR SL/TP
- CI/CD 3-job pipeline + SSH auto-deploy to Hetzner

**Implication:** engine momentum is strong; the product layer (multi-user bot, learn, subscriptions, broker-connect UX) is greenfield — that's Phase 0.
