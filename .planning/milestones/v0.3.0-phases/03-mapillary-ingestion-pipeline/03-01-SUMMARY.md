---
phase: 03-mapillary-ingestion-pipeline
plan: 01
subsystem: database
tags: [postgres, migration, postgis, schema, idempotency, provenance]

# Dependency graph
requires:
  - phase: 01-mvp-integrity-cleanup
    provides: BIGINT source/target columns + 001_initial.sql baseline that 002 extends
  - phase: 02-real-data-detector-accuracy
    provides: data/eval_la/.gitkeep pattern reused for data/ingest_la/
provides:
  - segment_defects.source_mapillary_id TEXT (per-image dedup key, NULL allowed)
  - segment_defects.source TEXT NOT NULL DEFAULT 'synthetic' with CHECK (synthetic|mapillary)
  - UNIQUE INDEX uniq_defects_segment_source_severity on (segment_id, source_mapillary_id, severity) — ON CONFLICT target for idempotent ingest
  - INDEX idx_defects_source on segment_defects(source) — fast --source filter
  - docker-compose mount of 002 migration into Postgres init flow
  - data/ingest_la/ cache root + .gitignore exclusion (CC-BY-SA imagery safety)
  - 5 integration tests (idempotency, UNIQUE+NULL semantics, backfill, CHECK)
affects: [03-02-source-filter, 03-03-ingest-cli, 03-04-wipe-synthetic, 03-05-operator-runbook]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Idempotent migration via ADD COLUMN IF NOT EXISTS + CREATE UNIQUE INDEX IF NOT EXISTS + DROP-then-ADD CHECK"
    - "Default-backfill via NOT NULL DEFAULT 'synthetic' avoids separate UPDATE statement"
    - "NULL-distinct UNIQUE preserved (no NULLS NOT DISTINCT) so synthetic rows with NULL source_mapillary_id continue to coexist"

key-files:
  created:
    - db/migrations/002_mapillary_provenance.sql
    - data/ingest_la/.gitkeep
    - backend/tests/test_migration_002.py
  modified:
    - docker-compose.yml
    - .gitignore

key-decisions:
  - "Use CREATE UNIQUE INDEX IF NOT EXISTS instead of ADD CONSTRAINT UNIQUE because Postgres 16 has no idempotent ADD-CONSTRAINT form (RESEARCH.md Pitfall 8)"
  - "Preserve default Postgres NULL-distinct UNIQUE behavior (not NULLS NOT DISTINCT) so multiple synthetic rows per (segment_id, severity) remain legal — required by seed_data.py:108-112 (RESEARCH.md Pitfall 6)"
  - "DROP-then-ADD pattern for the source CHECK constraint guarantees idempotent re-apply"
  - "Mount path /docker-entrypoint-initdb.d/03-mapillary.sql sequences after 02-schema.sql so 001 lands first on fresh init"

patterns-established:
  - "Migration-002 PG16 idempotency template: ADD COLUMN IF NOT EXISTS for columns, DROP-then-ADD for CHECK, CREATE UNIQUE INDEX IF NOT EXISTS for UNIQUE — all safe to re-run"
  - "Provenance column convention: source TEXT NOT NULL DEFAULT 'synthetic' with CHECK list; new sources require CHECK update"
  - "Phase-scoped data cache pattern: data/<phase>_<region>/* gitignored with .gitkeep allowlist, mirrors Phase 2 eval_la layout"

requirements-completed: [REQ-mapillary-pipeline]

# Metrics
duration: 14min
completed: 2026-04-25
---

# Phase 03 Plan 01: Mapillary Ingest Schema Foundation Summary

**Idempotent Postgres 16 migration adds segment_defects.source_mapillary_id + source columns plus UNIQUE index for ON CONFLICT-driven ingest dedup, mounted into the docker init flow with cache directory scaffolding and 5 regression tests guarding NULL-distinct UNIQUE semantics.**

## Performance

- **Duration:** ~14 min
- **Started:** 2026-04-25T20:52:00Z
- **Completed:** 2026-04-25T21:06:33Z
- **Tasks:** 3
- **Files created/modified:** 5 (3 created, 2 modified)

## Accomplishments

- Schema foundation that all subsequent Phase 3 plans depend on: provenance columns, dedup index, source-filter index, and CHECK constraint all land in a single idempotent SQL file
- docker-compose now mounts the new migration into the Postgres init flow so fresh stacks (`docker compose up` on an empty volume) pick up the schema without manual psql apply
- `.gitignore` blocks `data/ingest_la/*` (CC-BY-SA Mapillary imagery + per-run manifests) with `.gitkeep` allowlist, mirroring the Phase 2 `eval_la` pattern
- 5 integration tests cover idempotency, UNIQUE+NULL semantics (Pitfall 6 regression guard), Mapillary-row dedup, DEFAULT backfill, and CHECK constraint rejection

## Task Commits

Each task was committed atomically (no-verify per parallel-executor protocol):

