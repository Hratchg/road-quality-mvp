"""Test migration 003_users.sql: idempotency, locked column shape, UNIQUE
email index, app-layer-vs-DB-layer case-sensitivity contract, and the
no-seed-INSERT invariant. Auto-skip when DB unreachable (via the db_conn /
db_available fixtures in conftest.py).

Tests use raw psycopg2 (matches project convention; no SQLAlchemy). The
test file uses RealDictCursor by default (db_conn fixture) — handle dict
rows accordingly.

Phase 4 SC #5: "A new migration in db/migrations/ adds the users table;
the migration applies cleanly to a fresh DB via the existing init flow."
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import errors as pgerr

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = REPO_ROOT / "db" / "migrations" / "003_users.sql"


@pytest.fixture
def applied_migration(db_conn):
    """Apply the migration before each test. Idempotent — safe to call repeatedly."""
    sql = MIGRATION_PATH.read_text()
    with db_conn.cursor() as cur:
        cur.execute(sql)
    db_conn.commit()
    return db_conn


def _scalar(row):
    """Helper: extract the first scalar from either a dict row or a tuple row."""
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


def test_migration_idempotent(db_conn):
    """Apply migration twice — second apply must not error.
    The IF NOT EXISTS guards on both CREATE TABLE and CREATE UNIQUE INDEX
    make re-application a clean no-op."""
    sql = MIGRATION_PATH.read_text()
    with db_conn.cursor() as cur:
        cur.execute(sql)
        db_conn.commit()
        cur.execute(sql)  # second apply
        db_conn.commit()
        # users_email_key index must exist exactly once.
        cur.execute(
            "SELECT COUNT(*) AS c FROM pg_indexes WHERE indexname = 'users_email_key'"
        )
        row = cur.fetchone()
        count = row["c"] if isinstance(row, dict) else row[0]
        assert count == 1, f"users_email_key must exist exactly once, got {count}"


def test_users_table_has_locked_column_shape(applied_migration):
    """The four locked columns from 04-CONTEXT.md must be present with exact types.
    Regression guard against someone changing BIGSERIAL→SERIAL, dropping NOT NULL,
    or removing the DEFAULT NOW() on created_at."""
    with applied_migration.cursor() as cur:
        cur.execute(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_name = 'users' "
            "ORDER BY ordinal_position"
        )
        cols = {row["column_name"]: row for row in cur.fetchall()}
    assert set(cols.keys()) == {"id", "email", "password_hash", "created_at"}, (
        f"users table must have exactly the locked columns; got {set(cols.keys())}"
    )
    # id: bigint (BIGSERIAL → bigint with sequence default)
    assert cols["id"]["data_type"] == "bigint", (
        f"id must be bigint (BIGSERIAL); got {cols['id']['data_type']}"
    )
    # email: text NOT NULL
    assert cols["email"]["data_type"] == "text"
    assert cols["email"]["is_nullable"] == "NO"
    # password_hash: text NOT NULL
    assert cols["password_hash"]["data_type"] == "text"
    assert cols["password_hash"]["is_nullable"] == "NO"
    # created_at: timestamp with time zone NOT NULL DEFAULT NOW()
    assert cols["created_at"]["data_type"] == "timestamp with time zone"
    assert cols["created_at"]["is_nullable"] == "NO"
    assert cols["created_at"]["column_default"] is not None
    assert "now()" in cols["created_at"]["column_default"].lower()


def test_email_unique_index_rejects_duplicates(applied_migration):
    """Second INSERT with the same email must raise UniqueViolation."""
    test_email = "dup-test@example.com"
    with applied_migration.cursor() as cur:
        # Cleanup any leftover from prior runs.
        cur.execute("DELETE FROM users WHERE email = %s", (test_email,))
        applied_migration.commit()
        cur.execute(
            "INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id",
            (test_email, "$argon2id$placeholder_first"),
        )
        applied_migration.commit()
        with pytest.raises(pgerr.UniqueViolation):
            cur.execute(
                "INSERT INTO users (email, password_hash) VALUES (%s, %s)",
                (test_email, "$argon2id$placeholder_second"),
            )
        applied_migration.rollback()
        # Cleanup.
        cur.execute("DELETE FROM users WHERE email = %s", (test_email,))
        applied_migration.commit()


def test_email_uniqueness_is_case_sensitive_at_db_layer(applied_migration):
    """The DB stores emails byte-exact — User@Example.com and user@example.com
    are TWO distinct rows at the DB layer. App-layer normalization (lowercasing
    in _normalize_email) is what enforces case-insensitive uniqueness — see
    04-RESEARCH.md Pitfall 3. This test documents the intentional contract.
    Regression guard: if someone adds a LOWER(email) functional index later
    without also updating the app-layer SELECTs, this test fails LOUD."""
    mixed = "User@Example.com"
    lower = "user@example.com"
    with applied_migration.cursor() as cur:
        cur.execute("DELETE FROM users WHERE email IN (%s, %s)", (mixed, lower))
        applied_migration.commit()
        cur.execute(
            "INSERT INTO users (email, password_hash) VALUES (%s, %s)",
            (mixed, "$argon2id$placeholder"),
        )
        applied_migration.commit()
        # Insert the lowercased form — DB allows it because email is byte-exact.
        cur.execute(
            "INSERT INTO users (email, password_hash) VALUES (%s, %s)",
            (lower, "$argon2id$placeholder"),
        )
        applied_migration.commit()
        cur.execute(
            "SELECT COUNT(*) AS c FROM users WHERE email IN (%s, %s)", (mixed, lower)
        )
        row = cur.fetchone()
        count = row["c"] if isinstance(row, dict) else row[0]
        assert count == 2, (
            "DB-layer email uniqueness is byte-exact; app-layer lowercasing is "
            "the case-insensitivity guarantee (see _normalize_email in routes/auth.py)"
        )
        # Cleanup.
        cur.execute("DELETE FROM users WHERE email IN (%s, %s)", (mixed, lower))
        applied_migration.commit()


def test_demo_user_not_seeded_by_migration(applied_migration):
    """The migration must not seed the demo user (D-05 + RESEARCH §7).
    Demo seeding lives in scripts/seed_demo_user.py (plan 04-05) so password
    hashes don't bake into git history. Regression guard: if anyone adds an
    INSERT INTO users to 003_users.sql, the demo email shows up here.

    The test isolates against Tests 3/4 leftovers by filtering for the
    specific demo email locked in CONTEXT.md D-05."""
    demo_email = "demo@road-quality-mvp.dev"
    with applied_migration.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS c FROM users WHERE email = %s", (demo_email,)
        )
        row = cur.fetchone()
        count = row["c"] if isinstance(row, dict) else row[0]
        assert count == 0, (
            f"Migration 003_users.sql must NOT seed the demo user "
            f"(D-05 says scripts/seed_demo_user.py owns this). "
            f"Found {count} rows with email={demo_email}."
        )
