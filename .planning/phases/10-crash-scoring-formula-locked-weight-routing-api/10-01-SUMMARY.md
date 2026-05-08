---
phase: 10-crash-scoring-formula-locked-weight-routing-api
plan: 01
subsystem: scoring
tags: [pytest, tdd, scoring-constants, crash-scoring, locked-weights, python]

# Dependency graph
requires:
  - phase: 09-crash-data-schema-la-city-ingest-naive-snap-match
    provides: "segment_scores.crash_norm DEFAULT 0.0 NOT NULL column (migration 004), crash_records.severity_kabco / snapped_segment_id (Phase 9 ingest)"
provides:
  - "Module constants W_IRI=0.40, W_POT=0.35, W_CRASH=0.25 in backend/app/scoring.py (D-10-01)"
  - "Severity weights FATAL_WEIGHT=8, INJURY_WEIGHT=3, PDO_WEIGHT=1 (D-10-04, Pitfall 5: NOT 100:10:1)"
  - "Single-fatal cap FATAL_CAP_K=3, FATAL_CAP=24 (D-10-05)"
  - "New 4-arg compute_segment_cost(travel_time_s, iri_norm, pothole_total, crash_norm) (D-10-02)"
  - "Deprecated-but-importable normalize_weights() with DEPRECATED v0.4.0 marker (D-10-03)"
  - "20 new unit tests + 6 preserved v0.2.0 tests = 26 tests passing in test_scoring.py"
affects: [10-02-compute-scores-crash-correlated-subquery, 10-03-routing-locked-weights-swap]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Locked module-level scoring constants — single source of truth shared between offline compute_scores.py and online routing.py"
    - "TDD RED → GREEN gate sequence with explicit ImportError documentation in RED commit"
    - "Test-only helper assertions for SQL primitives (cap clamp, length floor, p95 clip) so Python and SQL implementations of the same numerical contract are mutually verified"
    - "Kept-but-deprecated function pattern (DEPRECATED v0.4.0 marker) — preserves legacy unit tests during one milestone of confidence rather than hard-deleting"

key-files:
  created: []
  modified:
    - "backend/app/scoring.py — locked constants + new 4-arg compute_segment_cost (35→100 LOC)"
    - "backend/tests/test_scoring.py — 20 new tests across 4 new classes; 6 preserved v0.2.0 tests; 3 v0.2.0 tests on old 5-arg signature deleted (87→332 LOC)"

key-decisions:
  - "Used inspect.signature parameter list comparison to pin the 4-arg signature against accidental drift (TestComputeSegmentCostV4::test_signature_is_four_args_no_kwargs) — guards Plans 10-02 / 10-03 from a contract mismatch"
  - "Deprecation marker placed in BOTH the docstring AND a sibling source comment — test_deprecation_marker_present accepts either, providing forward-compat for downstream patch styles"
  - "Inline static-method helpers (_capped, _floor_km, _p95_normalize, _p95_normalize_safe) on TestCrashScoringMath rather than module-level — keeps SQL-mirror primitives co-located with the tests that exercise them"
  - "Added 2 extra TestComputeSegmentCostV4 tests beyond the plan's 7 (test_pothole_only_contribution, test_crash_only_contribution) for symmetric per-weight isolation coverage; test count is well above the D-10-19 floor of ≥8 either way"

patterns-established:
  - "TDD gate per plan: test() commit (RED with documented ImportError) → feat() commit (GREEN with verification) → optional follow-up test() commit for contract-pinning helpers"
  - "Wave-1 foundation plan exposes only constants and signatures; downstream plans (10-02, 10-03) consume them — no behavioral coupling at the Wave-1 boundary"

requirements-completed:
  - REQ-crash-scoring-formula
  - REQ-route-api-locked-weights

# Metrics
duration: ~12min
completed: 2026-05-08
---

# Phase 10 Plan 01: Crash Scoring Constants + 4-arg compute_segment_cost Summary

