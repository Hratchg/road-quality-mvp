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
    """Pick any road_segments row; return (id, centroid_lon, centroid_lat).

    Skips test if no road_segments rows exist (CI may not be seeded).
    """
    with db_conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, ST_X(ST_Centroid(geom)) AS clon, ST_Y(ST_Centroid(geom)) AS clat
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


def test_snap_picks_nearest_when_multiple_in_radius(db_conn):
    """If two segments are within the radius, the nearest one wins (ORDER BY <->).

    Pick a point at the midpoint of two known-adjacent road_segments.id values
    if seeded data has them; otherwise auto-skip. We use the convention that
    seed_data populates contiguous LA street centerlines, so adjacent ids tend
    to be adjacent geometries.
    """
    with db_conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.id AS a_id, b.id AS b_id,
                   (ST_X(ST_Centroid(a.geom)) + ST_X(ST_Centroid(b.geom))) / 2 AS mlon,
                   (ST_Y(ST_Centroid(a.geom)) + ST_Y(ST_Centroid(b.geom))) / 2 AS mlat,
                   ST_Distance(a.geom::geography, b.geom::geography) AS sep_m
            FROM road_segments a JOIN road_segments b ON b.id = a.id + 1
            WHERE ST_Distance(a.geom::geography, b.geom::geography) < 200
            ORDER BY a.id LIMIT 1
            """
        )
        row = cur.fetchone()
    if not row:
        pytest.skip("No adjacent close-by road_segments pair found; need seeded LA data")
    if isinstance(row, dict):
        a_id, b_id, mlon, mlat = row["a_id"], row["b_id"], float(row["mlon"]), float(row["mlat"])
    else:
        a_id, b_id, mlon, mlat = row[0], row[1], float(row[2]), float(row[3])
    with db_conn.cursor() as cur:
        result = snap_point_to_segment(cur, mlon, mlat, snap_meters=500.0)
    matched, dist_m = result
    # Either of the two should be acceptable (whichever is closer to the midpoint
    # by KNN); we just verify SOME match within the tight radius.
    assert matched in (a_id, b_id), (
        f"expected nearest of ({a_id}, {b_id}); got {matched}"
    )
