---
phase: 08-routing-performance
plan: 03
subsystem: api
tags: [routing, performance, pgrouting, control-flow, fallback-chain, temp-table, gist-prefilter]

# Dependency graph
requires:
  - phase: 08-routing-performance
    provides: "Plan 08-02 — module-level constants ROUTE_FILTER_BUFFER_DEG, ROUTE_FILTER_WIDEN_FACTOR, CREATE_FILTERED_EDGES_SQL, INDEX_FILTERED_EDGES_SQL, KSP_FILTERED_SQL, KSP_FULL_SQL (all imported and used here)"
  - phase: 08-routing-performance
    provides: "Plan 08-01 — RED perf regression suite (test_routing_performance.py); turns GREEN once Plan 08-04 runs against a seeded DB"
  - phase: 05-deploy
    provides: "psycopg2 ThreadedConnectionPool with 12s SET LOCAL statement_timeout (db.py:97-98) — caps each of the 3 attempts at 12s for a 36s worst case"
provides:
  - "find_route() body wired to the 3-attempt fallback chain: filter (BUFFER) -> wide-filter (BUFFER * WIDEN_FACTOR) -> full-graph (KSP_FULL_SQL)"
  - "Single-connection invariant for all 3 attempts: temp table persists across CREATE/INDEX/KSP within the same `with get_connection() as conn:` block; ON COMMIT DROP fires only at outer block exit"
  - "Inter-attempt cleanup via explicit `DROP TABLE rq_filtered_edges` (NOT `IF EXISTS`) — fail-loud per RESEARCH Assumption A7"
  - "Mock-test compatibility note in test_route.py preventing future maintainers from 'fixing' the side_effect lists that don't need fixing"
