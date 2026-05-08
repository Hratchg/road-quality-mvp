---
phase: 10-crash-scoring-formula-locked-weight-routing-api
reviewed: 2026-05-07T00:00:00Z
depth: standard
files_reviewed: 14
files_reviewed_list:
  - backend/app/scoring.py
  - backend/app/cache.py
  - backend/app/models.py
  - backend/app/routes/routing.py
  - backend/app/routes/segments.py
  - scripts/compute_scores.py
  - backend/tests/test_scoring.py
  - backend/tests/test_compute_scores_source.py
  - backend/tests/conftest.py
  - backend/tests/test_cache.py
  - backend/tests/test_models.py
  - backend/tests/test_route.py
  - backend/tests/test_segments.py
  - docs/API.md
findings:
  critical: 0
  warning: 2
  info: 3
  total: 5
status: issues_found
---

# Phase 10: Code Review Report

**Reviewed:** 2026-05-07
**Depth:** standard
**Files Reviewed:** 14
**Status:** issues_found

## Summary

Phase 10 (Crash-Scoring Formula + Locked-Weight Routing API) implementation is correct on all the prompt's load-bearing axes:

- **SQL injection / parameter binding (compute_scores.py):** Severity weights and FATAL_CAP pass via psycopg2 `%(name)s` named placeholders; only system-controlled `args.source` is interpolated via f-string into the synthetic/mapillary INSERT, and that value is constrained by argparse `choices=VALID_SOURCES`. No user input crosses into any SQL string.
- **Length-floor + p95 cap + LEAST(1.0, ...) clip:** `rs.length_m / 1000.0` is correct (verified against `db/migrations/001_initial.sql:5` — column is `length_m DOUBLE PRECISION`). `GREATEST(length_m / 1000.0, 0.05)` floors to 50m. `PERCENTILE_CONT(0.95) WHERE raw_per_km > 0` honors Pitfall 6. `LEAST(1.0, ...)` clip + `NULLIF((SELECT p95 FROM p95v), 0)` defense both present.
- **Single-fatal cap K=3:** `FATAL_CAP_K=3` and `FATAL_CAP=24` (= 3 * `FATAL_WEIGHT`=8) in `scoring.py`; `compute_scores.py` imports `FATAL_CAP` and binds via `%(fatal_cap)s` — single source of truth, in sync.
- **Idempotency (`--source crash`):** Pure UPDATE pattern (no INSERT, no ON CONFLICT). Given identical `crash_records` + `road_segments` input, re-running produces identical row updates and identical written values (the CTE is deterministic).
- **No inline crash-aggregation SQL in routing.py:** Verified by `grep crash_records|SUM\(.*severity backend/app/routes/` — zero matches. routing.py only reads `ss.crash_norm` from the LEFT JOIN at line 82 and consumes it at line 428.
- **Deprecation header (Pitfall 4):** Set at routing.py:254 BEFORE audit-log INSERT and BEFORE cache check. Persists across all three return paths (success, cache-hit, no-route fallback). EXACT-string `weight_iri,weight_potholes ignored as of v0.4.0` matches CONTEXT D-10-15. Pinned by 3 separate tests in test_route.py.
- **Cache key (Pitfall 2):** `make_route_cache_key` signature is exactly `(origin_lat, origin_lon, dest_lat, dest_lon, max_extra_minutes)` — 5 fields, none of `weight_iri/weight_potholes/include_iri/include_potholes`. Pinned via `inspect.signature` in test_cache.py.
- **Semantic ignore (Pitfall 7):** `RouteRequest` has `ConfigDict(extra='ignore')`. `test_identical_route_with_legacy_weight_fields` pins byte-equal `geojson` and `total_cost` between requests with/without legacy fields.
- **compute_segment_cost (4-arg):** Single call site at routing.py:432 updated. Signature pinned by `test_signature_is_four_args_no_kwargs` in test_scoring.py. `normalize_weights` retained with `# DEPRECATED v0.4.0` comment at line 74 + docstring marker — pinned by `test_deprecation_marker_present`.
- **GET /segments crash_norm = 0.0 default (D-10-18):** `COALESCE(ss.crash_norm, 0)` in segments.py:33, plus migration 004 column is `NOT NULL DEFAULT 0.0`. Pinned by `test_segments_includes_crash_norm` (asserts `isinstance(crash_norm, (int, float))`, not None).
- **Test isolation:** No `DELETE FROM road_segments` in any reviewed test file. Test row cleanup in `cleanup_test_rows` (test_compute_scores_source.py) is scoped to `segment_defects` filtered by a unique marker — safe.

Five non-critical findings below. None block merge.

## Warnings

### WR-01: `response` parameter shadowed by local variable in find_route()

**File:** `backend/app/routes/routing.py:245`, `backend/app/routes/routing.py:483`

