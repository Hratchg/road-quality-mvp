from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.auth.dependencies import get_current_user_id


@pytest.fixture(autouse=True)
def _override_auth():
    """Bypass JWT verification for all tests in this module — these tests
    cover route logic, not the auth gate (covered by test_auth_routes.py)."""
    app.dependency_overrides[get_current_user_id] = lambda: 1
    yield
    app.dependency_overrides.pop(get_current_user_id, None)


def _mock_ksp_results():
    """Simulate pgr_ksp returning 2 paths on a tiny graph."""
    return [
        {"path_id": 1, "seq": 1, "edge": 1, "cost": 60.0},
        {"path_id": 1, "seq": 2, "edge": 2, "cost": 60.0},
        {"path_id": 2, "seq": 1, "edge": 3, "cost": 70.0},
        {"path_id": 2, "seq": 2, "edge": 4, "cost": 70.0},
    ]


def _mock_segment_data():
    """Segment data for edges referenced by ksp.

    Plan 10-03: crash_norm added (D-10-17). Set to 0.0 to preserve the
    v0.2.0 invariant that path 1 is both fastest and lowest-cost on this
    synthetic graph; path-2-cheaper test scenarios are out of scope here.
    """
    return [
        {
            "id": 1, "travel_time_s": 60.0, "iri_norm": 0.8,
            "pothole_score_total": 3.0, "moderate_score": 1.5, "severe_score": 1.5,
            "crash_norm": 0.0,
            "geojson": '{"type":"LineString","coordinates":[[-118.24,34.05],[-118.245,34.055]]}',
        },
        {
            "id": 2, "travel_time_s": 60.0, "iri_norm": 0.7,
            "pothole_score_total": 2.0, "moderate_score": 1.0, "severe_score": 1.0,
            "crash_norm": 0.0,
            "geojson": '{"type":"LineString","coordinates":[[-118.245,34.055],[-118.25,34.06]]}',
        },
        {
            "id": 3, "travel_time_s": 70.0, "iri_norm": 0.2,
            "pothole_score_total": 0.5, "moderate_score": 0.3, "severe_score": 0.2,
            "crash_norm": 0.0,
            "geojson": '{"type":"LineString","coordinates":[[-118.24,34.05],[-118.242,34.058]]}',
        },
        {
            "id": 4, "travel_time_s": 70.0, "iri_norm": 0.1,
            "pothole_score_total": 0.0, "moderate_score": 0.0, "severe_score": 0.0,
            "crash_norm": 0.0,
            "geojson": '{"type":"LineString","coordinates":[[-118.242,34.058],[-118.25,34.06]]}',
        },
    ]


def _mock_dijkstra_iteration_1():
    """Simulate pgr_dijkstra returning path 1 (2 edges) on a tiny mock graph.

    Row shape matches pgr_dijkstra's output (seq, edge, cost) -- not pgr_ksp's.
    The helper find_k_shortest_via_dijkstra() tags these with path_id=1 before
    returning to find_route().
    """
    return [
        {"seq": 1, "edge": 1, "cost": 60.0},
        {"seq": 2, "edge": 2, "cost": 60.0},
    ]


def _mock_dijkstra_iteration_2():
    """Simulate pgr_dijkstra returning path 2 (different 2 edges) on iteration 2."""
    return [
        {"seq": 1, "edge": 3, "cost": 70.0},
        {"seq": 2, "edge": 4, "cost": 70.0},
    ]


def _mock_dijkstra_empty():
    """Iteration 3 returns 0 rows -> helper breaks early, returns 2 paths total."""
    return []


def _setup_mock_conn(mock_conn):
    """Wire up mock connection with cursor context managers."""
    mock_cursor = MagicMock()
    mock_conn.return_value.__enter__ = lambda s: s
    mock_conn.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn.return_value.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.return_value.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn.return_value.commit = MagicMock()
    return mock_cursor


