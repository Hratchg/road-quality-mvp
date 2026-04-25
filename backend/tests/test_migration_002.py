"""Test migration 002_mapillary_provenance.sql: idempotency, UNIQUE+NULL semantics,
backfill, and CHECK constraint behavior. Auto-skip when DB unreachable
(via the db_conn / db_available fixtures in conftest.py).

Tests must run AFTER seed_data.py has been applied at least once (so road_segments
contains rows the inserts can reference). The test file uses raw psycopg2 (matches
project convention; no SQLAlchemy).
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import errors as pgerr

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = REPO_ROOT / "db" / "migrations" / "002_mapillary_provenance.sql"


@pytest.fixture
def applied_migration(db_conn):
    """Apply the migration before each test. Idempotent — safe to call repeatedly."""
    sql = MIGRATION_PATH.read_text()
    with db_conn.cursor() as cur:
        cur.execute(sql)
    db_conn.commit()
    return db_conn


@pytest.fixture
def a_segment_id(applied_migration):
    """Return any existing road_segments.id (skip if no segments seeded)."""
    with applied_migration.cursor() as cur:
        cur.execute("SELECT id FROM road_segments ORDER BY id LIMIT 1")
        row = cur.fetchone()
    if not row:
        pytest.skip("No road_segments rows; run seed_data.py first")
    # `db_conn` uses RealDictCursor — row is a dict, but with a plain cursor it
    # would be a tuple. Handle both (test should not depend on cursor flavor).
    return row["id"] if isinstance(row, dict) else row[0]


def test_migration_idempotent(db_conn):
    """Apply migration twice — second apply must not error."""
    sql = MIGRATION_PATH.read_text()
    with db_conn.cursor() as cur:
        cur.execute(sql)
        db_conn.commit()
        cur.execute(sql)  # second apply
        db_conn.commit()
        # Verify the unique index exists exactly once
        cur.execute(
            "SELECT COUNT(*) AS c FROM pg_indexes "
            "WHERE indexname = 'uniq_defects_segment_source_severity'"
        )
        row = cur.fetchone()
        count = row["c"] if isinstance(row, dict) else row[0]
        assert count == 1
        # Verify the CHECK constraint exists exactly once
        cur.execute(
            "SELECT COUNT(*) AS c FROM pg_constraint "
            "WHERE conname = 'segment_defects_source_check'"
        )
        row = cur.fetchone()
        count = row["c"] if isinstance(row, dict) else row[0]
        assert count == 1


def test_unique_allows_multiple_null_synthetic_rows(applied_migration, a_segment_id):
    """Default Postgres NULL-distinct UNIQUE: two synthetic rows with NULL
    source_mapillary_id must coexist. Regression guard for Pitfall 6
    (someone adding the option that treats NULLs as equal would break seed_data.py)."""
    with applied_migration.cursor() as cur:
        try:
            cur.execute(
                "INSERT INTO segment_defects "
                "(segment_id, severity, count, confidence_sum, source_mapillary_id, source) "
                "VALUES (%s, %s, %s, %s, NULL, 'synthetic'), "
                "(%s, %s, %s, %s, NULL, 'synthetic')",
                (a_segment_id, "moderate", 1, 0.5,
                 a_segment_id, "moderate", 1, 0.6),
            )
            applied_migration.commit()
        finally:
            applied_migration.rollback()


def test_unique_blocks_duplicate_mapillary_rows(applied_migration, a_segment_id):
    """Two rows with the same (segment_id, source_mapillary_id, severity) must
    collide on the UNIQUE index. Bare INSERT (no ON CONFLICT) raises."""
    test_image_id = "test_dup_999999"
    with applied_migration.cursor() as cur:
        cur.execute("DELETE FROM segment_defects WHERE source_mapillary_id = %s",
                    (test_image_id,))
        cur.execute(
            "INSERT INTO segment_defects "
            "(segment_id, severity, count, confidence_sum, source_mapillary_id, source) "
            "VALUES (%s, 'severe', 1, 0.9, %s, 'mapillary')",
            (a_segment_id, test_image_id),
        )
        applied_migration.commit()
        with pytest.raises(pgerr.UniqueViolation):
            cur.execute(
                "INSERT INTO segment_defects "
                "(segment_id, severity, count, confidence_sum, source_mapillary_id, source) "
                "VALUES (%s, 'severe', 1, 0.5, %s, 'mapillary')",
                (a_segment_id, test_image_id),
            )
        applied_migration.rollback()
        # Cleanup
        cur.execute("DELETE FROM segment_defects WHERE source_mapillary_id = %s",
                    (test_image_id,))
        applied_migration.commit()


def test_existing_synthetic_rows_backfill_source(applied_migration):
    """All existing segment_defects rows must have source='synthetic' after
    migration (via DEFAULT). New rows inserted without source value also default."""
    with applied_migration.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS total, "
                    "COUNT(*) FILTER (WHERE source = 'synthetic') AS synth "
                    "FROM segment_defects")
        row = cur.fetchone()
        total = row["total"] if isinstance(row, dict) else row[0]
        synth = row["synth"] if isinstance(row, dict) else row[1]
        # Every existing row must be tagged synthetic. (Mapillary rows do not
        # exist yet at this point — they arrive via plan 03's ingest CLI.)
        assert synth == total, (
            f"backfill incomplete: {synth} synthetic of {total} total"
        )


def test_check_constraint_rejects_invalid_source(applied_migration, a_segment_id):
    """source='unknown' violates the CHECK constraint."""
    with applied_migration.cursor() as cur:
        with pytest.raises(pgerr.CheckViolation):
            cur.execute(
                "INSERT INTO segment_defects "
                "(segment_id, severity, count, confidence_sum, source) "
                "VALUES (%s, 'moderate', 1, 0.5, 'unknown')",
                (a_segment_id,),
            )
        applied_migration.rollback()
