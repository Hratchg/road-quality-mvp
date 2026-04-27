import os

import pytest
import psycopg2
from psycopg2.extras import RealDictCursor

# IMPORTANT: AUTH_SIGNING_KEY must be set BEFORE the FastAPI app is imported,
# because backend/app/auth/tokens.py reads the env var at call-time but
# app.main → app.routes.auth → app.auth.tokens occurs during test collection.
# pytest_configure runs BEFORE collection, so this is the correct hook.
# RESEARCH §8 + PATTERNS Confidence flag #1.
os.environ.setdefault("AUTH_SIGNING_KEY", "test_secret_do_not_use_in_production_padding_padding")

from fastapi.testclient import TestClient
from app.main import app
from app.db import DATABASE_URL


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: marks tests that need a live database")
    # Belt-and-suspenders: ensure AUTH_SIGNING_KEY is set even if a child process
    # or a test that monkeypatches the env didn't restore it. setdefault is
    # idempotent — won't clobber an explicit override from CI.
    os.environ.setdefault("AUTH_SIGNING_KEY", "test_secret_do_not_use_in_production_padding_padding")


@pytest.fixture(scope="session")
def db_available():
    """Check if the database is reachable; skip all integration tests if not."""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.close()
        return True
    except psycopg2.OperationalError:
        pytest.skip("Database not available — skipping integration tests")


@pytest.fixture(scope="session")
def client(db_available):
    return TestClient(app)


@pytest.fixture(scope="session")
def db_conn(db_available):
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    yield conn
    conn.close()


# --- Phase 4 auth fixtures (RESEARCH Pattern 1 override seam) ---


@pytest.fixture
def fake_user_id():
    """Default authenticated user_id for tests; override per-test if needed."""
    return 42


@pytest.fixture
def authed_client(fake_user_id):
    """A TestClient that bypasses JWT verification and presents user_id=fake_user_id.

    Use this for endpoint tests that don't care about the token shape — only that
    the auth dep returned a user. For tests that need to exercise the real JWT
    decode path (e.g., test_alg_none_rejected at the route layer), use the plain
    `client` fixture and craft a real token via app.auth.tokens.encode_token.
    """
    from app.auth.dependencies import get_current_user_id
    app.dependency_overrides[get_current_user_id] = lambda: fake_user_id
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user_id, None)