@patch("app.routes.routing.get_connection")
def test_route_returns_best_and_fastest(mock_conn):
    mock_cursor = _setup_mock_conn(mock_conn)

    mock_cursor.fetchone.side_effect = [
        {"id": 100},  # origin node
        {"id": 200},  # destination node
    ]
    # find_route() now calls find_k_shortest_via_dijkstra (K=5 iterations).
    # Mock iteration 1 returns path 1, iteration 2 returns path 2, iteration 3
    # returns empty (helper breaks early -- 2 distinct paths total). Then
    # SEGMENTS_BY_IDS_SQL fetchall returns segment data. The CREATE TEMP TABLE,
    # CREATE INDEX, and DROP TABLE statements all use cur.execute() but
    # don't consume from fetchall.side_effect.
    mock_cursor.fetchall.side_effect = [
        _mock_dijkstra_iteration_1(),  # K=1 dijkstra result (path 1)
        _mock_dijkstra_iteration_2(),  # K=2 dijkstra result (path 2)
        _mock_dijkstra_empty(),         # K=3 dijkstra returns empty -> helper breaks
        _mock_segment_data(),           # SEGMENTS_BY_IDS_SQL
    ]

    client = TestClient(app)
    response = client.post("/route", json={
        "origin": {"lat": 34.05, "lon": -118.24},
        "destination": {"lat": 34.06, "lon": -118.25},
        "include_iri": True,
        "include_potholes": True,
        "weight_iri": 50,
        "weight_potholes": 50,
        "max_extra_minutes": 5,
    })

    assert response.status_code == 200
    data = response.json()
    assert "fastest_route" in data
    assert "best_route" in data
    # Path 1 is fastest (120s vs 140s)
    assert data["fastest_route"]["total_time_s"] <= data["best_route"]["total_time_s"] or \
           data["fastest_route"]["total_time_s"] == data["best_route"]["total_time_s"]
    # Path 2 should have lower cost (smoother road)
    assert data["best_route"]["total_cost"] <= data["fastest_route"]["total_cost"]


@patch("app.routes.routing.get_connection")
def test_route_returns_warning_with_zero_budget(mock_conn):
    mock_cursor = _setup_mock_conn(mock_conn)

    mock_cursor.fetchone.side_effect = [
        {"id": 100},
        {"id": 200},
    ]
    # See test_route_returns_best_and_fastest above for the per-iteration mock
    # rationale. Same 4-element fetchall.side_effect: 3 dijkstra iterations
    # (path 1, path 2, empty -> break) + segment data.
    mock_cursor.fetchall.side_effect = [
        _mock_dijkstra_iteration_1(),
        _mock_dijkstra_iteration_2(),
        _mock_dijkstra_empty(),
        _mock_segment_data(),
    ]

    client = TestClient(app)
    response = client.post("/route", json={
        "origin": {"lat": 34.05, "lon": -118.24},
        "destination": {"lat": 34.06, "lon": -118.25},
        "include_iri": True,
        "include_potholes": True,
        "weight_iri": 50,
        "weight_potholes": 50,
        "max_extra_minutes": 0,
    })

    assert response.status_code == 200
    data = response.json()
    # With 0 extra minutes budget, only the fastest route fits
    # best_route should equal fastest, possibly with a warning
    assert data["fastest_route"]["total_time_s"] == data["best_route"]["total_time_s"] or \
           data["warning"] is not None


# =====================================================================
# Plan 10-03 (Phase 10): /route locked-weights + Deprecation header tests.
# =====================================================================


