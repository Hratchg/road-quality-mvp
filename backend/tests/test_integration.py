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
