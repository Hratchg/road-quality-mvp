import json
import os

import psycopg2  # for psycopg2.errors.QueryCanceled in find_route() Task 2
from fastapi import APIRouter, Response
from app.db import get_connection
from app.models import RouteRequest, RouteResponse, RouteInfo, SegmentMetric
from app.scoring import compute_segment_cost
from app.cache import get_route_cached, set_route_cached, make_route_cache_key

router = APIRouter()

SNAP_NODE_SQL = """
    SELECT id FROM road_segments_vertices_pgr
    ORDER BY the_geom <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326)
    LIMIT 1
"""

# Phase 8: Pre-filter buffer for the OD bbox passed into ST_MakeEnvelope.
# Default 0.03 deg ~= 3.3 km at LA latitude (RESEARCH §3, §9 defaults table).
# Override via env to widen on operator request without a redeploy.
ROUTE_FILTER_BUFFER_DEG = float(os.environ.get("ROUTE_FILTER_BUFFER_DEG", "0.03"))
ROUTE_FILTER_WIDEN_FACTOR = float(os.environ.get("ROUTE_FILTER_WIDEN_FACTOR", "2.0"))

KSP_FULL_SQL = """
    SELECT path_id, seq, edge, cost
    FROM pgr_ksp(
        'SELECT id, source, target, travel_time_s AS cost FROM road_segments',
        %s, %s, %s, directed := false
    )
    WHERE edge != -1
"""

# Phase 8: Pre-filter the OD-corridor edges using the GiST index on
# road_segments.geom (RESEARCH §1 — the index is invisible inside pgr_ksp's
# SPI, so the filter MUST happen in this OUTER psycopg2 query, not inlined).
# AND source IS NOT NULL / AND target IS NOT NULL excludes any edges that
# pgr_createTopology failed to wire up — those would be useless to pgr_ksp.
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

# Phase 8 Pitfall G: pgr_ksp's inner Dijkstra joins on source/target. Without
# btree indexes on those columns the temp table degrades back to seq scan.
# Two CREATE INDEX statements separated by `;` — psycopg2 supports multiple
# statements per execute() call (RESEARCH Assumption A4).
INDEX_FILTERED_EDGES_SQL = """
    CREATE INDEX ON rq_filtered_edges (source);
    CREATE INDEX ON rq_filtered_edges (target);
"""

# Phase 8: Same pgr_ksp call as KSP_FULL_SQL but reads from the temp table
# instead of the full 209k-edge road_segments. K=5 + directed:=false locked
# by CON-route-selection-algorithm.
KSP_FILTERED_SQL = """
    SELECT path_id, seq, edge, cost
    FROM pgr_ksp(
        'SELECT id, source, target, travel_time_s AS cost FROM rq_filtered_edges',
        %s, %s, %s, directed := false
    )
    WHERE edge != -1
"""

SEGMENTS_BY_IDS_SQL = """
    SELECT
        rs.id, rs.travel_time_s, rs.iri_norm,
        ST_AsGeoJSON(rs.geom) AS geojson,
        COALESCE(ss.moderate_score, 0) AS moderate_score,
        COALESCE(ss.severe_score, 0) AS severe_score,
        COALESCE(ss.pothole_score_total, 0) AS pothole_score_total,
        COALESCE(ss.crash_norm, 0) AS crash_norm
    FROM road_segments rs
    LEFT JOIN segment_scores ss ON rs.id = ss.segment_id
    WHERE rs.id = ANY(%s)
"""

K = 5

# Phase 8 — pgr_dijkstra outer SQL. The inner_sql is built per-iteration
# inside find_k_shortest_via_dijkstra(); see that function's docstring for
# why edge-weight perturbation runs Yen's-style algorithm linear in K
# instead of pgr_ksp's super-linear-in-K Yen's enumeration.
PGR_DIJKSTRA_OUTER_SQL = """
    SELECT seq, edge, cost
    FROM pgr_dijkstra(
        %(inner_sql)s,
        %(origin)s, %(dest)s, directed := false
    )
    WHERE edge != -1
    ORDER BY seq
"""