**Issue:** The FastAPI `Response` parameter is named `response` at line 245 (used at line 254 to set the Deprecation header). At line 483, the local variable `response = RouteResponse(...)` rebinds the same name to a Pydantic model, making the FastAPI `Response` object inaccessible for the remainder of the function. The current implementation works because the Deprecation header is set before the rebind and FastAPI persists the header on the actual `Response` object regardless of subsequent local-variable shadowing. However, this is a maintenance hazard: any future change that needs to set another header (e.g. `Cache-Control`, `Vary`) below the rebind point will silently fail because `response.headers["..."] = ...` would be operating on a `RouteResponse` Pydantic model, not the FastAPI Response.

**Fix:** Rename the local `RouteResponse` variable to disambiguate:
```python
# routing.py around line 483
route_resp = RouteResponse(
    fastest_route=to_route_info(fastest),
    best_route=to_route_info(best, include_details=True),
    warning=warning,
    per_segment_metrics=best["metrics"],
)
set_route_cached(cache_key, route_resp.model_dump())
return route_resp
```
This keeps the FastAPI `response: Response` parameter live for the entire handler so any future header-setting works as expected.

### WR-02: `find_route()` does not roll back the audit-log INSERT if a later step raises

**File:** `backend/app/routes/routing.py:264-271`

**Issue:** The audit-log INSERT into `route_requests` runs inside a `with get_connection() as conn:` block and is committed at line 271. If a subsequent step in the second `with get_connection()` block (lines 305+) raises an unhandled non-`QueryCanceled` exception (e.g., a programming error in `find_k_shortest_via_dijkstra` that escapes the three `try/except psycopg2.errors.QueryCanceled` guards, or any exception during segment-data fetch at line 404), the audit row will already be committed but the user receives a 500. The audit log will then claim a route was requested when no route was actually computed. This is intentional per the comment "Log request -- always, even on cache hits" but the corollary "audit reflects requests that produced HTTP 500" should be documented or the behavior should change to commit the audit log only on successful response.

**Fix (option A, document):** Add a code comment at line 266 noting the intentional commit-before-success semantics:
```python
# Audit log is committed UNCONDITIONALLY before the routing pipeline runs
# so that 500-producing requests still appear in route_requests for ops
# correlation. Operators reading route_requests should NOT assume a row
# implies a successful response was sent.
```

**Fix (option B, defer commit):** Move the INSERT into the second connection block and commit only on the success path. This is a behavior change — choose A unless the audit-log semantic shift is desired.

## Info

### IN-01: Dead constant `KSP_FULL_SQL` in routing.py

**File:** `backend/app/routes/routing.py:25-32`

**Issue:** `KSP_FULL_SQL` is defined as a module-level SQL string but is never executed anywhere in the file. The full-graph fallback (attempt 3) at line 369-379 uses `find_k_shortest_via_dijkstra(..., edges_table="road_segments", ...)` — i.e., the dijkstra-based helper, not `pgr_ksp`. This dead constant predates the Phase 8 perf overhaul that replaced `pgr_ksp` with `pgr_dijkstra` + edge-weight perturbation. Phase 10 did not introduce this — but since the file is in scope for review, flagging.

**Fix:** Delete `KSP_FULL_SQL` and its 8-line comment, or add a comment explaining it is kept for documentation/historical reference.

### IN-02: Unused `K` module constant duplicates per-call argument

**File:** `backend/app/routes/routing.py:88`

**Issue:** `K = 5` is defined at module scope and used three times below as `k=K` in the `find_k_shortest_via_dijkstra(...)` calls (lines 335, 355, 373). Phase 8 also encodes the `K=5` semantic in the docstring of `find_k_shortest_via_dijkstra` (default `k=5`) and via `early_exit_at=3` (which is the operative cap on the filtered-subgraph attempts). The constant adds an indirection layer without eliminating any magic-number duplication (the helper's signature still hardcodes `k=5` as default). Not Phase 10 specific — existing pattern.

**Fix:** Either remove `K` and rely on the helper's default, or reference `K` from the helper's `k=K` default to make it the single source of truth. Low priority.

### IN-03: Unused fixture-mock fetchone entries in `test_deprecation_header_on_cache_hit`

**File:** `backend/tests/test_route.py:280-283`

**Issue:** The test provides `fetchone.side_effect` with 4 entries (two pairs of `{"id": 100}, {"id": 200}`), but the second request hits the cache after only the audit-log INSERT and never reaches the SNAP queries. The trailing two `fetchone` entries are dead test setup. Comment at lines 277-279 acknowledges the cache-hit consumes "no fetchall" but still provides extra fetchone entries — confusing but harmless.

**Fix:** Trim `fetchone.side_effect` to two entries and add a comment:
```python
# Only the first request snaps origin/dest; second request hits the cache
# immediately after audit-log INSERT and never invokes SNAP_NODE_SQL.
mock_cursor.fetchone.side_effect = [{"id": 100}, {"id": 200}]
```

---

_Reviewed: 2026-05-07_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
