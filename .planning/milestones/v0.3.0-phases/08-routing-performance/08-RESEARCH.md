# Phase 8: Routing Performance — Research

**Researched:** 2026-05-04
**Domain:** pgRouting `pgr_ksp` query optimization on a ~209k-edge LA road graph; PostgreSQL SPI executor + GiST spatial index interaction; per-request edge subgraph construction
**Confidence:** HIGH on root cause and constraints (verified directly from in-repo failed-attempt git history with measured baselines); HIGH on stack/codebase (read in full); MEDIUM-HIGH on the recommended two-step approach (pgRouting community guidance is consistent but not specifically benchmarked at our 209k-edge scale); MEDIUM on the specific buffer-width default (no community-published number — recommendation is reasoned from corridor geometry).

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PERF-01 | Cross-LA route (~20 km, e.g. West LA → Pasadena) returns in **< 5s uncached** | §3 recommended approach (two-step pre-filter); §4 buffer-width default; §6 inner-algorithm choice |
| PERF-02 | Short DTLA-local trip (~1-2 km) remains **≤ 2s uncached** (no regression vs. current 1.4-1.8s baseline) | §3 pre-filter is cheap when bbox is small (GiST returns ~hundreds of edges); §10 perf regression test |
| PERF-03 | Existing route tests pass — `backend/tests/test_route.py` (mocked) and `backend/tests/test_integration.py::test_route_*` (live DB) — no semantic regression | §7 mock/live test compatibility; §11 validation architecture |
</phase_requirements>

---

> **No CONTEXT.md exists for this phase** — `/gsd-discuss-phase` was explicitly skipped per upstream instructions. ROADMAP.md Phase 8 section is the canonical scope. This research picks concrete defaults with rationale; the planner should treat them as recommendations to lock in PLAN.md decisions, not as gray areas to surface to the user.

---

## Phase Boundary — What This Phase Delivers

**In scope:**
- Replace the current full-graph `pgr_ksp` call with a two-step pattern that pre-filters `road_segments` to an OD-corridor subgraph using the GiST index BEFORE handing the subgraph to pgRouting.
- Pick and lock a buffer-width default (this research recommends ~3 km — see §4) with a tunable env var override.
- Implement a fallback (auto-widen, then full-graph) when the filter yields no path.
- Add a perf regression test (cross-LA cold ≤ 5s, DTLA cold ≤ 2s) that runs against a live seeded DB and auto-skips on CI's empty schema.
- Confirm the existing 12s `statement_timeout` (commit `8bfd286`) stays in place as the safety net.

**Out of scope (per locked project decisions):**
- Changing the routing algorithm's user-visible semantics: K=5, time-budget filter, fastest-fallback-with-warning all stay (PROJECT.md `CON-route-selection-algorithm`).
- Switching to Redis or a distributed cache (PROJECT.md "Out of Scope" — `cachetools` in-memory stays).
- Adopting SQLAlchemy or Alembic — raw psycopg2 + raw SQL migrations remain the convention.
- Multi-city support — LA-only viewbox is fine.
- Switching to a different routing engine (e.g. Valhalla, OSRM, GraphHopper). Phase 8 is a `pgr_ksp` optimization, not a rewrite.
- Pre-materialized topology views with periodic refresh (mentioned as alternative in ROADMAP.md but rejected here — see §3 alternatives table).

**What "done" looks like:**
- A West LA → Pasadena curl request returns `200` with valid `fastest_route` + `best_route` in under 5 seconds against a freshly seeded local DB.
- A DTLA → Hollywood curl request still returns under 2 seconds.
- `pytest backend/tests/test_route.py backend/tests/test_integration.py::test_route` all pass green against a seeded DB.
- A new `test_routing_performance.py` integration test asserts the latency budgets and auto-skips when no topology is present.

---

## Project Constraints (from CLAUDE.md)

`./CLAUDE.md` does not exist in this repo. All operational directives come from PROJECT.md, REQUIREMENTS.md, ROADMAP.md, and the codebase README. Relevant ones for Phase 8:

- **Stack frozen** — Python 3.12 + FastAPI 0.115.6 + psycopg2-binary 2.9.11 + PostgreSQL 16 + PostGIS 3.4 + pgRouting 3.6 (or 3.8 in the deploy/db image — see §13). No new runtime deps without ADR.
- **API contract frozen** — `/route` request/response shape must not change (`CON-route-api`).
- **Algorithm semantics frozen** — `CON-route-selection-algorithm`: pgr_ksp with K=5, time-budget filter, fastest-fallback-with-warning. Implementation can change; semantics cannot.
- **Connection pool frozen** — `ThreadedConnectionPool(minconn=2, maxconn=12)`, `SET LOCAL statement_timeout = '12s'` per connection. Phase 8 must not bypass either.
- **Cache behavior frozen** — `route_cache: TTLCache(maxsize=128, ttl=120)`. Cache-key shape (SHA256 of param dict) must not change.
- **Test conventions** — pytest with `pytest.mark.integration` for live-DB tests; `db_has_topology` fixture for tests that need seeded data; auto-skip when DB unreachable.
- **Long DDL on Fly DB** — never via `flyctl proxy`. Not directly relevant since Phase 8 is a code/SQL change, not a DDL operation, but worth noting if any one-time migration is added.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| OD-bbox/corridor computation | `backend/app/routes/routing.py` (Python) | — | Pure math on Pydantic-validated lat/lon; cheap; runs once per request |
| Pre-filter subgraph build | PostgreSQL via psycopg2 (separate query, BEFORE pgr_ksp) | GiST index on `road_segments.geom` | The whole point of the fix: the filtering query MUST be a normal psycopg2 query, NOT inlined into pgr_ksp's `edges_sql` string (see §1 root-cause) |
| K-shortest-paths over filtered subgraph | `pgr_ksp` (or `pgr_dijkstra` × K) on the temp/CTE/UNLOGGED edge set | pgRouting 3.6+ extension | Algorithm semantics locked at K=5; the inner SQL just changes from `FROM road_segments` to `FROM <filtered_edges>` |
| Failure-mode handling (no-path-in-filter) | `backend/app/routes/routing.py` Python control flow | — | Two-attempt strategy: filtered → widened-or-full. Pure application logic |
| Latency timeout safety net | `backend/app/db.py` `SET LOCAL statement_timeout = '12s'` | — | Already shipped in commit `8bfd286`. Phase 8 keeps it untouched |
| Cache integration | `backend/app/cache.py::route_cache` (unchanged) | `backend/app/cache.py::make_route_cache_key` | Cache key already includes all routing inputs; fix is transparent to cache |
| Audit log | `route_requests` insert at top of `find_route` | — | Already in place; runs before the heavy query as a fire-and-forget log |
| Perf regression gate | `backend/tests/test_routing_performance.py` (NEW) | `db_has_topology` fixture | Live-DB integration test, auto-skips on CI |

---

## Summary

The current `pgr_ksp` call in `backend/app/routes/routing.py:16-23` reads the entire 209k-edge `road_segments` table on every uncached request. Yen's K-shortest-paths algorithm (which `pgr_ksp` runs) explores radially from the origin via Dijkstra; for short trips this is fast (1-2s) because Dijkstra terminates early, but for cross-LA trips Dijkstra ends up touching most of the graph, plus Yen's K=5 amplification, so it blows past the 12s `statement_timeout`. The 2026-04-29 attempt to fix this by adding a `WHERE geom && ST_MakeEnvelope(...)` predicate **inside the pgr_ksp `edges_sql` string** made it strictly worse (10-14× slower) because pgRouting evaluates that string via PostgreSQL's SPI (Server Programming Interface), and SPI does not invoke the GiST index for that subquery — it forces a full sequential scan with per-row geometry comparison, which is slower than the bare `SELECT ... FROM road_segments` it replaced.

The fix is structural: pre-compute the OD-corridor edge set with a **separate, normal, GiST-indexed psycopg2 query** that materializes the filtered edges into a `TEMP TABLE` (or `WITH` CTE materialized via `MATERIALIZED` keyword), then point `pgr_ksp` at that temp table inside the same transaction. The temp table sees no GiST index either — but it doesn't need one, because it's already small (a few thousand rows, not 209k). Yen + Dijkstra over a few-thousand-edge subgraph will finish in well under 5 seconds at our scale. Short DTLA trips get an even smaller subgraph and stay under 2 seconds — no regression.