# Penalty multiplier applied to edges from previously-found paths. Multiplicative
# (not additive) so it dominates any realistic alt-path cost difference. 1000x
# means a blocked 300-second edge becomes a 300000-second edge -- two orders of
# magnitude above any plausible full-route cost in LA. Override via env var if
# operator wants tighter or looser path-diversity behavior.
DIJKSTRA_BLOCKED_EDGE_PENALTY = float(
    os.environ.get("DIJKSTRA_BLOCKED_EDGE_PENALTY", "1000.0")
)


def find_k_shortest_via_dijkstra(
    cur,
    origin_node: int,
    dest_node: int,
    k: int = 5,
    edges_table: str = "rq_filtered_edges",
    weight_penalty: float | None = None,
    early_exit_at: int | None = None,
) -> list[dict]:
    """Run pgr_dijkstra k times with edge-weight perturbation between iterations.

    Returns a list of row dicts in pgr_ksp output shape:
      [{"path_id": 1, "seq": 1, "edge": 42, "cost": 3.5}, ...]

    Why this exists (Phase 8 second-replan):
      pgr_ksp with K=5 explodes super-linearly on dense urban subgraphs
      (08-PERF-NUMBERS.md: K=1 = 0.4s, K=3 = 20s+, K=5 = 12s timeout, all
      on the same 10k-edge subgraph). pgr_dijkstra called K times with
      edge-weight perturbation between calls is linear in K -- the
      industry-standard k-shortest-paths approach used by OSRM and Valhalla.
      Same K=5 candidate paths, same row shape, much better complexity.

    Algorithm (Yen's-style edge-weight perturbation):
      1. Run pgr_dijkstra(origin, dest) on the unperturbed graph -> path_1.
      2. Collect path_1's edge IDs into the `blocked` set.
      3. For i in 2..k: run pgr_dijkstra with cost-of-blocked-edges
         multiplied by weight_penalty (so subsequent runs prefer
         alternatives but can still cross blocked edges if no
         alternative exists). Add new path's edges to `blocked`.
      4. If iteration i returns 0 rows, stop early (no more distinct paths).
      5. If `early_exit_at` is set and we have collected that many distinct
         paths, stop early.

    Why edge-weight perturbation (not edge removal):
      - Edge removal can leave the graph disconnected for the OD pair,
        returning 0 rows after the first path.
      - Multiplicative penalty (cost * 1000) makes blocked edges
        "expensive but still traversable"; pgr_dijkstra still finds
        a path through them if no cheaper alternative exists.

    Args:
        cur: an open psycopg2 cursor on a connection that has already
            run CREATE TEMP TABLE for `edges_table` (when edges_table
            != "road_segments"). The cursor MUST share the transaction
            with the temp-table creation -- see Pitfall C in 08-RESEARCH.md.
        origin_node: vertex ID returned by SNAP_NODE_SQL for the origin.
        dest_node: vertex ID returned by SNAP_NODE_SQL for the destination.
        k: number of K-shortest paths to find. Default 5
            (CON-route-selection-algorithm).
        edges_table: name of the table to read edges from. "rq_filtered_edges"
            (the bbox-filtered temp table from Plan 08-02) or "road_segments"
            (full-graph fallback). Caller-controlled, never user-supplied --
            do NOT pass user input here (T-08-03b-01).
        weight_penalty: multiplier applied to edges in already-found paths.
            None = read DIJKSTRA_BLOCKED_EDGE_PENALTY (1000.0 default).
        early_exit_at: if set, stop after this many distinct paths collected
            even if k is larger. Used by find_route() to cap dijkstra calls
            on filtered-subgraph attempts (where path diversity is naturally
            limited by the smaller search space, so 3 paths capture nearly
            all the variation that 5 would). The full-graph fallback passes
            None to get the full K=5 enumeration. None = no early exit.

    Returns:
        list of dicts with keys {"path_id", "seq", "edge", "cost"}. Empty
        list when iteration 1 returns 0 rows (caller falls back). Up to
        k * <path-length> rows in the happy path; capped at
        early_exit_at * <path-length> when early_exit_at is set.

    Security (T-08-03b-01):
        The inner SQL string interpolates ONLY system-controlled values:
        - `edges_table` is a hardcoded caller-side string (caller is
          find_route() in this same module).
        - `blocked_literal` is a comma-separated list of int()-coerced
          edge IDs returned BY pgr_dijkstra ITSELF in prior iterations.
          User input never reaches this string.
        - `weight_penalty` is float()-coerced from a module constant.
        psycopg2 still parameter-binds origin / dest via %(origin)s /
        %(dest)s in the OUTER SQL.
    """
    if weight_penalty is None:
        weight_penalty = DIJKSTRA_BLOCKED_EDGE_PENALTY

    rows: list[dict] = []
    blocked: list[int] = []

    for path_id in range(1, k + 1):
        # int() coercion prevents any non-integer slipping through.
        # blocked items are always BIGINT edge IDs from the DB.
        blocked_literal = ",".join(str(int(e)) for e in blocked)
        inner_sql = (
            f"SELECT id, source, target, "
            f"CASE WHEN id = ANY(ARRAY[{blocked_literal}]::bigint[]) "
            f"THEN cost * {float(weight_penalty)} ELSE cost END AS cost "
            f"FROM (SELECT id, source, target, travel_time_s AS cost "
            f"FROM {edges_table}) AS e"
        )
        cur.execute(
            PGR_DIJKSTRA_OUTER_SQL,
            {"inner_sql": inner_sql, "origin": origin_node, "dest": dest_node},
        )
        path_rows = cur.fetchall()

        if not path_rows:
            # Iteration 1 with no rows -> no path in this subgraph; caller
            # must widen or fall back. Iterations 2..k with no rows ->
            # we just ran out of distinct alternatives; return what we have.
            break

        for r in path_rows:
            rows.append(
                {
                    "path_id": path_id,
                    "seq": r["seq"],
                    "edge": r["edge"],
                    "cost": r["cost"],
                }
            )
            blocked.append(int(r["edge"]))

        # Phase 8 tuning (08-PERF-NUMBERS.md Run 2 -> Run 3): early-exit when
        # caller has signalled a smaller path budget. On filtered subgraphs
        # the search space is naturally limited, so 3 paths capture nearly
        # all the diversity that 5 would -- saving 40% of the dijkstra calls
        # on cross-LA where each iteration is ~580ms.
        if early_exit_at is not None and path_id >= early_exit_at:
            break

    return rows


