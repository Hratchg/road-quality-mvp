"""Integration tests for backend/app/routes/auth.py + auth gating on
/route + /cache/*. Phase 4 SC #1, #2, #3, #4.

pytestmark = pytest.mark.integration because the happy path needs a live DB.
401-enforcement tests are bundled here for cohesion; they auto-skip when
DB is down via the conftest db_available chain. Cleanup namespaces test
emails with `test-04-03-` and DELETEs them in a session-scoped fixture.
"""

from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.auth.tokens import decode_token, encode_token

pytestmark = pytest.mark.integration

ROUTE_BODY = {
    "origin": {"lat": 34.05, "lon": -118.24},
    "destination": {"lat": 34.06, "lon": -118.25},
    "include_iri": True,
    "include_potholes": True,
    "weight_iri": 50,
    "weight_potholes": 50,
    "max_extra_minutes": 5,
}


@pytest.fixture(scope="module", autouse=True)
def cleanup_test_users(db_conn):
    """Delete any test-04-03-* users that survived prior runs and after."""
    with db_conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE email LIKE 'test-04-03-%'")
    db_conn.commit()
    yield
    with db_conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE email LIKE 'test-04-03-%'")
    db_conn.commit()


# --- SC #1: Register ---

def test_register_success_returns_201_with_token(client):
    resp = client.post("/auth/register", json={
        "email": "test-04-03-r1@example.com",
        "password": "hunter22pass",
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert isinstance(body["user_id"], int) and body["user_id"] > 0
    assert body["email"] == "test-04-03-r1@example.com"
    assert isinstance(body["access_token"], str)
    assert body["access_token"].count(".") == 2  # JWT: header.body.sig
    assert body["token_type"] == "bearer"


def test_register_duplicate_email_returns_400(client):
    client.post("/auth/register", json={
        "email": "test-04-03-r2@example.com",
        "password": "first-pw-12",
    })
    resp = client.post("/auth/register", json={
        "email": "test-04-03-r2@example.com",
        "password": "different-pw-12",
    })
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Email already registered"


def test_register_invalid_email_returns_422(client):
    resp = client.post("/auth/register", json={
        "email": "not-an-email",
        "password": "hunter22pass",
    })
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert any("email" in str(e.get("loc", [])) for e in detail)


def test_register_short_password_returns_422(client):
    resp = client.post("/auth/register", json={
        "email": "test-04-03-r4@example.com",
        "password": "tiny",  # 4 chars; min_length=8
    })
    assert resp.status_code == 422


def test_register_normalizes_email_case(client):
    """Pitfall 3: User@Example.COM and user@example.com are the same account."""
    r1 = client.post("/auth/register", json={
        "email": "test-04-03-NORM@Example.COM",
        "password": "hunter22pass",
    })
    assert r1.status_code == 201, r1.text
    r2 = client.post("/auth/register", json={
        "email": "test-04-03-norm@example.com",
        "password": "different-pw",
    })
    assert r2.status_code == 400
    assert r2.json()["detail"] == "Email already registered"


# --- SC #2: Login ---

def test_login_success_returns_200_with_token(client):
    client.post("/auth/register", json={
        "email": "test-04-03-l1@example.com",
        "password": "correctpw12",
    })
    resp = client.post("/auth/login", json={
        "email": "test-04-03-l1@example.com",
        "password": "correctpw12",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body["access_token"], str)
    assert body["token_type"] == "bearer"
    payload = decode_token(body["access_token"])
    # sub is the user_id as a string per OWASP convention
    assert payload["sub"].isdigit()


def test_login_wrong_password_returns_401(client):
    client.post("/auth/register", json={
        "email": "test-04-03-l2@example.com",
        "password": "correctpw34",
    })
    resp = client.post("/auth/login", json={
        "email": "test-04-03-l2@example.com",
        "password": "wrongpw34",
    })
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid credentials"


def test_login_unknown_email_returns_401_same_detail(client):
    """Enumeration defense: unknown email and wrong password return identical detail."""
    resp = client.post("/auth/login", json={
        "email": "test-04-03-no-such@example.com",
        "password": "anything12",
    })
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid credentials"


# --- SC #3: Gating ---

def test_route_without_token_returns_401(client):
    resp = client.post("/route", json=ROUTE_BODY)
    assert resp.status_code == 401, resp.text


def test_route_with_bad_token_returns_401(client):
    resp = client.post(
        "/route",
        headers={"Authorization": "Bearer not-a-real-jwt"},
        json=ROUTE_BODY,
    )
    assert resp.status_code == 401


def test_route_with_alg_none_token_returns_401(client):
    """Pitfall 2 at the route layer: alg=none bypass attempt is rejected."""
    def _b64(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    header = _b64({"alg": "none", "typ": "JWT"})
    body = _b64({"sub": "1", "iat": 0, "exp": 9_999_999_999})
    none_tok = f"{header}.{body}."
    resp = client.post(
        "/route",
        headers={"Authorization": f"Bearer {none_tok}"},
        json=ROUTE_BODY,
    )
    assert resp.status_code == 401


def test_cache_stats_without_token_returns_401(client):
    resp = client.get("/cache/stats")
    assert resp.status_code == 401


def test_cache_clear_without_token_returns_401(client):
    resp = client.post("/cache/clear")
    assert resp.status_code == 401


def test_health_remains_public(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_segments_remains_public(client):
    """SC #3 negative half: /segments stays open even without a token."""
    resp = client.get("/segments?bbox=-118.26,34.04,-118.23,34.07")
    # 200 when DB has segments; 5xx when DB unreachable; never 401/403.
    assert resp.status_code != 401
    assert resp.status_code != 403


def test_route_with_dep_override_authorizes(authed_client):
    """The auth gate is the only thing this test exercises. Whether /route
    actually returns 200 depends on whether the DB has a routable graph.
    Acceptable codes: 200 (graph present), 502/503 (DB unreachable), 500
    (route engine error). The CRITICAL invariant: NOT 401."""
    resp = authed_client.post("/route", json=ROUTE_BODY)
    assert resp.status_code != 401, (
        f"authed_client overrides get_current_user_id; should never see 401. "
        f"got {resp.status_code}: {resp.text[:200]}"
    )


# --- SC #4: Hashing ---

def test_password_hash_in_db_is_argon2id_not_plaintext(client, db_conn):
    plaintext_marker = "unique-marker-987-abc"
    client.post("/auth/register", json={
        "email": "test-04-03-h1@example.com",
        "password": plaintext_marker,
    })
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT password_hash FROM users WHERE email = %s",
            ("test-04-03-h1@example.com",),
        )
        row = cur.fetchone()
    assert row is not None, "registered user must exist in users table"
    encoded = row["password_hash"] if isinstance(row, dict) else row[0]
    assert encoded.startswith("$argon2id$"), (
        f"password_hash must be argon2id encoded; got prefix {encoded[:20]!r}"
    )
    assert plaintext_marker not in encoded, (
        "password_hash must NEVER contain the plaintext (SC #4)"
    )


# --- /auth/logout ---

def test_logout_returns_204_no_body(client):
    resp = client.post("/auth/logout")
    assert resp.status_code == 204
    assert resp.content == b""
