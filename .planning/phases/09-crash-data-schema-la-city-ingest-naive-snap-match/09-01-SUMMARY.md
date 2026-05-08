---
phase: 09-crash-data-schema-la-city-ingest-naive-snap-match
plan: 01
subsystem: database
tags: [postgres, postgis, migration, schema, idempotency, crash-data, foreign-key]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: road_segments table with SERIAL id (FK parent for snapped_segment_id)
  - phase: 03-mapillary
    provides: 002_mapillary_provenance.sql idempotency template (CREATE IF NOT EXISTS, DROP-then-ADD CHECK)
provides:
  - crash_records table (BIGSERIAL id, source/source_record_id UNIQUE, severity CHECK, geom POINT 4326, snapped_segment_id INTEGER FK SET NULL)
  - segment_scores.crash_norm DOUBLE PRECISION NOT NULL DEFAULT 0.0 column (Phase 10 will populate)
  - GIST(geom) and btree(snapped_segment_id) access indexes
  - UNIQUE(source, source_record_id) ON CONFLICT target for idempotent ingest
  - 5-test pytest module pinning schema invariants on a live DB
affects: [09-02 snap helper, 09-03 socrata client, 09-04 ingest_crashes driver, phase 10 crash_norm population, phase 12 disclaimer copy]

# Tech tracking
tech-stack:
  added: []  # No new libraries — pure DDL + psycopg2 already vendored
  patterns:
    - "DROP CONSTRAINT IF EXISTS ... ADD CONSTRAINT pattern for idempotent CHECK constraints (Postgres 16 has no idempotent ADD-CONSTRAINT form)"
    - "Separate CREATE UNIQUE INDEX IF NOT EXISTS instead of inline column UNIQUE for re-applicable migrations"
    - "FK column type must match parent column type literally (INTEGER vs BIGINT) — Pitfall D"

key-files:
  created:
    - db/migrations/004_crash_records.sql
    - backend/tests/test_migration_004.py
  modified: []  # No edits to existing files; both artifacts are new

key-decisions:
  - "Used INTEGER not BIGINT for crash_records.snapped_segment_id to match road_segments.id SERIAL parent type (Pitfall D resolution; CONTEXT D-09-10 first draft was BIGINT)"
  - "Added segment_scores.crash_norm in this migration despite Phase 10 owning population — keeps schema atomic and the LEFT JOIN COALESCE(0) safety net intact during the 09→10 gap (D-09-11)"
  - "Mirrored 002_mapillary_provenance.sql idempotency pattern line-by-line; no clever simplifications (D-09-12)"
  - "ON DELETE SET NULL on the FK so historical crash records survive segment topology rebuilds"

patterns-established:
  - "Migration idempotency template (CREATE IF NOT EXISTS / CREATE UNIQUE INDEX IF NOT EXISTS / DROP-then-ADD CHECK) is now used in both 002 and 004 — codify as the project DDL convention for any future migration"
  - "FK type matching is verified at test time via information_schema.columns (test_migration_004_fk_type_is_integer) — apply this pattern to future FKs against SERIAL parents"
  - "PostGIS column shape verified via geometry_columns view (type + srid) — repeatable across future spatial migrations"

requirements-completed:
  - REQ-crash-ingest-lacity

# Metrics
duration: ~4min
completed: 2026-05-08
---

# Phase 9 Plan 01: Crash-Data Schema Foundation Summary

**Migration 004 introduces `crash_records` (BIGSERIAL id, source/source_record_id UNIQUE, severity CHECK, GEOMETRY POINT 4326, INTEGER FK to road_segments) and adds `segment_scores.crash_norm` — applied cleanly twice on a live PostGIS DB and pinned by a 5-test pytest module verifying idempotency, FK type, geom shape, and CHECK enforcement.**

## Performance