**Locked W_IRI/W_POT/W_CRASH (40/35/25) + severity 8:3:1 + FATAL_CAP K=3 + new 4-arg compute_segment_cost in backend/app/scoring.py; normalize_weights deprecated-but-importable; 20 new unit tests pin all contracts**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-05-08
- **Completed:** 2026-05-08
- **Tasks:** 2 (TDD: Task 1 RED→GREEN, Task 2 helper tests)
- **Files modified:** 2 (backend/app/scoring.py, backend/tests/test_scoring.py)
- **Test count:** 26 passed (6 preserved v0.2.0 + 20 new)

## Accomplishments

- Replaced v0.2.0's user-tunable weight sliders with locked module constants — `W_IRI=0.40`, `W_POT=0.35`, `W_CRASH=0.25` (D-10-01).
- Introduced severity weight constants `FATAL_WEIGHT=8`, `INJURY_WEIGHT=3`, `PDO_WEIGHT=1` (D-10-04, locked at literature-converged 8:3:1 — Pitfall 5 explicitly forbids the academic 100:10:1 ratio).
- Introduced single-fatal cap `FATAL_CAP_K=3`, `FATAL_CAP=24` (D-10-05, researcher recommendation per RESEARCH.md §Alternatives Considered).
- Replaced `compute_segment_cost(travel_time_s, iri_norm, pothole_total, w_iri, w_pot)` with new 4-arg signature `compute_segment_cost(travel_time_s, iri_norm, pothole_total, crash_norm)` — no normalization step (D-10-02).
- Marked `normalize_weights()` with `DEPRECATED v0.4.0` in BOTH a sibling source comment AND its docstring; body unchanged so the existing 6 `TestNormalizeWeights` tests pass UNCHANGED (D-10-03, D-10-21 backward-compat gate).
- Added 20 new unit tests across 4 new classes pinning every constant and primitive contract that downstream plans rely on; well above the D-10-19 floor of ≥8 new tests.

## Task Commits

Each task was committed atomically per the TDD gate sequence:

1. **Task 1 RED:** `d048c96` (test) — add failing unit tests for locked weights + 4-arg compute_segment_cost + deprecated normalize_weights. RED state documented in commit body: collection ImportError because the new constants don't yet exist in `app.scoring`.

2. **Task 1 GREEN:** `6c69b21` (feat) — lock outer weights (40/35/25), severity (8:3:1) + cap K=3, deprecate normalize_weights per D-10-01..D-10-05. Makes the failing tests pass: 20 passed in 0.01s.

3. **Task 2:** `1998a71` (test) — add cap/length-floor/p95-clip helper tests pinning the SQL formula contract for plan 10-02. Test-only commit (no production code change). Final state: 26 passed in 0.01s.

**TDD gate sequence verified:** `git log --oneline` shows `test → feat → test` in chronological order — RED before GREEN gate satisfied.

## Final Test Counts (per class)

| Test class                          | Count | Source                | Status   |
| ----------------------------------- | ----- | --------------------- | -------- |
| `TestNormalizeWeights`              |     6 | preserved v0.2.0      | PASS unchanged (D-10-21) |
| `TestNormalizeWeightsDeprecated`    |     2 | new (Task 1)          | PASS     |
| `TestLockedConstants`               |     2 | new (Task 1)          | PASS     |
| `TestCrashScoringMath`              |     9 | new (3 Task 1 + 6 Task 2) | PASS |
| `TestComputeSegmentCostV4`          |     7 | new (Task 1)          | PASS     |
| **Total**                           |  **26** |                     | **PASS** |

**v0.2.0 backward-compat gate confirmed:** All 6 `TestNormalizeWeights` tests passed UNCHANGED — no edits to that class. The 3 deleted `TestComputeSegmentCost` tests (on the v0.2.0 5-arg signature) are intentionally superseded by the 7-test `TestComputeSegmentCostV4` class which provides stronger coverage of the new contract (basic arithmetic, signature inspection, zero-input pass-through, no-normalization-step pin, per-weight isolation).

