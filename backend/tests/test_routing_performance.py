"""Phase 8 — live-DB performance regression tests for /route.

PERF-01: cross-LA trip (~20 km) returns < 5s uncached.
PERF-02: short DTLA-local trip remains <= 2s uncached (no regression).

These tests run against a fully-seeded local DB. They auto-skip on CI / any
DB without `road_segments_vertices_pgr` populated, via the existing
`db_has_topology` fixture in conftest.py.
"""
import time

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user_id
from app.cache import route_cache
from app.main import app

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _override_auth():
    """Bypass JWT verification for all tests in this module — these tests
    cover routing perf, not the auth gate (covered by test_auth_routes.py)."""
    app.dependency_overrides[get_current_user_id] = lambda: 1
    yield
    app.dependency_overrides.pop(get_current_user_id, None)


def _post_uncached_route(body: dict) -> tuple[int, float, dict]:
    """Clear route_cache, POST /route, return (status_code, elapsed_s, body_json)."""
    route_cache.clear()
    client = TestClient(app)
    t0 = time.perf_counter()
    resp = client.post("/route", json=body)
    elapsed = time.perf_counter() - t0
    return resp.status_code, elapsed, resp.json()


@pytest.mark.integration
@pytest.mark.timeout(15)
def test_dtla_under_2s(db_has_topology):
    """PERF-02: short DTLA-local trip <= 2s uncached.

    Anchors the no-regression budget — cross-LA fix in Plan 08-03 must not
    slow down short trips.
    """
    body = {
        "origin": {"lat": 34.0522, "lon": -118.2437},       # DTLA core
        "destination": {"lat": 34.0689, "lon": -118.2531},  # Echo Park (~2 km N)
        "include_iri": True,
        "include_potholes": True,
        "weight_iri": 50,
        "weight_potholes": 50,
        "max_extra_minutes": 5,
    }
    status, elapsed, _ = _post_uncached_route(body)
    assert status == 200
    assert elapsed < 2.0, (
        f"PERF-02 regression: DTLA route took {elapsed:.2f}s (budget 2.0s)"
    )


@pytest.mark.integration
@pytest.mark.timeout(15)
def test_cross_la_under_5s(db_has_topology):
    """PERF-01: cross-LA trip < 5s uncached.

    West LA / Sawtelle -> Pasadena, ~20 km diagonal. Pre-fix this is the
    > 90s timeout case from commit 704a70c. Post-fix (Plan 08-02 + 08-03)
    must complete in < 5 seconds.
    """
    body = {
        "origin": {"lat": 34.0489, "lon": -118.4521},        # West LA / Sawtelle
        "destination": {"lat": 34.1478, "lon": -118.1445},   # Pasadena
        "include_iri": True,
        "include_potholes": True,
        "weight_iri": 50,
        "weight_potholes": 50,
        "max_extra_minutes": 5,
    }
    status, elapsed, _ = _post_uncached_route(body)
    assert status == 200
    assert elapsed < 5.0, (
        f"PERF-01 regression: cross-LA route took {elapsed:.2f}s (budget 5.0s)"
    )
