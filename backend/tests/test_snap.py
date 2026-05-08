"""Unit-flavor DB integration tests for data_pipeline.snap.snap_point_to_segment.

Tests run against the live local Postgres (auto-skip if unreachable). They use
the existing seeded road_segments rows (run scripts/seed_data.py first to
populate). The snap function is purely a SELECT — no inserts, no rollback hassle.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_pipeline.snap import snap_point_to_segment

pytestmark = pytest.mark.integration


@pytest.fixture
def a_segment_centroid(db_conn):
    """Pick any road_segments row; return (id, point_lon, point_lat) where the
    point is GUARANTEED to lie on the LineString (its midpoint).

    Note: we use ST_LineInterpolatePoint(geom, 0.5), NOT ST_Centroid(geom).
    For a curved or multi-vertex LineString the centroid (geometric mean of
    vertices / bbox center) sits OFF the line — empirically up to 7m off
    even for short LA street segments — which would make `dist_m < 1.0`
    assertions flaky. ST_LineInterpolatePoint always returns a point ON
    the line at the requested fractional offset (0.5 = midpoint).

    Skips test if no road_segments rows exist (CI may not be seeded).
    """
    with db_conn.cursor() as cur:
        cur.execute(
            """
            SELECT id,
                   ST_X(ST_LineInterpolatePoint(geom, 0.5)) AS clon,
                   ST_Y(ST_LineInterpolatePoint(geom, 0.5)) AS clat
            FROM road_segments
            ORDER BY id
            LIMIT 1
            """
        )
        row = cur.fetchone()
    if not row:
        pytest.skip("No road_segments rows; run scripts/seed_data.py first")
    if isinstance(row, dict):
        return (int(row["id"]), float(row["clon"]), float(row["clat"]))
    return (int(row[0]), float(row[1]), float(row[2]))


def test_snap_within_radius(db_conn, a_segment_centroid):
    """Snapping a point ON a known segment's centroid returns that segment with
    near-zero distance.
    """
    seg_id, clon, clat = a_segment_centroid
    with db_conn.cursor() as cur:
        result = snap_point_to_segment(cur, clon, clat, snap_meters=10.0)
    assert result[0] is not None, "should match the segment we picked"
    matched_id, dist_m = result
    # The centroid sits exactly on the LineString; distance should be < 1m.
    assert dist_m < 1.0, f"distance {dist_m}m should be near zero on the centroid"


def test_snap_outside_radius(db_conn):
    """A point far from any LA road (Pacific Ocean coords) returns (None, None)
    even with a generous radius. This proves the radius filter actually filters.
    """
    # Mid-Pacific ocean — definitely no LA road segments here.
    pacific_lon, pacific_lat = -150.0, 20.0
    with db_conn.cursor() as cur:
        result = snap_point_to_segment(cur, pacific_lon, pacific_lat, snap_meters=100.0)
    assert result == (None, None), f"expected (None, None), got {result}"


def test_snap_returns_distance_in_meters(db_conn, a_segment_centroid):
    """Confirm the ::geography cast: snap a point ~30m offset from a known segment.
    Distance must be in METERS (~30m), not DEGREES (~3e-4) or kilometers (~0.03).
    Without the geography cast, ST_DWithin would interpret the radius in degrees
    (~111km/degree at LA's latitude) and silently match the entire city.
    """
    seg_id, clon, clat = a_segment_centroid
    # Offset ~30m east at LA's latitude: 1 deg lon ≈ 92km at lat 34°, so
    # 30m ≈ 30 / 92000 ≈ 3.26e-4 degrees.
    offset_deg = 30.0 / 92000.0
    offset_lon = clon + offset_deg
    with db_conn.cursor() as cur:
        result = snap_point_to_segment(cur, offset_lon, clat, snap_meters=100.0)
    assert result[0] is not None, "should still match within 100m"
    matched_id, dist_m = result
    # Allow ±50% tolerance around 30m (the segment may not be perfectly E-W).
    assert 5.0 < dist_m < 80.0, (
        f"distance {dist_m}m is not in the meter scale; "
        "::geography cast may be missing (degree-scale would be ~3e-4 or ~111000)"
    )


def test_snap_returns_none_tuple_outside_radius(db_conn, a_segment_centroid):
    """Tight radius (0.0001m) when the nearest segment is meters away → (None, None).
    Verifies the precise 2-tuple shape, not just `None` (Pitfall C: callers
    pattern-match `if seg_id is None`, so we must return a tuple of two Nones).
    """
    seg_id, clon, clat = a_segment_centroid
    # Offset ~30m so even a 1m radius can't reach the segment.
    offset_deg = 30.0 / 92000.0
    with db_conn.cursor() as cur:
        result = snap_point_to_segment(
            cur, clon + offset_deg, clat, snap_meters=1.0,
        )
    assert isinstance(result, tuple), f"expected tuple, got {type(result)}"
    assert len(result) == 2, f"expected 2-tuple, got len={len(result)}"
    assert result == (None, None), f"expected (None, None), got {result}"


def test_snap_picks_nearest_when_multiple_in_radius(db_conn, a_segment_centroid):
    """If many segments are within the radius, the NEAREST one wins (ORDER BY <->).

    LA's seeded road network is dense (>200k segments), so a 500m radius
    centered on any segment's midpoint will include many candidates. The
    `ORDER BY geom <-> point LIMIT 1` clause must pick the original segment
    (distance ~0) rather than any of its many neighbors at meter-scale
    distances. If the ORDER BY were missing, ST_DWithin would simply return
    "the first row PostGIS happens to find," which is unlikely to be the
    on-line midpoint segment.
    """
    seg_id, clon, clat = a_segment_centroid
    with db_conn.cursor() as cur:
        # Sanity check: the radius is large enough to include many candidates,
        # so the test exercises KNN ordering rather than a single-candidate
        # short-circuit.
        cur.execute(
            """
            SELECT COUNT(*) AS n FROM road_segments
            WHERE ST_DWithin(
                geom::geography,
                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                500
            )
            """,
            (clon, clat),
        )
        row = cur.fetchone()
        candidate_count = int(row["n"]) if isinstance(row, dict) else int(row[0])
        assert candidate_count > 1, (
            f"test prerequisite: need >1 candidate within 500m to exercise KNN ordering; "
            f"got {candidate_count}"
        )

        result = snap_point_to_segment(cur, clon, clat, snap_meters=500.0)
    matched, dist_m = result
    # The exact same segment whose midpoint we used must win — its distance
    # is ~0, all others are meters away. KNN ordering picks the smallest <->.
    assert matched == seg_id, (
        f"expected nearest segment id={seg_id} (midpoint distance ~0); "
        f"got id={matched} at dist_m={dist_m} — ORDER BY geom <-> may be missing "
        f"or KNN GIST index not being used"
    )
    assert dist_m < 1.0, (
        f"distance to the picked segment should be ~0; got {dist_m}m"
    )
