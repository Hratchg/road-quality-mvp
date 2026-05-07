# Phase 8 — Measured Performance Numbers

**Measured:** 2026-05-07
**Validator:** Claude (executor agent) — orchestrator triggered post-seed
**Hardware:** developer laptop, OS macOS Darwin 25.4 (arm64)
**Environment:** Docker Compose / `road-quality-mvp-backend:latest` (rebuilt with `pytest-timeout==2.4.0`)
**DB:** PostgreSQL 16 + PostGIS 3.4 + pgRouting (Docker container `agent-a85c90f3-db-1`, host port 5432)
**Implementation under test:** commits `be277bf` (find_route() rewire) + `783cf1e` (mock test compat) — Plan 08-03's 3-attempt fallback chain
**Buffer:** ROUTE_FILTER_BUFFER_DEG = 0.03 (default, from Plan 08-02)
**ROUTE_FILTER_WIDEN_FACTOR:** 2.0 (default — wide attempt = 0.06°)

## Status: FAILED — perf budgets not met

Both PERF-01 and PERF-02 fail by a wide margin. PERF-03 passes (no regression on existing tests). Root cause: `pgr_ksp` with K=5 on a dense urban subgraph hits the 12s `statement_timeout` even after the bbox filter trims 209k → 10k edges. The temp-table fix from Plan 08-02 is insufficient on its own; the K-shortest-paths complexity dominates on dense LA grids.

Per the plan body and the executor caveats: this surface is escalated to the operator via the Task 2 checkpoint with the `failed: K=5 ksp explosion on dense urban subgraph` recommendation. Replanning is required.

## DB seed state (verified)

| Table | Rows | RESEARCH §3 expectation | Status |
|-------|------|-------------------------|--------|
| `road_segments` | 209,856 | ~209,000 | PASS |
| `road_segments_vertices_pgr` | 74,270 | ~74,000 | PASS |
| `segment_defects` | 125,632 | ~125,000 | PASS |

## Latency Table

| Trip | Pre-fix (RESEARCH §1 baseline) | Post-fix (measured) | Budget | Status |
|------|-------------------------------|---------------------|--------|--------|
| 1 km DTLA-local cold (DTLA core → Echo Park) | 1.4 s | **17.37 s (HTTP 500 — pgr_ksp QueryCanceled)** | ≤ 2.0 s | **FAIL** |
| 5 km cross-neighborhood cold (Echo Park → Hollywood) | 1.8 s | 0.67 s (HTTP 200) | (no formal budget) | PASS — informational only |
| 20 km West LA → Pasadena cold | > 90 s (timeout) | **18.07 s (HTTP 500 — pgr_ksp QueryCanceled)** | < 5.0 s | **FAIL** |

## Test Results

### Regression gates (PERF-03 — Plan 08-03 did NOT break correctness)

| Test | Result | Notes |
|------|--------|-------|
| `tests/test_integration.py::test_route_real_points` | PASS | 200m DTLA points, K=5 ksp completes < 1s |
| `tests/test_integration.py::test_route_respects_time_budget` | PASS | Same 200m points |
| `tests/test_integration.py::test_route_with_weights` | PASS | Same 200m points |
| `tests/test_integration.py::test_route_distant_points` | PASS | 500m DTLA points |
| `tests/test_route.py` (mocked) | PASS (2/2) | Plan 08-03 mock-test compat fix verified |
| `tests/test_routing_filter_helpers.py` (mocked) | PASS (7/7) | Buffer/widen-factor and SQL shape unchanged |
| `tests/test_routing_pool_release.py` | PASS (1/1) | No new pool-leak path from Plan 08-03 |

**Aggregate:** 4 + 2 + 7 + 1 = 14/14 regression tests PASS. PERF-03 met.

### Perf gates (PERF-01 and PERF-02 — the new contract)