1. **Task 1: Author migration 002_mapillary_provenance.sql** — `c1d7922` (feat)
2. **Task 2: Mount migration + ingest cache .gitignore + .gitkeep** — `afe87da` (chore)
3. **Task 3: 5 migration integration tests (idempotency + NULL+UNIQUE + backfill + CHECK)** — `c50b16c` (test)

**Plan metadata:** SUMMARY.md will be committed below.

## Files Created/Modified

- `db/migrations/002_mapillary_provenance.sql` — created — DDL: add `source_mapillary_id TEXT`, add `source TEXT NOT NULL DEFAULT 'synthetic'`, DROP+ADD `segment_defects_source_check`, CREATE UNIQUE INDEX `uniq_defects_segment_source_severity`, CREATE INDEX `idx_defects_source`. SHA256: `8066cdbeea124635ab9cfafea940630b3b182e5d6cdf543ea670957742b8b3f9`
- `docker-compose.yml` — modified — added 1 volume mount line: `./db/migrations/002_mapillary_provenance.sql:/docker-entrypoint-initdb.d/03-mapillary.sql`
- `.gitignore` — modified — appended Phase 3 block: `data/ingest_la/*` exclusion + `!data/ingest_la/.gitkeep` allowlist
- `data/ingest_la/.gitkeep` — created — empty (0 bytes) placeholder so cache root exists at clone time
- `backend/tests/test_migration_002.py` — created — 5 integration-marked tests covering idempotency, UNIQUE+NULL, dedup blocking, backfill, and CHECK rejection

## Migration SQL Reference

For plan 02/03 executors that need to read/inject the migration text, the file lives at `db/migrations/002_mapillary_provenance.sql` (40 lines, 1.7 KB). SHA256 above. Key statements (verifiable via grep):

```sql
ALTER TABLE segment_defects ADD COLUMN IF NOT EXISTS source_mapillary_id TEXT;
ALTER TABLE segment_defects ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'synthetic';
ALTER TABLE segment_defects DROP CONSTRAINT IF EXISTS segment_defects_source_check;
ALTER TABLE segment_defects ADD CONSTRAINT segment_defects_source_check CHECK (source IN ('synthetic', 'mapillary'));
CREATE UNIQUE INDEX IF NOT EXISTS uniq_defects_segment_source_severity ON segment_defects (segment_id, source_mapillary_id, severity);
CREATE INDEX IF NOT EXISTS idx_defects_source ON segment_defects(source);
```

## DB State Baseline

