"""Test migration 004_crash_records.sql: idempotency, FK type (INTEGER not BIGINT
per Pitfall D), segment_scores.crash_norm column add, geom shape, severity CHECK
constraint enforcement. Auto-skip when DB unreachable (db_conn / db_available
fixtures in conftest.py).

Tests must run AFTER seed_data.py has been applied at least once (so road_segments
contains rows the inserts can reference for the FK test). The test file uses raw
psycopg2 (project convention; no SQLAlchemy).
"""

from __future__ import annotations

from pathlib import Path

import psycopg2
import pytest
from psycopg2 import errors as pgerr

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = REPO_ROOT / "db" / "migrations" / "004_crash_records.sql"


@pytest.fixture
def applied_migration(db_conn):
    """Apply migration 004 before each test. Idempotent — safe to call repeatedly."""
    sql = MIGRATION_PATH.read_text()
    with db_conn.cursor() as cur:
        cur.execute(sql)
    db_conn.commit()
    return db_conn


def test_migration_004_idempotent(db_conn):
    """Apply migration twice — second apply must not error.

    Verifies unique index and CHECK constraints exist exactly once after the
    second apply (idempotency = no duplicates, no drops).
    """
    sql = MIGRATION_PATH.read_text()
    with db_conn.cursor() as cur:
        cur.execute(sql)
        db_conn.commit()
        cur.execute(sql)  # second apply
        db_conn.commit()

        cur.execute(
            "SELECT COUNT(*) AS c FROM pg_indexes "
            "WHERE indexname = 'idx_crash_records_source_id'"
        )
        row = cur.fetchone()
        count = row["c"] if isinstance(row, dict) else row[0]
        assert count == 1, "unique index should exist exactly once"

        cur.execute(
            "SELECT COUNT(*) AS c FROM pg_constraint "
            "WHERE conname = 'crash_records_source_check'"
        )
        row = cur.fetchone()
        count = row["c"] if isinstance(row, dict) else row[0]
        assert count == 1, "source CHECK constraint should exist exactly once"

        cur.execute(
            "SELECT COUNT(*) AS c FROM pg_constraint "
            "WHERE conname = 'crash_records_severity_check'"
        )
        row = cur.fetchone()
        count = row["c"] if isinstance(row, dict) else row[0]
        assert count == 1, "severity CHECK constraint should exist exactly once"


def test_migration_004_fk_type_is_integer(applied_migration):
    """Pitfall D: snapped_segment_id MUST be INTEGER (not BIGINT) to match
    road_segments.id which is SERIAL = INTEGER. If this fails, the FK won't
    apply and migration will error mid-flight on a fresh DB.
    """
    with applied_migration.cursor() as cur:
        cur.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'crash_records' "
            "AND column_name = 'snapped_segment_id'"
        )
        row = cur.fetchone()
        dtype = row["data_type"] if isinstance(row, dict) else row[0]
        assert dtype == "integer", (
            f"snapped_segment_id type is {dtype!r}, expected 'integer' "
            "(Pitfall D: BIGINT would FK-fail against road_segments.id SERIAL)"
        )


def test_migration_004_adds_crash_norm_column(applied_migration):
    """D-09-11: segment_scores.crash_norm DOUBLE PRECISION NOT NULL DEFAULT 0.0
    must be added by migration 004 (Phase 10 populates).
    """
    with applied_migration.cursor() as cur:
        cur.execute(
            "SELECT data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_name = 'segment_scores' "
            "AND column_name = 'crash_norm'"
        )
        row = cur.fetchone()
        assert row is not None, "segment_scores.crash_norm column missing"
        if isinstance(row, dict):
            dtype, nullable, default = row["data_type"], row["is_nullable"], row["column_default"]
        else:
            dtype, nullable, default = row[0], row[1], row[2]
        assert dtype == "double precision", f"crash_norm type is {dtype!r}"
        assert nullable == "NO", "crash_norm must be NOT NULL"
        # Postgres normalizes "0.0" to "0.0" or "0.0::double precision";
        # accept either by checking it starts with "0.0" or contains "0".
        assert default is not None and "0" in default, (
            f"crash_norm default {default!r} should contain '0'"
        )


def test_migration_004_geom_is_point_4326(applied_migration):
    """D-09-10: geom is GEOMETRY(POINT, 4326). Verify via PostGIS geometry_columns view."""
    with applied_migration.cursor() as cur:
        cur.execute(
            "SELECT type, srid FROM geometry_columns "
            "WHERE f_table_name = 'crash_records' "
            "AND f_geometry_column = 'geom'"
        )
        row = cur.fetchone()
        assert row is not None, "crash_records.geom not registered in geometry_columns"
        if isinstance(row, dict):
            gtype, srid = row["type"], row["srid"]
        else:
            gtype, srid = row[0], row[1]
        assert gtype == "POINT", f"geom type is {gtype!r}, expected 'POINT'"
        assert srid == 4326, f"geom SRID is {srid}, expected 4326"


def test_migration_004_check_severity_rejects_unknown(applied_migration):
    """D-09-10: severity CHECK constraint allows only ('fatal','injury','pdo').
    A row with severity='unknown' must raise CheckViolation.
    """
    with applied_migration.cursor() as cur:
        try:
            cur.execute(
                "INSERT INTO crash_records "
                "(source, source_record_id, severity, occurred_at, geom) "
                "VALUES (%s, %s, %s, %s, "
                "ST_SetSRID(ST_MakePoint(%s, %s), 4326))",
                ("lacity", "TEST-INVALID-SEV", "unknown", "2020-01-01", -118.3, 34.05),
            )
            pytest.fail("INSERT with severity='unknown' should have raised CheckViolation")
        except pgerr.CheckViolation:
            pass  # expected
        finally:
            applied_migration.rollback()