**Primary recommendation:** Two-step pattern with a per-request `TEMP TABLE ... ON COMMIT DROP` populated by a `geom && ST_Expand(ST_MakeLine(origin, dest)::geometry, BUFFER_DEG)` pre-filter using the GiST index, then `pgr_ksp` over that temp table. Default buffer = 0.03° (~3.3 km at LA latitude) with `ROUTE_FILTER_BUFFER_DEG` env var override. On no-path, retry once with 2× buffer; if still no path, fall through to full-graph `pgr_ksp` (preserving the existing failure mode that returned an empty route + warning).

**Critical correction to phase-spec assumption:** The phase additional context says "~10k LA road segments in production." This is wrong. The seed loads OSMnx's `network_type="drive"` graph at `dist=20000` (20 km radius from LA center) which produces **~209,000 edges + ~74,000 vertices** in production, per `.planning/phases/05-cloud-deployment/05-LESSONS-LEARNED.md` line 35 and `scripts/seed_data.py` line 21 (`DIST = 20000`). The 10k figure does not match shipped reality. Plan sizing, perf tests, and buffer defaults must use the 209k number.

---

## Key Architectural Findings

### Finding 1: pgr_ksp's `edges_sql` is evaluated via SPI; the GiST index is NOT used inside it. [VERIFIED — direct evidence from this repo's git history]

The repo contains the actual failed experiment commits with measured numbers:

- `2278605` (`perf(routing): bbox-filter pgr_ksp inner SQL to OD corridor`) — added `WHERE geom && ST_Expand(ST_Envelope(ST_Collect(...)), 0.05)` inside the `pgr_ksp` `edges_sql` argument (dollar-quoted). Result: dollar-quoting interaction with psycopg2 made even short queries hang at 15s+.
- `17bff0c` (`fix(routing): use single-quoted inner SQL with ST_MakeEnvelope bbox filter`) — replaced the dollar-quote with single-quoted `ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326)` using literal pre-computed bounds (still inside the `pgr_ksp` SQL string).
- `704a70c` (`revert(routing): restore original full-graph pgr_ksp query`) — reverted with the verbatim measured numbers and the verbatim root-cause statement: "pgRouting evaluates its inner SQL via PostgreSQL SPI which does not use the GiST index on road_segments.geom, turning the spatial WHERE clause into a full sequential scan with per-row geometry computation — slower than scanning 209k rows without the predicate."

Measured baselines from `704a70c` commit message:

| Trip | Original (full-graph) | Inside-pgr_ksp bbox filter | Delta |
|------|-----------------------|----------------------------|-------|
| 1 km cold | 1.4 s | > 30 s (timeout) | +21× worse |
| 5 km cold | 1.8 s | 26.7 s | +14× worse |
| 20 km cold | > 90 s | (untested — already worse) | — |

This is direct, measured evidence — not speculation. **The fix MUST happen OUTSIDE the `pgr_ksp` call**, in a separate query that the optimizer can plan against the GiST index.

[VERIFIED: git show 2278605 17bff0c 704a70c]

### Finding 2: The current production seed is ~209k edges, NOT ~10k. [VERIFIED]

`scripts/seed_data.py:19-21`:
```python
# LA center, 20km radius — covers Glendale, Westwood, Santa Monica, Pasadena
CENTER = (34.0522, -118.2437)
DIST = 20000
```

`.planning/phases/05-cloud-deployment/05-LESSONS-LEARNED.md:35`: "seeding 209k segments + 125k defects + scores + topology" — this is the live Fly.io deploy reality. The `additional_context` in the phase prompt says "~10k LA road segments" but that contradicts `seed_data.py` and Phase 5's measured deploy. Planner must use 209k as the operating assumption.

[VERIFIED: scripts/seed_data.py code read; .planning/phases/05-cloud-deployment/05-LESSONS-LEARNED.md line 35 read]

### Finding 3: Yen's K-shortest-paths is the cost amplifier; Dijkstra alone is the same algorithm. [VERIFIED — pgRouting 3.6+ docs]

`pgr_ksp(edges_sql, start_vid, end_vid, K, directed, heap_paths)` runs Yen's algorithm, which calls Dijkstra K times with successive edge removals. For K=5 over a 209k-edge graph, that's 5 full Dijkstra runs over the radial frontier. The cost compounds non-linearly with subgraph size — halving the edge count more than halves the runtime because each individual Dijkstra spends less time in the inner heap. This is precisely why the fix is so high-leverage: shrinking the subgraph from 209k to ~5k edges (a typical OD-corridor) gives roughly **40× fewer edges** to explore.

