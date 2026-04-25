"""Integration tests that run against a live PostgreSQL + PostGIS + pgRouting database.

Auto-skipped when the DB is unreachable (via db_available fixture in conftest.py),
so CI without Docker still passes.

NOTE: Route tests use points ~200m apart so pgr_ksp(K=5) completes in <1s.
Wider spacing causes exponential blowup on the 62k-segment network.
"""
import pytest

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Segments endpoint
# ---------------------------------------------------------------------------

LA_BBOX = "-118.28,34.02,-118.20,34.08"
EMPTY_BBOX = "0,0,0.001,0.001"


def test_segments_returns_geojson(client):
    resp = client.get(f"/segments?bbox={LA_BBOX}")
    assert resp.status_code == 200

    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) > 0

    feat = data["features"][0]
    assert feat["geometry"]["type"] == "LineString"
    for key in ("id", "iri_norm", "moderate_score", "severe_score", "pothole_score_total"):
        assert key in feat["properties"]


def test_segments_empty_bbox(client):
    resp = client.get(f"/segments?bbox={EMPTY_BBOX}")
    assert resp.status_code == 200

    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 0


# ---------------------------------------------------------------------------
# Route endpoint — points ~200m apart (pgr_ksp K=5 ≈ 0.2s)
# ---------------------------------------------------------------------------

ORIGIN_DOWNTOWN = {"lat": 34.0522, "lon": -118.2437}
DEST_NEARBY = {"lat": 34.0535, "lon": -118.2450}


def _post_route(client, *, origin=ORIGIN_DOWNTOWN, destination=DEST_NEARBY, **overrides):
    payload = {
        "origin": origin,
        "destination": destination,
        "include_iri": True,
        "include_potholes": True,
        "weight_iri": 50,
        "weight_potholes": 50,
        "max_extra_minutes": 5,
        **overrides,
    }
    return client.post("/route", json=payload)


@pytest.mark.timeout(30)
def test_route_real_points(client):
    resp = _post_route(client)
    assert resp.status_code == 200

    data = resp.json()
    assert "fastest_route" in data
    assert "best_route" in data

    for key in ("fastest_route", "best_route"):
        route = data[key]
        assert route["total_time_s"] > 0
        assert route["total_cost"] > 0
        geom_type = route["geojson"].get("type")
        assert geom_type in ("LineString", "MultiLineString")

    assert data["best_route"]["total_cost"] <= data["fastest_route"]["total_cost"]


@pytest.mark.timeout(30)
def test_route_respects_time_budget(client):
    resp = _post_route(client, max_extra_minutes=0)
    assert resp.status_code == 200

    data = resp.json()
    fastest = data["fastest_route"]
    best = data["best_route"]

    # With zero budget, best should equal fastest OR a warning is present
    same_route = (
        fastest["total_time_s"] == best["total_time_s"]
        and fastest["total_cost"] == best["total_cost"]
    )
    assert same_route or data.get("warning") is not None


@pytest.mark.timeout(60)
def test_route_with_weights(client):
    resp_iri = _post_route(
        client, include_iri=True, include_potholes=False, weight_iri=100, weight_potholes=0,
    )
    resp_pot = _post_route(
        client, include_iri=False, include_potholes=True, weight_iri=0, weight_potholes=100,
    )
    assert resp_iri.status_code == 200
    assert resp_pot.status_code == 200

    cost_iri = resp_iri.json()["best_route"]["total_cost"]
    cost_pot = resp_pot.json()["best_route"]["total_cost"]

    # Different weight configs should produce different scoring
    # (they *could* pick the same path, but total_cost will differ because
    # the cost formula uses different weights)
    assert cost_iri != cost_pot


@pytest.mark.timeout(30)
def test_route_distant_points(client):
    # Slightly farther apart (~500m) but still fast enough for pgr_ksp
    far_origin = {"lat": 34.0522, "lon": -118.2437}
    far_dest = {"lat": 34.0560, "lon": -118.2480}

    resp = _post_route(client, origin=far_origin, destination=far_dest, max_extra_minutes=10)
    assert resp.status_code == 200

    data = resp.json()
    if data.get("warning") and "No route found" in data["warning"]:
        assert data["fastest_route"]["total_time_s"] == 0
    else:
        assert data["fastest_route"]["total_time_s"] > 0
        assert data["best_route"]["total_time_s"] > 0


# ============================================================
# Phase 3 -- REQ-mapillary-pipeline integration tests (plan 03-04)
# ============================================================
#
# These tests cover the four critical success criteria of REQ-mapillary-pipeline:
#   SC #1: ingest writes rows tagged source='mapillary' end-to-end
#   SC #2: re-running on the same target inserts zero new rows (idempotency)
#   SC #3: /segments reflects mapillary detections after auto-recompute
#   SC #4: --source synthetic vs --source mapillary produce different rankings
#   D-14:  --wipe-synthetic preserves pre-existing mapillary rows
#
# Approach: monkeypatch data_pipeline entry points on the imported
# scripts.ingest_mapillary module and call ing.main() in-process under
# manipulated sys.argv -- same pattern test_ingest_mapillary.py uses.

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