## Files Created/Modified

- `backend/app/scoring.py` — 35→100 LOC. Adds module docstring referencing D-10-01 through D-10-05; defines 8 module-level constants (`W_IRI`, `W_POT`, `W_CRASH`, `FATAL_WEIGHT`, `INJURY_WEIGHT`, `PDO_WEIGHT`, `FATAL_CAP_K`, `FATAL_CAP`); defines new 4-arg `compute_segment_cost`; preserves `normalize_weights` body unchanged with `DEPRECATED v0.4.0` marker in both sibling comment AND docstring.
- `backend/tests/test_scoring.py` — 87→332 LOC. Updates import to pull all 8 constants + both functions; preserves 6 `TestNormalizeWeights` tests; deletes 3 v0.2.0 `TestComputeSegmentCost` tests (5-arg signature); adds 4 new test classes (`TestLockedConstants`, `TestCrashScoringMath`, `TestComputeSegmentCostV4`, `TestNormalizeWeightsDeprecated`) totaling 20 new tests with 4 inline SQL-mirror static-method helpers (`_capped`, `_floor_km`, `_p95_normalize`, `_p95_normalize_safe`).

## Decisions Made

- **Symmetric per-weight isolation tests in TestComputeSegmentCostV4:** Added `test_pothole_only_contribution` and `test_crash_only_contribution` alongside the planned `test_iri_only_contribution`, so each of the three locked outer weights has its own multiply-not-add proof. Plan listed 5 tests in this class; shipping 7 is purely additive coverage well within the D-10-19 ≥8 floor.
- **Deprecation marker in two places:** The plan said "docstring OR a sibling comment". Shipped both. `test_deprecation_marker_present` accepts either via `or`, so future patches that touch one without the other will not break the test.
- **Helper functions co-located on TestCrashScoringMath:** Used `@staticmethod` inside the class rather than module-level helpers. Keeps the SQL-mirror primitives next to the tests that exercise them; matches the existing test file's idiom of self-contained classes.

## Deviations from Plan

None - plan executed exactly as written. The TDD RED→GREEN gate sequence and the Task 2 test-only commit landed in three atomic commits matching the plan's success criteria.

Two minor non-deviations to note (not deviations because they stay within plan-stated minimums):
- Shipped 20 new tests vs. the plan's stated 17 (extra `test_pothole_only_contribution` + `test_crash_only_contribution` for symmetric isolation; both well within `≥8` D-10-19 floor).
- Deprecation marker present in BOTH the docstring AND a sibling comment vs. plan's "OR" phrasing — strictly more defensive, accepted by the same `or`-form test assertion.

## Issues Encountered

None. Plan-level pytest gate (`cd backend && DATABASE_URL=... AUTH_SIGNING_KEY=... PYTHONPATH=. /tmp/rq-venv/bin/python -m pytest tests/test_scoring.py -x -q`) returned `26 passed in 0.01s` on first GREEN run.

Constants spot-check verified: `W_IRI W_POT W_CRASH FATAL_WEIGHT INJURY_WEIGHT PDO_WEIGHT FATAL_CAP_K FATAL_CAP` print as `0.4 0.35 0.25 8 3 1 3 24` and `compute_segment_cost(100.0, 0.5, 2.0, 0.3)` prints as `100.97500000000001` (within `1e-9` of expected `100.975` — IEEE 754 representation is exact within tolerance; pytest assertion uses `abs(... - 100.975) < 1e-9` which passes).

Deprecation-marker spot-check: `grep -c 'DEPRECATED v0.4.0' backend/app/scoring.py` returns `2` (sibling comment line + docstring), exceeding the ≥1 floor.

## Known Broken (Wave 2 awareness)

**`backend/tests/test_route.py` will TypeError until Plan 10-03 lands.** This is INTENTIONAL and pre-documented in the plan's `<callers_who_will_break_until_their_plan_lands>` section.

