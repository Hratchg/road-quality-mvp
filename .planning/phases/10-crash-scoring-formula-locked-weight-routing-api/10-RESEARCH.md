# Phase 10: Crash Scoring Formula + Locked-Weight Routing API — Research

**Researched:** 2026-05-08
**Domain:** Backend scoring math + FastAPI request/response contract evolution + PostgreSQL UPDATE-from-aggregate patterns
**Confidence:** HIGH on stack and patterns (verified against live DB + existing code); MEDIUM on the single-fatal cap value (no empirical LA data yet — researcher recommends, planner pins)

## Summary

Phase 10 is a focused **scoring + API-contract** phase. There are no new tables, no new dependencies, no new processes. Every change lands inside three files (`backend/app/scoring.py`, `backend/app/models.py`, `backend/app/routes/routing.py`), one script (`scripts/compute_scores.py`), and one read-side handler (`backend/app/routes/segments.py`). All extension points are already wired: Phase 9 left `segment_scores.crash_norm DOUBLE PRECISION NOT NULL DEFAULT 0.0` populated and a `crash_records` table indexed on `snapped_segment_id` and `geom`. The only "new" infrastructure is a correlated-subquery UPDATE inside `compute_scores.py` and a `Response.headers["Deprecation"] = ...` line inside `routing.py`.

The intellectual surface area is small but every decision is load-bearing: get severity weights wrong → `crash_norm` saturates bimodal at 0/1 (Pitfall 5) and routing degenerates to "avoid every street with any crash"; get the cache key wrong → the identical-route guarantee in D-10-16 silently fails on cache hits; forget that `road_segments.length_km` does not exist (the column is `length_m`) → migration-style runtime errors at first invocation.

**Primary recommendation:** Plan as **3 plans in 3 waves** (10-01 foundation → 10-02 + 10-03 parallel → 10-04 thin polish), with the single-fatal cap pinned at `min(per_segment_raw_sum, 3 * FATAL_WEIGHT) = min(raw, 24)` (justified below) and the correlated subquery written as a single `UPDATE ... FROM (subquery)` with the p95 computed in a sibling subquery rather than a CTE (PostgreSQL 16 has no syntactic advantage to CTE here and avoids one extra plan node).

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Locked Weight Constants (REQ-route-api-locked-weights)**
- **D-10-01:** Module constants live in `backend/app/scoring.py`: `W_IRI = 0.40`, `W_POT = 0.35`, `W_CRASH = 0.25`. Exact float literals; no env var overrides.
- **D-10-02:** `compute_segment_cost(travel_time_s, iri_norm, pothole_total, crash_norm)` signature drops the `w_iri` / `w_pot` parameters. Returns `travel_time_s + W_IRI*iri_norm + W_POT*pothole_total + W_CRASH*crash_norm`. No normalization step (the constants already sum to 1.0).
- **D-10-03:** `normalize_weights()` is kept-but-unused with `# DEPRECATED v0.4.0 — remove after one milestone of confidence` comment. Existing v0.2.0 unit tests for `normalize_weights` continue to pass unchanged. Removal is deferred.

**Severity Weighting (REQ-crash-scoring-formula)**
- **D-10-04:** Severity weights `FATAL_WEIGHT = 8`, `INJURY_WEIGHT = 3`, `PDO_WEIGHT = 1` as named constants in `backend/app/scoring.py`. NOT the academic 100:10:1.
- **D-10-05:** Single-fatal cap: cap the per-segment **raw** severity sum so one freak crash cannot dominate a long arterial. Exact cap mechanism is Claude's discretion — researcher recommends a value. Pin in unit tests once chosen.
- **D-10-06:** PDO support: schema accepts the `pdo` tier. LA City `mocodes` → PDO mapping is lossy by design; documented in Phase 12 runbook, not blocking for Phase 10.

**Per-Segment crash_norm Formula (REQ-crash-scoring-formula)**
- **D-10-07:** Per-segment formula: `raw_sum / GREATEST(length_km, 0.05)`, where `raw_sum = SUM(severity_weight)` over crashes snapped to that segment within the 5-year window. The `0.05` km floor (50m minimum). Length is read from `road_segments.length_km` (already populated by Phase 8 baseline).
- **D-10-08:** Normalize against the **95th percentile** of all per-segment per-km severity sums across the whole dataset (`PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY raw_per_km)`). Clip the result to `[0, 1]`.
- **D-10-09:** Segments with zero crashes get `crash_norm = 0` (already guaranteed by the migration 004 `DEFAULT 0.0 NOT NULL` column).

**`compute_scores.py` Extension (REQ-crash-scoring-formula)**
- **D-10-10:** Extend `VALID_SOURCES = ("synthetic", "mapillary", "all")` to `("synthetic", "mapillary", "crash", "all")`. New `--source crash` path runs the crash correlated subquery only. `--source all` runs every source's UPDATE in sequence.
- **D-10-11:** Crash UPDATE is a **correlated subquery** against `crash_records`, NOT a JOIN-then-aggregate cross-product with `segment_defects`. The constraint is no cross-product blowup with `segment_defects`.
- **D-10-12:** Existing `--source mapillary` and `--source synthetic` paths are unchanged.

**`/route` Backwards-Compat (REQ-route-api-locked-weights)**
- **D-10-13:** `RouteRequest` Pydantic model gains `model_config = ConfigDict(extra='ignore')`. `weight_iri` / `weight_potholes` Field defaults are preserved.
- **D-10-14:** `routing.py` no longer calls `normalize_weights(...)`. Uses `compute_segment_cost(travel_time_s, iri_norm, pothole_total, crash_norm)` directly.
- **D-10-15:** `Deprecation` response header on every `/route` response: literal value `weight_iri,weight_potholes ignored as of v0.4.0`. Set via `response.headers["Deprecation"] = ...`.
- **D-10-16:** Identical-route guarantee: `POST /route {... "weight_iri": 0.99, "weight_potholes": 0.01}` returns the SAME `geojson` and `total_cost` as `POST /route` without those fields. Pinned by integration test.

**`GET /segments` crash_norm Exposure (cross-cutting for Phase 11)**
- **D-10-17:** `GET /segments?bbox=...` returns `crash_norm` (numeric, 0.0 default) on every feature's `properties` dict. Additive change — non-breaking.
- **D-10-18:** Default to `0.0` (not `null`) for segments with no crashes.

**Validation**
- **D-10-19:** ≥8 unit tests in `backend/tests/test_scoring.py` (or new `test_crash_scoring.py`) pin: severity-weight ratio, length-floor math, p95 cap, single-fatal cap, no-crash-segments default to 0, locked outer constants, `compute_segment_cost` signature, deprecated-but-importable `normalize_weights`.
- **D-10-20:** Histogram smoke test (manual via runbook or pytest mark): `python scripts/compute_scores.py --source crash` after Phase 9 ingest + assert ≥50% of crash-bearing segments land in `crash_norm ∈ [0.05, 0.5]` (Pitfall 5 verification).
- **D-10-21:** Existing 6 v0.2.0 integration tests + Phase 8 routing integration tests pass unchanged. The fatal-overweighting smoke test lives in the runbook for Phase 12.
- **D-10-22:** Test command remains `cd backend && DATABASE_URL=... PYTHONPATH=. /tmp/rq-venv/bin/python -m pytest tests/...` (host venv per project runtime memory).

**Documentation**
- **D-10-23:** Update `README.md` (or new `docs/API.md`) section documenting silent-ignore behavior, locked weights, the `Deprecation` header, REQ-ID hygiene cite to commit `d0ef452`.

### Claude's Discretion
- Exact mechanism for the single-fatal cap (researcher recommends; pin in unit test).
- Whether to introduce a new `test_crash_scoring.py` file or extend `test_scoring.py` (default: extend existing for cohesion).
- Exact SQL of the correlated subquery (researcher refines; the constraint is no `segment_defects` cross-product).
- File location of the API documentation update (README section vs new `docs/API.md`).
- Whether `compute_scores.py --source all` runs sources sequentially or in a single multi-CTE UPDATE (default: sequential — easier to debug).