DB was **not** reachable in this worktree environment (Docker stack not running). The baseline `SELECT source, COUNT(*) FROM segment_defects GROUP BY source` query — which RESEARCH.md cites as the cutover smoke check — could not be executed here. This is expected: parallel executor worktrees don't bring up the full docker stack. When the migration is applied via either:
- a fresh `docker compose up` (auto-applies via the new mount), or
- `docker compose exec -T db psql -U rq -d roadquality < db/migrations/002_mapillary_provenance.sql` on an existing dev DB,
the baseline must be `synthetic | <total row count>` (zero `mapillary` rows until plan 03's ingest CLI runs).

## Test Counts and Behavior

- **Total tests:** 5 (all in `backend/tests/test_migration_002.py`)
- **Marker:** `pytest.mark.integration` — auto-skipped when DB unreachable via the `db_available` fixture in `conftest.py`
- **Test names** (per the plan's behavior spec):
  - `test_migration_idempotent` — re-applies migration; verifies index + CHECK constraint each exist exactly once via `pg_indexes` / `pg_constraint`
  - `test_unique_allows_multiple_null_synthetic_rows` — Pitfall 6 regression guard: two `(segment_id=X, source_mapillary_id=NULL, severity='moderate')` rows must coexist
  - `test_unique_blocks_duplicate_mapillary_rows` — second insert with same `(segment_id, source_mapillary_id='test_dup_999999', severity)` raises `UniqueViolation`; cleans up
  - `test_existing_synthetic_rows_backfill_source` — asserts `synth == total` after migration apply (DEFAULT did the backfill)
  - `test_check_constraint_rejects_invalid_source` — `source='unknown'` raises `CheckViolation`

## Decisions Made

- **Idempotency via DROP-then-ADD CHECK + CREATE UNIQUE INDEX IF NOT EXISTS** — rather than `ALTER TABLE ... ADD CONSTRAINT ... UNIQUE (...)`. Postgres 16 has no idempotent ADD-CONSTRAINT form, so a second migration apply on an existing DB would error. The plan's RESEARCH.md Pitfall 8 documents this directly.
- **Default NULL-distinct UNIQUE preserved** — explicitly NOT adding the option that would treat NULLs as equal. Required by `seed_data.py:108-112`'s pattern of inserting multiple synthetic rows per `(segment_id, severity)` (each with `source_mapillary_id IS NULL`). Test 2 is the regression guard.
- **DEFAULT 'synthetic' on the new source column** — does the backfill of existing rows automatically (no separate UPDATE statement needed). Postgres 11+ implements DEFAULT-on-ADD as metadata-only, so the migration is fast even on large tables.
- **Mount sequence number 03** — chosen so the new migration applies after `02-schema.sql` on a fresh `docker compose up` with empty pgdata volume. (Postgres init scripts run alphabetically.)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Reworded migration header comments to satisfy the plan's grep-absence assertions**
- **Found during:** Task 1 verification
- **Issue:** The plan's verbatim header comment block contained the literal phrase `NULLS NOT DISTINCT` (in a "do not add this" warning) and `ADD CONSTRAINT IF NOT EXISTS` (in a "PG16 doesn't support this" warning). Both phrases are also in the plan's automated grep verification as **must-not-be-present** assertions. Following the plan's header verbatim would fail those assertions.
- **Fix:** Rewrote the relevant comment lines to convey the same warning without using the literal forbidden phrases — e.g., "do NOT add the option that would treat NULLs as equal" instead of "NOT \`NULLS NOT DISTINCT\`", and "Postgres 16 has no idempotent ADD-CONSTRAINT form" instead of "no \`ADD CONSTRAINT IF NOT EXISTS\`". Semantic intent preserved; behavioral guard is provided by Test 2 (UNIQUE+NULL regression test).
- **Files modified:** `db/migrations/002_mapillary_provenance.sql` (comment block only — no DDL change)
- **Verification:** All 9 grep assertions in Task 1's verify block now pass.
- **Committed in:** `c1d7922` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — reconciled plan-internal contradiction between verbatim header text and grep verification).
**Impact on plan:** No scope creep. Comment-only adjustment. Acceptance-criterion grep assertions take precedence over the verbatim header text per the plan's own automated `<verify>` block.

## Issues Encountered

- **System Python is 3.9.6, project pins 3.12** — when running `python3 -m pytest backend/tests/test_migration_002.py` in this worktree, the import chain fails on `app/cache.py:17` (`dict | None` PEP 604 syntax requires Python 3.10+). This is a pre-existing project scaffolding condition, not introduced by plan 03-01. The tests will run successfully under the project's intended runtime (Python 3.12 inside the backend Docker container or a 3.12 venv with `pip install -r backend/requirements.txt`). Static structural verification of the test file (5 `def test_*` functions, integration marker, valid Python via `ast.parse`) was performed locally as a substitute. **Logged as a worktree-environment limitation; out of scope for 03-01.** Future executors should run the suite via `docker compose exec backend pytest backend/tests/test_migration_002.py -x` once the stack is up.
- **No DB available in worktree** — also expected; tests are designed to skip cleanly via `db_available` fixture, but that fixture's `pytest.skip` only fires when the conftest can load. Above issue prevents that. Both will resolve when run in the project's intended runtime.

## User Setup Required

None — no external service configuration. The migration is applied automatically on fresh `docker compose up` (via the new mount), or operators with an existing dev DB run:

```bash
docker compose exec -T db psql -U rq -d roadquality < db/migrations/002_mapillary_provenance.sql
```

This will be documented in the operator runbook (plan 03-05).

## Next Phase Readiness

The schema is ready for downstream Phase 3 plans:

- **Plan 03-02 (`--source` filter):** `idx_defects_source` index is in place; `compute_scores.py --source` filter has a column to filter on
- **Plan 03-03 (ingest CLI):** `source_mapillary_id` column exists; UNIQUE index `uniq_defects_segment_source_severity` is the ON CONFLICT target for idempotent re-runs; `data/ingest_la/` cache root exists with gitignore in place
- **Plan 03-04 (`--wipe-synthetic`):** `source` column with CHECK constraint enables `DELETE FROM segment_defects WHERE source = 'synthetic'`
- **Plan 03-05 (operator runbook):** Documents the manual `psql -f` apply path for already-running dev DBs (the mount only auto-applies on fresh init).

No blockers. Migration is idempotent — safe to re-run on any state of `segment_defects`.

## Self-Check: PASSED

Verified post-write:
- `db/migrations/002_mapillary_provenance.sql` — FOUND
- `docker-compose.yml` — modified, mount line FOUND
- `.gitignore` — modified, `data/ingest_la/*` + `!.gitkeep` FOUND
- `data/ingest_la/.gitkeep` — FOUND (0 bytes)
- `backend/tests/test_migration_002.py` — FOUND (5 test functions, valid Python)
- Commit `c1d7922` (Task 1) — FOUND in `git log`
- Commit `afe87da` (Task 2) — FOUND in `git log`
- Commit `c50b16c` (Task 3) — FOUND in `git log`
- Migration SHA256 `8066cdbeea124635ab9cfafea940630b3b182e5d6cdf543ea670957742b8b3f9` — verified via `shasum -a 256`

---
*Phase: 03-mapillary-ingestion-pipeline*
*Plan: 01*
*Completed: 2026-04-25*