| Test | Budget | Measured wall-clock | Internal SQL behavior | Status |
|------|--------|---------------------|-----------------------|--------|
| `test_dtla_under_2s` | < 2.0 s | 17.34 s (pytest-timeout fired at 15s; underlying request 17.37s via curl) | First filtered ksp at line 138 raises `psycopg2.errors.QueryCanceled: canceling statement due to statement timeout` after 12s | **FAIL** |
| `test_cross_la_under_5s` | < 5.0 s | 18.15 s (pytest-timeout fired at 15s; underlying request 18.07s via curl) | Same — first filtered ksp at line 138 raises QueryCanceled after 12s | **FAIL** |

Pytest output:
```
FAILED tests/test_routing_performance.py::test_dtla_under_2s - Failed: Timeout (>15.0s) from pytest-timeout
FAILED tests/test_routing_performance.py::test_cross_la_under_5s - Failed: Timeout (>15.0s) from pytest-timeout
============================== 2 failed in 35.60s ==============================
slowest 10 durations:
18.15s call     tests/test_routing_performance.py::test_cross_la_under_5s
17.44s call     tests/test_routing_performance.py::test_dtla_under_2s
```

## Subgraph Size Observation

Bbox-filtered edge counts at default buffer 0.03° (ROUTE_FILTER_BUFFER_DEG):

| OD pair | bbox-filtered edges | Pre-fix scan | Reduction | pgr_ksp K=5 outcome |
|---------|---------------------|--------------|-----------|---------------------|
| 1 km DTLA-local (DTLA → Echo Park) | 10,006 | 209,856 | 21.0× reduction (10006/209856) | TIMEOUT at 12s — K=5 explodes |
| 5 km cross-neighborhood (Echo Park → Hollywood) | 21,650 | 209,856 | 9.7× reduction (21650/209856) | 0.67s — succeeds |
| 20 km cross-LA (West LA → Pasadena) | 83,493 | 209,856 | 2.5× reduction (83493/209856) | TIMEOUT at 12s — K=5 explodes |