# REPO_ROOT relative to this test file: backend/tests/test_integration.py
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from data_pipeline.detector import Detection  # noqa: E402
from scripts import ingest_mapillary as _ing  # noqa: E402


def _fake_search_images(bbox, *, token=None, limit=100):
    """Return a deterministic small set of fake Mapillary images.

    Each image gets an all-digits id (download_image's T-02-20 guard requires
    digits-only ids) and coordinates inside the queried bbox so snap-match
    locks onto the target segment.
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    cx = (min_lon + max_lon) / 2
    cy = (min_lat + max_lat) / 2
    # Build a digits-only id deterministic in the bbox center
    base = abs(int(cx * 1_000_000)) + abs(int(cy * 1_000_000))
    return [
        {
            "id": f"{base}{i:02d}",
            "thumb_2048_url": f"https://example.invalid/img_{i}.jpg",
            "computed_geometry": {"coordinates": [cx, cy]},
        }
        for i in range(2)
    ]


def _fake_download_image(meta, cache_dir, timeout_s=60.0):
    """Write a 1-byte file under cache_dir using the all-digits image id."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    image_id = str(meta["id"])
    path = cache_dir / f"{image_id}.jpg"
    path.write_bytes(b"\x00")
    return path


def _seed_target_segment_id(db_conn) -> int:
    """Pick a real seeded segment id for tests."""
    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM road_segments ORDER BY id LIMIT 1")
        row = cur.fetchone()
    if not row:
        pytest.skip("No road_segments rows; run seed_data.py first")
    return row["id"] if isinstance(row, dict) else row[0]


def _count_mapillary(db_conn) -> int:
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS c FROM segment_defects WHERE source = 'mapillary'"
        )
        row = cur.fetchone()
    return row["c"] if isinstance(row, dict) else row[0]


def _count_synthetic(db_conn) -> int:
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS c FROM segment_defects WHERE source = 'synthetic'"
        )
        row = cur.fetchone()
    return row["c"] if isinstance(row, dict) else row[0]


def _cleanup_mapillary_rows(db_conn):
    """Delete any mapillary rows tagged with our test markers."""
    with db_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM segment_defects WHERE source = 'mapillary'"
        )
    db_conn.commit()


@pytest.fixture
def cache_root(tmp_path):
    """Per-test cache directory so manifest writes don't collide."""
    p = tmp_path / "ingest_cache"
    p.mkdir()
    return p


@pytest.fixture
def stub_mapillary(monkeypatch, db_available):
    """Patch the entry points the CLI uses on data_pipeline + token gate."""
    monkeypatch.setenv("MAPILLARY_ACCESS_TOKEN", "stub_token_for_tests")
    # Patch the names AS IMPORTED INTO ingest_mapillary's namespace.
    # All-digits-id detector test factory: a deterministic StubDetector-like
    # mock that always yields one severe detection per image.
    deterministic_detector = MagicMock()
    deterministic_detector.detect = MagicMock(
        return_value=[Detection(severity="severe", confidence=0.9)]
    )
    monkeypatch.setattr(_ing, "search_images", _fake_search_images)
    monkeypatch.setattr(_ing, "download_image", _fake_download_image)
    monkeypatch.setattr(
        _ing, "get_detector",
        lambda use_yolo=False, model_path=None: deterministic_detector,
    )
    # MAPILLARY_TOKEN is read at module load on data_pipeline.mapillary, but
    # the script's gate uses the imported MAPILLARY_TOKEN symbol; override it.
    monkeypatch.setattr(_ing, "MAPILLARY_TOKEN", "stub_token_for_tests")
    yield


def _invoke_ingest(monkeypatch, *args):
    """Invoke ing.main() with synthetic argv. Returns the exit code."""
    full_argv = ["ingest_mapillary.py", *args]
    monkeypatch.setattr(sys, "argv", full_argv)
    return _ing.main()


