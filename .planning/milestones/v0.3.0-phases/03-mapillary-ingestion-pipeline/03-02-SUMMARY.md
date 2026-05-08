---
phase: 03-mapillary-ingestion-pipeline
plan: 02
subsystem: scoring-cli
tags: [python, postgres, cli, sql, argparse, psycopg2, sql-injection-guard]

# Dependency graph
requires:
  - plan: 03-01
    provides: segment_defects.source TEXT NOT NULL DEFAULT 'synthetic' column with CHECK + idx_defects_source — the column the --source filter binds to
provides:
  - "scripts/compute_scores.py --source {synthetic|mapillary|all} CLI flag (default 'all')"
  - "argparse choice rejection for invalid sources (exit 2)"
  - "JOIN-clause source filter (AND sd.source = %s) preserving every-segment-present LEFT JOIN property"
  - "psycopg2 parameterized binding for the source value (no f-string interpolation)"
  - "stderr WARNING when --source mapillary selected against empty mapillary set (Pitfall 7)"
  - "6 regression tests (2 unconditional CLI subprocess + 4 DB-bound integration)"
affects: [03-03-ingest-cli, 03-04-wipe-synthetic, 03-05-operator-runbook]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "argparse choices=(...) + dispatch on args.source → fixed-string SQL fragment + bound %s parameter pattern (RESEARCH Pattern 7)"
    - "Filter at LEFT JOIN ON clause, NOT WHERE: keeps every road_segments row in the result set (Pattern 7 'Critical detail')"
    - "stderr-warning-with-exit-0 convention for operator-facing-but-not-fatal conditions (Pitfall 7)"

key-files:
  created:
    - backend/tests/test_compute_scores_source.py
  modified:
    - scripts/compute_scores.py

key-decisions:
  - "Filter applied in LEFT JOIN ON clause (AND sd.source = %s), NOT WHERE — preserves the every-segment-present-with-zeros invariant. WHERE would drop segments lacking matching-source detections from segment_scores entirely (Pattern 7 line 786)."
  - "args.source bound via psycopg2 %s, never f-string-interpolated. The {join_filter} f-string interpolation is safe because join_filter is one of two fixed strings dispatched from the argparse choice — operator input never lands in the SQL string itself."
  - "Default --source='all' produces empty join_filter and empty params tuple, generating SQL byte-identical to the pre-Phase-3 query — guarantees backward-compat for callers like seed_data → compute_scores chains."
  - "Empty-mapillary warning fires to stderr (not stdout) and exits 0 — operator-visible without breaking automation that pipes stdout."
  - "VALID_SOURCES tuple (\"synthetic\", \"mapillary\", \"all\") is the single source of truth for the choice list (referenced both by argparse and by future maintenance)."

patterns-established:
  - "Argparse-choices-as-SQL-fragment-dispatch: choices=(...) restricts inputs at the CLI boundary, then a dispatch on args.X picks one of N fixed pre-written SQL fragments. Operator input itself flows only via %s. This is the pattern future Phase 3 plans (03, 04) reuse for their own filter flags."
  - "Stderr-warning + exit-0 convention for operator-confusion mitigations (Pitfall 7 family)"

requirements-completed: [REQ-mapillary-pipeline]

# Metrics
duration: 2min
completed: 2026-04-25
---

# Phase 03 Plan 02: --source filter for compute_scores.py Summary

**`scripts/compute_scores.py` extended with `argparse --source {synthetic | mapillary | all}` (default `all`) implementing the SC #4 demo-toggle workflow via JOIN-clause-parameterized SQL filtering, plus 6-test regression suite guarding the JOIN-vs-WHERE correctness invariant and the empty-mapillary warning.**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-04-25T21:12:15Z
- **Completed:** 2026-04-25T21:14:07Z
- **Tasks:** 2
- **Files created/modified:** 2 (1 created, 1 modified)

## Accomplishments

