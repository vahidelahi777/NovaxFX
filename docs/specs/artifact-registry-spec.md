# Artifact & Provenance Registry (Phase 0.7)

**Status:** implemented + tested (`src/novax/artifacts.py`, `src/novax/provenance.py`).

## Purpose
Every research claim must be backed by an artifact whose provenance is verifiable and
whose content is hashed. The gate reads artifacts, not assertions; the registry is what
makes "no validation claim without an artifact path" enforceable.

## Artifact schema
Every `Artifact` carries (all required; missing metadata fails closed):

| Field | Meaning |
|---|---|
| `artifact_id` | content-addressed id (hash of type + payload + provenance) |
| `run_id` | the `evaluate` run that produced it |
| `trial_id` | the logged trial it belongs to (must be blessed) |
| `campaign_id` | multiple-testing campaign |
| `artifact_type` | `ArtifactType` enum (equity curve, trade ledger, MC dd, …) |
| `created_at` | UTC, tz-aware (naive rejected) |
| `git_commit` | repo commit at run time |
| `config_hash` | hash of params |
| `data_hash` | dataset/version identity |
| `feature_version` | feature-pipeline version |
| `cost_model_version` | cost model identity |
| `validation_protocol_version` | protocol identity |
| `random_seed` | seed for determinism |
| `code_version` | package version |
| `environment_hash`, `dependency_lock_hash` | env + lockfile identity (Phase 1 to populate) |
| `parent_artifact_ids` | lineage (e.g. MC dd derives from equity curve) |
| `file_path` | where the payload lives |
| `content_hash` | sha256 of the serialized payload |

## ArtifactType (required gate set)
`EQUITY_CURVE`, `TRADE_LEDGER`, `DATA_QUALITY`, `NO_LOOKAHEAD`, `WALK_FORWARD`,
`RANDOMIZED_ENTRY`, `ONE_BAR_DELAY`, `COST_STRESS`, `MONTE_CARLO_DD`. The gate's
`REQUIRED_ARTIFACTS` tuple is exactly this set; a run missing any is `NO_GO`.

## Immutability rules
- Artifacts are frozen dataclasses; `content_hash` is computed at creation.
- `register_trial_id` must be called (by the runner) before any artifact for that trial
  is accepted — `ArtifactRegistry` refuses artifacts for unblessed trial_ids.
- Re-emitting the same `(run_id, artifact_type)` is a duplicate and is rejected/flagged.

## Stale & mismatch detection
The gate computes a provenance tuple `(data_hash, feature_version, cost_model_version)`
for each artifact and requires them to be identical across the required set. Mixing a
fresh equity curve with a stale cost-stress artifact → "provenance mismatch" → `NO_GO`.
`run_id` mismatch is likewise rejected.

## Directory layout (Phase 1 on-disk; Phase 0.7 in-memory)
```
artifacts/
  <campaign_id>/
    <run_id>/
      equity_curve.json      # + sidecar .meta.json with full provenance
      trade_ledger.json
      monte_carlo_dd.json
      ...
```
In Phase 0.7 the registry is in-memory (no ingested data yet); the schema and hashing
are identical so the on-disk layout is a serialization detail.

## Lineage graph
`parent_artifact_ids` lets the registry reconstruct derivation (MC drawdown ← equity
curve ← trade ledger). Orphan detection walks all artifacts and flags any `trial_id`
not present in the trial registry.

## Tests
- [x] Artifact rejects naive `created_at`.
- [x] Registry refuses an artifact whose `trial_id` was never blessed.
- [x] Duplicate `(run_id, type)` detected.
- [x] `orphans()` finds artifacts with no logged trial.
- [x] Content hash changes when payload changes.

## Failure modes
| Failure | Behavior |
|---|---|
| Artifact for unblessed trial | rejected at emit |
| Missing provenance field | fail closed (cannot construct) |
| Mixed provenance across required set | gate `NO_GO` |
| Orphan artifact | CI audit violation |

## Adversarial cases
- **Provenance forgery via mixing:** can't pass an old favorable artifact alongside new
  ones — provenance tuple mismatch is caught.
- **Artifact without a trial:** rejected; can't manufacture evidence out of band.

## Specced for Phase 1
On-disk serialization, real `environment_hash` / `dependency_lock_hash` capture from the
live venv + lockfile, and a persisted lineage graph viewer.