- `backend/app/routes/routing.py:424` calls the OLD 5-arg `compute_segment_cost(t, iri, pot, w_iri, w_pot)` — that signature no longer exists.
- `backend/app/routes/routing.py:8, :245-248` still imports and calls `normalize_weights(...)` — this still works (deprecated import preserved per D-10-03), but the result is unused after Plan 10-03 swaps to the new locked-weight call.

**Resolution:** Plan 10-03 (Wave 3) replaces both call sites, restoring `pytest tests/test_route.py` to GREEN. The phase-level verification gate runs only after Plans 10-02 AND 10-03 both merge.

**Smoke test that proves Plan 10-01 didn't break unit-level scoping:** `pytest tests/test_scoring.py -x -q` returns 26 passed (this plan's own gate, executed above).

## Next Phase Readiness

Wave 2 plans can now consume the locked-weight foundation:

- **Plan 10-02 (`compute_scores.py --source crash`)** imports `FATAL_WEIGHT`, `INJURY_WEIGHT`, `PDO_WEIGHT`, `FATAL_CAP` from `app.scoring`. The correlated subquery's SQL primitives (cap clamp, length floor, p95 clip) are pre-pinned in pure Python by `TestCrashScoringMath::_capped` / `_floor_km` / `_p95_normalize_safe` — Plan 10-02's executor can copy the formulas directly into the SQL with confidence that any drift between the SQL and the Python contract is caught either by the Python helper tests OR by Plan 10-02's histogram smoke test.

- **Plan 10-03 (`/route` locked-weights swap)** imports `W_IRI`, `W_POT`, `W_CRASH`, `compute_segment_cost` from `app.scoring`. The 4-arg signature is contract-pinned via `inspect.signature` in `TestComputeSegmentCostV4::test_signature_is_four_args_no_kwargs` so Plan 10-03's executor will get a clear test failure rather than a silent miscall if the signature ever drifts.

- **No blockers.** All Wave 1 success criteria met; both Wave 2 plans are unblocked and may execute in parallel.

## Verification Summary

| Gate                                              | Status | Evidence                                                       |
| ------------------------------------------------- | ------ | -------------------------------------------------------------- |
| Plan-level pytest (`tests/test_scoring.py -x -q`) | PASS   | 26 passed in 0.01s                                             |
| TDD gate sequence (RED→GREEN visible in git log)  | PASS   | d048c96 (test) → 6c69b21 (feat) → 1998a71 (test)               |
| 8 module constants exported                       | PASS   | constants spot-check: `0.4 0.35 0.25 8 3 1 3 24`               |
| 4-arg compute_segment_cost                        | PASS   | inspect.signature parameter names + count test passes          |
| compute_segment_cost arithmetic                   | PASS   | `100.975 ≈ 100 + 0.40*0.5 + 0.35*2.0 + 0.25*0.3`               |
| 6 v0.2.0 TestNormalizeWeights pass UNCHANGED      | PASS   | class body untouched; 6/6 PASS                                 |
| `DEPRECATED v0.4.0` marker present                | PASS   | `grep -c` returns 2 (comment + docstring)                      |
| ≥8 new unit tests (D-10-19)                       | PASS   | 20 new tests (well above floor)                                |
| files_modified scope respected                    | PASS   | `git diff --name-only base..HEAD` returns only the 2 expected files |
| .planning/STATE.md and .planning/ROADMAP.md untouched | PASS | not in git diff (parallel-executor invariant)                |

## Self-Check: PASSED

- [x] FOUND: backend/app/scoring.py
- [x] FOUND: backend/tests/test_scoring.py
- [x] FOUND commit: d048c96 (test RED)
- [x] FOUND commit: 6c69b21 (feat GREEN)
- [x] FOUND commit: 1998a71 (test Task 2)
- [x] FOUND: .planning/phases/10-crash-scoring-formula-locked-weight-routing-api/10-01-SUMMARY.md (this file)

---

*Phase: 10-crash-scoring-formula-locked-weight-routing-api*
*Plan: 01 (Wave 1, foundation)*
*Completed: 2026-05-08*