affects: [08-04, 08-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "3-attempt fallback chain with single shared connection: outer GiST bbox pre-filter -> btree-indexed temp table -> pgr_ksp on the temp table; widen on empty; full-graph fallback on still-empty"
    - "psycopg2 dict-spread for parameter overrides: `{**bbox_params, 'buf': ROUTE_FILTER_BUFFER_DEG * ROUTE_FILTER_WIDEN_FACTOR}` keeps origin/destination lon/lat parameter-bound when only the buffer changes"
    - "Inter-attempt temp-table cleanup via explicit `DROP TABLE` (not `DROP TABLE IF EXISTS`) — surfaces logic errors instead of silently masking them"
    - "Mock-test invariance under control-flow changes that add execute() calls: MagicMock.execute does not consume from fetchone/fetchall side_effect lists, so DDL execute() additions need no test adjustment"

key-files:
  created: []
  modified:
    - "backend/app/routes/routing.py — second `with get_connection()` block replaced. Added 3-attempt fallback (lines 117-167 in new file). Path-grouping/empty-route/segment-fetch logic from line 169 onward unchanged. Net diff: +43/-5 in this plan."
    - "backend/tests/test_route.py — added 10-line Phase 8 compat note above _setup_mock_conn explaining why side_effect lists don't need extending. Zero test-logic changes. Net diff: +10/-0 in this plan."

key-decisions:
  - "Took Branch A of Task 2: the RESEARCH §7 mock-compatibility prediction held. Existing fetchone/fetchall side_effect lists worked unchanged because MagicMock decouples execute() from fetchone/fetchall consumption. No test-logic edits required — only the documentary compat-note comment landed."
  - "Used `DROP TABLE rq_filtered_edges` (no IF EXISTS) per plan body and RESEARCH Assumption A7. If the table is absent for any reason during attempt 2/3, this fails loudly and surfaces as a 500 — louder than silently retrying with stale state. The 12s statement_timeout (db.py:97) bounds each attempt's wall time."
  - "Did NOT wrap the chain in try/except. Letting exceptions propagate keeps the pool's `try/finally putconn` (db.py:100-101) in charge of slot release. Adding a try/except around the chain would either swallow useful errors or bypass `ON COMMIT DROP` cleanup."
  - "Built bbox_params dict once and used dict-spread `{**bbox_params, 'buf': ...}` for the widen step. T-08-03-01 mitigation: every value flows through psycopg2 named-param binding; no risk of forgetting to re-bind origin/destination on the wide attempt."

patterns-established:
  - "Two-phase SQL refactor under TDD landed in full: Plan 08-02 shipped the SQL constants + their unit-test contract; Plan 08-03 wires them into the request handler. Each diff stays small and reviewable. The plan-level RED gate (test_routing_performance.py latency assertions) turns GREEN once Plan 08-04 exercises this against a seeded DB."
  - "Mock-test invariance verification: when a control-flow change adds N more cur.execute() calls but does NOT add fetchone()/fetchall() calls, the existing MagicMock side_effect lists work unchanged. This was predicted in RESEARCH §7 and confirmed in execution."

requirements-completed: [PERF-01, PERF-02, PERF-03]

# Metrics
duration: 2m 4s
completed: 2026-05-07
---

# Phase 8 Plan 03: Wire 3-attempt fallback chain into find_route() Summary

**`find_route()` now executes the 3-attempt fallback chain — pre-filter the OD-corridor edges via the GiST index on road_segments.geom, build a btree-indexed temp table, run pgr_ksp on it; on empty result widen the buffer by ROUTE_FILTER_WIDEN_FACTOR and retry; on still-empty result fall back to the original full-graph KSP_FULL_SQL. All 3 attempts share one pooled connection so the temp table persists across CREATE/INDEX/KSP and ON COMMIT DROP fires only at outer block exit. Inter-attempt cleanup via explicit `DROP TABLE rq_filtered_edges`. The path-grouping, empty-route handling, segment-data fetch, scoring, time-budget filter, fastest/best selection, and cache write are bit-for-bit unchanged. Mocked test suite passes UNCHANGED — RESEARCH §7 prediction confirmed.**

## Performance

- **Duration:** 2m 4s
- **Started:** 2026-05-07T22:27:49Z
- **Completed:** 2026-05-07T22:29:53Z
- **Tasks:** 2/2
- **Files modified:** 2 (routing.py: +43/-5; test_route.py: +10/-0)
- **Files created:** 0

## Accomplishments

### Diff applied to find_route() — line ranges in the new file

| Lines | Phase | One-line summary |
|-------|-------|------------------|
| 117-124 | Snap | Snap origin/destination lon-lat to nearest pgr vertex IDs (UNCHANGED from pre-08-03) |
| 126-141 | Attempt 1 (filter) | Build bbox_params dict; CREATE TEMP TABLE via GiST bbox at default buffer; CREATE INDEX on source/target; pgr_ksp reads the temp table |
| 143-158 | Attempt 2 (widen) | If `not ksp_rows`: DROP TABLE; rebuild bbox with buf = ROUTE_FILTER_BUFFER_DEG * ROUTE_FILTER_WIDEN_FACTOR; CREATE/INDEX/pgr_ksp again |
| 160-167 | Attempt 3 (full-graph) | If still `not ksp_rows`: DROP TABLE; fall back to KSP_FULL_SQL on the full road_segments table — preserves pre-Phase-8 correctness |
| 169-172 | Group | Group ksp_rows by path_id (UNCHANGED) |
| 174-189 | Empty-route | Return RouteResponse with empty geometry + warning if no path found across all 3 attempts (UNCHANGED, just relocated to after the chain) |
| 191-195 | Fetch segments | SEGMENTS_BY_IDS_SQL fetch + dict-by-id (UNCHANGED) |

Lines after 195 (path scoring, time-budget filter, fastest/best selection, to_route_info helper, response assembly, cache write) are byte-for-byte identical to before this plan.

### test_route.py defensive comment

A 10-line block above `_setup_mock_conn` documents that MagicMock.execute does NOT consume from fetchone/fetchall side_effect lists, so the existing 2-element fetchone and 2-element fetchall side_effect arrays remain correct under the new control flow. Future maintainers reading the test won't be tempted to "fix" something that isn't broken.

### Test results (no regressions)

- `pytest tests/test_route.py -x -v` — 2/2 passed (mocked tests unchanged, mocks proved sufficient — Branch A confirmed)
- `pytest tests/test_routing_filter_helpers.py -x` — 7/7 passed (Plan 08-02 contracts intact)
- `pytest tests/test_routing_pool_release.py` — 1 skipped (no-DB host, expected baseline)
- `pytest tests/test_routing_performance.py --collect-only -q` — 2 tests collected (PERF-01 + PERF-02 contract preserved; will turn GREEN in Plan 08-04 against a seeded DB)
- Combined: `9 passed, 3 skipped` for the routing-related test surface — no regressions.

### Acceptance gates (all 10 from the plan body)

- `grep -q "cur.execute(CREATE_FILTERED_EDGES_SQL, bbox_params)"` — PASS
- `grep -q "cur.execute(INDEX_FILTERED_EDGES_SQL)"` — PASS
- `grep -q "cur.execute(KSP_FILTERED_SQL, (origin_node, dest_node, K))"` — PASS
- `grep -q "ROUTE_FILTER_BUFFER_DEG \* ROUTE_FILTER_WIDEN_FACTOR"` — PASS
- `grep -q "DROP TABLE rq_filtered_edges"` — PASS
- `grep -q "cur.execute(KSP_FULL_SQL, (origin_node, dest_node, K))"` — PASS
- `grep -c "if not ksp_rows:"` — 2 (one per filtered attempt) PASS
- `grep -c "cur.execute(KSP_FILTERED_SQL"` — 2 PASS
- `grep -c "cur.execute(KSP_FULL_SQL"` — 1 PASS
- `! grep -E '\bKSP_SQL\b' backend/app/routes/routing.py` — PASS (old name retired)
- `! grep -E 'f".*ST_MakeEnvelope|\.format\(.*ST_MakeEnvelope'` — PASS (no f-string SQL)
- `python -c "import ast; ast.parse(open('backend/app/routes/routing.py').read())"` — PASS
- `grep -q "Phase 8 compat note" backend/tests/test_route.py` — PASS (Branch A document landed)

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire 3-attempt fallback chain into find_route()** — `be277bf` (feat)
2. **Task 2: Document mock compatibility — Branch A** — `783cf1e` (test)

**Plan metadata commit:** to follow this SUMMARY (final docs commit).

## Files Created/Modified

- `backend/app/routes/routing.py` — +43 lines, -5 lines. Replaced the second `with get_connection() as conn:` block body (lines 117-155 in old file) with the 3-attempt fallback chain (lines 117-167 in new file). Path-grouping, empty-route handling, segment fetch, scoring, time-budget logic, response assembly, and cache write all UNCHANGED.
- `backend/tests/test_route.py` — +10 lines, -0 lines. Added a Phase 8 compat note above `_setup_mock_conn` explaining the MagicMock side_effect invariance. No test-logic changes.

## Decisions Made

- **Took Branch A of Task 2.** Task 1's verify command (`pytest tests/test_route.py -x -v`) exited 0 on the first try — both mocked tests passed without any change to the side_effect lists. This confirmed the RESEARCH §7 prediction: MagicMock.execute does NOT consume from fetchone/fetchall side_effect lists, so the 5 extra `cur.execute()` calls per request (CREATE, INDEX, KSP_FILTERED + optional widen + optional full-graph fallback) do not perturb the mock setup. The Branch A action — landing a defensive comment block — was applied; no test-logic changes were needed.
- **Used `DROP TABLE rq_filtered_edges` (no IF EXISTS).** Per plan body and RESEARCH Assumption A7. Within the same `with get_connection()` block the temp table persists across attempts (ON COMMIT DROP only fires at transaction end, which is the outer block exit). Each subsequent attempt therefore MUST explicitly drop the table before re-creating with a new buffer. Using `IF EXISTS` would mask the bug "we got to attempt 2/3 but the temp table is gone" — fail loudly is preferable.
- **No try/except wrapping the chain.** Letting exceptions propagate keeps the pool's `try/finally putconn` (db.py:100-101) in charge of slot release. The 12s `SET LOCAL statement_timeout` (db.py:97-98) bounds each attempt; a query that exceeds 12s raises QueryCanceled, which propagates up through `find_route()` and is mapped to HTTP 500 by FastAPI's default exception handler. Wrapping in try/except here would either swallow useful errors OR bypass the cleanup.
- **Built `bbox_params` dict once; used dict-spread for the widen step.** `wide_params = {**bbox_params, "buf": ROUTE_FILTER_BUFFER_DEG * ROUTE_FILTER_WIDEN_FACTOR}` ensures origin/destination lon/lat values stay parameter-bound on attempt 2 — no risk of forgetting to re-bind. Direct application of T-08-03-01 mitigation pattern from Plan 08-02.

## Deviations from Plan

None — plan executed exactly as written. Both tasks completed atomically with the expected commit shape (`feat(08-03):` and `test(08-03):`). The acceptance criteria for both tasks all passed. Branch A of Task 2 (the expected branch per RESEARCH §7) was the actual path taken.

## Issues Encountered

- **Pre-existing test-suite issues outside this plan's scope:** Running the full backend test suite reveals collection errors in `tests/test_detector.py`, `test_detector_factory.py`, `test_eval_detector.py`, `test_ingest_mapillary.py`, `test_iri_ingestion.py`, `test_mapillary.py`, `test_yolo_detector.py` (all `ModuleNotFoundError: No module named 'data_pipeline'`) and 14 unrelated failures in `tests/test_fetch_eval_data.py`, `test_finetune_detector.py`, `test_secrets_no_defaults.py`, `test_seed_topology.py`. These are pre-existing baseline issues with the docker-image test env (`data_pipeline` is in repo root, not in the backend image; some tests reference scripts/deploy configs that don't fit a backend-only test container). NONE of these are caused by Plan 08-03's changes — verified by running `pytest tests/test_route.py tests/test_routing_filter_helpers.py tests/test_routing_pool_release.py tests/test_routing_performance.py -v` which is fully green (9 passed, 3 expected-skip). Logged for visibility; out of scope for Plan 08-03 (DEFERRED to a future cleanup plan if ever needed).

