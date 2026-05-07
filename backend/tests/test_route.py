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
    """Segment data for edges referenced by ksp."""
    return [
        {
            "id": 1, "travel_time_s": 60.0, "iri_norm": 0.8,
            "pothole_score_total": 3.0, "moderate_score": 1.5, "severe_score": 1.5,
            "geojson": '{"type":"LineString","coordinates":[[-118.24,34.05],[-118.245,34.055]]}',
        },
        {
            "id": 2, "travel_time_s": 60.0, "iri_norm": 0.7,
            "pothole_score_total": 2.0, "moderate_score": 1.0, "severe_score": 1.0,
            "geojson": '{"type":"LineString","coordinates":[[-118.245,34.055],[-118.25,34.06]]}',
        },
        {
            "id": 3, "travel_time_s": 70.0, "iri_norm": 0.2,
            "pothole_score_total": 0.5, "moderate_score": 0.3, "severe_score": 0.2,
            "geojson": '{"type":"LineString","coordinates":[[-118.24,34.05],[-118.242,34.058]]}',
        },
        {
            "id": 4, "travel_time_s": 70.0, "iri_norm": 0.1,
            "pothole_score_total": 0.0, "moderate_score": 0.0, "severe_score": 0.0,
            "geojson": '{"type":"LineString","coordinates":[[-118.242,34.058],[-118.25,34.06]]}',
        },
    ]


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
    mock_cursor.fetchall.side_effect = [
        _mock_ksp_results(),
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
    mock_cursor.fetchall.side_effect = [
        _mock_ksp_results(),
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
