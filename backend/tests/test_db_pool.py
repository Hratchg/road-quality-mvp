"""Unit tests for backend/app/db.py's ThreadedConnectionPool wrapper.

Phase 5 SC #6: connections are pooled.
Phase 5 SC #9 (unit form): the pool wrapper's putconn-in-finally guarantees
slot release on every exit path, including exceptions. The integration form
of SC #9 lives in test_routing_pool_release.py.

These tests are pure unit tests — no DB required, no integration marker.
They patch app.db._get_pool to inject a MagicMock pool and verify that
get_connection() correctly delegates to getconn/putconn.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import psycopg2.extras

from app import db


def test_get_connection_calls_putconn_on_success():
    """Happy path: pool.getconn on enter, pool.putconn on exit."""
    fake_conn = MagicMock()
    fake_pool = MagicMock()
    fake_pool.getconn.return_value = fake_conn
    with patch.object(db, "_get_pool", return_value=fake_pool):
        with db.get_connection() as conn:
            assert conn is fake_conn, "context manager must yield the pool's conn"
            fake_pool.getconn.assert_called_once()
            fake_pool.putconn.assert_not_called()  # not yet — only on exit
        fake_pool.putconn.assert_called_once_with(fake_conn)


def test_get_connection_calls_putconn_on_exception():
    """SC #9 (unit form): slot releases even if caller raises mid-block."""
    fake_conn = MagicMock()
    fake_pool = MagicMock()
    fake_pool.getconn.return_value = fake_conn
    with patch.object(db, "_get_pool", return_value=fake_pool):
        with pytest.raises(ValueError, match="boom mid-query"):
            with db.get_connection() as conn:
                assert conn is fake_conn
                raise ValueError("boom mid-query")
        fake_pool.putconn.assert_called_once_with(fake_conn)


def test_get_connection_lazy_pool_init():
    """Pool is created on first use, cached thereafter (single instance per process).

    This matters because tests may set DATABASE_URL via fixture BEFORE the pool
    opens its first connection — eager init at module import would race the fixture.
    """
    # Reset state.
    original = db._connection_pool
    db._connection_pool = None
    try:
        with patch("psycopg2.pool.ThreadedConnectionPool") as MockPool:
            instance = MagicMock()
            MockPool.return_value = instance
            p1 = db._get_pool()
            p2 = db._get_pool()
            assert p1 is p2 is instance, "pool must be cached after first init"
            assert MockPool.call_count == 1, (
                f"pool constructor must run exactly once; got {MockPool.call_count}"
            )
    finally:
        db._connection_pool = original


def test_pool_uses_real_dict_cursor():
    """The pool MUST forward cursor_factory=RealDictCursor so the ~30
    row["id"] / row["password_hash"] call sites across segments.py, routing.py,
    and auth.py keep working unchanged after the migration.

    Regression guard: if someone refactors db.py and drops cursor_factory,
    every dict-style row access breaks at runtime with TypeError: tuple indices
    must be integers, not str. This test catches that at import time.
    """
    original = db._connection_pool
    db._connection_pool = None
    try:
        with patch("psycopg2.pool.ThreadedConnectionPool") as MockPool:
            MockPool.return_value = MagicMock()
            db._get_pool()
            assert MockPool.call_count == 1
            kwargs = MockPool.call_args.kwargs
            assert kwargs.get("cursor_factory") is psycopg2.extras.RealDictCursor, (
                f"pool must be initialized with cursor_factory=RealDictCursor; "
                f"got cursor_factory={kwargs.get('cursor_factory')!r}"
            )
            assert kwargs.get("minconn") == 2, f"minconn must be 2; got {kwargs.get('minconn')}"
            assert kwargs.get("maxconn") == 12, f"maxconn must be 12; got {kwargs.get('maxconn')}"
    finally:
        db._connection_pool = original
