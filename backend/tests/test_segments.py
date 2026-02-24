from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app


def _mock_segments():
    """Return fake segment rows as if from DB."""
    return [
        {
            "id": 1,
            "geojson": '{"type":"LineString","coordinates":[[-118.24,34.05],[-118.25,34.06]]}',
            "iri_norm": 0.4,
            "moderate_score": 1.5,
            "severe_score": 0.5,
            "pothole_score_total": 2.0,
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