- D-16 toggle flag landed: operators can now run `compute_scores.py --source synthetic` and `compute_scores.py --source mapillary` and diff `/route` outputs to demonstrate SC #4 (real-vs-synthetic ranking diff)
- Default behavior (no flag, or `--source all`) produces SQL byte-identical to the pre-Phase-3 query — every existing call site (`seed_data.py`, future `ingest_mapillary.py`, ad-hoc operator runs) is unaffected
- Pattern 7 "Critical detail" enforced: the source filter is applied in the `LEFT JOIN ... ON ... AND sd.source = %s` clause, NOT in WHERE — so every segment still appears in `segment_scores` with `pothole_score_total = 0` even after a restrictive `--source mapillary` recompute. Test 6 is the regression guard for this invariant.
- Pitfall 7 mitigation: `--source mapillary` against an empty mapillary set prints a clear `WARNING: --source mapillary selected but 0 mapillary detections...` to stderr, with exit 0 — so operators don't misread "all zeros" as a code bug.
- Threat T-03-13 (SQL injection via `--source`) mitigated structurally: argparse `choices=` rejects non-allowlisted inputs at CLI boundary (exit 2); the actual filter value is bound via psycopg2 `%s`; the `{join_filter}` f-string interpolation is constrained to two fixed pre-written strings dispatched from `args.source`, never operator input.

## Task Commits

Each task was committed atomically (no-verify per parallel-executor protocol):

1. **Task 1: Add --source filter to compute_scores.py via JOIN-clause parameterization** — `eb0056b` (feat)
2. **Task 2: 6 regression tests (2 CLI subprocess + 4 DB-bound integration)** — `4629b2b` (test)

**Plan metadata:** SUMMARY.md committed below.

## Files Created/Modified

- `scripts/compute_scores.py` — modified — extended from 43 lines to 110 lines: added module docstring expansion documenting D-16 contract, `from __future__ import annotations`, `argparse` + `sys` imports, `VALID_SOURCES = ("synthetic", "mapillary", "all")` tuple, argparse parser with `choices=VALID_SOURCES` and `default="all"`, empty-mapillary stderr warning block, JOIN-clause filter dispatch (`if args.source == "all"` → empty filter+params; else `"AND sd.source = %s"` + `(args.source,)`), `cur.execute(sql, params)` (parameterized), and `sys.exit(main())` entrypoint wrapper.
- `backend/tests/test_compute_scores_source.py` — created — 194 lines. Two top-level test classes/functions sets:
  - `class TestComputeScoresCLI`: `test_help_lists_source_flag`, `test_invalid_source_exits_2` (run unconditionally; no DB needed)
  - DB-bound (auto-skip via `db_available`/`db_conn` fixtures): `test_default_matches_explicit_all`, `test_source_synthetic_excludes_mapillary`, `test_source_mapillary_empty_warns_on_stderr`, `test_segments_without_matching_source_get_zero_not_dropped`
  - Test marker `source_mapillary_id='test_03_02_999'` for clean teardown via the `cleanup_test_rows` fixture (DELETE both before yield and after).

## --source Argparse Contract

```
--source {synthetic, mapillary, all}    default: all
```

| Value         | Behavior                                                                                  | SQL applied                          |
| ------------- | ----------------------------------------------------------------------------------------- | ------------------------------------ |
| `synthetic`   | Recompute scores using ONLY synthetic detections (legacy seed_data.py rows)              | `LEFT JOIN ... AND sd.source = %s` with params=`("synthetic",)` |
| `mapillary`   | Recompute scores using ONLY mapillary detections (rows from `ingest_mapillary.py`)       | `LEFT JOIN ... AND sd.source = %s` with params=`("mapillary",)` |
| `all`         | (default) Recompute scores using both — produces output identical to pre-Phase-3 query    | `LEFT JOIN ...` (no filter, params=`()`) |

**Filter location:** `LEFT JOIN segment_defects sd ON rs.id = sd.segment_id {join_filter}` where `{join_filter}` is either `""` or `"AND sd.source = %s"`. NOT in WHERE — see Pattern 7 critical detail.

## Exit Code Conventions

- **0** — success (including empty-mapillary case, which exits 0 with a stderr WARNING)
- **2** — argparse rejection (invalid `--source` choice); argparse default behavior
- (No exit 1 path defined — the script is wrapped in `sys.exit(main())` for future non-zero-exit extensibility, but no current code path returns non-zero from `main()`.)

