"""Integration tests for scripts/ingest_crashes.py — the Phase 9 driver.

5 tests cover REQ-crash-snap-match acceptance criteria:
  1. test_run_summary_shape           — D-09-08 (10 top-level keys)
  2. test_idempotent_reingest         — D-09-15 (ON CONFLICT)
  3. test_snap_distance_recorded      — D-09-04 (audit column populated)
  4. test_dropped_outside_snap        — D-09-18 (out-of-radius drops)
  5. test_fk_set_null_on_segment_delete — D-09-10 (FK preservation on segment delete)

All tests use the committed CSV fixture at data/crashes_la/lacity_fixture.csv
(per D-09-06: no live API in CI). Each test cleans up crash_records before
running so re-running pytest is repeatable.

Auto-skip when DATABASE_URL unreachable (db_available fixture in conftest.py).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DRIVER_PATH = REPO_ROOT / "scripts" / "ingest_crashes.py"
FIXTURE_PATH = REPO_ROOT / "data" / "crashes_la" / "lacity_fixture.csv"
MIGRATION_004 = REPO_ROOT / "db" / "migrations" / "004_crash_records.sql"

pytestmark = pytest.mark.integration


def _ensure_migration_applied(db_conn):
    """Apply migration 004 idempotently before each test."""
    sql = MIGRATION_004.read_text()
    with db_conn.cursor() as cur:
        cur.execute(sql)
    db_conn.commit()


def _wipe_lacity_crash_records(db_conn):
    """Clean slate for each test — delete all source='lacity' rows."""
    with db_conn.cursor() as cur:
        cur.execute("DELETE FROM crash_records WHERE source = 'lacity'")
    db_conn.commit()


@pytest.fixture
def clean_db(db_conn):
    """Apply migration + wipe crash_records before each test."""
    _ensure_migration_applied(db_conn)
    _wipe_lacity_crash_records(db_conn)
    yield db_conn
    _wipe_lacity_crash_records(db_conn)


def _run_driver(*extra_args: str) -> tuple[int, dict]:
    """Run scripts/ingest_crashes.py as a subprocess, returning (rc, parsed_summary).

    The driver imports from data_pipeline.* which lives at the repo root, so
    PYTHONPATH must include the repo root for those imports to resolve when
    the driver is invoked from any CWD.
    """
    env = {**os.environ}
    # Ensure data_pipeline.* imports resolve (driver also does sys.path.insert
    # internally, but be explicit so the subprocess inherits the right path).
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{REPO_ROOT}{os.pathsep}{existing_pp}" if existing_pp else str(REPO_ROOT)
    )
    cmd = [
        sys.executable, str(DRIVER_PATH),
        "--source", "lacity",
        "--csv", str(FIXTURE_PATH),
        *extra_args,
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(REPO_ROOT), env=env,
    )
    if result.returncode != 0:
        pytest.fail(
            f"driver exited {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    # Driver prints the summary JSON to stdout; logger.info messages go to
    # stderr per logging.basicConfig default — but argparse sets log_level
    # which DOES go through the root logger which writes to stderr by default
    # in basicConfig. So stdout should contain only the JSON.
    try:
        summary = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        pytest.fail(
            f"driver stdout is not JSON: {e}\nstdout: {result.stdout!r}\n"
            f"stderr: {result.stderr!r}"
        )
    return (result.returncode, summary)


def test_run_summary_shape(clean_db):
    """D-09-08: run-summary JSON has EXACTLY the 10 top-level keys."""
    rc, summary = _run_driver()
    assert rc == 0

    # Top-level keys.
    expected_keys = {
        "source", "fetched", "inserted", "skipped_duplicate",
        "dropped_outside_snap", "errors", "snap_distance_m",
        "by_severity", "started_at", "duration_s",
    }
    assert set(summary.keys()) == expected_keys, (
        f"unexpected top-level keys: extra={set(summary)-expected_keys}, "
        f"missing={expected_keys-set(summary)}"
    )

    # Nested shape: snap_distance_m has p50, p95, max.
    assert set(summary["snap_distance_m"].keys()) == {"p50", "p95", "max"}
    # Nested shape: by_severity has fatal, injury, pdo.
    assert set(summary["by_severity"].keys()) == {"fatal", "injury", "pdo"}

    # Type sanity.
    assert summary["source"] == "lacity"
    assert isinstance(summary["fetched"], int)
    assert isinstance(summary["inserted"], int)
    assert isinstance(summary["dropped_outside_snap"], int)
    assert isinstance(summary["snap_distance_m"]["p50"], (int, float))
    assert isinstance(summary["duration_s"], (int, float))
    assert summary["fetched"] >= 150, "fixture has at least 150 rows"


def test_idempotent_reingest(clean_db):
    """D-09-15: re-running on the same input inserts 0 new rows."""
    rc1, summary1 = _run_driver()
    assert rc1 == 0
    first_inserted = summary1["inserted"]
    assert first_inserted > 0, "first run should insert at least 1 row"

    rc2, summary2 = _run_driver()
    assert rc2 == 0
    assert summary2["inserted"] == 0, (
        f"second run should insert 0 rows; got {summary2['inserted']}"
    )
    assert summary2["skipped_duplicate"] == first_inserted, (
        f"second run skipped_duplicate ({summary2['skipped_duplicate']}) "
        f"should equal first run inserted ({first_inserted})"
    )


def test_snap_distance_recorded(clean_db):
    """D-09-04: every snapped row has a non-null snap_distance_m."""
    rc, summary = _run_driver()
    assert rc == 0
    with clean_db.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS c FROM crash_records "
            "WHERE source = 'lacity' "
            "AND snapped_segment_id IS NOT NULL "
            "AND snap_distance_m IS NULL"
        )
        row = cur.fetchone()
        bad = row["c"] if isinstance(row, dict) else row[0]
    assert bad == 0, (
        f"{bad} rows have a snapped_segment_id but a NULL snap_distance_m "
        "(D-09-04 contract violated)"
    )

    # Sanity: all recorded distances are within the snap radius (default 50m).
    with clean_db.cursor() as cur:
        cur.execute(
            "SELECT max(snap_distance_m) AS m FROM crash_records "
            "WHERE source = 'lacity' AND snapped_segment_id IS NOT NULL"
        )
        row = cur.fetchone()
        max_dist = row["m"] if isinstance(row, dict) else row[0]
    if max_dist is not None:
        assert max_dist <= 50.0, (
            f"max snap_distance_m {max_dist} exceeds default 50m "
            "(D-09-18: outside-radius rows should have been dropped)"
        )


def test_dropped_outside_snap(clean_db):
    """D-09-18: rows beyond snap radius are dropped (NOT inserted) and counted.

    The fixture's OUTSIDE-SNAP-001 row sits at LAX runway coords (33.9416,-118.4085)
    where seeded LA road_segments don't reach within 50m. It must:
      (a) appear in the run-summary's dropped_outside_snap count (>= 1).
      (b) NOT appear as a row in crash_records.
    """
    rc, summary = _run_driver()
    assert rc == 0
    assert summary["dropped_outside_snap"] >= 1, (
        f"expected dropped_outside_snap >= 1 (fixture has OUTSIDE-SNAP rows); "
        f"got {summary['dropped_outside_snap']}"
    )

    # The OUTSIDE-SNAP-001 dr_no specifically must NOT have been inserted.
    with clean_db.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS c FROM crash_records "
            "WHERE source = 'lacity' AND source_record_id = 'OUTSIDE-SNAP-001'"
        )
        row = cur.fetchone()
        present = row["c"] if isinstance(row, dict) else row[0]
    assert present == 0, (
        "OUTSIDE-SNAP-001 should have been dropped; "
        f"found {present} rows in crash_records"
    )


def test_fk_set_null_on_segment_delete(clean_db):
    """D-09-10: ON DELETE SET NULL on snapped_segment_id FK.

    Pick a snapped crash row; delete its road_segments row; verify the
    crash_records.snapped_segment_id becomes NULL, the crash row persists,
    and the FK constraint did NOT cascade-delete it. Rollback after.
    """
    rc, summary = _run_driver()
    assert rc == 0

    # Pick a victim row + its segment id.
    with clean_db.cursor() as cur:
        cur.execute(
            "SELECT id AS crash_id, snapped_segment_id, source_record_id "
            "FROM crash_records "
            "WHERE source = 'lacity' AND snapped_segment_id IS NOT NULL "
            "ORDER BY id LIMIT 1"
        )
        row = cur.fetchone()
    if not row:
        pytest.skip("no crash_records row with non-null FK; cannot test ON DELETE SET NULL")
    if isinstance(row, dict):
        crash_id = row["crash_id"]
        seg_id = row["snapped_segment_id"]
        src_rec_id = row["source_record_id"]
    else:
        crash_id, seg_id, src_rec_id = row[0], row[1], row[2]

    # SAVEPOINT so we can rollback the road_segments delete.
    with clean_db.cursor() as cur:
        cur.execute("SAVEPOINT before_seg_delete")
        # Delete dependent rows that have ON DELETE CASCADE first
        # (segment_defects + segment_scores reference road_segments(id) ON DELETE CASCADE
        # per migration 001 — we only care that crash_records survives via SET NULL).
        cur.execute("DELETE FROM segment_defects WHERE segment_id = %s", (seg_id,))
        cur.execute("DELETE FROM segment_scores WHERE segment_id = %s", (seg_id,))
        cur.execute("DELETE FROM road_segments WHERE id = %s", (seg_id,))

        # Verify the crash row still exists with NULL snapped_segment_id.
        cur.execute(
            "SELECT snapped_segment_id FROM crash_records "
            "WHERE id = %s",
            (crash_id,),
        )
        post_row = cur.fetchone()
        assert post_row is not None, (
            f"crash_records row {crash_id} (dr_no={src_rec_id}) was deleted "
            "(FK was wrongly ON DELETE CASCADE); D-09-10 contract violated"
        )
        new_seg_id = (
            post_row["snapped_segment_id"]
            if isinstance(post_row, dict)
            else post_row[0]
        )
        assert new_seg_id is None, (
            f"snapped_segment_id should be NULL after segment delete; got {new_seg_id} "
            "(FK was not ON DELETE SET NULL)"
        )

        # Rollback so the road_segments + segment_defects + segment_scores rows return.
        cur.execute("ROLLBACK TO SAVEPOINT before_seg_delete")
    clean_db.commit()