@router.post("/route", response_model=RouteResponse)
def find_route(req: RouteRequest, response: Response):
    # D-10-15 + Pitfall 4: set Deprecation header at the TOP of the handler,
    # BEFORE the audit-log INSERT and BEFORE the cache check, so that:
    #   - cache hits (early return below) inherit the header
    #   - no-route fallbacks (RouteResponse return at "No route found") inherit it
    #   - successful responses (final return response) inherit it
    # FastAPI Response-parameter pattern: response.headers persist on the
    # final response regardless of which return statement executes.
    # EXACT-STRING locked per CONTEXT D-10-15 — do NOT paraphrase.
    response.headers["Deprecation"] = (
        "weight_iri,weight_potholes ignored as of v0.4.0"
    )

    cache_key = make_route_cache_key(
        req.origin.lat, req.origin.lon,
        req.destination.lat, req.destination.lon,
        req.max_extra_minutes,
    )

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Log request -- always, even on cache hits
            cur.execute(
                "INSERT INTO route_requests (params_json) VALUES (%s)",
                (json.dumps(req.model_dump()),),
            )
            conn.commit()

    # Check cache after audit log but before expensive pgr_ksp
    cached = get_route_cached(cache_key)
    if cached is not None:
        return RouteResponse(**cached)

    # Phase 8 routing-performance contract — DO NOT "simplify" this back to a
    # single full-graph pgr_ksp call. The structure here is load-bearing:
    #
    #   1. Pre-filter the OD-corridor edges via the GiST index on
    #      road_segments.geom in an OUTER psycopg2 query that materializes
    #      to TEMP TABLE rq_filtered_edges. RESEARCH §8 Pitfall A — putting
    #      the spatial WHERE INSIDE pgr_ksp's edges_sql forces a full seq
    #      scan because pgRouting evaluates that string via SPI which does
    #      not invoke the GiST index. The 2026-04-29 attempt to do this
    #      lost > 14× to the unfiltered baseline; commits 2278605 / 17bff0c
    #      / 704a70c document the disaster.
    #
    #   2. Build btree indexes on rq_filtered_edges(source) and (target)
    #      before calling pgr_ksp on it. RESEARCH §8 Pitfall G — without
    #      these, Yen's inner Dijkstra degrades back to seq scan inside
    #      the K=5 loop and the cross-LA budget slips by 5×+.
    #
    #   3. Fall back to a wider buffer (×ROUTE_FILTER_WIDEN_FACTOR), then
    #      finally to KSP_FULL_SQL on the full road_segments table, when
    #      the filtered subgraph yields no path. RESEARCH §4 — preserves
    #      the correctness guarantee for OD pairs near the LA boundary.
    #
    #   4. The 12s SET LOCAL statement_timeout (db.py:97-98, commit 8bfd286)
    #      is the safety net that bounds each attempt. Worst case is 3 × 12s.
    #
    # Tunable: set ROUTE_FILTER_BUFFER_DEG in the environment to widen the
    # default 0.03° (~3.3 km) corridor at deploy time without a code change.
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Snap to nearest nodes (UNCHANGED)
            cur.execute(SNAP_NODE_SQL, (req.origin.lon, req.origin.lat))
            origin_node = cur.fetchone()["id"]
            cur.execute(SNAP_NODE_SQL, (req.destination.lon, req.destination.lat))
            dest_node = cur.fetchone()["id"]

            ksp_rows: list[dict] = []
            bbox_params = {
                "o_lon": req.origin.lon, "o_lat": req.origin.lat,
                "d_lon": req.destination.lon, "d_lat": req.destination.lat,
                "buf": ROUTE_FILTER_BUFFER_DEG,
            }

            # Phase 8 attempt 1: bbox-filtered subgraph + pgr_dijkstra K=5
            # with edge-weight perturbation. Catches QueryCanceled so a
            # timeout at this layer doesn't bubble to HTTP 500 (08-PERF-NUMBERS.md
            # 'Fallback Chain Observation' was the bug in the reverted plan).
            #
            # early_exit_at=3 (08-PERF-NUMBERS.md Run 2 -> Run 3 tuning): the
            # filtered subgraph has limited path diversity, so the marginal
            # benefit of K=5 over K=3 is tiny while the cost is ~40% extra
            # dijkstra calls. Cross-LA before tuning: 5 x ~580ms = 2.9s of
            # dijkstra alone. After tuning: 3 x ~580ms = 1.7s. Full K=5
            # is reserved for attempt 3 below.
            try:
                cur.execute(CREATE_FILTERED_EDGES_SQL, bbox_params)
                cur.execute(INDEX_FILTERED_EDGES_SQL)
                ksp_rows = find_k_shortest_via_dijkstra(
                    cur, origin_node, dest_node, k=K,
                    edges_table="rq_filtered_edges",
                    early_exit_at=3,
                )
            except psycopg2.errors.QueryCanceled:
                conn.rollback()
                ksp_rows = []

            # Phase 8 attempt 2: widen the buffer. Triggers on either empty
            # result OR QueryCanceled from attempt 1.
            if not ksp_rows:
                try:
                    cur.execute("DROP TABLE IF EXISTS rq_filtered_edges")
                    wide_params = {
                        **bbox_params,
                        "buf": ROUTE_FILTER_BUFFER_DEG * ROUTE_FILTER_WIDEN_FACTOR,
                    }
                    cur.execute(CREATE_FILTERED_EDGES_SQL, wide_params)
                    cur.execute(INDEX_FILTERED_EDGES_SQL)
                    ksp_rows = find_k_shortest_via_dijkstra(
                        cur, origin_node, dest_node, k=K,
                        edges_table="rq_filtered_edges",
                        early_exit_at=3,
                    )
                except psycopg2.errors.QueryCanceled:
                    conn.rollback()
                    ksp_rows = []

            # Phase 8 attempt 3: full-graph fallback via pgr_dijkstra K=5.
            # Last-resort correctness guarantee. Triggers on either empty
            # result OR QueryCanceled from attempt 2. early_exit_at=None
            # (full K=5 enumeration) since this is the only attempt that
            # sees the entire graph and we want maximum path diversity for
            # the rare-case where filtered subgraph yielded 0 paths.
            if not ksp_rows:
                try:
                    cur.execute("DROP TABLE IF EXISTS rq_filtered_edges")
                    ksp_rows = find_k_shortest_via_dijkstra(
                        cur, origin_node, dest_node, k=K,
                        edges_table="road_segments",
                        early_exit_at=None,
                    )
                except psycopg2.errors.QueryCanceled:
                    conn.rollback()
                    ksp_rows = []

            # Group by path_id (UNCHANGED from pre-Phase-8 logic)
            paths: dict[int, list[int]] = {}
            for row in ksp_rows:
                paths.setdefault(row["path_id"], []).append(row["edge"])

            if not paths:
                return RouteResponse(
                    fastest_route=RouteInfo(
                        geojson={"type": "LineString", "coordinates": []},
                        total_time_s=0,
                        total_cost=0,
                    ),
                    best_route=RouteInfo(
                        geojson={"type": "LineString", "coordinates": []},
                        total_time_s=0,
                        total_cost=0,
                    ),
                    warning="No route found between these points",
                    per_segment_metrics=[],
                )

            # Fetch all segment data (UNCHANGED)
            all_edge_ids = list({eid for edges in paths.values() for eid in edges})
            cur.execute(SEGMENTS_BY_IDS_SQL, (all_edge_ids,))
            seg_rows = cur.fetchall()
            seg_data = {row["id"]: row for row in seg_rows}

    # Score each path
    scored_paths = []
    for path_id, edge_ids in paths.items():
        total_time = 0.0
        total_cost = 0.0
        total_iri = 0.0
        total_mod = 0.0
        total_sev = 0.0
        coordinates = []
        metrics = []
        count = 0

        for eid in edge_ids:
            seg = seg_data.get(eid)
            if not seg:
                continue
            count += 1
            t = seg["travel_time_s"]
            iri = seg["iri_norm"] or 0.0
            pot = seg["pothole_score_total"] or 0.0
            crash = seg["crash_norm"] or 0.0   # D-10-14: Plan 10-02 populates this column

            total_time += t
            # D-10-02 / D-10-14: new 4-arg signature, no w_iri/w_pot, locked outer weights.
            total_cost += compute_segment_cost(t, iri, pot, crash)
            total_iri += iri
            total_mod += seg["moderate_score"]
            total_sev += seg["severe_score"]

            geom = json.loads(seg["geojson"])
            coordinates.extend(geom.get("coordinates", []))
            metrics.append(SegmentMetric(id=eid, iri_norm=iri, pothole_score=pot))

        scored_paths.append({
            "path_id": path_id,
            "total_time_s": total_time,
            "total_cost": total_cost,
            "avg_iri_norm": total_iri / count if count else 0,
            "total_moderate_score": total_mod,
            "total_severe_score": total_sev,
            "geojson": {"type": "LineString", "coordinates": coordinates},
            "metrics": metrics,
        })

    # Find fastest (min travel time)
    fastest = min(scored_paths, key=lambda p: p["total_time_s"])
    fastest_time = fastest["total_time_s"]
    max_time = fastest_time + req.max_extra_minutes * 60

    # Filter by time budget
    within_budget = [p for p in scored_paths if p["total_time_s"] <= max_time]

    warning = None
    if not within_budget or (
        len(within_budget) == 1
        and within_budget[0]["path_id"] == fastest["path_id"]
    ):
        best = fastest
        if len(scored_paths) > 1:
            warning = "No route within time budget found; returning fastest route"
    else:
        best = min(within_budget, key=lambda p: p["total_cost"])

    def to_route_info(p, include_details=False):
        info = RouteInfo(
            geojson=p["geojson"],
            total_time_s=p["total_time_s"],
            total_cost=p["total_cost"],
        )
        if include_details:
            info.avg_iri_norm = p["avg_iri_norm"]
            info.total_moderate_score = p["total_moderate_score"]
            info.total_severe_score = p["total_severe_score"]
        return info

    response = RouteResponse(
        fastest_route=to_route_info(fastest),
        best_route=to_route_info(best, include_details=True),
        warning=warning,
        per_segment_metrics=best["metrics"],
    )

    # Cache the computed response as a dict for serialization
    set_route_cached(cache_key, response.model_dump())

    return response