@patch("app.routes.routing.get_connection")
def test_identical_route_with_legacy_weight_fields(mock_conn):
    """D-10-16 + Pitfall 7: POST /route {... weight_iri: 0.99} returns
    SAME geojson + total_cost AS POST /route without those fields.
    Semantic ignore — not just accepted by Pydantic.
    """
    mock_cursor = _setup_mock_conn(mock_conn)
    # Two requests, each: 2 SNAP fetchone + 4 fetchall calls
    # (3 dijkstra iterations + 1 segment data).
    mock_cursor.fetchone.side_effect = [
        {"id": 100}, {"id": 200},
        {"id": 100}, {"id": 200},
    ]
    mock_cursor.fetchall.side_effect = [
        _mock_dijkstra_iteration_1(), _mock_dijkstra_iteration_2(),
        _mock_dijkstra_empty(), _mock_segment_data(),
        _mock_dijkstra_iteration_1(), _mock_dijkstra_iteration_2(),
        _mock_dijkstra_empty(), _mock_segment_data(),
    ]

    client = TestClient(app)
    # Clear cache to ensure both requests run the full pipeline.
    from app.cache import clear_all_caches
    clear_all_caches()

    # Request A: without legacy fields.
    resp_a = client.post("/route", json={
        "origin": {"lat": 34.05, "lon": -118.24},
        "destination": {"lat": 34.06, "lon": -118.25},
        "max_extra_minutes": 5,
    })
    assert resp_a.status_code == 200
    data_a = resp_a.json()

    clear_all_caches()  # reset for second request

    # Request B: with legacy fields set to extreme values.
    resp_b = client.post("/route", json={
        "origin": {"lat": 34.05, "lon": -118.24},
        "destination": {"lat": 34.06, "lon": -118.25},
        "weight_iri": 0.99,
        "weight_potholes": 0.01,
        "include_iri": False,
        "include_potholes": False,
        "max_extra_minutes": 5,
    })
    assert resp_b.status_code == 200
    data_b = resp_b.json()

    # SEMANTIC ignore: same geojson, same cost, same time.
    assert data_a["best_route"]["geojson"] == data_b["best_route"]["geojson"], (
        "Identical-route guarantee broken: geojson differs between "
        "requests with/without legacy weight fields. Pitfall 7."
    )
    assert data_a["best_route"]["total_cost"] == data_b["best_route"]["total_cost"], (
        "Identical-route guarantee broken: total_cost differs. "
        "Probable cause: routing.py still reads req.weight_iri/req.weight_potholes."
    )
    assert data_a["fastest_route"]["total_time_s"] == data_b["fastest_route"]["total_time_s"]


@patch("app.routes.routing.get_connection")
def test_deprecation_header_on_success(mock_conn):
    """D-10-15: every /route response carries Deprecation header
    with the EXACT locked-string value. Success path."""
    mock_cursor = _setup_mock_conn(mock_conn)
    mock_cursor.fetchone.side_effect = [{"id": 100}, {"id": 200}]
    mock_cursor.fetchall.side_effect = [
        _mock_dijkstra_iteration_1(), _mock_dijkstra_iteration_2(),
        _mock_dijkstra_empty(), _mock_segment_data(),
    ]
    from app.cache import clear_all_caches
    clear_all_caches()

    client = TestClient(app)
    response = client.post("/route", json={
        "origin": {"lat": 34.05, "lon": -118.24},
        "destination": {"lat": 34.06, "lon": -118.25},
        "max_extra_minutes": 5,
    })
    assert response.status_code == 200
    # EXACT-STRING locked per CONTEXT D-10-15 — do not paraphrase.
    assert response.headers.get("Deprecation") == (
        "weight_iri,weight_potholes ignored as of v0.4.0"
    )


@patch("app.routes.routing.get_connection")
def test_deprecation_header_on_cache_hit(mock_conn):
    """D-10-15 + Pitfall 4: Deprecation header MUST persist through
    the cache-hit early-return path."""
    mock_cursor = _setup_mock_conn(mock_conn)
    # First request: 2 SNAP fetchone + 4 fetchall (3 dijkstra + 1 seg).
    # Second request: 2 SNAP fetchone (audit log path) and then cache hit
    # (no fetchall consumed beyond the first request's allocation).
    mock_cursor.fetchone.side_effect = [
        {"id": 100}, {"id": 200},
        {"id": 100}, {"id": 200},
    ]
    mock_cursor.fetchall.side_effect = [
        _mock_dijkstra_iteration_1(), _mock_dijkstra_iteration_2(),
        _mock_dijkstra_empty(), _mock_segment_data(),
    ]
    from app.cache import clear_all_caches
    clear_all_caches()

    client = TestClient(app)
    # First request — populates cache.
    resp1 = client.post("/route", json={
        "origin": {"lat": 34.05, "lon": -118.24},
        "destination": {"lat": 34.06, "lon": -118.25},
        "max_extra_minutes": 5,
    })
    assert resp1.status_code == 200

    # Second identical request — should hit cache (no fetchall consumed).
    resp2 = client.post("/route", json={
        "origin": {"lat": 34.05, "lon": -118.24},
        "destination": {"lat": 34.06, "lon": -118.25},
        "max_extra_minutes": 5,
    })
    assert resp2.status_code == 200
    # Header MUST be present even on cache hit.
    assert resp2.headers.get("Deprecation") == (
        "weight_iri,weight_potholes ignored as of v0.4.0"
    )


