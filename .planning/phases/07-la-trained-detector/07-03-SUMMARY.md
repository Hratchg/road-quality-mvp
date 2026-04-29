---
phase: 07-la-trained-detector
plan: "03"
subsystem: database
tags: [python, psycopg2, cli, argparse, ingestion, wipe, phase-07]

requires:
  - phase: 03-mapillary-ingestion-pipeline
    provides: wipe_synthetic_rows pattern + --wipe-synthetic flag in scripts/ingest_mapillary.py
  - phase: 07-la-trained-detector
    plan: "01"
    provides: Wave-0 RED tests for wipe_mapillary_rows (test_ingest_mapillary.py::TestPlan04Flags)

provides:
  - wipe_mapillary_rows(conn) -> int helper in scripts/ingest_mapillary.py
  - --wipe-mapillary CLI flag + --force-wipe safety latch in scripts/ingest_mapillary.py
  - mapillary_rows_wiped counter and wipe_mapillary_applied boolean in run summary JSON

affects:
  - 07-07 (prod re-ingestion: uses --wipe-synthetic --wipe-mapillary against Fly DB)
  - 07-04 (GATE A does not use this flag, but shares the same script)

tech-stack:
  added: []
  patterns:
    - "Hard-coded WHERE clause in wipe helpers (T-03-18/T-07-04): no f-string, no parameterization"
    - "Shared --force-wipe latch governs both --wipe-synthetic and --wipe-mapillary"
    - "Wipe-then-INSERT ordering: synthetic first, mapillary second, then execute_values INSERT"

key-files:
  created: []
  modified:
    - scripts/ingest_mapillary.py

key-decisions:
  - "D-15 (Phase 7): wipe_mapillary_rows mirrors wipe_synthetic_rows exactly with 'mapillary' literal substituted"
  - "Shared --force-wipe flag covers both wipe modes; help text updated to reflect both"
  - "Zero-detection guard checked per flag independently before any wipe runs"

patterns-established:
  - "Wipe helper pattern: def wipe_<source>_rows(conn) -> int with hard-coded WHERE, conn.commit(), logger.info, return deleted"

requirements-completed:
  - REQ-trained-la-detector

duration: 12min
completed: 2026-04-29
---

# Phase 7 Plan 03: wipe_mapillary_rows() + --wipe-mapillary flag for D-15 prod cutover

**Hard-coded `DELETE WHERE source='mapillary'` helper + `--wipe-mapillary` CLI flag with shared `--force-wipe` safety latch added to `scripts/ingest_mapillary.py`, turning 4 Wave-0 RED tests GREEN**

## Performance

- **Duration:** 12 min
- **Started:** 2026-04-29T01:50:00Z
- **Completed:** 2026-04-29T02:02:56Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Added `wipe_mapillary_rows(conn) -> int` function mirroring `wipe_synthetic_rows` exactly with `'mapillary'` literal substituted (T-03-18 + T-07-04 mitigation: hard-coded WHERE, no parameterization)
- Added `--wipe-mapillary` argparse flag (action=store_true) surfaced in `--help`, guarded by shared `--force-wipe` latch
- Refactored wipe-state tracking from single `wipe_planned`/`wipe_applied` to dual `wipe_synthetic_planned/applied` + `wipe_mapillary_planned/applied` variables
- Extended run summary JSON with `wipe_mapillary_applied` boolean and `counters["mapillary_rows_wiped"]` integer
- Turned 4/4 Plan 07-01 Wave-0 RED tests GREEN (all 45 non-integration tests pass, no regressions)

## Task Commits

1. **Task 1: Add wipe_mapillary_rows() + --wipe-mapillary flag** - `054c389` (feat)

## Files Created/Modified

- `scripts/ingest_mapillary.py` — ~67 net insertions (17 deletions + 84 additions): new helper, new argparse flag, updated --force-wipe help text, refactored wipe-state tracking, updated run summary dict

## Decisions Made

- Followed plan exactly: `wipe_mapillary_rows` mirrors `wipe_synthetic_rows` pattern with `'mapillary'` literal
- Safety latch checks each flag independently (not combined): allows partial invocation semantics where one flag passes but the other would fail
- `--wipe-mapillary` inserted between `--force-wipe` and `--no-recompute` in argparse, as specified

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The plan's `<verify>` command referenced `TestCLISmokes::test_wipe_mapillary_rows_*` but the tests live in `TestPlan04Flags` (Wave-0 tests were added to `TestPlan04Flags` in Plan 07-01). Used the correct class in verification. No code impact.
- `/tmp/rq-venv` does not auto-include its own site-packages in `sys.path` (externally managed UV Python). Created temporary `/tmp/test-rq-venv` with Python 3.12 + full backend requirements for test execution. No code impact.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `scripts/ingest_mapillary.py` now has both `--wipe-synthetic` and `--wipe-mapillary` flags ready
- Plan 07-07 (prod re-ingestion) can invoke `--wipe-synthetic --wipe-mapillary` together against the Fly DB after the LA-trained model SHA is captured
- This plan does NOT invoke the prod cutover — that is Plan 07-07's responsibility

## Threat Flags

None - no new network endpoints, auth paths, file access patterns, or schema changes. The new `wipe_mapillary_rows` function is bounded by the existing schema-level CHECK constraint (`source IN ('synthetic', 'mapillary')`) established in `db/migrations/002_mapillary_provenance.sql`.

---
*Phase: 07-la-trained-detector*
*Completed: 2026-04-29*

## Self-Check: PASSED

- `scripts/ingest_mapillary.py` contains `def wipe_mapillary_rows`: FOUND
- `scripts/ingest_mapillary.py` contains `DELETE FROM segment_defects WHERE source = 'mapillary'`: FOUND
- `scripts/ingest_mapillary.py` contains `"--wipe-mapillary"`: FOUND
- `scripts/ingest_mapillary.py` contains `wipe_mapillary_planned`: FOUND
- `scripts/ingest_mapillary.py` contains `"wipe_mapillary_applied"`: FOUND
- Commit `054c389` exists: VERIFIED
- 4/4 target tests GREEN: VERIFIED (TestPlan04Flags::test_wipe_mapillary_rows_*)
- 45/45 non-integration tests pass: VERIFIED
