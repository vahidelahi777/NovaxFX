# NovaxFX — Dev → Prod workflow (Claude operating model)

How the Claude "team" plans and ships to your two environments: **local dev**
(your computer) and **production** (Hetzner). Grounded in the existing pipeline
(`.github/workflows/ci.yml`, `deploy.yml`, `docker-compose.yml`).

## Roles
- **Cowork (planning brain)** — reviews the repo, creates & prioritizes tasks on
  `phase-0-task-board.md`, writes grounded prompts (`agent-prompts.md`), reviews
  results, maintains `decision-log.md`. Never edits prod.
- **VSCode Claude plugin (the hands)** — implements ONE task at a time on your
  local machine; runs `ruff` + `mypy` + `pytest` locally before pushing.
- **GitHub Actions CI (the gatekeeper)** — `lint → test (3.12 & 3.13) → docker`.
  No secrets; must be green to merge.
- **Hetzner (production)** — Docker Compose services; real secrets in
  `/opt/NovaxFX/.env`. Updated only by `deploy.yml` on green CI.

## Environments
| | Local dev | CI | Production (Hetzner) |
|---|---|---|---|
| Where | your computer | GitHub runners | `/opt/NovaxFX` |
| Data | InMemory repo / local Postgres | none (unit tests only) | Postgres + Parquet volumes |
| Secrets | `.env` with a **separate dev** bot token | none | prod `.env` (never in git) |
| Trading | paper / education only | none | live data; **no real money until risk engine ships** |
| Bot token | dev bot from @BotFather | — | prod bot |

Use a **different Telegram bot** for dev vs prod so testing never posts to real
users. Same for the database.

## The loop (per task)
1. **Cowork** scopes one board task → writes a prompt grounded in current code.
2. **You** paste it into the VSCode plugin; it implements + adds tests.
3. **Locally** (VSCode runs these): `ruff check src tests` · `ruff format --check src tests` · `mypy` · `pytest`.
4. **Branch + PR**: `git checkout -b <task-id>-slug`, commit, push, open a PR to `main`.
5. **CI** runs the 3-job pipeline. Red = fix on the branch. Green = mergeable.
6. **Review**: paste the diff back to Cowork for a second-pass review, or self-merge.
7. **Merge to `main`** → `deploy.yml` fires on CI success → SSH to Hetzner:
   `git pull --ff-only` → `docker compose build` → `docker compose up -d` → health check.
8. **Verify** the `docker ps` status line in the deploy log; watch `logs/`.

## Best practices (hold these)
- **Protect `main`.** Require PR + green CI; never push straight to `main`. All
  work on short-lived feature branches named by task id (`A3-onboarding`).
- **One task per PR.** Small, reviewable diffs. Additive changes only unless the
  task says otherwise.
- **Secrets never in git.** `.env` is git-ignored; prod secrets live only on
  Hetzner and in GitHub Actions secrets (`DEPLOY_HOST/USER/KEY`). Rotate the
  Telegram token if it ever leaks. Never log tokens.
- **Parity via Docker.** Before pushing infra changes, `docker compose build`
  locally so the image that CI/Hetzner builds is the one you tested.
- **Safety gates first.** No live broker execution until the risk engine +
  kill switch ship (decision D-001). Dev and staging stay paper-only.
- **Rollback plan.** A bad deploy is fixed by `git revert` + re-merge (re-runs
  deploy), or SSH `git checkout <prev-sha> && docker compose up -d --build`.
- **Observability.** Keep the daemon heartbeat; tail `logs/`; add an uptime
  alert on the prod containers.
- **Backups.** Once Postgres is in prod, schedule `pg_dump` of the users DB.

## Known gaps to close before the product bot runs in prod
1. **Bot not in `docker-compose.yml`.** Only `prod-daemon`, `channel-aggregator`,
   `weekly-analysis` exist. Add a `product-bot` service running
   `python scripts/run_bot.py`. → task DZ1.
2. **No Postgres service.** The user registry (A2) needs one in prod. Add a
   `postgres` service (or a managed DB) + a volume + `apply_schema` on boot,
   and wire `DATABASE_URL` into `.env`. → task DZ2.
3. **Path mismatch.** ~~Fixed (DZ3)~~ — both `deploy.yml` and `deploy/setup_ubuntu.sh`
   now use `/opt/NovaxFX`.
4. **Branch protection** not enforced — enable required PR + CI on `main`. → DZ4.
5. ~~**channel-aggregator crash-loops** when aggregator secrets absent.~~ Fixed (DZ5) — service is
   now opt-in via the `aggregator` Compose profile. `docker compose up -d` no longer starts it.
   Enable on demand: `docker compose --profile aggregator up -d channel-aggregator`.
   Requires four secrets in `.env`: `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE`,
   `ANTHROPIC_API_KEY` (see `.env.example` for the commented template).
