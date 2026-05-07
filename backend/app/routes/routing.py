import json
import os
from fastapi import APIRouter
from app.db import get_connection
from app.models import RouteRequest, RouteResponse, RouteInfo, SegmentMetric
from app.scoring import normalize_weights, compute_segment_cost
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
        COALESCE(ss.pothole_score_total, 0) AS pothole_score_total
    FROM road_segments rs
    LEFT JOIN segment_scores ss ON rs.id = ss.segment_id
    WHERE rs.id = ANY(%s)
"""

K = 5


@router.post("/route", response_model=RouteResponse)
def find_route(req: RouteRequest):
    w_iri, w_pot = normalize_weights(
        req.include_iri, req.include_potholes,
        req.weight_iri, req.weight_potholes,
    )

    cache_key = make_route_cache_key(
        req.origin.lat, req.origin.lon,
        req.destination.lat, req.destination.lon,
        req.include_iri, req.include_potholes,
        req.weight_iri, req.weight_potholes,
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

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Snap to nearest nodes (unchanged)
            cur.execute(SNAP_NODE_SQL, (req.origin.lon, req.origin.lat))
            origin_node = cur.fetchone()["id"]

            cur.execute(SNAP_NODE_SQL, (req.destination.lon, req.destination.lat))
            dest_node = cur.fetchone()["id"]

            # Phase 8 attempt 1: pre-filter the OD-corridor edges via the
            # GiST index on road_segments.geom (RESEARCH §1 — the index is
            # invisible inside pgr_ksp's SPI, so this OUTER query is the
            # whole point of the fix). T-08-03-01 mitigation: every value
            # bound via psycopg2 named-param style; never f-string.
            bbox_params = {
                "o_lon": req.origin.lon, "o_lat": req.origin.lat,
                "d_lon": req.destination.lon, "d_lat": req.destination.lat,
                "buf": ROUTE_FILTER_BUFFER_DEG,
            }
            cur.execute(CREATE_FILTERED_EDGES_SQL, bbox_params)
            cur.execute(INDEX_FILTERED_EDGES_SQL)
            cur.execute(KSP_FILTERED_SQL, (origin_node, dest_node, K))
            ksp_rows = cur.fetchall()

            # Phase 8 attempt 2: widen the buffer if no path found in the
            # tight corridor (RESEARCH §4 — covers the corridor-edge case
            # without falling all the way back to the full graph). DROP
            # without IF EXISTS — RESEARCH Assumption A7: ON COMMIT DROP
            # only fires at transaction end, so within this same `with`
            # block the temp table persists across attempts and MUST be
            # explicitly dropped before re-creating.
            if not ksp_rows:
                cur.execute("DROP TABLE rq_filtered_edges")
                wide_params = {
                    **bbox_params,
                    "buf": ROUTE_FILTER_BUFFER_DEG * ROUTE_FILTER_WIDEN_FACTOR,
                }
                cur.execute(CREATE_FILTERED_EDGES_SQL, wide_params)
                cur.execute(INDEX_FILTERED_EDGES_SQL)
                cur.execute(KSP_FILTERED_SQL, (origin_node, dest_node, K))
                ksp_rows = cur.fetchall()

            # Phase 8 attempt 3: full-graph fallback. Preserves the original
            # pre-Phase-8 behavior (RESEARCH §4 — correctness guarantee).
            # Triggers if both filtered attempts found no path — usually
            # means an edge-of-graph OD pair near the LA-area boundary.
            if not ksp_rows:
                cur.execute("DROP TABLE rq_filtered_edges")
                cur.execute(KSP_FULL_SQL, (origin_node, dest_node, K))
                ksp_rows = cur.fetchall()

            # Group by path_id (unchanged from pre-Phase-8 logic)
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

            # Fetch all segment data (unchanged)
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

            total_time += t
            total_cost += compute_segment_cost(t, iri, pot, w_iri, w_pot)
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
