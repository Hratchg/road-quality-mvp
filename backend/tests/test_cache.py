import pytest

from app.cache import (
    get_segments_cached,
    set_segments_cached,
    get_route_cached,
    set_route_cached,
    clear_all_caches,
    make_route_cache_key,
    segments_cache,
    route_cache,
)
from fastapi.testclient import TestClient
from app.main import app
from app.auth.dependencies import get_current_user_id


@pytest.fixture(autouse=True)
def _override_auth():
    """Bypass JWT verification for /cache/* endpoint tests — these tests
    cover cache logic, not the auth gate (covered by test_auth_routes.py)."""
    app.dependency_overrides[get_current_user_id] = lambda: 1
    yield
    app.dependency_overrides.pop(get_current_user_id, None)


def setup_function():
    """Clear caches before each test to avoid cross-test contamination."""
    clear_all_caches()


def test_cache_set_and_get():
    """Basic cache store and retrieve for both segments and route caches."""
    seg_data = {"type": "FeatureCollection", "features": [{"id": 1}]}
    set_segments_cached("bbox_key_1", seg_data)
    assert get_segments_cached("bbox_key_1") == seg_data

    route_data = {"fastest_route": {}, "best_route": {}}
    set_route_cached("hash_abc", route_data)
    assert get_route_cached("hash_abc") == route_data


def test_cache_miss_returns_none():
    """A lookup on a key that was never set should return None."""
    assert get_segments_cached("nonexistent_bbox") is None
    assert get_route_cached("nonexistent_hash") is None


def test_clear_all_caches():
    """clear_all_caches should evict every entry from both caches."""
    set_segments_cached("k1", {"data": 1})
    set_segments_cached("k2", {"data": 2})
    set_route_cached("r1", {"route": 1})

    assert segments_cache.currsize == 2
    assert route_cache.currsize == 1

    clear_all_caches()

    assert segments_cache.currsize == 0
    assert route_cache.currsize == 0
    assert get_segments_cached("k1") is None
    assert get_route_cached("r1") is None


def test_make_route_cache_key_deterministic():
    """Same inputs should always produce the same hash."""
    key1 = make_route_cache_key(34.05, -118.24, 34.06, -118.25, True, True, 50, 50, 5)
    key2 = make_route_cache_key(34.05, -118.24, 34.06, -118.25, True, True, 50, 50, 5)
    assert key1 == key2


def test_make_route_cache_key_differs_on_param_change():
    """Different parameters should produce different hashes."""
    key1 = make_route_cache_key(34.05, -118.24, 34.06, -118.25, True, True, 50, 50, 5)
    key2 = make_route_cache_key(34.05, -118.24, 34.06, -118.25, True, True, 60, 40, 5)
    assert key1 != key2


def test_cache_stats_endpoint():
    """GET /cache/stats should return current cache sizes and maxsizes."""
    clear_all_caches()
    client = TestClient(app)
    response = client.get("/cache/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["segments_cache_size"] == 0
    assert data["route_cache_size"] == 0
    assert data["segments_cache_maxsize"] == 256
    assert data["route_cache_maxsize"] == 128


def test_cache_clear_endpoint():
    """POST /cache/clear should evict all entries and return cleared: true."""
    set_segments_cached("test_key", {"x": 1})
    client = TestClient(app)
    response = client.post("/cache/clear")
    assert response.status_code == 200
    assert response.json() == {"cleared": True}
    assert get_segments_cached("test_key") is None
