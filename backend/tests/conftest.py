import pytest
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi.testclient import TestClient
from app.main import app
from app.db import DATABASE_URL


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: marks tests that need a live database")


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