### Deferred Ideas (OUT OF SCOPE)
- **Fatal-overweighting smoke test against 5 known-safe arterials** — deferred to Phase 12 runbook.
- **Removing `normalize_weights()` outright** — kept-but-deprecated. Remove "after one milestone of confidence" (post-v0.4.0).
- **Single-fatal cap calibration** — exact K constant is researcher-recommended; recalibration post-deploy is a one-line constant change.
- **GET /segments pagination** — already deferred to post-v0.4.0.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REQ-crash-scoring-formula | Per-segment `crash_norm` pre-baked into `segment_scores` from a severity-weighted sum normalized to `[0, 1]`; `cost_segment` formula extends to include the third term using locked weight constants; replaces v0.3.0's user-tunable weight normalization with module constants | §Standard Stack (no new deps), §Architecture Patterns Pattern 1 (correlated-subquery UPDATE), §Code Examples (the canonical `compute_scores.py --source crash` UPDATE), §Common Pitfalls 1 (bimodal saturation), 5 (length-unit mismatch in CONTEXT) |
| REQ-route-api-locked-weights | `POST /route` continues to accept `weight_iri` / `weight_potholes` per CON-route-api but silently ignores them; server uses 40/35/25 regardless; `Deprecation` response header signals the change | §Architecture Patterns Pattern 2 (Pydantic v2 `extra='ignore'`), Pattern 3 (FastAPI Response param + response_model preserved), §Code Examples (the canonical `find_route(req: RouteRequest, response: Response)` shape), §Common Pitfalls 2 (cache-key contamination), 3 (semantic ignore vs accepted) |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Severity weight constants + module-level locked outer weights | API/Backend (`backend/app/scoring.py`) | — | Pure-Python scoring math; imported by both routing.py (online) and compute_scores.py (offline); single source of truth. |
| Per-segment `crash_norm` aggregation (correlated subquery) | Database/Storage (PostgreSQL UPDATE) | API/Backend driver (`scripts/compute_scores.py`) | Pre-baked once at ingest time per PROJECT.md anti-pattern lock; routing.py reads the materialized column at query time. |
| `/route` cost computation (read crash_norm, apply W_CRASH) | API/Backend (`routing.py`) | — | Per-request, hot path; reads pre-baked `segment_scores.crash_norm` via the existing temp-table pattern. NEVER inline crash-aggregation SQL here. |
| `RouteRequest` validation + silent-ignore of legacy fields | API/Backend (`backend/app/models.py` Pydantic v2) | — | Contract surface; `extra='ignore'` is a model-level config, not a per-route concern. |
| `Deprecation` header injection | API/Backend (`routing.py` route handler) | — | Per-response side effect; FastAPI `Response` parameter is the idiomatic seam. |
| `GET /segments` `crash_norm` exposure | API/Backend (`backend/app/routes/segments.py`) | — | Read-only projection; one extra column in SELECT, one extra key in the feature `properties` dict. |
| Histogram + identical-route smoke validation | API/Backend (pytest fixtures + integration tests) | — | Lives next to the code it pins, not in a separate runbook (D-10-19 / D-10-21). |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Pydantic v2 | (already pinned by FastAPI 0.115.6) | `model_config = ConfigDict(extra='ignore')` for backwards-compatible request schema | Locked stack constraint per PROJECT.md "Stack (backend)"; the `model_config` + `ConfigDict` pattern is the v2-canonical replacement for v1's nested `class Config` [VERIFIED: docs.pydantic.dev/latest/api/config/] |
| FastAPI | 0.115.6 (pinned) | `response: Response` parameter pattern for setting headers without disrupting `response_model` | Locked stack constraint; this is the documented pattern in fastapi.tiangolo.com/advanced/response-headers/ — the `response_model` filter still runs on the returned object [VERIFIED: fastapi.tiangolo.com docs] |
| psycopg2-binary | 2.9.11 (pinned) | `cur.execute(sql, params)` correlated-subquery UPDATE; `%s` parameterization | Locked stack; existing pattern throughout `scripts/compute_scores.py` and `scripts/ingest_*.py` |
| PostgreSQL | 16 + PostGIS 3.4 | `PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY ...)` aggregate; `UPDATE ... FROM (subquery) WHERE ...` syntax | Locked stack constraint; PERCENTILE_CONT is built-in SQL standard ordered-set aggregate [VERIFIED: postgresql.org docs] |
| pytest | (existing test suite) | unit tests + `pytestmark = pytest.mark.integration` for live-DB tests | Codified in Phase 9 09-04-SUMMARY; conftest.py registers the `integration` marker |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `cachetools.TTLCache` | (already pinned via `app/cache.py`) | TTL-bounded route cache — **must be re-keyed** in Phase 10 (see Pitfall 2) | Existing infra; Phase 10 changes the cache-key signature |
| `psycopg2.extras.RealDictCursor` | psycopg2 2.9.11 | Already used by `db.get_connection()`; row-as-dict access for crash UPDATE | No change |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Correlated subquery `UPDATE ... FROM (SELECT ... GROUP BY) sub WHERE ss.segment_id = sub.id` | Multi-CTE: `WITH per_seg AS (...), p95 AS (...) UPDATE ss SET crash_norm = ... FROM per_seg, p95 WHERE ...` | CTE form is more readable but PostgreSQL 16 inlines single-reference CTEs anyway — no perf win. Pick CTE only if the planner finds 3+ subqueries are needed; otherwise stay with the flat form. [CITED: postgresql.org/docs/current/queries-with.html — single-reference non-modifying CTEs are inlined since PG12] |
| Single multi-source UPDATE for `--source all` | Sequential per-source UPDATEs in a loop | Sequential is easier to debug, easier to log per-source counts, and matches the existing `--source synthetic\|mapillary` precedent in compute_scores.py:78-103. The CONTEXT explicitly defaults to sequential. |
| `ConfigDict(extra='ignore')` | Drop `weight_iri`/`weight_potholes` from `RouteRequest` entirely | Dropping the fields would 422-reject any client still sending them — Phase 11 hasn't shipped yet, and any 3rd-party caller still uses the old fields. `extra='ignore'` is the additive non-breaking choice locked in D-10-13. |
| FastAPI `Response` parameter for header | `JSONResponse(content=..., headers=...)` direct return | Direct `JSONResponse` bypasses the `response_model=RouteResponse` filter (verified at [fastapi.tiangolo.com/advanced/response-headers/](https://fastapi.tiangolo.com/advanced/response-headers/)) — would silently break the typed contract. **Use the Response-parameter pattern.** |
| Per-segment cap (each crash contributes ≤ FATAL_WEIGHT regardless of multi-victim) | Whole-sum cap: `min(raw_sum, K * FATAL_WEIGHT)` | The whole-sum cap is simpler (one constant K, one MIN call in SQL) and more directly addresses the "freak fatal dominates a long arterial" failure mode. Per-victim cap requires per-row severity decomposition. **Recommend whole-sum cap with K=3.** |

**Installation:** No new dependencies. Phase 10 reuses the existing pinned stack. Verify versions with:
```bash
/tmp/rq-venv/bin/pip show pydantic fastapi psycopg2-binary
```

## Architecture Patterns

### System Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│  OFFLINE PATH (operator runs once per quarter, also Phase 12 deploy)     │
│                                                                           │
│  scripts/compute_scores.py --source crash                                 │
│    ↓                                                                      │
│    [1] SELECT PERCENTILE_CONT(0.95) ... FROM (per-segment raw_per_km)    │
│        → p95_value (single scalar)                                       │
│    ↓                                                                      │
│    [2] UPDATE segment_scores SET crash_norm = LEAST(1.0, raw_per_km/p95) │
│        FROM (per-segment aggregation correlated subquery)                │
│        WHERE segment_scores.segment_id = sub.id                          │
│    ↓                                                                      │
│    segment_scores.crash_norm now non-zero on crash-bearing segments      │
└──────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼  (read-only at query time)
┌──────────────────────────────────────────────────────────────────────────┐
│  ONLINE PATH (per request, hot path; Phase 8 perf budget intact)         │
│                                                                           │
│  POST /route { origin, dest, weight_iri?, weight_potholes? }              │
│    ↓                                                                      │
│  RouteRequest (Pydantic v2, model_config=ConfigDict(extra='ignore'))     │
│    ↓ extra fields silently dropped                                       │
│  routing.find_route(req, response: Response)                              │
│    ↓                                                                      │
│    [1] response.headers["Deprecation"] = "weight_iri,weight_potholes ..."│
│    [2] cache_key = make_route_cache_key(origin, dest, max_extra_min)     │
│        ← REKEYED (no longer includes weight_iri/weight_potholes)         │
│    [3] hit cache? → return RouteResponse                                 │
│    [4] pgr_dijkstra K=5 (Phase 8 unchanged)                              │
│    [5] SELECT … crash_norm … FROM segment_scores (existing temp-table)   │
│    [6] cost = compute_segment_cost(t, iri, pot, crash_norm)              │
│        = t + 0.40*iri + 0.35*pot + 0.25*crash_norm                       │
│    [7] response_model=RouteResponse filter applied; headers preserved    │
│    ↓                                                                      │
│  Response: { fastest_route, best_route, ... } + Deprecation header       │
└──────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  CROSS-CUTTING (Phase 11 readiness)                                      │
│                                                                           │
│  GET /segments?bbox=...                                                   │
│    ↓ adds COALESCE(ss.crash_norm, 0) to existing SELECT                  │
│    ↓ adds "crash_norm": row["crash_norm"] to feature properties dict     │
│  → Phase 11 frontend can render data-vintage caption without redeploy    │
└──────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities
| Component | File | Responsibility |
|-----------|------|---------------|
| Weight constants module | `backend/app/scoring.py` | Holds `W_IRI`, `W_POT`, `W_CRASH`, `FATAL_WEIGHT`, `INJURY_WEIGHT`, `PDO_WEIGHT`, `FATAL_CAP_K`; new `compute_segment_cost(t, iri, pot, crash)`; deprecated-but-kept `normalize_weights` |
| RouteRequest contract | `backend/app/models.py` | Pydantic v2 `model_config = ConfigDict(extra='ignore')`; preserves `weight_iri` / `weight_potholes` Field defaults for v0.2.0 test compat |
| Route handler | `backend/app/routes/routing.py` | Drops `normalize_weights()` call; calls new `compute_segment_cost`; injects `Deprecation` header via `response: Response` parameter; reads `crash_norm` via existing temp-table pattern |
| Segments handler | `backend/app/routes/segments.py` | Adds `COALESCE(ss.crash_norm, 0) AS crash_norm` to SQL; adds `crash_norm` to feature properties dict |
| Score recomputer (extension) | `scripts/compute_scores.py` | New `--source crash` branch: single correlated-subquery UPDATE writing `segment_scores.crash_norm` from `crash_records`; `--source all` runs each branch sequentially |
| Cache keying | `backend/app/cache.py` | `make_route_cache_key` signature **must drop `weight_iri` / `weight_potholes`** to honor identical-route guarantee on cache hits |

### Recommended Project Structure (additive only — nothing moves)
```
backend/app/
├── scoring.py                  # +constants, +new compute_segment_cost, deprecated normalize_weights
├── models.py                   # +model_config = ConfigDict(extra='ignore')
├── cache.py                    # signature change to make_route_cache_key
└── routes/
    ├── routing.py              # drop normalize_weights call, add response: Response, set Deprecation
    └── segments.py             # add crash_norm column to SELECT + feature properties

scripts/
└── compute_scores.py           # +VALID_SOURCES "crash"; +crash UPDATE branch; +"--source all" loop

backend/tests/
├── test_scoring.py             # extended with TestCrashScoringMath class (or new test_crash_scoring.py)
├── test_route.py               # extended with test_identical_route_with_legacy_fields
├── test_segments.py            # extended with test_segments_includes_crash_norm
└── test_compute_scores_source.py  # extended with --source crash branch tests

docs/                            # new (or README section)
└── API.md                      # silent-ignore + Deprecation header + REQ-ID hygiene cite
```

### Pattern 1: Correlated-Subquery UPDATE for Pre-Baked Aggregations

**What:** Use a flat `UPDATE ... FROM (SELECT ... GROUP BY) sub WHERE ss.segment_id = sub.id` rather than a CTE chain or a JOIN-then-aggregate over multiple source tables. The aggregation runs once over `crash_records` only; the result joins back to `segment_scores` by segment_id.

**When to use:** Pre-baking per-row aggregates from a single-source detail table (here: `crash_records`). The anti-pattern this avoids is joining `crash_records` *and* `segment_defects` in the same query — that's a M×N row blowup that PROJECT.md explicitly forbids ("Phase 10 must NOT inline crash-aggregation SQL into routing.py").

**Example (the canonical Phase 10 SQL):**
```sql
-- Source: refined from CONTEXT D-10-11 + PostgreSQL 16 docs (postgresql.org/docs/16/sql-update.html)
-- Two-step approach: compute p95 first as a scalar, then UPDATE.
-- Avoids re-evaluating the percentile aggregate per row.

-- Step 1: compute p95 of per-segment per-km severity sums.
WITH per_seg AS (
    SELECT
        rs.id AS segment_id,
        SUM(
            CASE c.severity
                WHEN 'fatal' THEN %(fatal_w)s
                WHEN 'injury' THEN %(injury_w)s
                WHEN 'pdo' THEN %(pdo_w)s
                ELSE 0
            END
        ) AS raw_sum,
        rs.length_m
    FROM road_segments rs
    LEFT JOIN crash_records c ON c.snapped_segment_id = rs.id
    GROUP BY rs.id, rs.length_m
),
per_seg_capped AS (
    SELECT
        segment_id,
        length_m,
        LEAST(raw_sum, %(fatal_cap)s) AS capped_sum,
        LEAST(raw_sum, %(fatal_cap)s) / GREATEST(length_m / 1000.0, 0.05) AS raw_per_km
    FROM per_seg
),
p95v AS (
    SELECT PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY raw_per_km) AS p95
    FROM per_seg_capped
    WHERE raw_per_km > 0  -- p95 over crash-bearing segments only; zero-segments dominate
)
UPDATE segment_scores ss
SET crash_norm = LEAST(
    1.0,
    psc.raw_per_km / NULLIF((SELECT p95 FROM p95v), 0)
),
    updated_at = NOW()
FROM per_seg_capped psc
WHERE ss.segment_id = psc.segment_id
  AND psc.raw_per_km > 0;  -- Leave zero-crash segments at DEFAULT 0.0 (D-10-09 safety net)
```

**Critical detail (units):**
- Column is `road_segments.length_m` in METERS (not `length_km` as CONTEXT D-10-07 says — see Pitfall 5 below).
- `length_m / 1000.0` converts to km; `GREATEST(..., 0.05)` then enforces the 50m floor in km units (0.05 km = 50 m).
- This matches the literature convention of "crashes per km".

**Critical detail (p95 over non-zero only):**
- If we compute p95 over ALL segments (including ~99% with zero crashes), the p95 is dominated by zeros → degenerate normalization.
- Filter `WHERE raw_per_km > 0` in the p95 aggregation only. The UPDATE itself also filters > 0 so zero-crash segments stay at the migration-default 0.0.

**Critical detail (no segment_defects join):**
- The query joins `road_segments` ↔ `crash_records` ONLY. `segment_defects` is not referenced. PROJECT.md anti-pattern lock: "no cross-product blowup with segment_defects."

### Pattern 2: Pydantic v2 `extra='ignore'` for Backwards-Compatible Schema Evolution

**What:** Add `model_config = ConfigDict(extra='ignore')` to a request model. Unknown extra fields are silently dropped before the model instance is constructed, so callers that send legacy fields (or even unrelated fields) get 200 OK instead of 422 Unprocessable Entity.

**When to use:** Whenever a public API contract needs to evolve in a backwards-compatible way. The locked CON-route-api contract in PROJECT.md says `weight_iri`/`weight_potholes` must continue to be accepted — this is the canonical Pydantic v2 way to honor that without renaming or version-bumping the endpoint.

**Example:**
```python
# Source: docs.pydantic.dev/latest/api/config/ — ConfigDict.extra
from pydantic import BaseModel, ConfigDict, Field

class RouteRequest(BaseModel):
    model_config = ConfigDict(extra='ignore')   # NEW in Phase 10

    origin: LatLon
    destination: LatLon
    include_iri: bool = True
    include_potholes: bool = True
    # Field defaults preserved so existing v0.2.0 tests still see them.
    # Values are accepted by the model but unused by routing.find_route().
    weight_iri: float = Field(default=50, ge=0, le=100)
    weight_potholes: float = Field(default=50, ge=0, le=100)
    max_extra_minutes: float = Field(default=5, ge=0)
```

**Why preserve the Field defaults:** Removing `weight_iri`/`weight_potholes` outright would break v0.2.0 unit tests that introspect `RouteRequest().weight_iri == 50`. Keeping them as Field defaults is the safest evolution — the values are accepted but unused.

### Pattern 3: FastAPI `Response` Parameter for Header Injection While Preserving `response_model`

**What:** Declare a `response: Response` parameter in the path operation. Set headers/cookies/status on it. Continue to return the typed response object — FastAPI extracts the headers from the `Response` and applies the `response_model` filter to the returned object.

**When to use:** Any time you need a static header on a typed-response endpoint. Direct `JSONResponse(content=..., headers=...)` returns BYPASS the `response_model` filter — silently breaking the schema contract.

**Example (the canonical Phase 10 shape):**
```python
# Source: fastapi.tiangolo.com/advanced/response-headers/ — Response parameter pattern
from fastapi import Response

@router.post("/route", response_model=RouteResponse)
def find_route(req: RouteRequest, response: Response):
    response.headers["Deprecation"] = "weight_iri,weight_potholes ignored as of v0.4.0"
    # ... existing logic ...
    return RouteResponse(...)  # response_model filter still runs
```

**Critical detail:** The header is set BEFORE any early-returns (cache hit, no-route fallback). Otherwise cached responses return without the header — see Pitfall 4.

### Anti-Patterns to Avoid
- **Inline crash aggregation inside `routing.py`** (PROJECT.md lock): pre-bake in `compute_scores.py` ONLY. Routing.py reads the materialized column.
- **Academic 100:10:1 severity weights** (Pitfall 5): produces bimodal `crash_norm` saturated at 0/1; one fatal anywhere on a segment maxes the segment score.
- **`extra='ignore'` without an identical-route integration test** (Pitfall 7): "accepted" silently does NOT mean "ignored" — the test must assert geometry + cost equality.
- **`JSONResponse(content=..., headers=...)` for the `/route` deprecation header**: bypasses `response_model=RouteResponse` filter, breaks the typed contract.
- **Forgetting to re-key the route cache** (Pitfall 2): if `make_route_cache_key` still includes `weight_iri`/`weight_potholes`, two functionally-identical requests get separate cache slots — semantic-identical, but it leaks the supposedly-ignored fields into observable behavior (cache miss latency).
- **Computing p95 over all segments including zeros** (Pitfall 6): the ~99% of segments with zero crashes dominate the percentile and degenerate the normalization.
- **Putting `pytestmark = pytest.mark.integration` on the unit test file** (test_scoring.py is module-level marker-free — pure-python unit tests should NOT be skipped on CI without a DB).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 95th-percentile computation across rows | Loop in Python over a `SELECT raw_per_km FROM ...` then `numpy.percentile` | PostgreSQL built-in `PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY raw_per_km)` | Round-trip is wasteful (~210k rows); SQL aggregate is one DB op; matches existing pre-baked-stats pattern in compute_scores.py [VERIFIED: postgresql.org/docs/current/functions-aggregate.html#FUNCTIONS-ORDEREDSET-TABLE] |
| Backwards-compatible request schema with field rename / removal | Custom Pydantic validator that pops keys before construction | `model_config = ConfigDict(extra='ignore')` | One line; idiomatic Pydantic v2; battle-tested across the FastAPI ecosystem [CITED: docs.pydantic.dev/latest/api/config/] |
| Static response header on every response | Middleware that intercepts every `/route` response | FastAPI `response: Response` parameter | Middleware is global (would taint other endpoints); param is local and visible in the route signature |
| Deterministic cache key for floats | `f"{lat:.6f}-{lon:.6f}-..."` string concat | Existing `hashlib.sha256(json.dumps(d, sort_keys=True)...)` in `app/cache.py:43` | Already in place; just remove the `weight_iri` / `weight_potholes` parameters from the function signature |
| Seg-length-floored division (avoid divide-by-near-zero) | `if length < 0.05: length = 0.05` in Python pre-update loop | SQL `GREATEST(length_m / 1000.0, 0.05)` | Inline in the UPDATE; one expression; no Python round-trip |

**Key insight:** Phase 10's "complexity" is concentrated in two SQL idioms (correlated-subquery UPDATE + `PERCENTILE_CONT`). Both are vanilla PostgreSQL — not new tooling, not new libraries. Treat the SQL as a first-class artifact, not a quick patch.

## Common Pitfalls

### Pitfall 1: Bimodal Saturation from Wrong Severity Weights
**What goes wrong:** With academic 100:10:1, a single fatal crash on a 200m segment produces `raw_per_km = 100/0.2 = 500`. With LA's typical p95 ~10–30 (depending on injury density), `crash_norm = LEAST(1, 500/30) = 1.0`. The segment gets the maximum possible cost contribution. Long arterials with one freak fatal look identical to actively dangerous corridors → routing recommends bizarre detours.
**Why it happens:** The 100:10:1 ratio comes from EPDO crash-cost methodologies (FHWA HSIP) that *intentionally* differentiate fatal injuries by 2 orders of magnitude. That's correct for project prioritization but wrong for routing cost — routing wants smooth gradients, not categorical "this segment had a fatal" cliffs.
**How to avoid:** Use `8:3:1` (D-10-04). Pin a unit test asserting `assert FATAL_WEIGHT == 8 * PDO_WEIGHT` and `assert INJURY_WEIGHT == 3 * PDO_WEIGHT`. Run the histogram smoke test (D-10-20) and assert ≥50% of crash-bearing segments fall in `[0.05, 0.5]`.
**Warning signs:** A histogram that has spikes at exactly 0.0 and exactly 1.0 with very few values in between. A `--source crash` run that reports >95% of segments with `crash_norm = 1.0`.

### Pitfall 2: Cache-Key Contamination Breaks Identical-Route Guarantee
**What goes wrong:** `app/cache.py:make_route_cache_key` currently takes `weight_iri` and `weight_potholes` as parameters and includes them in the SHA-256 hash. After Phase 10's silent-ignore, `POST /route {... "weight_iri": 0.99}` still computes the same route as `POST /route` without the field — but the two requests get different cache keys, so the second one re-runs pgr_dijkstra. The response is identical (D-10-16 satisfied at the body level), but cache effectiveness drops and an observer monitoring DB query rates would see "ignored" fields still affecting backend behavior.
**Why it happens:** The cache-key function and the cost computation are separate concerns. Easy to fix the latter and forget the former.
**How to avoid:** Update `make_route_cache_key`'s signature to drop the four legacy parameters in the same plan as the cost-formula swap (Plan 10-03). Add a unit test in `test_cache.py` (or extend `test_route.py`) that sends two requests differing only in `weight_iri` and asserts both hit the same cache slot (e.g., second response < 50ms).
**Warning signs:** A test that passes "same body returned" but the second request takes 2 seconds.

### Pitfall 3: "Accepted" vs "Semantically Ignored"
**What goes wrong:** `extra='ignore'` makes Pydantic NOT raise 422 — but if `routing.find_route` still reads `req.weight_iri` and passes it to `normalize_weights()`, the field is "accepted" but very much NOT ignored. The integration test `test_route_returns_best_and_fastest` already passes `weight_iri: 50` and would still pass after `extra='ignore'` is added — but it doesn't pin the *semantic* contract.
**Why it happens:** Two-step refactor: (a) add `extra='ignore'`, (b) drop `normalize_weights` from routing.py. Skipping (b) leaves the field active.
**How to avoid:** The Phase 10 integration test must POST two requests differing ONLY in `weight_iri` (e.g., 50 vs 99) and assert byte-identical `geojson` and `total_cost`. This is the test pinned by D-10-16.
**Warning signs:** A test that asserts "200 OK with weight_iri: 99" but doesn't compare the response body to an alternate request.

### Pitfall 4: `Deprecation` Header Missing on Cache Hits or No-Route Fallbacks
**What goes wrong:** The route handler has three early-return paths: (a) cache hit at line 270, (b) no-route fallback at line 381, (c) success at line 485. If the `response.headers["Deprecation"] = ...` line is added inside the success block (line 470-485), the header is missing from cache hits and fallbacks. A client that filters/depends on the header sees inconsistent behavior.
**Why it happens:** The natural place to set "API metadata" is alongside the success-path response construction. Easy to miss the early returns.
**How to avoid:** Set the header at the TOP of `find_route()`, immediately after the `req: RouteRequest, response: Response` parameter list — before any early returns. Pin with two tests: one that exercises the cache path (call twice, assert header on second) and one that exercises the no-route fallback (use coordinates outside any segment, assert header).

### Pitfall 5: CONTEXT D-10-07 References Wrong Column Name (`length_km` does not exist)
**What goes wrong:** CONTEXT.md D-10-07 says "Length is read from `road_segments.length_km` (already populated by Phase 8 baseline)." This column does NOT exist. The actual column (verified via live DB schema, migration 001 line 5, seed_data.py line 79) is `road_segments.length_m` (DOUBLE PRECISION, METERS, NOT NULL). A planner who copies the CONTEXT formula verbatim into SQL gets `column "length_km" does not exist` at first execution.
**Why it happens:** CONTEXT was auto-generated from REQUIREMENTS.md / ROADMAP.md, which use the human-readable "per km" framing. The schema uses meters.
**How to avoid:** SQL formula is `GREATEST(length_m / 1000.0, 0.05)` (km units throughout) OR equivalently `GREATEST(length_m, 50.0)` with a 50m floor in meter units. Plan must surface this column-name mismatch in the plan body so the implementer doesn't hit a runtime error. Empirical check (probed on live DB 2026-05-08): 14% of segments (29,476 of 209,856) have `length_m < 50` — the floor applies to a real population of segments and is NOT a defensive-only check.

### Pitfall 6: p95 Dominated by Zero-Crash Segments
**What goes wrong:** Computing `PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY raw_per_km)` over ALL segments — when ~99% have `raw_per_km = 0` because they have no crashes — produces a degenerate p95. Concretely: if 99% of values are 0 and 1% are >0, the 95th percentile of the full distribution is still 0. Division becomes division-by-zero (or -very-small-number) and `crash_norm` blows up.
**Why it happens:** Naive reading of "p95 across all segments". The intent is "p95 across segments that have crashes" — i.e., the upper tail of the crash-bearing distribution.
**How to avoid:** Filter `WHERE raw_per_km > 0` in the p95 aggregation subquery. Use `NULLIF((SELECT p95 FROM p95v), 0)` defensively in the UPDATE so a zero p95 (no crashes anywhere) yields NULL → coalesce to 0 → no segment gets crash_norm > 0.
**Warning signs:** A test against an empty `crash_records` table either crashes with division-by-zero or sets every segment's `crash_norm` to 1.0.

### Pitfall 7: Live DB has 0 crash_records — Histogram Smoke Test Will Trivially Pass
**What goes wrong:** Probed live DB (2026-05-08) shows `crash_records` table exists but contains 0 rows. Phase 9 verification reported 197 rows — they have since been wiped (likely by another test run that uses a TRUNCATE). If the planner runs the histogram smoke test (D-10-20) without first re-ingesting, every segment has `crash_norm = 0`, the histogram is degenerate, and the assertion "≥50% of crash-bearing segments in [0.05, 0.5]" trivially passes (zero crash-bearing segments → zero in range → 0/0 → vacuously true unless guarded).
**Why it happens:** Test isolation: integration tests that DELETE crash_records leave the DB empty after the suite runs. Phase 10 inherits an empty crash table.
**How to avoid:** Plan 10-02's verification step must include `python scripts/ingest_crashes.py --source lacity --csv data/crashes_la/lacity_fixture.csv` BEFORE running `compute_scores.py --source crash`. The histogram smoke test must guard against the degenerate case: `assert len(crash_bearing) >= 100` before computing the in-range fraction.
**Warning signs:** Histogram test reports `0/0 segments in [0.05, 0.5]` and passes anyway.

## Runtime State Inventory

> Phase 10 is primarily code/config + a one-time UPDATE; there is also runtime state that must be checked.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `segment_scores.crash_norm` column (already exists, all 209,856 rows currently 0.0). `crash_records` table exists with 0 live rows (verified 2026-05-08); Phase 10 needs ≥1 row to validate the UPDATE produces non-zero crash_norm. | Re-run `scripts/ingest_crashes.py --source lacity --csv data/crashes_la/lacity_fixture.csv` before the histogram smoke test. Local-only — Fly.io DB unaffected (Phase 12 will land migration 004 + first ingest there). |
| Live service config | None. No external services configured for Phase 10 (no Socrata API call — that's Phase 9 territory; Phase 10 reads pre-ingested data only). | None. |
| OS-registered state | None. No cron jobs, systemd units, launchd plists for Phase 10. The quarterly recompute is operator-driven. | None. |
| Secrets/env vars | None new. `LACITY_APP_TOKEN` (Phase 9, optional) and `LACITY_SNAP_M` (Phase 9, default 50.0) unchanged. `DATABASE_URL` and `AUTH_SIGNING_KEY` already in place for tests. | None. |
| Build artifacts | TTL caches in-process (`segments_cache`, `route_cache` in `app/cache.py`). After Phase 10's `make_route_cache_key` signature change, ANY in-flight server with old cached entries would be technically wrong (entries keyed under old signature). | In dev, restart the backend (auto-reload picks up code change). In Phase 12 deploy, the redeploy naturally clears the in-process cache. No persistent cache state. |

## Code Examples

### Example 1: New `backend/app/scoring.py` (the locked constants and new signature)
```python
# Source: synthesis of CONTEXT D-10-01 through D-10-04 + existing scoring.py
"""Scoring constants and per-segment cost formula.

v0.4.0 (Phase 10) introduces locked outer weights replacing the user-tunable
sliders shipped in v0.2.0. The previous `normalize_weights()` function is
kept-but-unused for one milestone of confidence (D-10-03).
"""

# Locked outer weights — sum to 1.0 by construction; no normalization step.
W_IRI: float = 0.40
W_POT: float = 0.35
W_CRASH: float = 0.25

# Severity weights — literature-converged routing-cost ratio (NOT EPDO 100:10:1).
# Pitfall 5 in PROJECT.md: 100:10:1 saturates crash_norm bimodal at 0/1.
FATAL_WEIGHT: int = 8
INJURY_WEIGHT: int = 3
PDO_WEIGHT: int = 1

# Single-fatal cap (D-10-05): cap per-segment raw severity sum so one freak
# crash cannot dominate a long arterial. K=3 means up to 3 equivalent-fatal
# units contribute fully; beyond that the segment plateaus.
# Researcher recommendation: K=3 (24 = 3 fatals; or 1 fatal + 5 injuries + 1 pdo).
# Pinned in unit tests; recalibration is a one-line constant change.
FATAL_CAP_K: int = 3
FATAL_CAP: int = FATAL_CAP_K * FATAL_WEIGHT  # = 24


def compute_segment_cost(
    travel_time_s: float,
    iri_norm: float,
    pothole_total: float,
    crash_norm: float,
) -> float:
    """Compute cost for a single segment with locked outer weights.

    cost = travel_time_s + W_IRI*iri_norm + W_POT*pothole_total + W_CRASH*crash_norm

    No normalization step: W_IRI + W_POT + W_CRASH = 1.0 by construction.
    """
    return (
        travel_time_s
        + W_IRI * iri_norm
        + W_POT * pothole_total
        + W_CRASH * crash_norm
    )


# DEPRECATED v0.4.0 — kept for v0.2.0 unit-test compatibility (D-10-03).
# Remove after one milestone of confidence (post-v0.4.0) if no regressions.
def normalize_weights(
    include_iri: bool,
    include_potholes: bool,
    weight_iri: float,
    weight_potholes: float,
) -> tuple[float, float]:
    """[DEPRECATED v0.4.0] Use module constants W_IRI/W_POT/W_CRASH instead."""
    if not include_iri and not include_potholes:
        return 0.0, 0.0
    if include_iri and not include_potholes:
        return 1.0, 0.0
    if not include_iri and include_potholes:
        return 0.0, 1.0
    total = weight_iri + weight_potholes
    if total == 0:
        return 0.5, 0.5
    return weight_iri / total, weight_potholes / total
```

### Example 2: New `find_route` shape with `Response` parameter
```python
# Source: fastapi.tiangolo.com/advanced/response-headers/ — Response parameter pattern
from fastapi import APIRouter, Response

@router.post("/route", response_model=RouteResponse)
def find_route(req: RouteRequest, response: Response):
    # D-10-15: Deprecation header on EVERY response (set BEFORE early returns).
    # Pitfall 4: must be set before cache-hit early-return at line 270 below.
    response.headers["Deprecation"] = (
        "weight_iri,weight_potholes ignored as of v0.4.0"
    )

    # D-10-14: cache key no longer includes weight_iri/weight_potholes.
    # See app/cache.py — make_route_cache_key signature shrank from 9 params to 5.
    cache_key = make_route_cache_key(
        req.origin.lat, req.origin.lon,
        req.destination.lat, req.destination.lon,
        req.max_extra_minutes,
    )

    # ... [existing route_requests insert + cache check] ...
    cached = get_route_cached(cache_key)
    if cached is not None:
        return RouteResponse(**cached)  # header preserved by FastAPI

    # ... [existing pgr_dijkstra K=5 logic UNCHANGED — Phase 8 perf budget intact] ...

    # SEGMENTS_BY_IDS_SQL extended with crash_norm column:
    #   COALESCE(ss.crash_norm, 0) AS crash_norm
    # (COALESCE redundant since column is NOT NULL DEFAULT 0.0, but keeps the
    # query symmetric with moderate_score / severe_score / pothole_score_total.)

    # In the per-edge scoring loop:
    for eid in edge_ids:
        seg = seg_data.get(eid)
        # ...
        crash = seg["crash_norm"] or 0.0
        # D-10-02: new compute_segment_cost signature — no w_iri / w_pot params.
        total_cost += compute_segment_cost(t, iri, pot, crash)
        # ...
```

### Example 3: New `--source crash` branch in compute_scores.py
```python
# Source: synthesis of D-10-10 + D-10-11 + Pattern 1 SQL above.
# Drop into compute_scores.py main() alongside the existing synthetic/mapillary path.

CRASH_UPDATE_SQL = """
WITH per_seg AS (
    SELECT
        rs.id AS segment_id,
        rs.length_m,
        SUM(
            CASE c.severity
                WHEN 'fatal' THEN %(fatal_w)s
                WHEN 'injury' THEN %(injury_w)s
                WHEN 'pdo' THEN %(pdo_w)s
                ELSE 0
            END
        ) AS raw_sum
    FROM road_segments rs
    LEFT JOIN crash_records c ON c.snapped_segment_id = rs.id
    GROUP BY rs.id, rs.length_m
),
per_seg_capped AS (
    SELECT
        segment_id,
        length_m,
        LEAST(raw_sum, %(fatal_cap)s) AS capped_sum,
        LEAST(raw_sum, %(fatal_cap)s) /
            GREATEST(length_m / 1000.0, 0.05) AS raw_per_km
    FROM per_seg
),
p95v AS (
    SELECT PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY raw_per_km) AS p95
    FROM per_seg_capped
    WHERE raw_per_km > 0
)
UPDATE segment_scores ss
SET crash_norm = LEAST(
        1.0,
        psc.raw_per_km / NULLIF((SELECT p95 FROM p95v), 0)
    ),
    updated_at = NOW()
FROM per_seg_capped psc
WHERE ss.segment_id = psc.segment_id
  AND psc.raw_per_km > 0
"""

if args.source in ("crash", "all"):
    from app.scoring import (
        FATAL_WEIGHT, INJURY_WEIGHT, PDO_WEIGHT, FATAL_CAP,
    )
    cur.execute("SELECT COUNT(*) FROM crash_records")
    n_crashes = cur.fetchone()[0]
    if n_crashes == 0:
        print(
            "WARNING: --source crash selected but 0 rows in crash_records; "
            "crash_norm will stay at 0 for all segments. "
            "Run scripts/ingest_crashes.py --source lacity first.",
            file=sys.stderr,
        )
    else:
        cur.execute(CRASH_UPDATE_SQL, {
            "fatal_w": FATAL_WEIGHT,
            "injury_w": INJURY_WEIGHT,
            "pdo_w": PDO_WEIGHT,
            "fatal_cap": FATAL_CAP,
        })
        conn.commit()
        cur.execute("SELECT COUNT(*) FROM segment_scores WHERE crash_norm > 0")
        n_segments = cur.fetchone()[0]
        print(
            f"crash_norm recomputed. {n_segments} segments have non-zero crash_norm."
        )
```

### Example 4: GET /segments minimal additive change
```python
# Source: minimal diff against backend/app/routes/segments.py (D-10-17 + D-10-18).

# In the SQL string (line ~25-36):
sql = """
    SELECT
        rs.id,
        ST_AsGeoJSON(rs.geom) AS geojson,
        rs.iri_norm,
        COALESCE(ss.moderate_score, 0) AS moderate_score,
        COALESCE(ss.severe_score, 0) AS severe_score,
        COALESCE(ss.pothole_score_total, 0) AS pothole_score_total,
        COALESCE(ss.crash_norm, 0) AS crash_norm   -- NEW: D-10-17
    FROM road_segments rs
    LEFT JOIN segment_scores ss ON rs.id = ss.segment_id
    WHERE rs.geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)
"""

# In the feature-construction loop (line ~44-55):
features.append({
    "type": "Feature",
    "geometry": json.loads(row["geojson"]),
    "properties": {
        "id": row["id"],
        "iri_norm": row["iri_norm"],
        "moderate_score": row["moderate_score"],
        "severe_score": row["severe_score"],
        "pothole_score_total": row["pothole_score_total"],
        "crash_norm": row["crash_norm"],   # NEW: D-10-17 / D-10-18 (default 0.0 since col is NOT NULL DEFAULT 0.0)
    },
})
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Pydantic v1 `class Config: extra = 'ignore'` | Pydantic v2 `model_config = ConfigDict(extra='ignore')` | Pydantic v2.0 (2023) | Already on v2 in this project; no migration needed. |
| Manual `JSONResponse(content=..., headers=...)` | Inject `response: Response` into route signature | FastAPI 0.61+ (years ago) | Use the parameter form to preserve `response_model`. |
| User-tunable IRI/pothole weight sliders (v0.2.0) | Locked module constants `W_IRI=0.40, W_POT=0.35, W_CRASH=0.25` | v0.4.0 Phase 10 | Routing recommendations become deterministic across sessions; API contract preserved via `extra='ignore'`. |
| `pgr_ksp` super-linear Yen's enumeration | `pgr_dijkstra × K` with edge-weight perturbation (Yen's-style) | v0.3.0 Phase 8 | Phase 10 inherits Phase 8 perf — DO NOT rewire routing.py beyond the cost-formula swap. |

**Deprecated/outdated:**
- `normalize_weights()` in scoring.py: marked DEPRECATED v0.4.0; kept for one milestone of test compatibility; remove if no regressions surface in v0.4.0 → v0.4.1.
- `make_route_cache_key` parameter list `(..., weight_iri, weight_potholes, ...)`: shrinks to drop those params in Phase 10. The two callers (line 250-256 and the test mock in `test_route.py`) update in-place.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x (existing) |
| Config file | `backend/conftest.py` (registers `integration` marker, `db_available` fixture, `db_has_topology` fixture) |
| Quick run command | `cd backend && DATABASE_URL='postgresql://rq:rqpass@127.0.0.1:5432/roadquality' AUTH_SIGNING_KEY='test_secret_do_not_use_in_production_padding_padding' PYTHONPATH=. /tmp/rq-venv/bin/python -m pytest tests/test_scoring.py -x -q` (pure-python, no DB needed) |
| Full suite command | Same prefix + `tests/test_scoring.py tests/test_route.py tests/test_segments.py tests/test_compute_scores_source.py tests/test_routing_performance.py` |
| Phase gate | All Phase 10 tests + all 6 v0.2.0 integration tests + Phase 8 routing perf tests green before `/gsd-verify-work` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REQ-crash-scoring-formula | Severity weight ratio FATAL=8*PDO, INJURY=3*PDO | unit | `pytest tests/test_scoring.py::TestCrashScoringMath::test_severity_weight_ratios -x` | ❌ Wave 1 |
| REQ-crash-scoring-formula | `compute_segment_cost` signature is 4-arg (no w_iri/w_pot) | unit | `pytest tests/test_scoring.py::TestComputeSegmentCost::test_signature_drops_weight_params -x` | ❌ Wave 1 |
| REQ-crash-scoring-formula | Locked constants W_IRI=0.40, W_POT=0.35, W_CRASH=0.25 | unit | `pytest tests/test_scoring.py::TestLockedConstants -x` | ❌ Wave 1 |
| REQ-crash-scoring-formula | Single-fatal cap: `min(raw_sum, FATAL_CAP)` enforced | unit | `pytest tests/test_scoring.py::TestCrashScoringMath::test_single_fatal_cap -x` | ❌ Wave 1 |
| REQ-crash-scoring-formula | Length floor 0.05 km / 50 m applied | unit | `pytest tests/test_scoring.py::TestCrashScoringMath::test_length_floor_50m -x` | ❌ Wave 1 |
| REQ-crash-scoring-formula | p95 cap clips to [0,1] | unit | `pytest tests/test_scoring.py::TestCrashScoringMath::test_p95_clip_one -x` | ❌ Wave 1 |
| REQ-crash-scoring-formula | Zero-crash segments default crash_norm=0 | unit | `pytest tests/test_scoring.py::TestCrashScoringMath::test_zero_crash_segments_default_zero -x` | ❌ Wave 1 |
| REQ-crash-scoring-formula | `normalize_weights` still importable but marked deprecated | unit | `pytest tests/test_scoring.py::TestNormalizeWeights -x` (existing 6 tests + new docstring check) | ⚠️ Existing 6 pass unchanged |
| REQ-crash-scoring-formula | `compute_scores.py --source crash` CLI flag accepted | subprocess | `pytest tests/test_compute_scores_source.py::TestComputeScoresCLI::test_help_lists_crash_source -x` | ❌ Wave 2 |
| REQ-crash-scoring-formula | `--source crash` writes non-zero crash_norm to ≥1 segment after fixture ingest | integration | `pytest tests/test_compute_scores_source.py::test_crash_source_updates_crash_norm -x -m integration` | ❌ Wave 2 |
| REQ-crash-scoring-formula | Histogram smoke: ≥50% crash-bearing segments in `crash_norm ∈ [0.05, 0.5]` | integration / smoke | `pytest tests/test_compute_scores_source.py::test_crash_norm_histogram_not_bimodal -x -m smoke` | ❌ Wave 2 (mark as `smoke` per recommendation below) |
| REQ-route-api-locked-weights | RouteRequest has `model_config = ConfigDict(extra='ignore')` | unit | `pytest tests/test_models.py::test_route_request_extra_ignored -x` | ❌ Wave 2 |
| REQ-route-api-locked-weights | RouteRequest accepts unknown extra fields without 422 | unit | `pytest tests/test_models.py::test_route_request_unknown_field_silently_dropped -x` | ❌ Wave 2 |
| REQ-route-api-locked-weights | Identical-route guarantee: weight_iri=99 == weight_iri=50 (geojson + total_cost byte-equal) | integration (mocked DB) | `pytest tests/test_route.py::test_identical_route_with_legacy_weight_fields -x` | ❌ Wave 2 |
| REQ-route-api-locked-weights | `Deprecation` header set with exact-string value on success path | integration (mocked DB) | `pytest tests/test_route.py::test_deprecation_header_on_success -x` | ❌ Wave 2 |
| REQ-route-api-locked-weights | `Deprecation` header set on cache-hit path (Pitfall 4) | integration (mocked DB) | `pytest tests/test_route.py::test_deprecation_header_on_cache_hit -x` | ❌ Wave 2 |
| REQ-route-api-locked-weights | `Deprecation` header set on no-route fallback (Pitfall 4) | integration (mocked DB) | `pytest tests/test_route.py::test_deprecation_header_on_no_route -x` | ❌ Wave 2 |
| REQ-route-api-locked-weights | Cache key no longer differs by weight_iri (Pitfall 2) | integration (mocked DB) | `pytest tests/test_route.py::test_cache_key_ignores_weight_fields -x` | ❌ Wave 2 |
| REQ-route-api-locked-weights | All 6 v0.2.0 + Phase-8 integration tests pass unchanged | integration | `pytest tests/test_route.py tests/test_routing_performance.py -m integration` | ✅ Existing |
| Cross-cutting | `GET /segments` includes `crash_norm` field on every feature | integration (mocked DB) | `pytest tests/test_segments.py::test_segments_includes_crash_norm -x` | ❌ Wave 3 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_scoring.py -x -q` (pure-python, sub-second)
- **Per wave merge:** `pytest tests/test_scoring.py tests/test_route.py tests/test_segments.py tests/test_compute_scores_source.py -x` (DB-bound; ~30s)
- **Phase gate:** Full suite + Phase 8 perf tests green; histogram smoke run via runbook against fresh fixture-ingested DB

### Wave 0 Gaps
- [ ] `tests/test_scoring.py` exists — needs new `TestCrashScoringMath` class + `TestLockedConstants` class added (extend, do not replace; existing 6 normalize_weights tests must pass unchanged)
- [ ] `tests/test_models.py` exists — needs new `test_route_request_extra_ignored` + `test_route_request_unknown_field_silently_dropped`
- [ ] `tests/test_route.py` exists — needs 5 new tests for Deprecation header + identical-route + cache-key
- [ ] `tests/test_segments.py` exists — needs `test_segments_includes_crash_norm` (extend existing mock)
- [ ] `tests/test_compute_scores_source.py` exists — needs new `--source crash` branch tests (extend existing pattern)
- [ ] **Pre-test setup (operator):** re-run `python scripts/ingest_crashes.py --source lacity --csv data/crashes_la/lacity_fixture.csv` against the live local DB before histogram smoke test runs (Pitfall 7 — current state has 0 crash rows)
- [ ] **`smoke` pytest marker registration** — recommend adding to `conftest.py:pytest_configure`: `config.addinivalue_line("markers", "smoke: marks tests run by Phase-12 runbook, skipped in normal CI")`

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Auth removed in d0ef452 for public demo; no Phase 10 changes touch auth. |
| V3 Session Management | no | No sessions; stateless API. |
| V4 Access Control | no | Public demo; no per-user authorization rules. |
| V5 Input Validation | yes | `RouteRequest` Pydantic v2 model; `extra='ignore'` is a deliberate input-handling change — pin it in tests so a future "tighten to extra='forbid'" PR doesn't silently regress the contract. |
| V6 Cryptography | no | No new crypto. Cache keys are SHA-256 of structured input — collision-resistant for this non-adversarial use. |

### Known Threat Patterns for FastAPI + PostgreSQL stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection in correlated-subquery UPDATE | Tampering | All severity weights and FATAL_CAP passed via `%(name)s` parameterization (psycopg2). Raw column names are static strings. **No user input reaches the SQL string.** |
| Cache poisoning via crafted `weight_iri` value | Tampering | After Phase 10, `weight_iri` is dropped from cache key entirely (Pitfall 2 fix) — caller cannot influence the cache slot via that field. |
| Header injection via Deprecation value | Tampering | The header value is a hardcoded string literal (`"weight_iri,weight_potholes ignored as of v0.4.0"`); no interpolation, no user input. |
| Information disclosure via `extra='ignore'` accepting any field | Information Disclosure | `extra='ignore'` SILENTLY DROPS extra fields — they don't appear in logs or DB. The `route_requests.params_json` insert at routing.py:262 records `req.model_dump()` which excludes ignored fields. **Verify this in a unit test.** |

## Assumptions Log

> Claims tagged `[ASSUMED]` need user/planner confirmation before locking. The Phase 10 research has minimized these by verifying against live code/DB; remaining assumptions concern numerical-tuning values that can only be empirically validated post-Phase-9-fixture-ingest.

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `FATAL_CAP_K = 3` (cap = 24 = 3 fatals' worth) is a reasonable single-fatal cap value for the routing-cost domain. Literature supports cap-style attenuation for outliers but does not pin K=3 specifically. | Pattern 1 + Code Example 1 (FATAL_CAP) | Wrong K underweights or overweights freak fatals; histogram smoke test (D-10-20) would surface the failure. Recalibration is a one-line constant change + re-run of `compute_scores.py --source crash`. The deferred Phase 12 5-arterial spot check is the empirical validation. |
| A2 | Histogram smoke test threshold "≥50% in [0.05, 0.5]" is a reasonable Pitfall 5 guard. CONTEXT D-10-20 specifies this number. | Validation Architecture | If the threshold is too strict, the test fails on legitimate distributions; too loose, real bimodal saturation slips through. CONTEXT-specified value used as-is. |
| A3 | The `Deprecation` header literal value `weight_iri,weight_potholes ignored as of v0.4.0` does NOT comply with RFC 9745 (which mandates `@<unix-timestamp>` format). For a single-frontend-only system the practical impact is zero, but a strict HTTP-aware client could reject the header. | D-10-15 / Code Example 2 | Future external API consumers (none planned in v0.4.0) parsing per RFC 9745 would reject the header. Locked exact-string per CONTEXT — flagged here for visibility. **Researcher recommends keeping the locked string and adding an inline comment + docs callout that the value is documentation-style, not RFC-compliant.** |

**Empirically verified (NOT assumed):**
- Column name is `length_m`, not `length_km` — verified from migration 001 + live DB query (Pitfall 5).
- 14% of segments have `length_m < 50` — verified from live DB MIN/AVG/MAX query.
- `crash_records` table currently has 0 rows in live DB — verified from `SELECT COUNT(*)` (Pitfall 7).
- `segment_scores` has 209,856 rows; `crash_norm` column exists with type `double precision` and default `0.0` — verified from `information_schema.columns`.
- `road_segments.id` is INTEGER (matches `crash_records.snapped_segment_id`) — verified from `pg_typeof()`.

## Open Questions

1. **Single-fatal cap mechanism — researcher recommends K=3, but is this empirically right for LA?**
   - What we know: literature supports caps; the goal is to prevent freak-fatal dominance on long arterials. CONTEXT D-10-05 leaves the value to researcher's discretion.
   - What's unclear: K=3 vs K=2 vs K=5 vs per-victim-cap — without a fatal-overweighting smoke test against real LA data (deferred to Phase 12), the choice is reasoned, not measured.
   - Recommendation: **Pin K=3 in `scoring.py` and unit tests for Phase 10**, document the recalibration mechanism (one-line + recompute), and let the Phase 12 5-arterial spot check be the empirical gate. If Phase 12 finds K=3 produces nonsensical routes, change to K=2 (a one-line const change), recompute, redeploy.

2. **Should the histogram smoke test be `pytest.mark.smoke` (skipped on normal CI) or a separate runbook script?**
   - What we know: CONTEXT D-10-20 says "manual via runbook OR pytest mark." It depends on `crash_records` having data, which is fragile in CI.
   - What's unclear: whether to expect operators to run pytest with `-m smoke` or to ship a `scripts/check_crash_histogram.py` runbook tool.
   - Recommendation: **Use `pytest.mark.smoke` registered in `conftest.py`.** Same toolchain as the rest of the suite, no new script to maintain, easier to discover (`pytest -m smoke`). The runbook (D-10-23 docs section) tells the Phase-12 operator to run `pytest -m smoke -k crash_histogram` after `compute_scores.py --source all`. Keeps testing centralized and discoverable.

3. **Should `make_route_cache_key` drop `include_iri` / `include_potholes` too?**
   - What we know: After Phase 10, those flags are also functionally inert (the cost formula no longer branches on them; the locked constants apply unconditionally). They remain in `RouteRequest` per D-10-13 for v0.2.0 compat.
   - What's unclear: dropping them from the cache key would maximize cache hit rate; keeping them preserves "request body → cache key" determinism.
   - Recommendation: **Drop them from the cache key.** Same logic as `weight_iri`/`weight_potholes` — they don't affect the computed response, so they shouldn't fragment the cache. New `make_route_cache_key(origin_lat, origin_lon, dest_lat, dest_lon, max_extra_minutes)` — 5 params (down from 9). Pin with a unit test.

4. **`docs/API.md` (new file) vs `README.md` (existing) for D-10-23?**
   - What we know: CONTEXT leaves location to discretion. Project currently has no `docs/` directory, but `docs/DETECTOR_EVAL.md` is referenced (Phase 7 docs) — so the convention exists.
   - Recommendation: **Create `docs/API.md`.** README is already long (Phase 1 stale-prose carry-forward); a focused `docs/API.md` is easier to extend in v0.4.1 and beyond. Cross-link from README "API" section.

5. **Phase 9 reported 197 crash rows — live DB shows 0. What happened, and does it block Phase 10?**
   - What we know: Phase 9 verification (09-VERIFICATION.md) confirms 197 rows on 2026-05-08 06:26 UTC. Probe at 2026-05-08 (Phase 10 research) shows 0 rows. No DELETE or TRUNCATE in recent git history.
   - What's unclear: Whether tests cleaned up after themselves more aggressively than expected, or whether a manual operation wiped the table.
   - Recommendation: **Not a blocker.** Phase 10's plan must include a Wave-0 step (`scripts/ingest_crashes.py --source lacity --csv data/crashes_la/lacity_fixture.csv`) before any integration test that depends on non-zero crash_norm runs. The 5-test Phase 9 integration suite assumes this anyway (it ingests fresh in each test).

## Plans/Tasks Split — Recommended Decomposition

**Recommendation: 3 plans in 3 waves** (collapse the suggested 10-04 into 10-03 — it's trivial enough to fold).

### Plan 10-01: Scoring Constants + Cost-Formula Signature (Wave 1, foundation)
**Decisions covered:** D-10-01, D-10-02, D-10-03, D-10-04, D-10-05 (cap value), D-10-19 (unit tests)
**Files modified:** `backend/app/scoring.py`, `backend/tests/test_scoring.py`
**Why Wave 1:** Both 10-02 and 10-03 import constants from `scoring.py`. Must land first.
**Depends on:** Phase 9 complete (already complete).
**Tasks:**
1. Add `W_IRI`, `W_POT`, `W_CRASH`, `FATAL_WEIGHT`, `INJURY_WEIGHT`, `PDO_WEIGHT`, `FATAL_CAP_K`, `FATAL_CAP` constants to `scoring.py`
2. Implement new `compute_segment_cost(travel_time_s, iri_norm, pothole_total, crash_norm)` 4-arg signature
3. Mark `normalize_weights()` `# DEPRECATED v0.4.0` with retention rationale (test compat)
4. Extend `tests/test_scoring.py` with 8+ unit tests (`TestCrashScoringMath` + `TestLockedConstants` classes)
5. Verify existing 6 `TestNormalizeWeights` tests still pass unchanged

### Plan 10-02: `compute_scores.py --source crash` + Histogram Smoke (Wave 2, parallel with 10-03)
**Decisions covered:** D-10-06 (PDO support), D-10-07 (length floor), D-10-08 (p95 cap), D-10-09 (default 0), D-10-10 (VALID_SOURCES extension), D-10-11 (correlated subquery), D-10-12 (other sources unchanged), D-10-20 (histogram smoke), D-10-22 (test command)
**Files modified:** `scripts/compute_scores.py`, `backend/tests/test_compute_scores_source.py`, `backend/tests/conftest.py` (smoke marker registration)
**Why Wave 2:** Imports constants from `scoring.py` (Plan 10-01). Independent of routing.py changes (Plan 10-03).
**Depends on:** 10-01.
**Tasks:**
1. Extend `VALID_SOURCES` tuple to include `"crash"`
2. Add `CRASH_UPDATE_SQL` (the WITH ... UPDATE pattern from Code Example 3)
3. Wire `--source crash` and `--source all` paths
4. Add empty-crash-records WARNING (mirrors Pitfall-7 mapillary precedent)
5. Register `smoke` pytest marker in `conftest.py:pytest_configure`
6. Add `test_crash_source_updates_crash_norm` integration test
7. Add `test_crash_norm_histogram_not_bimodal` smoke test (marked)
8. Add `test_help_lists_crash_source` subprocess test
9. Wave-0 step in plan body: re-ingest fixture before running integration tests

### Plan 10-03: /route Locked-Weights Swap + Deprecation Header + RouteRequest Extra-Ignore + GET /segments crash_norm + API Docs (Wave 3)
**Decisions covered:** D-10-13 (Pydantic extra='ignore'), D-10-14 (drop normalize_weights call), D-10-15 (Deprecation header), D-10-16 (identical-route guarantee), D-10-17 (GET /segments), D-10-18 (default 0.0), D-10-21 (existing tests pass), D-10-23 (API docs)
**Files modified:** `backend/app/models.py`, `backend/app/routes/routing.py`, `backend/app/routes/segments.py`, `backend/app/cache.py`, `backend/tests/test_models.py`, `backend/tests/test_route.py`, `backend/tests/test_segments.py`, new `docs/API.md`
**Why Wave 3:** Imports new `compute_segment_cost` signature from Plan 10-01; depends on `crash_norm` being populated (Plan 10-02) for end-to-end validation.
**Depends on:** 10-01, 10-02.
**Tasks:**
1. Add `model_config = ConfigDict(extra='ignore')` to `RouteRequest` in `models.py`; preserve Field defaults
2. Update `make_route_cache_key` in `cache.py` — drop `include_iri`, `include_potholes`, `weight_iri`, `weight_potholes` from signature
3. Update `routing.py`: add `response: Response` param, set `Deprecation` header at top of handler, drop `normalize_weights` call, switch to new `compute_segment_cost(t, iri, pot, crash_norm)`, extend SEGMENTS_BY_IDS_SQL to include `crash_norm`
4. Update `segments.py`: add `COALESCE(ss.crash_norm, 0)` to SQL + `crash_norm` to feature properties
5. Add 5 new tests in `test_route.py`: identical-route + Deprecation header on success/cache-hit/no-route + cache-key ignores weight fields
6. Add 2 new tests in `test_models.py`: `extra='ignore'` accepts unknown field, drops legacy weight_iri/weight_potholes from `model_dump()` if extra
7. Extend `test_segments.py` with `test_segments_includes_crash_norm`
8. Verify existing 6 v0.2.0 integration tests + Phase 8 perf tests pass unchanged
9. Create `docs/API.md` documenting silent-ignore behavior, locked weights, Deprecation header, REQ-ID hygiene cite to `d0ef452`
10. Add cross-link from `README.md` "API" section to `docs/API.md`

### Plan Dependency Graph

```
            ┌──────────────────────────────────────┐
            │  Plan 10-01 (Wave 1)                 │
            │  scoring.py constants + new compute  │
            │  + 8+ unit tests                      │
            └────────────┬─────────────────────────┘
                         │ imports W_IRI, W_POT,
                         │ W_CRASH, FATAL_WEIGHT,
                         │ INJURY_WEIGHT, PDO_WEIGHT,
                         │ FATAL_CAP, compute_segment_cost
                         ▼
            ┌──────────────────────────┬───────────────────────────┐
            │                          │                           │
            ▼                          ▼                           │
  ┌───────────────────────┐   ┌───────────────────────┐            │
  │  Plan 10-02 (Wave 2)  │   │  Plan 10-03 (Wave 3)  │            │
  │  compute_scores.py    │   │  routing.py + models  │            │
  │  --source crash       │   │  + segments.py        │            │
  │  + histogram smoke    │   │  + cache.py + docs    │◄───────────┘
  │  + 3 tests             │   │  + 8+ tests           │
  └───────────┬───────────┘   └───────────────────────┘
              │
              │ populates segment_scores.crash_norm
              │ (so 10-03's integration tests can
              │  observe non-zero values)
              ▼
            ┌──────────────────────────────────────┐
            │  Wave 3 gate: end-to-end POST /route │
            │  observes non-zero crash contribution │
            └──────────────────────────────────────┘
```

**Dependency notes:**
- **10-02 and 10-03 CAN run in parallel after 10-01 lands** — they touch disjoint files except for the shared import of `scoring.py` constants (already locked by 10-01).
- **10-03's end-to-end test** (test_identical_route + test_deprecation_header_on_success in test_route.py) uses MOCKED DB connections (per `test_route.py:_mock_segment_data`), so it does NOT require 10-02 to have run. It's safe to merge 10-03 as soon as 10-01 is in.
- **The Phase-10 verification gate** (running `pytest tests/ -m integration` against the live DB with non-zero crash_records) requires BOTH 10-02 and 10-03 to be merged — that's the purpose of Wave 3 as a synchronization point even though 10-02 and 10-03 are independently mergeable.

**No file_modified overlaps that force sequential execution within a wave.**

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python venv `/tmp/rq-venv` | All Python tests | ✓ | 3.12 (per project memory) | — |
| `psycopg2` | Live DB tests | ✓ | 2.9.11 (pinned) | — |
| `pytest` | All tests | ✓ | 8.x (existing in venv) | — |
| Live PostGIS at 127.0.0.1:5432 | Integration tests | ✓ | PostgreSQL 16.4 + PostGIS 3.4 | conftest auto-skips with `db_available` fixture if down |
| `road_segments_vertices_pgr` (built topology) | Phase 8 perf tests | ✓ | Built per Phase 8 | conftest `db_has_topology` auto-skips if missing |
| `crash_records` non-empty | Histogram smoke + `--source crash` integration | ✗ (currently 0 rows) | — | Re-run `scripts/ingest_crashes.py --source lacity --csv data/crashes_la/lacity_fixture.csv` (Wave 0 of Plan 10-02) |
| `data/crashes_la/lacity_fixture.csv` | Re-ingest step | ✓ | 205 rows, committed to git | — |
| `data_pipeline/lacity_socrata.py`, `lacity_mocodes.py`, `snap.py` | `ingest_crashes.py` | ✓ | Phase 9 complete | — |

**Missing dependencies with no fallback:**
- None.

**Missing dependencies with fallback:**
- `crash_records` rows: re-ingest fixture (5-second operation against local DB).

## Sources

### Primary (HIGH confidence)
- **Pydantic v2 ConfigDict docs** [VERIFIED via WebSearch 2026-05-08]: https://docs.pydantic.dev/latest/api/config/ — confirms `model_config = ConfigDict(extra='ignore')` is the v2-canonical pattern.
- **FastAPI Response Headers docs** [VERIFIED via WebSearch 2026-05-08]: https://fastapi.tiangolo.com/advanced/response-headers/ — confirms the `response: Response` parameter pattern preserves `response_model`.
- **PostgreSQL 16 PERCENTILE_CONT docs** [CITED]: https://www.postgresql.org/docs/16/functions-aggregate.html#FUNCTIONS-ORDEREDSET-TABLE — confirms ordered-set aggregate syntax.
- **PostgreSQL 16 UPDATE FROM docs** [CITED]: https://www.postgresql.org/docs/16/sql-update.html — confirms `UPDATE ... FROM (subquery) WHERE` pattern.
- **PostgreSQL 16 WITH queries (CTE) docs** [CITED]: https://www.postgresql.org/docs/16/queries-with.html — confirms single-reference non-modifying CTEs are inlined.
- **RFC 9745 Deprecation header** [CITED]: https://www.rfc-editor.org/rfc/rfc9745.html — informs Open Question A3 (locked-string is not RFC-compliant; documented for visibility).
- **Live DB probe** [VERIFIED 2026-05-08]: PostgreSQL 16.4, segment_scores 209,856 rows, crash_records 0 rows, length_m min 0.53m / avg 149m / max 6663m, 29,476 segments < 50m.
- **Existing project files** [VERIFIED via Read tool]: `backend/app/scoring.py` (35 lines), `backend/app/models.py` (39 lines), `backend/app/routes/routing.py` (486 lines), `backend/app/routes/segments.py` (60 lines), `scripts/compute_scores.py` (119 lines), `db/migrations/001_initial.sql`, `db/migrations/004_crash_records.sql`, `backend/tests/test_scoring.py`, `backend/tests/test_route.py`, `backend/tests/test_segments.py`, `backend/tests/test_compute_scores_source.py`, `backend/tests/test_routing_performance.py`, `backend/tests/conftest.py`, `app/cache.py`.
- **Phase 9 hand-off** [VERIFIED via Read tool]: `.planning/phases/09-crash-data-schema-la-city-ingest-naive-snap-match/09-VERIFICATION.md` confirms migration 004 applied, `crash_norm` column NOT NULL DEFAULT 0.0 in place.

### Secondary (MEDIUM confidence)
- **HSM KABCO and EPDO weighting** [WebSearch verified with FHWA docs]: https://safety.fhwa.dot.gov/hsip/resources/fhwasa09029/sec4.cfm — confirms KABCO scale and that weighted severity indices vary by jurisdiction. Does NOT directly cite an "8:3:1" routing-cost ratio (CONTEXT-locked, treated as user decision).
- **Crash-cost methodology** [WebSearch]: UDOT crash costs page documents EPDO; this is the "academic 100:10:1" anti-pattern Pitfall 5 references.

### Tertiary (LOW confidence)
- None — every load-bearing claim is either VERIFIED (live probe / read tool) or CITED (official docs).

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every library is already pinned and in use; no version risk.
- Architecture patterns: HIGH — every pattern verified against existing code or official docs (FastAPI, Pydantic v2, PostgreSQL).
- Pitfalls: HIGH — 4 of 7 are empirically verified against the live DB; remaining 3 are concrete code-path traces in already-read files.
- Numerical-tuning values (FATAL_CAP_K=3, histogram threshold 50%): MEDIUM — reasoned, not measured. Recalibration is cheap (one-line constant + recompute).

**Research date:** 2026-05-08
**Valid until:** 2026-06-07 (30 days — stack is stable, only the LA City data freeze impacts validity, and that's already documented as a known limitation per REQ-crash-ingest-lacity acceptance bullet).