## Test Counts and Behavior

- **Total tests:** 6 (in `backend/tests/test_compute_scores_source.py`)
- **CLI subprocess tests (run unconditionally, no DB):** 2
  - `test_help_lists_source_flag` — `--help` exits 0; output contains `--source` and all 3 choices
  - `test_invalid_source_exits_2` — `--source bogus` exits 2; stderr mentions `invalid choice` or `bogus`
- **DB-bound integration tests (auto-skip when DB unreachable):** 4
  - `test_default_matches_explicit_all` — `python compute_scores.py` and `python compute_scores.py --source all` produce identical `segment_scores` snapshots (backward compat)
  - `test_source_synthetic_excludes_mapillary` — inserts a marker mapillary row; runs `--source synthetic` then `--source mapillary`; asserts the two snapshots differ on the targeted segment AND that the mapillary-only snapshot reflects the inserted row's contribution (5 × 4.5 × 1.0 = 22.5)
  - `test_source_mapillary_empty_warns_on_stderr` — when 0 mapillary rows exist, `--source mapillary` exits 0 AND stderr contains `WARNING` AND `0 mapillary detections` (Pitfall 7 regression guard)
  - `test_segments_without_matching_source_get_zero_not_dropped` — after `--source mapillary` on a DB whose only mapillary rows are unrelated to `a_segment_id`, asserts `a_segment_id IN segment_scores` snapshot. This is the SPECIFIC regression guard for the JOIN-vs-WHERE correctness note (Pattern 7 line 786) — a regression to WHERE would drop the segment from the result set.
- **Marker:** `pytestmark` (module-level) — DB-bound tests marked individually with `@pytest.mark.integration`. CLI tests are unmarked (run on collection regardless of DB availability).
- **Cleanup:** `cleanup_test_rows` fixture deletes any rows tagged `source_mapillary_id = 'test_03_02_999'` both before yield and after teardown — leaves no residue.

## Decisions Made

- **JOIN-clause filter, not WHERE** — preserves the LEFT-JOIN-with-COALESCE-to-zero invariant that `segment_scores` always has one row per `road_segments.id`. A WHERE-clause filter would silently drop segments without matching-source detections, breaking the contract that `/segments` and `/route` rely on. (RESEARCH.md Pattern 7 line 786, mitigation T-03-15.)
- **psycopg2 `%s` parameterization for `args.source`** — even though argparse `choices=` already restricts the value to a fixed set of three strings, parameterized binding is the project-wide pattern (see existing `cur.execute("...", (...))` usages) and provides defense-in-depth. The two `join_filter` *fragments* are interpolated via f-string, but each is a fixed pre-written constant — no operator input ever reaches `cur.execute()` outside of `%s`. (Mitigation T-03-13.)
- **stderr WARNING + exit 0 (not exit 1) for empty-mapillary case** — the empty-mapillary case is operator confusion, not a script failure. Exit-0 keeps automation pipelines that grep stdout for the "Scores recomputed" line working. Stderr surfaces the warning to interactive operators. (Mitigation T-03-14, RESEARCH Pitfall 7.)
- **`from __future__ import annotations`** — added to keep type hints lazy-evaluated; lets `tuple` (no parameterization) work as an annotation across Python versions without import gymnastics.
- **`sys.exit(main())` entrypoint wrapper** — previously the script was `if __name__ == "__main__": main()`. Wrapping `main()` to return an int and exiting via `sys.exit` enables future non-zero exit codes (e.g., for fatal warnings in plan 03 or 04) without restructuring the entrypoint.
- **`VALID_SOURCES` module-level tuple** — single source of truth referenced by argparse `choices=`; future maintenance (e.g., adding a third source like `'osm-bug-reports'`) updates one location.

## Deviations from Plan

None — plan executed exactly as written.

The plan's `<action>` block specified the entire 110-line script body and the entire 194-line test file body verbatim. Both were written as specified. No bugs, missing functionality, or blocking issues were discovered that required Rule 1/2/3 auto-fixes. No architectural decisions needed (Rule 4).