- **Duration:** ~4 min (217 s)
- **Started:** 2026-05-08T05:19:29Z
- **Completed:** 2026-05-08T05:23:06Z
- **Tasks:** 2 (both `type="auto"`; Task 2 is the Wave-0 RED test)
- **Files modified:** 2 (both created; no edits to existing files)

## Accomplishments

- `crash_records` table created with all decisions D-09-10/15 fields and constraints
- Pitfall D resolved: `snapped_segment_id INTEGER` matches `road_segments.id SERIAL` — verified live via `information_schema.columns` (`integer`)
- `segment_scores.crash_norm DOUBLE PRECISION NOT NULL DEFAULT 0.0` added by this migration so Phase 10 can populate without a second DDL change (D-09-11)
- Migration applies cleanly on a fresh DB AND on a previously-applied DB (idempotency confirmed via two consecutive `psql` applies on the live `agent-a85c90f3-db-1` Postgres 16 + PostGIS container; second apply emitted only `NOTICE: ... already exists, skipping` lines and no errors)
- 5 pytest assertions hold against the live DB; re-running pytest a second time also passes (idempotency holds at the test layer too)

## Task Commits

Each task was committed atomically (no `git add -A`; only the specific files):

1. **Task 1: Author migration 004 (crash_records + crash_norm column)** — `56fbb76` (feat)
2. **Task 2: Wave-0 RED test for migration 004 idempotency + FK type** — `bf270c3` (test)

_Note: Plan 09-01 is `type: execute`, not plan-level TDD, so Task 2 is a single test commit (no separate RED→GREEN→REFACTOR cycle). The test file IS the Wave-0 RED contract per 09-VALIDATION.md row 9-01-01._

**Plan metadata commit:** _Pending_ — this SUMMARY is committed in a separate `docs(09-01)` commit (see end of summary).

## Files Created/Modified

- `db/migrations/004_crash_records.sql` — Migration 004 DDL: `crash_records` table, both CHECK constraints (DROP-then-ADD), unique index on `(source, source_record_id)`, GIST index on `geom`, btree index on `snapped_segment_id`, and `segment_scores.crash_norm` additive column.
- `backend/tests/test_migration_004.py` — Five integration tests (auto-skipped if `db_available` fixture cannot connect):
  - `test_migration_004_idempotent` — applies migration twice, asserts each artifact exists exactly once
  - `test_migration_004_fk_type_is_integer` — Pitfall D regression guard (`data_type == 'integer'`)
  - `test_migration_004_adds_crash_norm_column` — verifies the additive column shape
  - `test_migration_004_geom_is_point_4326` — PostGIS `geometry_columns` view check
  - `test_migration_004_check_severity_rejects_unknown` — INSERT with `severity='unknown'` raises `CheckViolation`

## Final SQL contents (verbatim)

