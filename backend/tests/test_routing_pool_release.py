"""Integration test for SC #9: backend/app/routes/routing.py releases its
pooled connection on the exception path.

Mocks one of routing.py's SQL constants to invalid SQL so psycopg2 raises
inside the `with get_connection() as conn:` block. Asserts the pool's
internal `_used` count is back to baseline AFTER the request resolves —
proving the pool wrapper's try/finally putconn ran even though the caller
raised.

This test exercises the REAL pool against the LIVE DB. It auto-skips when
the DB is unreachable via the standard db_available fixture chain.

Phase 5 SC #9 + RESEARCH §7 + Pattern 4 (the pool wrapper IS the leak fix).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import db
from app.cache import route_cache
from app.main import app
from app.auth.dependencies import get_current_user_id
from app.routes import routing as routing_module

pytestmark = pytest.mark.integration


def test_route_handler_releases_pool_slot_on_exception(db_available, monkeypatch):
    """When /route raises mid-query, the pool slot MUST release.

    This is the SC #9 regression gate. If the pool wrapper's try/finally
    putconn is ever removed (e.g., by a refactor that uses Depends-style
    dep injection without thinking through error paths), this test fails
    with the pool's _used count permanently incremented.
    """
    # Force the pool to initialize with at least one warm connection so we
    # have a real baseline to compare against. Use the public get_pool_stats()
    # helper instead of reaching into pool._used directly (WR-02 fix); the
    # helper isolates the test from psycopg2's private-API renames.
    pool = db._get_pool()
    baseline_used = db.get_pool_stats()["used"]
    pool_id = id(pool)

    # Clear the in-memory route cache so a previous test that populated it
    # (via mocked fixtures in test_route.py) cannot serve a 200 response
    # for our request body and bypass the SQL we want to fail.
    route_cache.clear()

    # Inject invalid SQL into routing.py's SNAP_NODE_SQL constant so the
    # FIRST cur.execute() inside the route handler raises a psycopg2
    # syntax error. This simulates the real-world failure mode (a
    # transient DB hiccup, a malformed query during a refactor) without
    # needing to mock psycopg2 itself.
    invalid_sql = "SELECT this_column_does_not_exist FROM definitely_no_such_table_xyz"
    monkeypatch.setattr(routing_module, "SNAP_NODE_SQL", invalid_sql)

    # Use raise_server_exceptions=False so Starlette converts the unhandled
    # psycopg2 error into a 500 response instead of re-raising it into the
    # test. The pool-release behavior we're verifying happens INSIDE the
    # request lifecycle either way — this just gives us a status code to
    # assert on without losing the test outcome.
    app.dependency_overrides[get_current_user_id] = lambda: 42
    try:
        client = TestClient(app, raise_server_exceptions=False)

        body = {
            "origin": {"lat": 34.05, "lon": -118.24},
            "destination": {"lat": 34.06, "lon": -118.25},
            "include_iri": True,
            "include_potholes": True,
            "weight_iri": 50,
            "weight_potholes": 50,
            "max_extra_minutes": 5,
        }

        # The request MUST raise inside the route handler. FastAPI surfaces
        # the unhandled psycopg2 error as a 500. We don't care about the exact
        # status — we care about the pool state AFTER.
        response = client.post("/route", json=body)
        assert response.status_code >= 500, (
            f"injected SQL must trigger 5xx; got {response.status_code}: {response.text[:200]}"
        )
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)

    # The CRITICAL assertion: pool slot returned to baseline. Read via
    # the public get_pool_stats() helper (WR-02) — keeps the gate stable
    # if a future psycopg2 release renames or removes _used.
    after_used = db.get_pool_stats()["used"]
    assert after_used == baseline_used, (
        f"SC #9 LEAK: pool used count went from {baseline_used} to {after_used}. "
        f"The pool wrapper's try/finally putconn did not release the slot on "
        f"the exception path. This is the exact bug Phase 5 was supposed to fix."
    )

    # Defensive: ensure no test side-effect created a NEW pool object.
    assert id(db._get_pool()) == pool_id, (
        "pool instance must remain stable across requests — a test that "
        "replaces the pool would mask leaks in subsequent tests"
    )
