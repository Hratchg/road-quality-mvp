"""Tests for backend/app/main.py - Phase 5 SC #2: CORS restricted to deployed
frontend origin via ALLOWED_ORIGINS env var.

Tests use importlib.reload to re-read the env at module level, since
backend/app/main.py reads ALLOWED_ORIGINS once at import time (intentional -
mirrors db.py's DATABASE_URL pattern; runtime env changes require a process
restart, which Fly handles via 'fly secrets set' triggering a redeploy).
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


def test_cors_reads_allowed_origins_env(monkeypatch):
    """SC #2 core: ALLOWED_ORIGINS env var splits into the allow_origins list."""
    monkeypatch.setenv(
        "ALLOWED_ORIGINS", "https://a.example.com,https://b.example.com"
    )
    from app import main
    importlib.reload(main)
    assert "https://a.example.com" in main.ALLOWED_ORIGINS
    assert "https://b.example.com" in main.ALLOWED_ORIGINS
    assert "*" not in main.ALLOWED_ORIGINS, (
        "wildcard origin must NEVER appear in production allow_origins"
    )


def test_cors_rejects_disallowed_origin(monkeypatch):
    """SC #2 enforcement: a request from a non-allowlisted origin must NOT
    receive an access-control-allow-origin echo of its own origin."""
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://allowed.fly.dev")
    from app import main
    importlib.reload(main)
    client = TestClient(main.app)
    r = client.options(
        "/health",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    # FastAPI's CORSMiddleware: if origin not in allow_origins, the
    # access-control-allow-origin header is omitted (or set to a different
    # value). It must NOT be set to the requesting origin.
    assert r.headers.get("access-control-allow-origin") != "https://evil.example.com"


def test_cors_default_falls_through_to_localhost_in_dev(monkeypatch):
    """PATTERNS P-2 + RESEARCH Pattern 3: when ALLOWED_ORIGINS is unset, fall
    through to localhost:3000 so docker-compose dev startup works without an
    explicit env var. This is the safe-default pattern (mirrors DATABASE_URL),
    NOT the fail-fast pattern (which AUTH_SIGNING_KEY uses).
    """
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    from app import main
    importlib.reload(main)
    assert "http://localhost:3000" in main.ALLOWED_ORIGINS, (
        f"missing-env fallthrough must include localhost:3000; "
        f"got {main.ALLOWED_ORIGINS}"
    )


def test_cors_strips_whitespace_and_filters_empty(monkeypatch):
    """Defensive parser: handles trailing comma, double comma, and leading/trailing whitespace.

    Real-world env-var input from Fly secrets or operator typo:
        ALLOWED_ORIGINS="  https://a.example.com , ,https://b.example.com,"
    Must produce: ["https://a.example.com", "https://b.example.com"]
    """
    monkeypatch.setenv(
        "ALLOWED_ORIGINS",
        "  https://a.example.com , ,https://b.example.com,",
    )
    from app import main
    importlib.reload(main)
    assert main.ALLOWED_ORIGINS == [
        "https://a.example.com",
        "https://b.example.com",
    ], (
        f"defensive parser must strip whitespace + filter empty entries; "
        f"got {main.ALLOWED_ORIGINS}"
    )


def test_cors_allow_credentials_is_true(monkeypatch):
    """RESEARCH Pattern 3: keep allow_credentials=True for forward-compat with
    Phase 6+ cookie sessions. The CORS spec only forbids allow_credentials=True
    paired with allow_origins=['*'] - explicit origins + credentials is fine.
    """
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://allowed.fly.dev")
    from app import main
    importlib.reload(main)
    client = TestClient(main.app)
    r = client.options(
        "/health",
        headers={
            "Origin": "https://allowed.fly.dev",
            "Access-Control-Request-Method": "GET",
        },
    )
    # FastAPI/CORSMiddleware sets access-control-allow-credentials: true when
    # the origin is allowlisted AND allow_credentials=True.
    assert r.headers.get("access-control-allow-credentials") == "true", (
        f"allow_credentials=True must surface as response header; got "
        f"headers={dict(r.headers)}"
    )