```sql
-- Migration 004: crash_records table + segment_scores.crash_norm column.
-- Phase 9, plans 09-01..09-04. Implements decisions D-09-10 (table shape),
-- D-09-11 (segment_scores.crash_norm column), D-09-12 (idempotent mirror of
-- migration 002), D-09-15 (UNIQUE on source+source_record_id for ON CONFLICT).
--
-- Mirrors db/migrations/002_mapillary_provenance.sql line-by-line: CREATE IF
-- NOT EXISTS, separate CREATE UNIQUE INDEX, DROP-then-ADD CHECK constraints.
-- Postgres 16 supports IF NOT EXISTS on column adds and indexes but does NOT
-- support an idempotent ADD CONSTRAINT form. Safe to re-run on fresh,
-- half-applied, or fully-applied DBs.
--
-- FK type note: snapped_segment_id is INTEGER (not BIGINT) to match the
-- parent column type road_segments.id which is SERIAL (= INTEGER) per
-- migration 001. Postgres rejects FKs whose parent/child types don't match.
-- (Pitfall D in 09-RESEARCH.md; matches segment_defects.segment_id INTEGER
-- precedent in 001_initial.sql line 20.)

-- D-09-10: crash_records table (NEW). ON DELETE SET NULL preserves the raw
-- crash row even if segment topology is rebuilt.
CREATE TABLE IF NOT EXISTS crash_records (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    severity TEXT NOT NULL,
    occurred_at DATE NOT NULL,
    snapped_segment_id INTEGER REFERENCES road_segments(id) ON DELETE SET NULL,
    snap_distance_m DOUBLE PRECISION,
    geom GEOMETRY(POINT, 4326) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- DROP-then-ADD CHECK constraints (Postgres 16 has no idempotent ADD-CONSTRAINT form).
-- Mirrors 002_mapillary_provenance.sql lines 26-30.
ALTER TABLE crash_records DROP CONSTRAINT IF EXISTS crash_records_source_check;
ALTER TABLE crash_records ADD CONSTRAINT crash_records_source_check
    CHECK (source IN ('lacity'));   -- v0.4.1 will widen to ('lacity','switrs')

ALTER TABLE crash_records DROP CONSTRAINT IF EXISTS crash_records_severity_check;
ALTER TABLE crash_records ADD CONSTRAINT crash_records_severity_check
    CHECK (severity IN ('fatal', 'injury', 'pdo'));

-- D-09-15: ON CONFLICT target. UNIQUE on (source, source_record_id) so re-running
-- ingest produces zero new rows on the same Socrata `dr_no` set.
CREATE UNIQUE INDEX IF NOT EXISTS idx_crash_records_source_id
    ON crash_records (source, source_record_id);

-- Spatial + foreign-key access patterns.
CREATE INDEX IF NOT EXISTS idx_crash_records_geom
    ON crash_records USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_crash_records_segment
    ON crash_records (snapped_segment_id);

-- D-09-11: segment_scores.crash_norm column (NEW, additive, default 0).
-- Populated by Phase 10's compute_scores.py extension; Phase 9 leaves it at 0.
-- Adding it here keeps the schema migration atomic so the LEFT JOIN COALESCE(0)
-- safety net works during the Phase 9 → 10 gap.
ALTER TABLE segment_scores
    ADD COLUMN IF NOT EXISTS crash_norm DOUBLE PRECISION NOT NULL DEFAULT 0.0;
```

## Live DB Verification (Postgres 16 + PostGIS, container `agent-a85c90f3-db-1`)

```text
-- snapped_segment_id type
 column_name        | data_type
--------------------+-----------
 snapped_segment_id | integer        -- Pitfall D resolved (NOT bigint)

-- segment_scores.crash_norm shape
 column_name | data_type        | is_nullable | column_default
-------------+------------------+-------------+----------------
 crash_norm  | double precision | NO          | 0.0

-- crash_records.geom shape
 type  | srid
-------+------
 POINT | 4326

-- Constraint/index existence (1 each)
 source_check_count | sev_check_count | uniq_idx_count
                  1 |               1 |              1

-- pytest run (5/5 pass; second invocation also 5/5 pass)
============================== 5 passed in 0.33s ==============================
```

## Decisions Made

- **Used INTEGER (not BIGINT) for FK column** — required to match `road_segments.id SERIAL` per migration 001 line 2. Pitfall D from 09-RESEARCH.md, explicitly carried into the plan and re-verified against the live `\d road_segments` output (`id | integer`). The CONTEXT.md D-09-10 first draft said BIGINT; the corrected SQL block in the plan was followed verbatim.
- **`crash_norm` added in this migration** despite Phase 10 owning population — keeps the schema migration atomic. Phase 9 LEFT JOIN paths can `COALESCE(crash_norm, 0)` safely without breaking, and Phase 10 ships only the population code.
- **No deviations from the plan's verbatim SQL block** — copied as specified.

## Deviations from Plan

None — plan executed exactly as written.

### Acceptance-Criteria Note (informational, not a deviation)