@pytest.mark.integration
def test_ingest_mapillary_end_to_end_writes_rows(
    db_conn, cache_root, stub_mapillary, monkeypatch
):
    """SC #1: ingest writes rows tagged source='mapillary' with non-NULL
    source_mapillary_id; manifest is written under cache_root."""
    seg_id = _seed_target_segment_id(db_conn)
    _cleanup_mapillary_rows(db_conn)
    before = _count_mapillary(db_conn)

    rc = _invoke_ingest(
        monkeypatch,
        "--segment-ids", str(seg_id),
        "--cache-root", str(cache_root),
        "--no-recompute",  # avoid subprocess in this test
        "--limit-per-segment", "2",
    )
    assert rc == 0, "ingest returned non-zero"
    after = _count_mapillary(db_conn)
    assert after > before, "no mapillary rows inserted"

    # Manifest written
    manifests = list(cache_root.glob("manifest-*.json"))
    assert manifests, f"no manifest written under {cache_root}"
    payload = json.loads(manifests[0].read_text())
    # The manifest schema is locked by Phase 2; assert it has a 'files' key
    # (or equivalent entries list).
    assert isinstance(payload, dict)
    assert "files" in payload or "entries" in payload

    _cleanup_mapillary_rows(db_conn)


@pytest.mark.integration
def test_ingest_mapillary_idempotent_rerun(
    db_conn, cache_root, stub_mapillary, monkeypatch
):
    """SC #2: re-running on the same target inserts zero new rows (ON CONFLICT
    DO NOTHING + identical fake images)."""
    seg_id = _seed_target_segment_id(db_conn)
    _cleanup_mapillary_rows(db_conn)

    rc1 = _invoke_ingest(
        monkeypatch, "--segment-ids", str(seg_id),
        "--cache-root", str(cache_root), "--no-recompute",
        "--limit-per-segment", "2",
    )
    assert rc1 == 0
    after_first = _count_mapillary(db_conn)
    assert after_first > 0, "first run produced no mapillary rows"

    # Second run: identical args, identical fake images -> ON CONFLICT DO NOTHING
    rc2 = _invoke_ingest(
        monkeypatch, "--segment-ids", str(seg_id),
        "--cache-root", str(cache_root), "--no-recompute",
        "--limit-per-segment", "2",
    )
    assert rc2 == 0
    after_second = _count_mapillary(db_conn)
    assert after_second == after_first, (
        f"idempotency violated: {after_first} -> {after_second}"
    )

    _cleanup_mapillary_rows(db_conn)


@pytest.mark.integration
def test_segments_reflects_mapillary_after_compute_scores(
    db_conn, client, cache_root, stub_mapillary, monkeypatch
):
    """SC #3: ingest + auto-recompute -> /segments shows non-zero
    pothole_score_total for the target segment.

    The stub_mapillary fixture's deterministic detector mock guarantees one
    severe detection per image, so pothole_score_total MUST be > 0 once the
    mapillary write + compute_scores subprocess pipeline runs end-to-end.
    A zero score means the wiring is broken, not just unlucky randomness.
    """
    seg_id = _seed_target_segment_id(db_conn)
    _cleanup_mapillary_rows(db_conn)

    # Run ingest WITH the auto-recompute subprocess enabled (default; no
    # --no-recompute flag).
    rc = _invoke_ingest(
        monkeypatch, "--segment-ids", str(seg_id),
        "--cache-root", str(cache_root),
        "--limit-per-segment", "2",
    )
    assert rc == 0, "ingest with auto-recompute failed"

    # Get the bbox around the target segment for the /segments query
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT ST_XMin(ST_Envelope(geom)) - 0.001 AS minlon, "
            "       ST_YMin(ST_Envelope(geom)) - 0.001 AS minlat, "
            "       ST_XMax(ST_Envelope(geom)) + 0.001 AS maxlon, "
            "       ST_YMax(ST_Envelope(geom)) + 0.001 AS maxlat "
            "FROM road_segments WHERE id = %s",
            (seg_id,),
        )
        row = cur.fetchone()
    if isinstance(row, dict):
        bbox = [row["minlon"], row["minlat"], row["maxlon"], row["maxlat"]]
    else:
        bbox = list(row)
    bbox_str = ",".join(str(v) for v in bbox)

    # Clear cached /segments responses (cachetools TTL).
    try:
        client.post("/cache/clear")
    except Exception:
        pass

    resp = client.get(f"/segments?bbox={bbox_str}")
    assert resp.status_code == 200
    features = resp.json()["features"]
    target = next(
        (f for f in features if f["properties"]["id"] == seg_id), None
    )
    assert target is not None, f"target segment {seg_id} not in /segments response"
    # SC #3: with deterministic severe detections + auto-recompute, the score
    # MUST be non-zero.
    assert target["properties"]["pothole_score_total"] > 0, (
        f"pothole_score_total expected > 0 after ingest + recompute, got "
        f"{target['properties'].get('pothole_score_total')!r}"
    )

    _cleanup_mapillary_rows(db_conn)


