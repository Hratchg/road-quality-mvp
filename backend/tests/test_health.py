"""Tests for backend/app/routes/health.py - Phase 5 SC #5: /health reports
DB reachability for LB probes.

200 + {status:"ok", db:"reachable"} on success (PRD M0 contract preserved).
503 + {detail:{status:"unhealthy", db:"unreachable"}} on any DB failure.

Tests mock app.routes.health.get_connection to avoid touching a real DB -
this is a unit test, not an integration test. The integration form of /health
is exercised by the manual smoke UAT in Plan 05-05's deploy workflow.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import psycopg2
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok_when_db_reachable():
    """SC #5 happy path: 200 + {status:'ok', db:'reachable'}.

    The {status:'ok'} key is preserved for PRD M0 client-compat; the
    {db:'reachable'} field is additive.
    """
    with patch("app.routes.health.get_connection") as mock_conn:
        # Build a context manager mock chain:
        # get_connection() -> conn -> cursor() -> fetchone()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)

        mock_cursor_cm = MagicMock()
        mock_cursor_cm.__enter__.return_value = mock_cursor

        mock_conn_obj = MagicMock()
        mock_conn_obj.cursor.return_value = mock_cursor_cm

        mock_conn.return_value.__enter__.return_value = mock_conn_obj
        mock_conn.return_value.__exit__.return_value = False

        r = client.get("/health")

    assert r.status_code == 200, f"happy path must be 200; got {r.status_code}: {r.text}"
    body = r.json()
    assert body["status"] == "ok", f"PRD M0 contract requires status:ok; got {body}"
    assert body["db"] == "reachable", f"SC #5 requires db:reachable; got {body}"


def test_health_503_when_db_unreachable():
    """SC #5 unhealthy path: 503 + dict detail with db:unreachable.

    Fly's HTTP health check treats non-2xx as unhealthy and depools the
    machine (NOT restart - see RESEARCH Pitfall 5). So 503 is the right
    code for transient DB issues.
    """
    with patch("app.routes.health.get_connection") as mock_conn:
        mock_conn.side_effect = psycopg2.OperationalError("connection refused")
        r = client.get("/health")

    assert r.status_code == 503, f"unhealthy path must be 503; got {r.status_code}: {r.text}"
    body = r.json()
    # FastAPI serializes HTTPException(detail=dict) as {"detail": {...}}
    assert body["detail"]["status"] == "unhealthy", f"got {body}"
    assert body["detail"]["db"] == "unreachable", f"got {body}"


def test_health_503_does_not_leak_db_error_details():
    """Threat T-05-05/T-05-07 mitigation: psycopg2 error messages may include
    host, port, and (rarely but possibly) password fragments. /health is a
    public endpoint - its 503 response body MUST surface only the static
    'unreachable' string, never the exception message.
    """
    secret_msg = (
        'FATAL: password authentication failed for user "rq" at '
        "host=secret-host.fly.dev port=5432"
    )
    with patch("app.routes.health.get_connection") as mock_conn:
        mock_conn.side_effect = psycopg2.OperationalError(secret_msg)
        r = client.get("/health")

    assert r.status_code == 503
    body_text = r.text
    for sensitive in ("secret-host.fly.dev", "5432", "password authentication"):
        assert sensitive not in body_text, (
            f"/health 503 body MUST NOT leak DB error details; found "
            f"{sensitive!r} in body: {body_text!r}"
        )
