# NovaxFX — Admin Panel plan (Epic H)

Internal operations console for admins. First concrete slice of the FastAPI
gateway described in `Novax-FX-Implementation-Blueprint.md` (`/api/v1`, `admin`
role, `/admin/audit`, `/risk/kill-switch`), scoped to four v1 capabilities:
**user & tier management · signal monitoring · broadcast · system health + kill switch.**

## Decisions
- **Backend: FastAPI** (matches blueprint). New package `src/novax/admin/`.
- **UI: server-rendered Jinja2 + HTMX** for the admin panel specifically — one
  Python deployable, fast to build, easy to secure. (Next.js stays reserved for
  the customer-facing Phase 1 site; the admin console is an internal tool and
  doesn't need a separate SPA build.)
- **Auth v1: session-cookie login** with a single admin password hashed
  (argon2/bcrypt) in env; path to JWT + roles (research/trader/admin/operator)
  later per the blueprint.
- **Data: read from Postgres** (`bot_users`, via the existing repository) and the
  **DuckDB `SignalStore`** (`recent`, `score_breakdown`, `win_rate`,
  `count_by_status`, `cumulative_pnl_pips`). Kill switch = a persisted flag the
  signal fan-out (and later the auto-trade executor) checks before acting.
- **Deploy:** a new `admin` compose service **behind a TLS reverse proxy**
  (Caddy) — never expose FastAPI directly.

## Security (non-negotiable for an admin surface)
- TLS only; HttpOnly + Secure + SameSite=strict cookies.
- CSRF token on every mutating POST.
- Password hashed (argon2/bcrypt), never plaintext; login rate-limited + lockout.
- **Audit log** of every admin action (who, what, when, before/after).
- Kill switch is **fail-safe**: if in doubt, halted. Default-safe on error.
- Least privilege; no secrets in logs; optional IP allowlist; separate subdomain.

## Architecture (pure/wiring split, like the bot)
```
src/novax/admin/
  app.py         # FastAPI wiring: routers, session middleware, CSRF, startup
  auth.py        # password hash/verify, session issue/verify, login rate-limit
  services.py    # PURE query/command functions over repo + SignalStore (testable)
  views/         # Jinja2 templates (base, login, users, signals, broadcast, health)
  killswitch.py  # read/set the global halt flag (shared with signal fan-out)
  audit.py       # append-only admin action log (Postgres table)
scripts/run_admin.py   # uvicorn entry point
```
Tests hit `services.py`, `auth.py`, `killswitch.py`, `audit.py` (pure, no live
server/DB where possible); routes get thin smoke tests via FastAPI TestClient.

## Task breakdown (Epic H)
| ID | Task | Depends on |
|---|---|---|
| **H1** | FastAPI skeleton + auth (login/logout, hashed pw, session cookie, CSRF, rate-limit) + base layout + `/health` page | DZ2 |
| **H2** | Users & tiers: list/search/paginate, detail, set tier, ban/unban (+ additive `status` column on `bot_users`) | H1 |
| **H3** | Signal monitoring: recent signals, score breakdown, win rate, counts, cumulative PnL (reads `SignalStore`) | H1 |
| **H4** | Broadcast: compose → send to all/tier via the bot; confirm + rate-limit + audit | H1, B1 |
| **H5** | System health + **global kill switch** (service status, error counts; persisted halt flag read by fan-out/auto-trade) | H1 |
| **H6** | Admin **audit log** — record every mutating action + a view page | H1 |
| **H7** | Deploy: `admin` compose service behind Caddy TLS reverse proxy; env + docs | H1..H6 |
| **H8** | *(later)* Auto-trading controls (per-strategy enable, capital caps) — gated behind the risk engine | risk engine |

## Sequencing
DZ2 (Postgres) is a prerequisite. Then **H1 → H6 (audit early) → H2 → H3 → H5 →
H4 → H7**. H5's kill switch should land before any live-execution work.
