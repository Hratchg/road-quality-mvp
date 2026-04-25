"""Test scripts/compute_scores.py --source filter behavior (D-16).

Covers: argparse rejection, default backward-compat, source filtering at JOIN
time (not WHERE — preserves every-segment-present property), empty-mapillary
warning (Pitfall 7).

Auto-skip when DB unreachable (via the db_conn / db_available fixtures in
conftest.py). Subprocess-CLI tests do not need DB and run unconditionally.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "compute_scores.py"


# ---------- Pure subprocess (no DB) ----------

class TestComputeScoresCLI:
    def test_help_lists_source_flag(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        assert result.returncode == 0, result.stderr
        assert "--source" in result.stdout
        for choice in ("synthetic", "mapillary", "all"):
            assert choice in result.stdout, f"missing choice {choice!r} in help"

    def test_invalid_source_exits_2(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--source", "bogus"],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        # argparse rejects unknown choice with exit 2
        assert result.returncode == 2
        assert "invalid choice" in result.stderr.lower() or "bogus" in result.stderr


# ---------- DB-bound integration tests ----------

pytestmark_integration = pytest.mark.integration


@pytest.fixture
def a_segment_id(db_conn):
    """Return any existing road_segments.id."""
    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM road_segments ORDER BY id LIMIT 1")
        row = cur.fetchone()
    if not row:
        pytest.skip("No road_segments rows; run seed_data.py first")
    return row["id"] if isinstance(row, dict) else row[0]


@pytest.fixture
def cleanup_test_rows(db_conn):
    """Remove any detection rows tagged with our test marker before/after."""
    marker = "test_03_02_999"
    with db_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM segment_defects WHERE source_mapillary_id = %s",
            (marker,),
        )
    db_conn.commit()
    yield marker
    with db_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM segment_defects WHERE source_mapillary_id = %s",
            (marker,),
        )
    db_conn.commit()


def _run_recompute(source: str | None = None):
    """Invoke compute_scores.py and return (returncode, stdout, stderr)."""
    args = [sys.executable, str(SCRIPT)]
    if source is not None:
        args.extend(["--source", source])
    result = subprocess.run(
        args, capture_output=True, text=True, cwd=REPO_ROOT,
        env={**os.environ},  # inherit DATABASE_URL
    )
    return result


def _scores_snapshot(db_conn) -> dict:
    """Return {segment_id: pothole_score_total} for all rows."""
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT segment_id, pothole_score_total FROM segment_scores"
        )
        rows = cur.fetchall()
    return {
        (r["segment_id"] if isinstance(r, dict) else r[0]):
        (r["pothole_score_total"] if isinstance(r, dict) else r[1])
        for r in rows
    }


@pytest.mark.integration
def test_default_matches_explicit_all(db_conn):
    """Default `--source all` (no flag) and explicit `--source all` produce
    identical segment_scores. Backward-compat for callers like ingest CLIs."""
    r1 = _run_recompute(source=None)
    assert r1.returncode == 0, r1.stderr
    snapshot_default = _scores_snapshot(db_conn)

    r2 = _run_recompute(source="all")
    assert r2.returncode == 0, r2.stderr
    snapshot_all = _scores_snapshot(db_conn)

    assert snapshot_default == snapshot_all


@pytest.mark.integration
def test_source_synthetic_excludes_mapillary(db_conn, a_segment_id, cleanup_test_rows):
    """A row with source='mapillary' is excluded when --source synthetic."""
    marker = cleanup_test_rows
    # Insert one mapillary row that, if included, would push pothole_score_total
    # noticeably above synthetic-only.
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO segment_defects "
            "(segment_id, severity, count, confidence_sum, "
            " source_mapillary_id, source) "
            "VALUES (%s, 'severe', 5, 4.5, %s, 'mapillary') "
            "ON CONFLICT DO NOTHING",
            (a_segment_id, marker),
        )
    db_conn.commit()

    r_synth = _run_recompute(source="synthetic")
    assert r_synth.returncode == 0, r_synth.stderr
    snap_synth = _scores_snapshot(db_conn)

    r_mly = _run_recompute(source="mapillary")
    assert r_mly.returncode == 0, r_mly.stderr
    snap_mly = _scores_snapshot(db_conn)

    # The mapillary-only run on a_segment_id should reflect the inserted row
    # (5 * 4.5 * 1.0 weight for severe = 22.5). The synthetic-only run
    # excludes that row.
    assert snap_mly[a_segment_id] >= 22.0, (
        f"mapillary recompute did not include test row: {snap_mly[a_segment_id]}"
    )
    # The two snapshots must differ on the targeted segment
    assert snap_synth[a_segment_id] != snap_mly[a_segment_id]


@pytest.mark.integration
def test_source_mapillary_empty_warns_on_stderr(db_conn):
    """When no mapillary rows exist, --source mapillary warns clearly (Pitfall 7)."""
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM segment_defects WHERE source = 'mapillary'"
        )
        row = cur.fetchone()
        n = row["count"] if isinstance(row, dict) else row[0]
    if n > 0:
        pytest.skip(
            "Cannot run empty-mapillary warning test: mapillary rows exist. "
            "Run --wipe-synthetic style cleanup first."
        )
    r = _run_recompute(source="mapillary")
    assert r.returncode == 0, r.stderr
    assert "WARNING" in r.stderr
    assert "0 mapillary detections" in r.stderr


@pytest.mark.integration
def test_segments_without_matching_source_get_zero_not_dropped(
    db_conn, a_segment_id
):
    """JOIN-clause filter (not WHERE): segments with only synthetic detections
    still appear in segment_scores after --source mapillary, with score 0.
    Regression guard for Pattern 7 line 786."""
    r = _run_recompute(source="mapillary")
    assert r.returncode == 0, r.stderr
    snap = _scores_snapshot(db_conn)
    # Every road_segments id must have a row in segment_scores (LEFT JOIN
    # property preserved). a_segment_id is a known-existing id; assert it's
    # present even if it has no mapillary detections.
    assert a_segment_id in snap, (
        "JOIN-clause filter dropped segments without matching mapillary rows; "
        "see RESEARCH Pattern 7 'Critical detail'"
    )