## Security Confirmation (gate from plan output spec)

No string-formatted lat/lon escaped into SQL:
- `! grep -E 'f".*ST_MakeEnvelope|\.format\(.*ST_MakeEnvelope' backend/app/routes/routing.py` — PASS (no match)
- All 5 bbox parameters (`o_lon`, `o_lat`, `d_lon`, `d_lat`, `buf`) flow through psycopg2 named-param binding via `cur.execute(CREATE_FILTERED_EDGES_SQL, bbox_params)` and `cur.execute(CREATE_FILTERED_EDGES_SQL, wide_params)`. The dict-spread `{**bbox_params, "buf": ...}` preserves binding for all 4 lon/lat values when only the buffer changes.
- T-08-03-01 mitigation in place; consistent with Plan 08-02's locked SQL string and the unit-test contract in `test_routing_filter_helpers.py::test_create_filtered_uses_named_params`.

## User Setup Required

None — plan is purely a control-flow rewiring within `find_route()`. The two env vars (`ROUTE_FILTER_BUFFER_DEG`, `ROUTE_FILTER_WIDEN_FACTOR`) introduced in Plan 08-02 now have a real effect (they're consumed by the new fallback chain). Operators using the defaults (0.03 and 2.0) get the recommended OD-corridor pre-filter behavior with no action needed. To widen on operator request, set `ROUTE_FILTER_BUFFER_DEG=0.05` (or higher) at process start.

## Next Phase Readiness

- **Plan 08-04 (Wave 4 — live perf validation):** Can begin. The wiring is in place. Plan 08-04's job is to:
  1. Run the perf suite (`tests/test_routing_performance.py`) against a fully-seeded local or staging DB
  2. Capture before/after timings (PERF-01 cross-LA target < 5s; PERF-02 DTLA target ≤ 2s)
  3. Verify the 3-attempt chain works end-to-end on real geometry — that the filter at 0.03° actually finds paths for typical LA OD pairs, that the widen-to-0.06° handles edge cases, and that the full-graph fallback only triggers on truly far-edge OD pairs
  4. **Important:** This plan only verified via mocked unit tests. The live perf-test pass is what flips the Phase 8 plan-level RED gate to GREEN. Until then PERF-01/PERF-02 stay RED at the Phase level.
- **Plan 08-05 (Wave 5 — REFACTOR):** Can begin once 08-04 lands. Will polish observability (logging which attempt won, metrics counters), comment cleanup, and any small fixes surfaced during live validation.
- **No blockers.**

## Self-Check: PASSED

Verified at SUMMARY-creation time:

- Files exist:
  - `backend/app/routes/routing.py` — FOUND, modified (+43/-5 in this plan)
  - `backend/tests/test_route.py` — FOUND, modified (+10/-0 in this plan)
- Commits exist (verified via `git log --oneline | grep <hash>`):
  - `be277bf` (feat: 3-attempt fallback chain wired) — FOUND
  - `783cf1e` (test: mock compat note) — FOUND
- All acceptance gates PASS (10 grep-based + 1 ast.parse + 1 mocked test suite + 1 helper test suite + 1 pool-release skip-aware + 1 Branch A documentation grep)
- Routing-related test suite: `9 passed, 3 skipped` (test_route.py + test_routing_filter_helpers.py + test_routing_pool_release.py + test_routing_performance.py) — no regressions
- Security gate: `! grep -E 'f".*ST_MakeEnvelope|\.format\(.*ST_MakeEnvelope'` exits 1 (no match — no f-string/.format() lat/lon interpolation)
- `git diff --diff-filter=D --name-only HEAD~2 HEAD` for these two commits: empty (no accidental file deletions)
- `git diff HEAD~2 HEAD --stat` confirms only the two intended files changed (routing.py +48/-5, test_route.py +10/-0 — diff stat counts the comment+code rewrap; raw additions sum to +53)

---
*Phase: 08-routing-performance*
*Completed: 2026-05-07*