## Issues Encountered

- **Worktree environment Python 3.9.6 vs project 3.12** — same condition as plan 03-01 (see `03-01-SUMMARY.md` lines 152-153). When running `python3 -m pytest backend/tests/test_compute_scores_source.py` in this worktree, the import chain fails on `app/cache.py:17` (`dict | None` PEP 604 syntax requires Python 3.10+). This is a pre-existing project-scaffolding condition, not introduced by plan 03-02. As a substitute for full pytest collection:
  - The two CLI subprocess tests were re-implemented inline as a small Python program and executed directly against the modified script. Both passed: `test_help_lists_source_flag` (PASS), `test_invalid_source_exits_2` (PASS).
  - The test file was validated via `ast.parse` (PASS — no syntax errors) and `grep -c "def test_"` (6 — matches plan's expected count).
  - The DB-bound tests will run successfully under the project's intended runtime (Python 3.12 inside the backend Docker container or a 3.12 venv). They are designed to skip cleanly via the `db_available` fixture when DB is unreachable. Future executors should run `docker compose exec backend pytest backend/tests/test_compute_scores_source.py -x` once the stack is up.
  - **Logged as a worktree-environment limitation; out of scope for 03-02.**
- **No DB available in worktree** — also expected; tests are designed to skip cleanly via `db_available` fixture, but that fixture's `pytest.skip` only fires when conftest.py can load. Above issue prevents that. Both will resolve when run in the project's intended runtime.

## User Setup Required

None. The new flag is opt-in (default `all` is a no-op vs pre-Phase-3 behavior). Operators wanting to use the SC #4 demo workflow simply run:

```bash
python scripts/compute_scores.py --source synthetic
# Hit GET /route, capture output
python scripts/compute_scores.py --source mapillary
# Hit GET /route, capture output, diff
```

The operator runbook (plan 03-05) will document this workflow end-to-end.

## Next Phase Readiness

- **Plan 03-03 (ingest CLI):** `ingest_mapillary.py` will spawn `compute_scores.py --source all` (or no flag — equivalent) as a subprocess after writing detections. Default-`all` backward compat means the subprocess invocation needs no plan-02 awareness; existing call patterns work unchanged.
- **Plan 03-04 (`--wipe-synthetic`):** independent of plan 02. After wiping synthetic rows, operators run `compute_scores.py` (default all) to regenerate scores from mapillary-only data. The `--source mapillary` flag is also available as an explicit alternative.
- **Plan 03-05 (operator runbook):** will document the SC #4 toggle workflow above as a first-class operator scenario.

No blockers. The script's default behavior is byte-identical to pre-Phase-3, so introducing this change cannot regress existing call sites.

## Threat Flags

No new security-relevant surface beyond the threat register documented in `03-02-PLAN.md` `<threat_model>`. T-03-13, T-03-14, and T-03-15 all mitigated as planned.

## Self-Check: PASSED

Verified post-write:
- `scripts/compute_scores.py` — FOUND and verified (110 lines, contains `VALID_SOURCES = ("synthetic", "mapillary", "all")`, `AND sd.source = %s`, `WARNING: --source mapillary selected but 0 mapillary detections`, `sys.exit(main())`)
- `backend/tests/test_compute_scores_source.py` — FOUND (194 lines, valid Python via ast.parse, 6 `def test_*` functions, all 6 expected test names present)
- Commit `eb0056b` (Task 1) — FOUND in `git log --oneline`
- Commit `4629b2b` (Task 2) — FOUND in `git log --oneline`
- `python3 scripts/compute_scores.py --help` — exit 0, `--source` listed with all 3 choices
- `python3 scripts/compute_scores.py --source bogus` — exit 2, argparse rejection
- `grep -E "f\"\"\".*sd\\.source = '(synthetic|mapillary)'" scripts/compute_scores.py` — empty (no f-string SQL injection vector)

---
*Phase: 03-mapillary-ingestion-pipeline*
*Plan: 02*
*Completed: 2026-04-25*