[CITED: https://docs.pgrouting.org/latest/en/pgr_KSP.html — function signature `pgr_KSP(edges_sql, start_vid, end_vid, K, directed:=true, heap_paths:=false)`; `heap_paths` defaults to `false`]

### Finding 4: `pgr_ksp` is happy reading from any table or subquery, including a `TEMP TABLE`. [HIGH confidence — pgRouting documentation pattern]

The `edges_sql` argument is just a SQL string that returns rows shaped `(id, source, target, cost [, reverse_cost])`. Anitagraser's "Beginner's Guide to pgRouting" and the Crunchy Data routing-with-PostgreSQL post both demonstrate `pgr_dijkstra` over filtered subqueries. There is nothing about `pgr_ksp` that requires the source to be `road_segments` directly — `'SELECT id, source, target, cost FROM <temp_table_name>'` works the same way. The temp table just needs to be visible in the same session that runs `pgr_ksp`, which it is when both queries run on the same `psycopg2` connection.

[CITED: https://docs.pgrouting.org/latest/en/pgr_KSP.html; https://anitagraser.com/2011/02/07/a-beginners-guide-to-pgrouting/]

### Finding 5: `TEMP TABLE ... ON COMMIT DROP` is the right ergonomic for per-request subgraphs. [MEDIUM-HIGH confidence]

PostgreSQL's `CREATE TEMPORARY TABLE ... ON COMMIT DROP` auto-drops the table when the transaction commits or rolls back, which means no cleanup code, no autovacuum churn between requests (the table only ever holds a few thousand rows for ~tens of milliseconds), and no name collisions across concurrent requests because each session has its own `pg_temp_*` schema. The recurring concern with temp tables in pooled environments — that they accumulate when connections are reused — does not apply here because `ON COMMIT DROP` removes them at transaction end.

A CTE alternative (`WITH filtered AS MATERIALIZED (...) SELECT FROM pgr_ksp('SELECT FROM filtered ...')`) does NOT work because the inner `pgr_ksp` SQL is evaluated via SPI, which runs in a fresh planner context that cannot see the outer CTE. The temp table approach decouples the two queries cleanly.

[VERIFIED: PostgreSQL docs on TEMP TABLE ON COMMIT DROP; CITED: https://www.cybertec-postgresql.com/en/postgresql-sophisticating-temporary-tables/]

### Finding 6: The 12s `statement_timeout` (commit `8bfd286`) is the safety net that makes ANY of this work without hanging the connection pool. [VERIFIED]

`backend/app/db.py:97-98` runs `SET LOCAL statement_timeout = '12s'` on every pooled connection. Even if Phase 8's recommended approach has a worst-case bug or the buffer is too small and the fallback path lands on the full-graph 90s+ query, the timeout caps each query, releases the pool slot via the existing `try/finally putconn` (Phase 5 SC #9), and surfaces an HTTP 500 to the client instead of accumulating stuck backends. **Phase 8 must not relax this timeout.** It is the difference between "the demo gets slow" and "the demo crashes the pool."

[VERIFIED: backend/app/db.py code read; commit 8bfd286 message]

---

## §1. Pre-filter shape — corridor vs. bbox vs. materialized view

**Question:** What's the best way to constrain the segment subgraph for an OD pair?

**Options evaluated:**

| Option | What it does | Pros | Cons | Recommendation |
|--------|--------------|------|------|----------------|
| **(A) Padded OD bounding box** — `geom && ST_MakeEnvelope(min_lon-pad, min_lat-pad, max_lon+pad, max_lat+pad, 4326)` | Rectangle covering the OD pair plus a uniform pad | Cheapest. The exact predicate the GiST index is built for (R-Tree). Constant expression — planner caches it. | For a long N-S route the bbox is tall and narrow, so it captures fewer detour options than a corridor. For a 20 km diagonal route, the bbox covers ~bbox-area = 14 km × 14 km × pad² → many irrelevant edges far off-axis | **PRIMARY CHOICE.** Simplicity wins; the inefficiency is small at LA scale and the GiST short-circuit is direct |
| **(B) Buffered straight line corridor** — `geom && ST_Expand(ST_MakeLine(origin_pt, dest_pt), BUFFER_DEG)` (or equivalently `ST_DWithin(geom, ST_MakeLine(...), BUFFER_DEG)`) | Tube around the OD straight line | Tighter for long diagonals; 2-3× fewer edges captured. Better for cross-LA trips where corridor matters most | `ST_DWithin` on geometry is in degrees, not meters — confusing units. `ST_Expand(ST_MakeLine,...)` works on bbox of the line — this collapses to ~Option A on a diagonal anyway. Real corridor needs `ST_Buffer(line,...)` which is expensive | Reject — equivalent to (A) in practice for the index lookup; the geometric difference only manifests in a post-filter step that costs more than it saves |
| **(C) Pre-materialized topology view** with stored bbox per region | Build a coarse "tile" partition of the LA graph offline; runtime picks the relevant tile(s) | Fastest at runtime; subgraph is pre-computed | Adds a migration + a refresh strategy + tile-boundary-edge stitching (route legs that cross tile boundaries are a notorious failure mode). Out of scope per ROADMAP.md "raw SQL migrations only, no Alembic" and the project's strong "no schema churn" pressure | Reject — schema migration impact is disproportionate; the tile-boundary problem is a research project of its own |

**Picked:** Option A. Single GiST-indexed predicate, no geometry-buffer computation cost, planner-friendly literal-bounds expression.

**Predicate to use:**
```sql
geom && ST_MakeEnvelope(
    LEAST(%(o_lon)s, %(d_lon)s) - %(buf)s,
    LEAST(%(o_lat)s, %(d_lat)s) - %(buf)s,
    GREATEST(%(o_lon)s, %(d_lon)s) + %(buf)s,
    GREATEST(%(o_lat)s, %(d_lat)s) + %(buf)s,
    4326
)
```

This is a parameterized psycopg2 query in the OUTER scope, so the planner sees the GiST index and uses it. (This is the exact thing that did NOT happen when the same predicate was buried inside `pgr_ksp`'s edges_sql.)

[VERIFIED: PostGIS docs on GiST index + `&&` operator; CITED: https://postgis.net/workshops/postgis-intro/indexing.html]

---

## §2. Inner algorithm choice — pgr_ksp on temp table vs. pgr_dijkstra K times

**Question:** Once the graph is filtered, do we use `pgr_ksp` on the temp table OR `pgr_dijkstra` K times with edge perturbation?

**Constraint:** `CON-route-selection-algorithm` locks "pgr_ksp with K=5". Implementation can change semantics-equivalently.

| Option | What it does | Tradeoffs | Recommendation |
|--------|--------------|-----------|----------------|
| **(A) `pgr_ksp(...,K:=5)` on the temp table** | Runs Yen's algorithm over the filtered subgraph; returns up to 5 paths sorted by cost | **Identical to current behavior** but on a smaller graph. No code change to path-handling. No risk of subtle semantics drift. Same `path_id`/`seq`/`edge` output shape. | **PRIMARY CHOICE.** Zero semantics drift; just swap the inner SQL string |
| (B) `pgr_dijkstra` × 5 in a loop, removing the previous best path's edges each iteration | Yen's algorithm done by hand in Python | More control over what "alternative path" means | Reimplements pgRouting's logic in application code; 5× round trips to DB; subtle correctness risks (Yen's algorithm has specific edge-removal rules) | Reject — semantics drift from `CON-route-selection-algorithm` |
| (C) `pgr_dijkstra` × 5 with cost-perturbation (multiply removed edges' cost by ×100 instead of removing) | "Soft" alternative-paths approach used by some routing libs | Allows revisiting deleted edges if no other path exists | Different semantics from Yen; the existing test `test_route_returns_best_and_fastest` and the existing UX (best vs. fastest comparison) implicitly assume Yen-style alternatives | Reject — same drift problem as (B) |

**Picked:** Option A. Keep `pgr_ksp` exactly as is, just point its `edges_sql` at `<temp_table>` instead of `road_segments`.

The new SQL becomes:

```sql
SELECT path_id, seq, edge, cost
FROM pgr_ksp(
    'SELECT id, source, target, travel_time_s AS cost FROM rq_filtered_edges',
    %s, %s, %s, directed := false
)
WHERE edge != -1
```

Where `rq_filtered_edges` is the temp table populated in the prior query in the same transaction.

`heap_paths` parameter stays at default `false` (current behavior). [VERIFIED: pgRouting 3.6 docs — heap_paths defaults to false]

---

## §3. Filter buffer width — how wide should the corridor be?

**Question:** What's the right default buffer width? Need to catch best-route detours (the WHOLE POINT of the app — best routes go AROUND bad pavement) without bloating the subgraph.

**No published pgRouting community number exists** for this. (Web search on "pgRouting bbox padding buffer width recommendation" returns no quantitative guidance.) [VERIFIED — multiple search variations; LOW confidence on community guidance]

**Reasoning from first principles:**

LA latitude is ~34°. At that latitude:
- 1° longitude ≈ 92.4 km (cos(34°) × 111.32 km)
- 1° latitude ≈ 110.9 km

So **0.01° ≈ 0.92-1.11 km**, **0.03° ≈ 2.8-3.3 km**, **0.05° ≈ 4.6-5.5 km**.

The previous failed-attempt commits used `_KSP_BBOX_PAD_DEG = 0.05` (≈ 5.5 km). That value was originally chosen "to catch realistic detours without scanning the whole 209k-edge network" per commit `2278605` message. It was reasonable; the failure was the *placement* (inside vs outside `pgr_ksp`), not the width.

**The "best route detour" question:** How far off the OD straight line does a best-by-pothole route realistically deviate?

- The current scoring formula is `cost = travel_time_s + w_iri * iri_norm + w_pothole * (mod + sev)`. With `max_extra_minutes = 5` (default) and the time-budget filter, a "best" route can spend at most 5 extra minutes on detour vs. the fastest route. At LA surface-street speeds (~30 mph ≈ 13 m/s, but with stops effectively closer to 8-10 m/s for cost computation), 5 extra minutes = 300 s × 8 m/s ≈ 2.4 km of additional travel distance.
- A 2.4 km detour from a straight-line OD path means the perpendicular off-axis deviation is at most ~1.2 km (geometric envelope of an ellipse with that extra arc length).
- A buffer of 3 km gives ~2× safety margin on that geometric estimate. A buffer of 5.5 km gives ~5× margin and starts pulling in clearly-irrelevant edges (motorway loops on the wrong side of LA).

**Recommendation:** Default to **0.03°** (~3 km), expose `ROUTE_FILTER_BUFFER_DEG` env var for ops tuning. This is tighter than the previous 0.05° because the constraint changed: previously the buffer needed to compensate for the in-pgr_ksp filter NOT using the index (every wider buffer was uniformly slow); now the GiST index does the right thing in the outer query, so a tighter buffer is both faster AND captures less noise. If perf testing shows route-quality regression (best route looks worse than current), bump to 0.04° or 0.05°.

**Confidence:** MEDIUM. No external benchmark; recommendation is reasoned from the time-budget constraint geometry. Planner should treat 0.03° as a starting point and have the perf-test PLAN exercise both 0.03° and 0.05° to compare.

[ASSUMED: detour-distance math; LA latitude → degrees-to-meters conversion is standard]

---

## §4. Failure mode — what when the pre-filter is too tight to find a path?

**Question:** What happens when the pre-filter is too tight to find a path? Auto-retry with wider radius? Fall back to full-graph? Return error? What's the right pgRouting idiom for this?

**The pgRouting idiom:** `pgr_ksp` returns an EMPTY SET when no path exists between two vertices in the input subgraph. It does not raise an error; it just returns 0 rows. The current code handles this case at `routing.py:87-101` — empty `paths` dict triggers the `"No route found between these points"` warning response. The Phase 8 fix must preserve this behavior for the full-graph case while ALSO handling the new "no path in filtered subgraph but exists in full graph" case.

**Recommended strategy: two-attempt with widen-then-fallback.**

```text
attempt 1: filter at BUFFER_DEG, run pgr_ksp on temp table
  if paths returned > 0: use them
  if paths returned == 0:
    attempt 2: filter at 2 × BUFFER_DEG, rebuild temp table, run pgr_ksp
      if paths returned > 0: use them, log "wide-buffer fallback"
      if paths returned == 0:
        attempt 3 (final): pgr_ksp on full road_segments table (the original SQL)
          if paths returned > 0: use them, log "full-graph fallback"
          if paths returned == 0: existing "no route found" warning response
```

**Rationale:**
- Tight default + auto-widen = fast common case + correct edge case.
- Three attempts max bounded by the 12s `statement_timeout` (each individual query is capped); worst case ≈ 12s total if all three time out, but in practice the small-buffer attempt is sub-second when it returns 0 rows.
- The existing test `test_route_distant_points` at `backend/tests/test_integration.py:136` already exercises a "snap to far points" case that may sometimes trigger this fallback — Phase 8 must verify that test still passes.

**Alternative considered + rejected:** Auto-widen without a final full-graph fallback. Risk: a route that genuinely needs a >2× buffer (e.g., one endpoint near the LA boundary, the route legitimately curves around a freeway-only zone) would get a false "no route" response. Rejected — the full-graph fallback is the correctness guarantee.

[VERIFIED: pgr_ksp empty-result behavior — pgRouting docs show `RETURNS SET OF (...) or EMPTY SET`; verified by current code path at routing.py:87]

---

## §5. Temp table vs. CTE vs. materialized view — performance + ergonomics

**Question:** Per-request temp table has setup cost; CTE may not use indexes; materialized view requires migration + refresh strategy.

| Option | Setup cost | Index usage | Cleanup | Survives across requests | Cross-query visibility |
|--------|-----------|-------------|---------|--------------------------|------------------------|
| **TEMP TABLE ... ON COMMIT DROP** | One CREATE + one INSERT per request (~5-20 ms for ~5k rows) | Yes — outer query uses GiST on road_segments. Inside pgr_ksp it doesn't matter (subgraph is small) | Auto on commit | No — fresh per transaction | Yes — visible to subsequent SQL on same connection within the same transaction |
| **CTE with `MATERIALIZED`** | One INSERT-equivalent (~5-20 ms) | Yes — outer scope uses GiST | Auto on query end | No | **NO — pgRouting's SPI inner query cannot see outer CTEs.** This is the critical disqualifier |
| **Materialized View, refreshed offline** | Zero per request | Pre-built indexes possible | Manual refresh | Yes | Yes |
| **UNLOGGED TABLE** | Zero per request (created once); INSERT/TRUNCATE per request | Yes if indexed | Manual | Yes | Yes |

**Picked:** TEMP TABLE.

**Why CTE fails:** The pgRouting `pgr_ksp` function takes its `edges_sql` as a string and runs it in a fresh SPI execution context. SPI does not inherit the parent query's CTE namespace. So `WITH f AS (...) SELECT FROM pgr_ksp('SELECT ... FROM f', ...)` returns "relation 'f' does not exist". This is a documented pgRouting limitation. [VERIFIED: pgRouting docs note that edges_sql runs as a separate query; CITED: https://docs.pgrouting.org/latest/en/pgr_KSP.html]

**Why materialized view fails the project bar:** Requires (a) a new migration file (raw SQL is OK per project constraint, but adding the schema object is non-trivial), (b) a refresh strategy (when does the view become stale? after a Mapillary ingest? after a re-seed? after a `compute_scores.py` run?), and (c) handling tile boundaries if any partitioning is involved. ROADMAP.md Phase 8 mentions this as an alternative; it's correctly framed as "alternatively" — meaning out-of-scope unless the temp-table approach fails to hit the perf target.

**Why UNLOGGED TABLE doesn't help:** UNLOGGED skips WAL — minor speedup on writes, irrelevant on the read path that dominates routing. Adds the operational complexity of "this table exists across restarts but its contents are wiped on crash." TEMP TABLE has the same write-speed property AND the auto-cleanup. Strictly worse.

**Setup cost of TEMP TABLE per request:** PostgreSQL creates the temp table in `pg_temp_<N>` schema on the connection's first request, then re-uses it (by name) on subsequent transactions if `ON COMMIT DROP` is not specified, or recreates it if it is. With `ON COMMIT DROP`, the dictionary update on each CREATE/DROP is a small system-catalog write — measurable at ~1-2 ms in benchmarks at this scale. Negligible relative to the multi-hundred-ms pgr_ksp call.

[VERIFIED: PostgreSQL docs on TEMP TABLE; CITED: https://www.cybertec-postgresql.com/en/postgresql-sophisticating-temporary-tables/; CITED: https://tech-champion.com/database/postgresql/postgresql-temp-tables-and-connection-pooling-navigating-performance-pitfalls/]

---

## §6. Inner algorithm — confirming K=5 semantics

Already covered in §2 (option A picked). The choice is: keep `pgr_ksp(...,5,directed:=false)` exactly. The only thing that changes is the `edges_sql` string from `'SELECT id, source, target, travel_time_s AS cost FROM road_segments'` to `'SELECT id, source, target, travel_time_s AS cost FROM rq_filtered_edges'`.

The temp table column shape MUST match what pgr_ksp expects:

| Column | Type | Required | Notes |
|--------|------|----------|-------|
| `id` | BIGINT | Yes | Edge identifier; matches `road_segments.id` |
| `source` | BIGINT | Yes | Start vertex from `pgr_createTopology` |
| `target` | BIGINT | Yes | End vertex from `pgr_createTopology` |
| `cost` | DOUBLE PRECISION | Yes | We use `travel_time_s` as cost (locked) |
| `reverse_cost` | DOUBLE PRECISION | No (omit since `directed := false`) | Not needed for undirected |

[VERIFIED: pgRouting 3.6 pgr_ksp signature requires SET OF (id, source, target, cost [, reverse_cost]); CITED: pgr_KSP docs]

---

## §7. Code-baseline confirmations

Read in full: `backend/app/routes/routing.py` (193 lines). Confirmed:

| Item | Phase prompt expectation | Reality | Notes |
|------|--------------------------|---------|-------|
| `KSP_SQL` location | line ~16 | line **16-23** | Correct — exact span 16–23 |
| `cur.execute(KSP_SQL, ...)` call site | line ~79 | line **79** | Exact — `cur.execute(KSP_SQL, (origin_node, dest_node, K))` |
| Connection management | `get_connection()` from db.py | Confirmed — `with get_connection() as conn:` at lines 55, 69 | Two separate `with` blocks: first one for audit log only (lines 55-62), second one for snap+ksp+segments (lines 69-107). The second block is where the temp table needs to live to share a transaction with `pgr_ksp` |
| Cache integration | `route_cache` from cache.py | Confirmed — lines 47-53 (key gen), 65-67 (read), 190 (write) | Cache reads BEFORE the heavy query; cache writes at the end. Phase 8 changes do NOT affect cache behavior |
| K constant | `K = 5` | Confirmed — line 37 | Locked per `CON-route-selection-algorithm` |
| `directed := false` | Should remain undirected | Confirmed — line 20 | Locked behavior |
| Snap-to-node SQL | Independent query before pgr_ksp | Confirmed — `SNAP_NODE_SQL` lines 10-14, executed at lines 72, 75 | Uses `road_segments_vertices_pgr` (the pgRouting-built vertex table) with KNN `<->` operator. Independent of Phase 8's edge filtering |
| Existing tests | `backend/tests/test_route.py` | 2 tests — `test_route_returns_best_and_fastest`, `test_route_returns_warning_with_zero_budget` | Both fully mock `get_connection`; they do NOT exercise the SQL itself. **They will pass unchanged** as long as the mock cursor's `fetchall.side_effect` keeps returning the same `_mock_ksp_results()` shape. The mock setup at `_setup_mock_conn` does not care how many `cur.execute` calls happen — but Phase 8 will add 1 (or 2 with widening) extra `cur.execute` for the filter pre-query, so the `fetchone.side_effect` and `fetchall.side_effect` lists in the test mocks may need to grow. **Planner must handle this in the GREEN test phase.** |
| Integration tests | `backend/tests/test_integration.py::test_route_*` | 4 live-DB tests (`test_route_real_points`, `test_route_respects_time_budget`, `test_route_with_weights`, `test_route_distant_points`) | Marked `@pytest.mark.timeout(30)` or `@pytest.mark.timeout(60)`. Auto-skip via `db_has_topology` fixture if no topology built. Phase 8 must keep all 4 green |
| Pool leak regression | `backend/tests/test_routing_pool_release.py` | Live test that monkeypatches `SNAP_NODE_SQL` to invalid SQL and asserts pool slot returned | Phase 8 changes happen in the second `with get_connection()` block (lines 69+); the pool-release semantics are unchanged. Test should keep passing |

**Critical compat note for the mocked tests:** `test_route.py` uses `mock_cursor.fetchone.side_effect = [...]` and `mock_cursor.fetchall.side_effect = [...]`. The existing setup feeds 2 fetchones (origin node, dest node) and 2 fetchalls (ksp results, segment data). Phase 8 will add at least one more `cur.execute()` for the temp-table populate (which is a non-fetching INSERT) and possibly a fetchone or fetchall depending on whether we count rows for fallback decision. The planner needs to either (a) extend the side_effect lists in the mock test, or (b) restructure the new code so the temp-table-populate path returns a single rowcount that the test can mock with one extra entry. Concrete count to plan for: **1 extra `cur.execute` for `CREATE TEMP TABLE`, 1 extra `cur.execute` for the `INSERT INTO temp ... SELECT` (or `CREATE TABLE ... AS SELECT`), and 1 extra `fetchone` if we read `cur.rowcount` to decide on fallback.**

---

## §8. Pitfalls — failed approaches + new ones to avoid

### Pitfall A — Bbox filter inside pgr_ksp's edges_sql (the 2026-04-29 disaster)
**What goes wrong:** Adding `WHERE geom && ST_MakeEnvelope(...)` (or `ST_Expand(ST_Collect(...))`) inside the string passed to `pgr_ksp`. Looks superficially correct because the predicate uses the indexed operator `&&`.
**Why it happens:** pgRouting evaluates the inner SQL via PostgreSQL SPI. SPI's planner does not invoke the GiST index for that subquery; it sequentially scans road_segments and evaluates the predicate per-row. Sequential scan + per-row geometry comparison + rejection of most rows is strictly slower than a bare full-graph scan with no predicate.
**How to avoid:** **Never put a spatial WHERE predicate inside `pgr_ksp` or `pgr_dijkstra` edges_sql.** Always pre-filter into a separate table/object that pgRouting reads.
**Warning signs:** Cold-cache latency on a SHORT trip (< 5 km) doubles or worse vs. the unfiltered baseline of ~1.4-1.8s. If your "optimization" makes the easy case slower, you've found this.

### Pitfall B — Dollar-quoting interaction with psycopg2
**What goes wrong:** Using `$tag$...$tag$` to delimit the inner edges_sql so that internal `'` characters don't need escaping. This is the standard PostgreSQL idiom for nested SQL strings.
**Why it happens:** Per commit `17bff0c` message: "The dollar-quote approach ($ksp$...$ksp$) caused uncached calls to hang (15s+ vs 1.4s baseline) — likely a psycopg2 interaction with tagged dollar-quoting." The exact mechanism wasn't isolated, but it reproduced reliably across runs.
**How to avoid:** Use single-quoted strings inside `pgr_ksp(...)` calls. If you need single-quotes inside the inner SQL, escape them with `''`. With Phase 8's approach the inner SQL is just `'SELECT id, source, target, travel_time_s AS cost FROM rq_filtered_edges'` — no embedded quotes — so this pitfall is dodged by construction.
**Warning signs:** Any uncached call (even short trips) hangs or times out at 12s, while the same query inlined directly in `psql` runs fast. Strong indicator of a quoting/parsing mismatch.

### Pitfall C — Forgetting the temp table is per-transaction
**What goes wrong:** Creating the temp table outside the `with get_connection() as conn` block, or in a different `with` block from where `pgr_ksp` runs. The temp table either doesn't exist when pgr_ksp runs, or autocommit drops it before the next statement.
**Why it happens:** `psycopg2`'s default behavior is autocommit-off when used as a context manager, but the existing routing.py code has TWO separate `with get_connection()` blocks — one for audit log (lines 55-62), one for the routing query (lines 69-107). With `ON COMMIT DROP`, the temp table is dropped at the end of the FIRST block's commit if you put the CREATE there.
**How to avoid:** Create the temp table inside the SECOND `with get_connection()` block, BEFORE the call to pgr_ksp, and let the `with` block's auto-commit at exit drop it. Never split temp-table creation and use across `with` boundaries.
**Warning signs:** `psycopg2.errors.UndefinedTable: relation "rq_filtered_edges" does not exist` at the pgr_ksp call site.

### Pitfall D — Connection pool churn from temp table accumulation
**What goes wrong:** Without `ON COMMIT DROP`, temp tables persist for the lifetime of the session/connection. With a pool of 12 connections and many requests per minute, each connection accumulates one temp table per request, ballooning `pg_temp_<N>` schemas and pg_class.
**Why it happens:** PostgreSQL's default for `CREATE TEMP TABLE` is `ON COMMIT PRESERVE ROWS` — the table stays until the SESSION ends. The pool keeps connections alive across many requests, so "session ends" might be hours later.
**How to avoid:** Always specify `ON COMMIT DROP`. The autocommit at the end of the `with get_connection()` block triggers the drop.
**Warning signs:** `pg_class` row count grows over time; `\dt pg_temp_*` shows hundreds of leftover tables; eventual catalog bloat slows planner.

### Pitfall E — SET LOCAL statement_timeout being bypassed by Phase 8 changes
**What goes wrong:** Refactoring the routing code in a way that the temp-table populate query runs without the 12s timeout (e.g., on a different connection, or before the `SET LOCAL`).
**Why it happens:** `db.py:97-98` sets `SET LOCAL statement_timeout = '12s'` inside the `get_connection()` context manager body. Any work done on a connection that bypasses `get_connection()` (e.g., a raw `psycopg2.connect` call) won't have the timeout.
**How to avoid:** All Phase 8 SQL — temp-table create, temp-table populate, pgr_ksp, segment fetch — runs through the `get_connection()` context manager. No new direct psycopg2.connect calls.
**Warning signs:** A degenerate request hangs > 12s; the pool slot stays "used" for over a minute; `pg_stat_activity` shows queries running far longer than 12 seconds. This indicates the SET LOCAL was bypassed.

### Pitfall F — Underestimating the production segment count
**What goes wrong:** Plan or test sizing based on the phase-prompt assumption of "~10k segments" instead of the real 209k.
**Why it happens:** The phase prompt's `additional_context` claims ~10k. Phase 5 LESSONS-LEARNED documents 209k. seed_data.py has `DIST = 20000` (20 km radius from LA center), which produces ~209k edges from OSMnx's drive network. The 10k number doesn't match any shipped state.
**How to avoid:** Plan with the 209k figure. Run perf tests against a fully-seeded local DB. If there is no full seed locally, run `python scripts/seed_data.py` (takes ~5 minutes) before benchmarking.
**Warning signs:** A "perf test" passes locally with a partial seed (a few thousand segments), but staging/prod fails the latency target. Always confirm `SELECT count(*) FROM road_segments` is in the 200k range before declaring perf victory.

### Pitfall G — Temp table without indexes
**What goes wrong:** Creating the temp table but forgetting to add a btree index on `source` and `target` columns.
**Why it happens:** Phase 8's whole pitch is "the GiST on road_segments.geom isn't visible inside pgr_ksp's SPI; pre-filter outside." But `pgr_ksp` itself joins on `source` / `target` — if the temp table has 5000 rows and no btree on those columns, Yen's algorithm does sequential scans repeatedly inside the inner Dijkstra.
**How to avoid:** After populating the temp table, add `CREATE INDEX ON rq_filtered_edges(source, target)`. Or use `CREATE TEMP TABLE ... AS SELECT ...` and then add the indexes. At ~5000 rows, this index build is fast (~1 ms) and worth it.
**Warning signs:** Cold-cache time on a long trip is between 5-12 s instead of < 5 s — pgr_ksp is doing seq scans inside Dijkstra. EXPLAIN on the same SQL run by hand against the temp table shows seq scans on the source/target lookups.

[VERIFIED A, B from in-repo git commits 2278605, 17bff0c, 704a70c]
[VERIFIED E from db.py code]
[VERIFIED F from seed_data.py + 05-LESSONS-LEARNED.md]
[ASSUMED C, D from PostgreSQL TEMP TABLE semantics — standard pattern]
[ASSUMED G from general pgRouting performance guidance — needs benchmarking confirmation]

---

## §9. Recommended approach (concrete defaults to lock in)

This section gives the planner concrete numbers and code shape to lock into PLAN.md without re-deriving them.

### Code shape

```python
# backend/app/routes/routing.py — Phase 8 changes (CONCEPTUAL)

# Default buffer in degrees; ~3.3 km at LA latitude.
ROUTE_FILTER_BUFFER_DEG = float(os.environ.get("ROUTE_FILTER_BUFFER_DEG", "0.03"))

# Size factor for the auto-widen retry. 2× is a sensible compromise — enough
# to catch corridor-edge cases without a third intermediate step.
ROUTE_FILTER_WIDEN_FACTOR = 2.0

CREATE_FILTERED_EDGES_SQL = """
    CREATE TEMP TABLE rq_filtered_edges ON COMMIT DROP AS
    SELECT id, source, target, travel_time_s
    FROM road_segments
    WHERE geom && ST_MakeEnvelope(
        LEAST(%(o_lon)s, %(d_lon)s) - %(buf)s,
        LEAST(%(o_lat)s, %(d_lat)s) - %(buf)s,
        GREATEST(%(o_lon)s, %(d_lon)s) + %(buf)s,
        GREATEST(%(o_lat)s, %(d_lat)s) + %(buf)s,
        4326
    )
    AND source IS NOT NULL
    AND target IS NOT NULL
"""

INDEX_FILTERED_EDGES_SQL = """
    CREATE INDEX ON rq_filtered_edges (source);
    CREATE INDEX ON rq_filtered_edges (target);
"""

KSP_FILTERED_SQL = """
    SELECT path_id, seq, edge, cost
    FROM pgr_ksp(
        'SELECT id, source, target, travel_time_s AS cost FROM rq_filtered_edges',
        %s, %s, %s, directed := false
    )
    WHERE edge != -1
"""

# Existing full-graph SQL stays as a final fallback.
KSP_FULL_SQL = """  ... existing SQL from line 16-23 unchanged ... """
```

### Control flow

1. Snap origin/dest to vertex IDs (unchanged).
2. **Attempt 1:** populate `rq_filtered_edges` with `BUFFER`, run `KSP_FILTERED_SQL`.
3. If 0 rows → **Attempt 2:** `DROP TABLE rq_filtered_edges; ` repopulate with `BUFFER × 2`, run again.
4. If 0 rows → **Attempt 3:** `DROP TABLE rq_filtered_edges;` run `KSP_FULL_SQL` against `road_segments` directly.
5. Group + score paths exactly as today (lines 82-149 unchanged).

Note: between attempts, `DROP TABLE rq_filtered_edges` is needed because `ON COMMIT DROP` only fires at transaction end. Alternatively, use `CREATE TEMP TABLE IF NOT EXISTS ... ; TRUNCATE rq_filtered_edges; INSERT INTO ...` — slightly cleaner because the catalog churn happens once.

### Defaults table (ready to lock in PLAN.md)

| Param | Value | Rationale | Override |
|-------|-------|-----------|----------|
| Default buffer | 0.03° (~3.3 km) | §3 first-principles geometry | `ROUTE_FILTER_BUFFER_DEG` env var |
| Widen factor | 2.0 | Two-attempt strategy without micro-tuning | `ROUTE_FILTER_WIDEN_FACTOR` env var (optional) |
| Max attempts | 3 (filter, wide-filter, full-graph) | §4 — covers the no-path edge case while bounding worst-case to 3 × 12s timeout | Hardcoded |
| K | 5 (unchanged) | Locked by `CON-route-selection-algorithm` | None |
| `directed := false` | Unchanged | Locked behavior | None |
| `heap_paths` | `false` (default) | Unchanged behavior | None |
| Temp table name | `rq_filtered_edges` | Project-prefixed to avoid collisions | None |
| Temp table indexes | btree on `source`, btree on `target` | §8 Pitfall G | None |
| `statement_timeout` | 12s (unchanged from commit 8bfd286) | Safety net | None |
| Cache TTL | 120s (unchanged) | Locked by `CON-cache-admin-api` shape | None |

---

## §10. Expected performance numbers

Educated estimates based on Finding 3 + the measured baselines from commit `704a70c`:

| Trip | Current (full-graph) | Estimated (filtered, 0.03° buffer) | Filtered subgraph size estimate |
|------|---------------------|------------------------------------|----------------------------------|
| 1 km DTLA-local cold | 1.4 s | 0.3-0.6 s | ~500-1500 edges |
| 5 km cross-neighborhood cold | 1.8 s | 0.5-1.0 s | ~1500-3500 edges |
| 20 km West LA → Pasadena cold | > 90 s (timeout) | 2-4 s | ~5000-10000 edges |
| 30 km bbox-corner-to-corner cold | > 90 s (timeout) | 4-7 s (may need wider buffer) | ~10000-15000 edges |

**Confidence:** MEDIUM. Numbers are not benchmarked; they're projections based on:
- Yen's algorithm cost scales roughly O(K · |E| log |V|) for sparse graphs
- 209k → ~5k edges = ~40× reduction in |E|
- log-factor reduction from |V| ~74k → ~3k (vertex count scales with edge count)
- Assume ~50× total speedup for the cross-LA case → 90s+ becomes ~2-4s

The phase planner SHOULD include a benchmarking task (Plan 08-XX) that runs the actual numbers on a seeded local DB and writes them to `08-PERF-NUMBERS.md` for honesty.

---

## §11. Validation Architecture (Nyquist categories)

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.3.4 (existing) |
| Config file | None — pytest is configured via `backend/pytest.ini` if present, else default |
| Quick run command | `cd backend && pytest tests/test_route.py tests/test_routing_pool_release.py -x` |
| Full suite command | `cd backend && pytest -x` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PERF-01 | Cross-LA route < 5s uncached | integration (live DB, seeded) | `pytest tests/test_routing_performance.py::test_cross_la_under_5s -x` | Wave 0 — NEW |
| PERF-02 | DTLA short route ≤ 2s uncached (no regression) | integration (live DB, seeded) | `pytest tests/test_routing_performance.py::test_dtla_under_2s -x` | Wave 0 — NEW |
| PERF-03 | Existing mock-based route tests pass | unit (mocked) | `pytest tests/test_route.py -x` | ✅ exists, may need mock adjustment per §7 |
| PERF-03 | Existing live-DB route tests pass | integration (live DB) | `pytest tests/test_integration.py::test_route_real_points tests/test_integration.py::test_route_respects_time_budget tests/test_integration.py::test_route_with_weights tests/test_integration.py::test_route_distant_points -x` | ✅ exists |
| PERF-03 | Pool-leak regression still passes (no new leak path introduced) | integration (live DB) | `pytest tests/test_routing_pool_release.py -x` | ✅ exists |
| (correctness) | Best-route output equals or improves cost vs. fastest for the same OD pair (no quality regression) | integration (live DB) | Existing `test_route_real_points` covers this — `assert data["best_route"]["total_cost"] <= data["fastest_route"]["total_cost"]` at line 95 | ✅ exists |
| (edge case) | Origin and destination at same node returns sensible response | integration (live DB) | NEW — `test_route_same_node` returns either a valid 0-length route or empty + warning | Wave 0 — NEW |
| (edge case) | Origin near LA boundary triggers fallback widen | integration (live DB) | NEW — `test_route_boundary_widen_fallback` asserts request returns 200 (fallback works) | Wave 0 — NEW (optional) |

### Sampling Rate
- **Per task commit:** `pytest tests/test_route.py tests/test_routing_pool_release.py -x` (mock-based + leak gate; runs in seconds; doesn't need DB)
- **Per wave merge:** `pytest -x` (full suite; auto-skips integration when DB unreachable)
- **Phase gate:** Full suite green on a fully-seeded DB (`scripts/seed_data.py` run, ~5 min) before `/gsd-verify-work`. Includes the new perf-regression tests.

### Wave 0 Gaps
- [ ] `backend/tests/test_routing_performance.py` — NEW. Two perf tests + `db_has_topology` skip + `pytest.mark.timeout(15)`.
- [ ] Possibly extend `_setup_mock_conn` in `tests/test_route.py` to handle the additional `cur.execute()` calls for the temp-table populate (§7 critical compat note). Decide between (a) extending the side_effect lists vs. (b) restructuring code so mocks are still satisfied with the same call counts.
- [ ] No new fixture work — `db_has_topology` already exists at `conftest.py:50-75` and covers the seeded-DB precondition perfectly.
- [ ] No framework install — pytest + pytest-timeout are already in `backend/requirements.txt` per Phase 5 fixes.

---

## §12. Code Examples (Verified Patterns)

### Pre-filter into a TEMP TABLE on a pooled connection

```python
# Inside the second `with get_connection() as conn:` block in find_route()
with conn.cursor() as cur:
    cur.execute(SNAP_NODE_SQL, (req.origin.lon, req.origin.lat))
    origin_node = cur.fetchone()["id"]
    cur.execute(SNAP_NODE_SQL, (req.destination.lon, req.destination.lat))
    dest_node = cur.fetchone()["id"]

    # Phase 8: filtered subgraph
    buffer = ROUTE_FILTER_BUFFER_DEG
    cur.execute(CREATE_FILTERED_EDGES_SQL, {
        "o_lon": req.origin.lon, "o_lat": req.origin.lat,
        "d_lon": req.destination.lon, "d_lat": req.destination.lat,
        "buf": buffer,
    })
    cur.execute(INDEX_FILTERED_EDGES_SQL)

    cur.execute(KSP_FILTERED_SQL, (origin_node, dest_node, K))
    ksp_rows = cur.fetchall()

    if not ksp_rows:
        # Widen and retry (§4 strategy step 2)
        cur.execute("DROP TABLE rq_filtered_edges")
        cur.execute(CREATE_FILTERED_EDGES_SQL, {
            "o_lon": req.origin.lon, "o_lat": req.origin.lat,
            "d_lon": req.destination.lon, "d_lat": req.destination.lat,
            "buf": buffer * ROUTE_FILTER_WIDEN_FACTOR,
        })
        cur.execute(INDEX_FILTERED_EDGES_SQL)
        cur.execute(KSP_FILTERED_SQL, (origin_node, dest_node, K))
        ksp_rows = cur.fetchall()

    if not ksp_rows:
        # Final fallback: full graph (§4 strategy step 3)
        cur.execute("DROP TABLE rq_filtered_edges")
        cur.execute(KSP_FULL_SQL, (origin_node, dest_node, K))
        ksp_rows = cur.fetchall()
```

[ASSUMED — based on the existing routing.py shape + the recommended approach. The planner should validate against actual psycopg2 cursor semantics during implementation; specifically that `INDEX_FILTERED_EDGES_SQL` containing two `CREATE INDEX` statements separated by `;` runs correctly via `cur.execute` (it should, since psycopg2 supports multiple statements in a single execute call).]

### Live-DB perf regression test pattern

```python
# backend/tests/test_routing_performance.py — NEW
import time
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.auth.dependencies import get_current_user_id
from app.cache import route_cache

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _override_auth():
    app.dependency_overrides[get_current_user_id] = lambda: 1
    yield
    app.dependency_overrides.pop(get_current_user_id, None)


@pytest.mark.timeout(15)
def test_dtla_under_2s(db_has_topology):
    """PERF-02: short DTLA-local trip ≤ 2s uncached."""
    route_cache.clear()
    client = TestClient(app)
    body = {
        "origin": {"lat": 34.0522, "lon": -118.2437},      # DTLA core
        "destination": {"lat": 34.0689, "lon": -118.2531}, # Echo Park (~2 km N)
        "include_iri": True, "include_potholes": True,
        "weight_iri": 50, "weight_potholes": 50,
        "max_extra_minutes": 5,
    }
    t0 = time.perf_counter()
    resp = client.post("/route", json=body)
    elapsed = time.perf_counter() - t0
    assert resp.status_code == 200
    assert elapsed < 2.0, f"PERF-02 regression: DTLA route took {elapsed:.2f}s (budget 2.0s)"


@pytest.mark.timeout(15)
def test_cross_la_under_5s(db_has_topology):
    """PERF-01: cross-LA trip < 5s uncached."""
    route_cache.clear()
    client = TestClient(app)
    body = {
        "origin": {"lat": 34.0489, "lon": -118.4521},      # West LA / Sawtelle
        "destination": {"lat": 34.1478, "lon": -118.1445}, # Pasadena
        "include_iri": True, "include_potholes": True,
        "weight_iri": 50, "weight_potholes": 50,
        "max_extra_minutes": 5,
    }
    t0 = time.perf_counter()
    resp = client.post("/route", json=body)
    elapsed = time.perf_counter() - t0
    assert resp.status_code == 200
    assert elapsed < 5.0, f"PERF-01 regression: cross-LA route took {elapsed:.2f}s (budget 5.0s)"
```

[ASSUMED — recipe based on existing `test_routing_pool_release.py` patterns]

---

## §13. Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL 16 | All routing | ✓ (Docker Compose default) | 16.x | — |
| PostGIS 3.4 | `geom` column, GiST, ST_MakeEnvelope | ✓ (postgis/postgis:16-3.4 image) | 3.4 | — |
| pgRouting 3.6 | `pgr_ksp`, `pgr_createTopology` | ✓ — confirmed in `db/Dockerfile` | 3.6 (local), 3.8 (deploy/db image per `.planning/phases/05-cloud-deployment/05-03-PLAN.md` mention of `pgrouting 3.8`) | — |
| psycopg2-binary | DB client | ✓ | 2.9.11 | — |
| pytest + pytest-timeout | Test runner | ✓ (Phase 5 fix `df65509` added pytest-timeout) | 8.3.4 + present | — |
| OSMnx-seeded local DB (~209k edges) | Live perf tests | Operator must run `python scripts/seed_data.py` once (~5 min) | — | Tests auto-skip via `db_has_topology` if missing — but they MUST be run before phase verify |

**No missing dependencies.** All required tooling is already in the project. The only operator step is running the seed if it hasn't been run on the local DB this session.

---

## §14. State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Full-graph `pgr_ksp` for all trips | Pre-filter via GiST + temp table + `pgr_ksp` over subgraph | Phase 8 (this phase) | Cross-LA goes from > 90s timeout to < 5s |
| Bbox filter inside `pgr_ksp` edges_sql | Bbox filter in OUTER psycopg2 query, then materialize to temp table | Phase 8 (rejecting failed 2026-04-29 attempt) | The placement matters: SPI doesn't use the GiST index; outer query does |
| No statement_timeout | `SET LOCAL statement_timeout = '12s'` per pooled connection | Already shipped — commit `8bfd286` | Phase 8 keeps it; it's the safety net for the 3-attempt fallback chain |
| `SimpleConnectionPool` (single-thread) | `ThreadedConnectionPool` | Phase 5 — commit `789ec07` | Phase 8 inherits; concurrent /route calls are race-safe |

**Deprecated/outdated:**
- Inlining spatial predicates in `pgr_ksp` edges_sql — confirmed broken in this codebase. Don't.
- Dollar-quoted ($tag$) inner SQL strings — confirmed problematic with psycopg2 in this codebase. Use single-quoted, escape `'` as `''`.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Default buffer of 0.03° (~3 km) catches realistic best-route detours within the 5-extra-minute time budget | §3 | Tight buffer triggers false-empty-result fallbacks more often than expected; users hit the wide-buffer or full-graph fallback path on common queries; perf target slipped. Mitigation: planner adds a benchmarking task that compares 0.03°, 0.04°, 0.05° empirically against the seeded DB |
| A2 | Filtered subgraph at 0.03° contains ~5000 edges for a 20 km diagonal trip | §10 | If the actual count is much larger (say, 30k+), pgr_ksp may not hit the < 5s budget at K=5. Planner's benchmark task would surface this; fix is to tighten the buffer further |
| A3 | The two existing test_route.py mocked tests will need their `fetchone.side_effect` / `fetchall.side_effect` lists extended by exactly 1-2 extra entries to cover the temp-table populate step | §7 | If wrong, the mocked tests fail with `StopIteration` from the mock cursor. Easy to fix in the GREEN phase. Listed here so the planner sizes the test-update task realistically |
| A4 | `cur.execute("CREATE INDEX ...; CREATE INDEX ...")` (multiple statements separated by `;`) works in psycopg2 | §12 | If wrong, planner splits into two separate `cur.execute` calls. Adds one line of code. Trivial |
| A5 | Yen's algorithm runtime scales roughly O(K · \|E\| log \|V\|), so 40× edge reduction yields roughly 40-60× speedup for cross-LA trips | §10 | If real scaling is closer to O(K · \|E\|^1.2) (which can happen with high-degree vertices), speedup could be 100×+ — overshoot but still meets target. If closer to O(K · \|E\|^0.5) — undershoot; cross-LA might be 8-10s instead of < 5s. Planner's benchmark surfaces this |
| A6 | The deploy/db image runs pgRouting 3.8 (newer than the local 3.6) | §13 | The pgr_ksp signature is identical between 3.6 and 3.8 (verified across pgRouting docs versions). Should not affect Phase 8. If anything, 3.8 is faster |
| A7 | `ON COMMIT DROP` doesn't fire mid-transaction; only at the `with conn:` exit point. So `DROP TABLE rq_filtered_edges` is needed between the filter and the wide-filter attempts | §12 | Standard PostgreSQL semantics; LOW risk. Verified by docs cited |
| A8 | The 209k edges figure is current as of latest seed; not affected by Phase 3 (Mapillary ingestion) since that adds rows to `segment_defects`, not `road_segments` | §3 critical correction | road_segments rowcount is set by seed_data.py and only changes on full re-seed. Verified by code reading: ingest_mapillary.py inserts to segment_defects only |

**Decisions needing user confirmation before execution:** None of the above are user-facing. The planner can absorb all of them. The two values most worth empirically validating during implementation (per `assumptions A1, A2, A5`) are the buffer width and the actual perf numbers — both surfaceable via the recommended benchmark task in the plan.

---

## §15. Open Questions

1. **Is the deploy/db image's pgRouting version 3.6 or 3.8?**
   - What we know: docker-compose.yml's local db uses `db/Dockerfile` based on `postgis/postgis:16-3.4` + apt-installed pgRouting (~3.6 era). Phase 5's `deploy/db/Dockerfile` was reportedly updated to ship pgRouting 3.8 per a SUMMARY note. We didn't verify by reading deploy/db/Dockerfile in this session.
   - What's unclear: which exact pgRouting version is live on Fly.
   - Recommendation: Phase 8 work is pgr_ksp signature-identical between 3.6 and 3.8, so this doesn't block planning. Plan a small confirmation step in Wave 0 (a `cur.execute("SELECT pgr_version()")` integration test that just records the version, doesn't gate anything).

2. **Is there a risk that two-attempt + fallback creates a duplicate audit log entry?**
   - What we know: `route_requests` insert happens once at line 58-62, BEFORE any pgr_ksp call. It's a single insert per HTTP request, regardless of how many internal attempts.
   - What's unclear: Nothing — verified by reading the code.
   - Recommendation: No action; raised here for completeness because the wording of "three attempts" might raise the question.

3. **Do we need to clear cache.py's `route_cache` when changing `ROUTE_FILTER_BUFFER_DEG`?**
   - What we know: `route_cache` keys are SHA256 of request params (origin, dest, weights, budget). The buffer is NOT in the cache key.
   - What's unclear: After a buffer change deploy, cached entries from before the change may still serve. They're not WRONG — same OD pair → same routing math regardless of buffer (the buffer is a perf optimization, not a semantics change). But operationally a cache flush may be cleaner after a deploy.
   - Recommendation: Document in PLAN.md's deploy notes: "After Phase 8 deploy, optionally `POST /cache/clear` to refresh." Not blocking.

4. **Does the snap-to-node query need bbox-filtering too?**
   - What we know: `SNAP_NODE_SQL` uses `road_segments_vertices_pgr.the_geom <-> ...` ORDER BY. KNN with a GiST index (which `the_geom` has, built by `pgr_createTopology`) is O(log n). Even at 74k vertices it's fast.
   - What's unclear: The current latency budget is dominated by pgr_ksp; snap is ~milliseconds.
   - Recommendation: Don't touch snap. It's not the bottleneck.

5. **Will Phase 8 affect the `test_route_distant_points` test (lines 136-149 in test_integration.py)?**
   - What we know: The test uses two points ~500 m apart, well within any reasonable buffer. It already accepts EITHER a real route OR a "no route found" warning (line 145-146). So the test is robust to either Phase 8 outcome.
   - What's unclear: Nothing — the test is designed to handle both cases.
   - Recommendation: No action.

---

## Sources

### Primary (HIGH confidence — direct in-repo evidence)

- `backend/app/routes/routing.py` (193 lines, full read) — current full-graph KSP_SQL pattern, call site, control flow
- `backend/app/db.py` (full read) — ThreadedConnectionPool + 12s statement_timeout
- `backend/app/cache.py` (full read) — route_cache shape and TTL
- `backend/tests/test_route.py` (full read) — mock structure for unit tests
- `backend/tests/test_integration.py` (lines 70-150 read) — live-DB integration tests for /route
- `backend/tests/test_routing_pool_release.py` (full read) — pool-release regression test pattern
- `backend/tests/conftest.py` (full read) — `db_has_topology` fixture
- `db/migrations/001_initial.sql` (full read) — schema with `idx_segments_geom GIST(geom)`, source/target btrees
- `scripts/seed_data.py` (lines 1-60 read) — `DIST = 20000` (20 km radius, ~209k edges)
- `.planning/PROJECT.md` (full read) — project constraints, locked decisions
- `.planning/REQUIREMENTS.md` (full read) — REQ-* traceability
- `.planning/STATE.md` (full read) — current phase/state
- `.planning/codebase/{ARCHITECTURE,CONCERNS,STACK}.md` (read) — codebase context
- `.planning/phases/05-cloud-deployment/05-LESSONS-LEARNED.md` (line 35 read) — confirms 209k segment count
- Git commits `2278605`, `17bff0c`, `704a70c`, `8bfd286` (full diffs read) — the failed 2026-04-29 bbox-filter attempts AND the 12s statement_timeout safety net, with measured latency numbers in commit messages

### Secondary (MEDIUM-HIGH confidence — official documentation)

- [pgRouting Manual: pgr_KSP (latest)](https://docs.pgrouting.org/latest/en/pgr_KSP.html) — function signature, heap_paths default, output schema
- [PostGIS Spatial Indexing — Workshops](https://postgis.net/workshops/postgis-intro/indexing.html) — GiST + `&&` operator semantics
- [PostGIS ST_DWithin docs](https://postgis.net/docs/ST_DWithin.html) — geometry vs geography semantics
- [PostgreSQL TEMP TABLE / ON COMMIT DROP — Cybertec](https://www.cybertec-postgresql.com/en/postgresql-sophisticating-temporary-tables/) — pooled-environment ergonomics
- [PostgreSQL Temp Tables and Connection Pooling — tech-champion](https://tech-champion.com/database/postgresql/postgresql-temp-tables-and-connection-pooling-navigating-performance-pitfalls/) — temp table catalog churn caveats

### Tertiary (MEDIUM confidence — community + practitioner sources, cross-verified where possible)

- [pgRouting issue #556 — pgr_dijkstra performance](https://github.com/pgRouting/pgrouting/issues/556) — confirms pgRouting reads ways and builds graph per query
- [Anitagraser — Beginner's Guide to pgRouting](https://anitagraser.com/2011/02/07/a-beginners-guide-to-pgrouting/) — pgRouting subquery patterns
- [Crunchy Data — Routing with PostgreSQL](https://www.crunchydata.com/blog/routing-with-postgresql-and-crunchy-spatial) — pgRouting performance commentary
- [Improving Path Query Performance in pgRouting — research paper](https://www.researchgate.net/publication/326332580_IMPROVING_PATH_QUERY_PERFORMANCE_IN_PGROUTING_USING_A_MAP_GENERALIZATION_APPROACH) — confirms subset-reduction is the standard performance technique

### LOW confidence (single-source or unverified — flagged)

- The exact buffer-width default (0.03°) is reasoned from time-budget geometry, NOT benchmarked. Confidence MEDIUM. Planner should benchmark.
- The 40-60× speedup projection in §10 is an extrapolation, NOT a measurement. Planner should benchmark.
- The dollar-quote-with-psycopg2 hang reported in commit `17bff0c` is documented as the cause but not root-caused at the C level. The Phase 8 recommendation sidesteps the issue rather than fixing it; if a future plan needs dollar-quoting, more investigation would be warranted.

---

## Metadata

**Confidence breakdown:**
- Root cause analysis: HIGH (direct measured evidence from in-repo failed-attempt commits)
- Stack / codebase facts: HIGH (read in full)
- Recommended approach (two-step + temp table): MEDIUM-HIGH (consistent with pgRouting community guidance and PostgreSQL temp-table semantics; not specifically benchmarked at our 209k scale)
- Buffer-width default: MEDIUM (no community number; reasoned from time-budget geometry)
- Expected perf numbers: MEDIUM (extrapolation, not measured)
- Pitfalls: HIGH for A, B, E, F (verified in repo); MEDIUM for C, D, G (verified by general PostgreSQL semantics, not benchmarked here)

**Research date:** 2026-05-04
**Valid until:** 2026-06-04 (30 days — the stack and constraints are stable; pgRouting 3.x line is stable; project decisions are locked)