@pytest.mark.integration
def test_route_ranks_differ_by_source(db_conn):
    """SC #4: --source synthetic vs --source mapillary produce different
    score snapshots when both row types exist on different segments.

    Inserts a mapillary row directly (no CLI), then runs compute_scores.py
    twice and diffs the resulting segment_scores rows.
    """
    # Pick TWO distinct seeded segments
    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM road_segments ORDER BY id LIMIT 2")
        rows = cur.fetchall()
    if len(rows) < 2:
        pytest.skip("Need >= 2 seeded road_segments for this test")
    seg_a = rows[0]["id"] if isinstance(rows[0], dict) else rows[0][0]
    seg_b = rows[1]["id"] if isinstance(rows[1], dict) else rows[1][0]

    marker = "test030487654321"  # all-digits per T-02-20-style discipline
    with db_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM segment_defects WHERE source_mapillary_id = %s",
            (marker,),
        )
        # Insert one severe mapillary row on seg_b
        cur.execute(
            "INSERT INTO segment_defects "
            "(segment_id, severity, count, confidence_sum, "
            " source_mapillary_id, source) "
            "VALUES (%s, 'severe', 3, 2.7, %s, 'mapillary') "
            "ON CONFLICT DO NOTHING",
            (seg_b, marker),
        )
    db_conn.commit()

    def _score_snapshot():
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT segment_id, pothole_score_total FROM segment_scores "
                "WHERE segment_id IN (%s, %s)",
                (seg_a, seg_b),
            )
            return {
                (r["segment_id"] if isinstance(r, dict) else r[0]):
                (r["pothole_score_total"] if isinstance(r, dict) else r[1])
                for r in cur.fetchall()
            }

    repo_root = Path(__file__).resolve().parents[2]

    subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "compute_scores.py"),
         "--source", "synthetic"],
        check=True, capture_output=True, cwd=str(repo_root),
    )
    snap_synth = _score_snapshot()

    subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "compute_scores.py"),
         "--source", "mapillary"],
        check=True, capture_output=True, cwd=str(repo_root),
    )
    snap_mly = _score_snapshot()

    # The two snapshots must differ: under --source mapillary, seg_b has a
    # non-zero score from the test row; under --source synthetic, seg_b's
    # mapillary contribution is excluded -> score may be 0 or whatever
    # synthetic data exists. The two must not be identical.
    assert snap_synth != snap_mly, (
        f"--source toggle had no effect: synth={snap_synth} mly={snap_mly}"
    )

    # Cleanup + restore baseline
    with db_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM segment_defects WHERE source_mapillary_id = %s",
            (marker,),
        )
    db_conn.commit()
    subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "compute_scores.py"),
         "--source", "all"],
        check=True, capture_output=True, cwd=str(repo_root),
    )


@pytest.mark.integration
def test_wipe_synthetic_preserves_mapillary(
    db_conn, cache_root, stub_mapillary, monkeypatch
):
    """D-14: --wipe-synthetic deletes synthetic rows but preserves mapillary.

    Inserts a mapillary marker row directly, runs the CLI with
    --wipe-synthetic --force-wipe (so the wipe runs even if the mocked
    Mapillary returns nothing useful), then asserts the marker survives
    while synthetic rows are gone.

    NOTE: this test is intentionally placed LAST among the Phase 3 SC tests
    -- it leaves the DB with synthetic rows wiped. Subsequent integration
    tests that depend on synthetic rows would need a reseed.
    """
    seg_id = _seed_target_segment_id(db_conn)
    marker = "test030412345678"  # all-digits

    # Insert one mapillary row that must survive
    with db_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM segment_defects WHERE source_mapillary_id = %s",
            (marker,),
        )
        cur.execute(
            "INSERT INTO segment_defects "
            "(segment_id, severity, count, confidence_sum, "
            " source_mapillary_id, source) "
            "VALUES (%s, 'severe', 1, 0.9, %s, 'mapillary')",
            (seg_id, marker),
        )
    db_conn.commit()

    mly_before = _count_mapillary(db_conn)
    assert mly_before >= 1

    # Run with --wipe-synthetic + --force-wipe (the mocked Mapillary may or
    # may not yield rows; --force-wipe makes the test independent of that).
    rc = _invoke_ingest(
        monkeypatch, "--segment-ids", str(seg_id),
        "--cache-root", str(cache_root),
        "--no-recompute", "--wipe-synthetic", "--force-wipe",
        "--limit-per-segment", "2",
    )
    assert rc == 0, "wipe + ingest should succeed with --force-wipe"

    synth_after = _count_synthetic(db_conn)
    assert synth_after == 0, f"synthetic rows survived wipe: {synth_after}"

    # The pre-existing marker row must survive
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS c FROM segment_defects "
            "WHERE source_mapillary_id = %s",
            (marker,),
        )
        row = cur.fetchone()
    n = row["c"] if isinstance(row, dict) else row[0]
    assert n == 1, "specific pre-existing mapillary marker row was wiped"

    # CLEANUP: remove our marker row.
    with db_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM segment_defects WHERE source_mapillary_id = %s",
            (marker,),
        )
    db_conn.commit()