**Observation:** Filter reduction is meaningful but NOT sufficient. The 5km Echo Park → Hollywood case (21,650 edges, more than DTLA's 10,006!) succeeds in 0.67s while the DTLA case (10,006 edges, fewer) times out. **Edge count alone does not predict pgr_ksp K=5 cost — graph topology / OD-pair characteristics dominate.**

Direct SQL probe confirming the K-explosion (psql against `agent-a85c90f3-db-1`, statement_timeout=20s):

| OD pair | K | Filtered edges | Wall clock | Outcome |
|---------|---|----------------|------------|---------|
| DTLA core → Echo Park | 1 | 10,006 | 0.40 s | OK (24 ksp rows) |
| DTLA core → Echo Park | 3 | 10,006 | 20.00+ s | TIMEOUT (statement_timeout=20s ceiling hit; no result) |
| DTLA core → Echo Park | 5 (production) | 10,006 | 12.00 s | TIMEOUT (statement_timeout=12s) |

**Conclusion:** K is the dominant cost variable on dense urban grids. K=1 finishes in 0.4s on the same 10k-edge subgraph that K=3 cannot complete in 20s. The pre-Phase-8 root cause was `pgr_ksp` over the full 209k graph; the Plan 08-02 + 08-03 fix addresses the *graph size* dimension but the K=5 *path-enumeration* dimension on dense grids remains unaddressed.

## Fallback Chain Observation

**Did the wide-filter or full-graph fallback fire? NO.**

The 3-attempt chain in `routing.py` lines 138–166 only triggers attempt 2 / attempt 3 on `if not ksp_rows:` (empty result set). When the FIRST attempt at line 138 raises `psycopg2.errors.QueryCanceled` (statement_timeout), the exception propagates out of the `with conn.cursor()` block, past the fallback `if` checks, and bubbles up to FastAPI as HTTP 500. Neither attempt 2 (wide filter) nor attempt 3 (full graph) ever runs.

Backend traceback captured during direct curl probe to `localhost:8001`:
```
File "/app/app/routes/routing.py", line 138, in find_route
    cur.execute(KSP_FILTERED_SQL, (origin_node, dest_node, K))
psycopg2.errors.QueryCanceled: canceling statement due to statement timeout
CONTEXT:  SQL function "pgr_ksp" statement 1
```

This means the operative implementation surface is **a single-attempt code path in practice** for any OD pair where K=5 ksp blows past 12s. The fallback chain is reachable only on the much narrower "no path within bbox" case (e.g., a graph-island OD), not on the "ksp too slow" case which is what's failing the perf budgets.

This is a candidate **deviation Rule 1 bug** in Plan 08-03's implementation contract — the fallback chain was specified as a 3-attempt graceful-degradation chain, but it only degrades on no-result, not on timeout. However, fixing the fallback wouldn't help meet the perf budgets either: attempt 2 widens the buffer (more edges), making K=5 *worse*, not better; attempt 3 is the full graph, which is the original 90s+ pre-fix behavior.

The honest read: **changing the fallback semantics is out of scope for Plan 08-04**. The numbers above are what the operator must see and decide on.

## Recommendation to operator

**FAILED.** Plan 08-04 cannot approve PERF-01 or PERF-02 on the current Plan 08-02 + 08-03 implementation. Recommend `failed: K=5 ksp explosion on dense urban subgraph; bbox filter is necessary but insufficient`.

Possible directions for re-planning (NOT executed here — operator decides):

1. **Reduce K** — the locked decision is K=5 (PROJECT.md `CON-route-selection-algorithm`). If revisited and K is dropped to 1 or 2 for the corridor-filtered case, perf likely meets budgets. Trade-off: fewer alternative routes for the time-budget filter to choose from. (RESEARCH Assumption A1.)

2. **Switch ksp variant** — `pgr_ksp` enumerates K paths via Yen's algorithm; on dense grids many paths are within tiny cost differences and Yen rebuilds the graph each iteration. Alternatives: `pgr_dijkstra` (single shortest path) called K times with edge-removal between calls, or `pgr_withPointsKSP`, or a manual two-call scheme (fastest + alt-with-quality). (RESEARCH §6.)

3. **Tighten the buffer for short trips** — DTLA's 0.03° bbox catches ~10k edges including the entire downtown grid. A smaller adaptive buffer (e.g., 0.5–1× OD-distance) would yield fewer edges for short trips. Trade-off: more attempt-2/attempt-3 fallbacks; the wide-attempt path also needs work. (RESEARCH Assumption A2, A5.)

4. **Different graph representation** — pre-contract the road network into super-nodes per intersection, dropping interior edges from ksp consideration. Significant scope; out-of-scope per Phase 8 boundary.

5. **Catch QueryCanceled and try fallbacks** — at minimum, the fallback chain should kick in on timeout, not just on empty result. This would not fix perf but would surface clearer error semantics. Could be a small scope-add to Plan 08-03 (deviation Rule 2: missing critical functionality — graceful degradation on timeout).

## Sign-off

- [ ] PERF-01 cross-LA test passes with elapsed < 5.0s on a fully-seeded local DB — **FAILED (18.07s)**
- [ ] PERF-02 DTLA test passes with elapsed ≤ 2.0s — **FAILED (17.37s)**
- [x] All 4 existing live-DB route integration tests still pass — **PASS**
- [x] `test_routing_pool_release.py` still passes — no new leak path — **PASS**
- [x] Numbers entered above are measured, not projected — **MEASURED**

**Operator:** PENDING — perf gates failed; operator decides whether to revise Plan 08-03 or open a 08-x replan
**Date:** PENDING

## Verdict

- **PERF-01 (cross-LA < 5s uncached):** **FAIL** — 18.07 s, pgr_ksp K=5 timeout
- **PERF-02 (DTLA ≤ 2s uncached):** **FAIL** — 17.37 s, pgr_ksp K=5 timeout
- **PERF-03 (no regression on existing tests):** **PASS** — 14/14 regression tests green

This file is the measured-data hand-off to the operator. The next action is the Task 2 checkpoint sign-off, with recommended response `failed: K=5 ksp explosion on dense urban subgraph; bbox filter necessary but insufficient — bring back to planner for K-reduction or ksp-variant decision per RESEARCH §6`.
