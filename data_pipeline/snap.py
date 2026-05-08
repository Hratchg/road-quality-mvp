"""Shared point-to-segment snap-match SQL primitive.

Lifted from scripts/ingest_mapillary.py:255-281 (Phase 3 D-01..D-04).
Reused unchanged by Phase 9's scripts/ingest_crashes.py per D-09-17.

This file is the canonical home of the snap-match SQL. Phase 9 does NOT modify
ingest_mapillary.py; a future cleanup phase will migrate that call site to
import from this module. Setting the canonical (seg_id, dist_m) return shape
NOW means the future migration is "drop the dist_m return value at the call
site," not "re-port the SQL." (Pitfall C in 09-RESEARCH.md.)

Verified at 125k Mapillary rows in <30s on Fly (Phase 5 deploy). Uses ST_DWithin
geography for METER semantics + KNN <-> for GIST-indexed nearest-segment lookup.
"""

from __future__ import annotations


def snap_point_to_segment(
    cur,
    lon: float,
    lat: float,
    snap_meters: float,
) -> tuple[int, float] | tuple[None, None]:
    """Find the single nearest road_segment within snap_meters of (lon, lat).

    Args:
        cur: psycopg2 cursor (RealDictCursor or plain). The function handles both.
        lon: WGS84 longitude (negative in LA).
        lat: WGS84 latitude.
        snap_meters: Maximum distance in METERS to consider a match.

    Returns:
        (segment_id, distance_m) on hit; (None, None) if outside snap_meters.

    Implementation notes:
        - ST_DWithin (radius filter, GIST-indexed via idx_segments_geom on
          road_segments.geom) bounds candidates.
        - ORDER BY geom <-> ST_SetSRID(...) (KNN distance, GIST-indexed) +
          LIMIT 1 picks the single nearest within the radius.
        - The ::geography cast is REQUIRED for METER semantics on ST_DWithin —
          without it the radius is interpreted in degrees (~111km/degree at
          LA's latitude), which would silently match every segment in the
          city. (Anti-Patterns in 09-RESEARCH.md.)
        - Both query parameters are bound via psycopg2's %s placeholders;
          NEVER f-string concatenated (T-9-01).
    """
    cur.execute(
        """
        SELECT
            id,
            ST_Distance(
                geom::geography,
                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography
            ) AS dist_m
        FROM road_segments
        WHERE ST_DWithin(
            geom::geography,
            ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
            %s
        )
        ORDER BY geom <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326)
        LIMIT 1
        """,
        (lon, lat, lon, lat, snap_meters, lon, lat),
    )
    row = cur.fetchone()
    if not row:
        return (None, None)
    if isinstance(row, dict):
        return (int(row["id"]), float(row["dist_m"]))
    return (int(row[0]), float(row[1]))