@patch("app.routes.routing.get_connection")
def test_deprecation_header_on_no_route(mock_conn):
    """D-10-15 + Pitfall 4: Deprecation header MUST persist through
    the no-route fallback early-return path."""
    mock_cursor = _setup_mock_conn(mock_conn)
    mock_cursor.fetchone.side_effect = [{"id": 100}, {"id": 200}]
    # All 3 fallback attempts return empty -> 'No route found' branch.
    mock_cursor.fetchall.side_effect = [
        _mock_dijkstra_empty(),  # attempt 1: filtered
        _mock_dijkstra_empty(),  # attempt 2: widened
        _mock_dijkstra_empty(),  # attempt 3: full graph
    ]
    from app.cache import clear_all_caches
    clear_all_caches()

    client = TestClient(app)
    response = client.post("/route", json={
        "origin": {"lat": 34.05, "lon": -118.24},
        "destination": {"lat": 34.06, "lon": -118.25},
        "max_extra_minutes": 5,
    })
    assert response.status_code == 200
    assert response.json().get("warning") == "No route found between these points"
    # Header MUST be present even on no-route fallback.
    assert response.headers.get("Deprecation") == (
        "weight_iri,weight_potholes ignored as of v0.4.0"
    )


@patch("app.routes.routing.get_connection")
def test_cache_key_ignores_weight_fields(mock_conn):
    """D-10-14 + Pitfall 2: cache key no longer differs by weight_iri
    or weight_potholes. Two requests differing ONLY in those fields
    should hit the SAME cache slot — second request is a cache hit
    that consumes ZERO fetchall side effects beyond the audit log
    INSERT."""
    mock_cursor = _setup_mock_conn(mock_conn)
    mock_cursor.fetchone.side_effect = [
        {"id": 100}, {"id": 200},  # first request snap
        {"id": 100}, {"id": 200},  # second request snap (only audit, then cache hit)
    ]
    # Provide segment data ONLY for the first request — if the second
    # request is NOT a cache hit, fetchall will run out and StopIteration.
    mock_cursor.fetchall.side_effect = [
        _mock_dijkstra_iteration_1(), _mock_dijkstra_iteration_2(),
        _mock_dijkstra_empty(), _mock_segment_data(),
        # Intentionally NO further side effects — second request must hit cache.
    ]
    from app.cache import clear_all_caches
    clear_all_caches()

    client = TestClient(app)
    # Request A: weight_iri=50.
    resp_a = client.post("/route", json={
        "origin": {"lat": 34.05, "lon": -118.24},
        "destination": {"lat": 34.06, "lon": -118.25},
        "weight_iri": 50,
        "weight_potholes": 50,
        "max_extra_minutes": 5,
    })
    assert resp_a.status_code == 200

    # Request B: weight_iri=99 (only diff). Should hit the SAME cache slot.
    resp_b = client.post("/route", json={
        "origin": {"lat": 34.05, "lon": -118.24},
        "destination": {"lat": 34.06, "lon": -118.25},
        "weight_iri": 99,
        "weight_potholes": 1,
        "max_extra_minutes": 5,
    })
    assert resp_b.status_code == 200
    # Same response (cache hit).
    assert resp_a.json() == resp_b.json()