The plan's Task-1 acceptance criterion `grep -c "ON DELETE SET NULL" ... returns 1` actually returns `2` against the verbatim-copied SQL because the comment header on line 18 (`-- D-09-10: crash_records table (NEW). ON DELETE SET NULL preserves the raw...`) also matches. The substantive DDL clause exists exactly once on line 26 (the FK column definition). The plan's `<action>` block explicitly required copying the SQL "verbatim" including this comment, so the verbatim-copy directive supersedes the literal grep count. No code change was made; flagging here for orchestrator visibility.

---

**Total deviations:** 0
**Impact on plan:** None — Tasks 1 and 2 implemented exactly as specified.

## Issues Encountered

- **Docker volume mount conflict** when initially trying `docker cp` to apply the migration: the container has an active bind-mount on `db/migrations/` from the original worktree path. Resolved by piping the SQL via `cat ... | docker exec -i ... psql` instead — same outcome, no mount conflict. Did not affect any artifact in this plan.
- **`python` not on PATH; `pytest` not in system Python** — used `/tmp/rq-venv/bin/python -m pytest` per the project memory ("road-quality-mvp Python runtime"). Tests ran from `backend/` cwd with `PYTHONPATH=.` and `DATABASE_URL=postgresql://rq:rqpass@localhost:5432/roadquality` so `from app.main import app` and `from app.db import DATABASE_URL` resolved correctly.

## Threat Surface (per plan threat_model)

All three STRIDE entries from the plan threat_model were addressed by the artifacts (no new surface introduced):
- **T-9-05 (idempotent re-apply):** mitigated by `IF NOT EXISTS` and DROP-then-ADD; verified by `test_migration_004_idempotent`.
- **T-9-01 (FK type mismatch crash on apply):** mitigated by `INTEGER` FK type; verified by `test_migration_004_fk_type_is_integer` and the live `\d road_segments` cross-check.
- **T-9-02 (precise lat/lon information disclosure):** accepted; the API surface that exposes `crash_records.geom` directly is gated to internal callers only and is out of scope for this plan.

No additional threat flags surfaced during execution.

## Self-Check: PASSED

- `db/migrations/004_crash_records.sql` — FOUND
- `backend/tests/test_migration_004.py` — FOUND
- Commit `56fbb76` (Task 1 feat) — FOUND
- Commit `bf270c3` (Task 2 test) — FOUND

```bash
$ test -f db/migrations/004_crash_records.sql && echo FOUND
FOUND
$ test -f backend/tests/test_migration_004.py && echo FOUND
FOUND
$ git log --oneline | grep -E "56fbb76|bf270c3"
bf270c3 test(09-01): add migration 004 idempotency + schema invariant tests
56fbb76 feat(09-01): add migration 004 for crash_records table + crash_norm column
```

## Next Phase Readiness

- Plan 09-02 (`data_pipeline/snap.py` + `data_pipeline/lacity_mocodes.py`) can now FK-reference the live `crash_records.snapped_segment_id` shape during its DB-tests fixture setup.
- Plan 09-03 (Socrata client) is unaffected by 09-01 (no DB dependency).
- Plan 09-04 (`scripts/ingest_crashes.py`) can rely on:
  - `INSERT INTO crash_records ... ON CONFLICT (source, source_record_id) DO NOTHING` working as the idempotency target
  - `snapped_segment_id` accepting plain `INTEGER` values from `data_pipeline/snap.py::snap_point_to_segment`
  - Severity values constrained to `('fatal','injury','pdo')` (operator-style drift will surface as `CheckViolation` rather than silent corruption)
- Phase 10 can populate `segment_scores.crash_norm` directly without additional schema work.
- Operator runbook update (Phase 12) should note: applying 004 to an already-running v0.3.0 DB is safe; it adds the table, the column, and the indexes without touching existing rows.

---
*Phase: 09-crash-data-schema-la-city-ingest-naive-snap-match*
*Plan: 01*
*Completed: 2026-05-08*
