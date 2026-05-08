from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app


def _mock_segments():
    """Return fake segment rows as if from DB.

    Plan 10-03 (D-10-17): crash_norm added. Default 0.0 here so the existing
    test_segments_returns_geojson assertions stay numerically stable.
    """
    return [
        {
            "id": 1,
            "geojson": '{"type":"LineString","coordinates":[[-118.24,34.05],[-118.25,34.06]]}',
            "iri_norm": 0.4,
            "moderate_score": 1.5,
            "severe_score": 0.5,
            "pothole_score_total": 2.0,
            "crash_norm": 0.0,
        }
    ]


@patch("app.routes.segments.get_connection")
def test_segments_returns_geojson(mock_conn):
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = _mock_segments()
    mock_conn.return_value.__enter__ = lambda s: s
    mock_conn.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn.return_value.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.return_value.cursor.return_value.__exit__ = MagicMock(return_value=False)

    client = TestClient(app)
    response = client.get("/segments?bbox=-118.26,34.04,-118.23,34.07")
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 1
    assert data["features"][0]["properties"]["iri_norm"] == 0.4


def test_segments_rejects_missing_bbox():
    client = TestClient(app)
    response = client.get("/segments")
    assert response.status_code == 422


@patch("app.routes.segments.get_connection")
def test_segments_includes_crash_norm(mock_conn):
    """D-10-17 + D-10-18: every feature's properties dict has
    crash_norm. Phase 11 frontend depends on this field. Default
    to 0.0 numeric (not None/null) for segments without crashes."""
    mock_cursor = MagicMock()
    # Two rows: one with crash, one without.
    mock_cursor.fetchall.return_value = [
        {
            "id": 1,
            "geojson": '{"type":"LineString","coordinates":[[-118.24,34.05],[-118.25,34.06]]}',
            "iri_norm": 0.4, "moderate_score": 1.5, "severe_score": 0.5,
            "pothole_score_total": 2.0, "crash_norm": 0.7,
        },
        {
            "id": 2,
            "geojson": '{"type":"LineString","coordinates":[[-118.25,34.06],[-118.26,34.07]]}',
            "iri_norm": 0.2, "moderate_score": 0.0, "severe_score": 0.0,
            "pothole_score_total": 0.0, "crash_norm": 0.0,
        },
    ]
    mock_conn.return_value.__enter__ = lambda s: s
    mock_conn.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn.return_value.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.return_value.cursor.return_value.__exit__ = MagicMock(return_value=False)

    # Use a unique bbox to bypass any segments_cache from prior tests.
    from app.cache import clear_all_caches
    clear_all_caches()

    client = TestClient(app)
    response = client.get("/segments?bbox=-118.27,34.04,-118.23,34.08")
    assert response.status_code == 200
    features = response.json()["features"]
    assert len(features) == 2
    # crash_norm present on EVERY feature (D-10-17).
    for f in features:
        assert "crash_norm" in f["properties"], (
            "crash_norm missing from feature properties; "
            "Phase 11 frontend depends on this."
        )
    # Defaults to 0.0 numeric (not None/null) for segments without
    # crashes (D-10-18).
    assert features[1]["properties"]["crash_norm"] == 0.0
    assert isinstance(features[1]["properties"]["crash_norm"], (int, float))
    # Non-zero passes through.
    assert features[0]["properties"]["crash_norm"] == 0.7
