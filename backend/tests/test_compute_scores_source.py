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


# ---------- Phase 10 Plan 10-02 (D-10-10..D-10-12, D-10-20): --source crash ----------
#
# 4 new tests covering the new crash branch:
#   - TestComputeScoresCrashCLI.test_help_lists_crash_source (subprocess, no DB)
#   - test_crash_source_updates_crash_norm (integration; pins UPDATE writes
#       non-zero crash_norm + clip to [0, 1])
#   - test_crash_norm_histogram_not_bimodal (smoke; D-10-20 Pitfall 5
#       verification — ≥50% in [0.05, 0.5] with degenerate-DB skip guard)
#   - test_source_all_runs_crash_branch (integration; pins --source all runs
#       BOTH the existing synthetic+mapillary path AND the new crash path)
#
# Wave-0 prerequisite (operator-driven, see plan): re-ingest the LA City
# fixture so crash_records has ≥100 rows. The integration tests below each
# `pytest.skip` cleanly when crash_records is empty (Pitfall 7 fail-cleanly).
# ----------------------------------------------------------------------------


class TestComputeScoresCrashCLI:
    def test_help_lists_crash_source(self):
        """`--help` lists `crash` as a valid `--source` choice (D-10-10).

        Subprocess test; no DB required so this runs unconditionally.
        """
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        assert result.returncode == 0, result.stderr
        assert "crash" in result.stdout, (
            "crash missing from --source choices in --help output"
        )


@pytest.mark.integration
def test_crash_source_updates_crash_norm(db_conn):
    """`--source crash` UPDATEs crash_norm > 0 for ≥1 segment (D-10-09, D-10-11).

    Wave-0 re-ingest of `data/crashes_la/lacity_fixture.csv` MUST run BEFORE
    this test. If `crash_records` is empty, the test skips cleanly with the
    re-ingest instructions (Pitfall 7 fail-cleanly).
    """
    # Sanity guard: skip cleanly if crash_records is empty (Pitfall 7).
    with db_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM crash_records")
        row = cur.fetchone()
        n_rows = row["count"] if isinstance(row, dict) else row[0]
    if n_rows == 0:
        pytest.skip(
            "crash_records is empty; run "
            "scripts/ingest_crashes.py --source lacity --csv "
            "data/crashes_la/lacity_fixture.csv first (Wave-0 step)."
        )

    # Reset crash_norm to 0 so we can detect the UPDATE's effect.
    with db_conn.cursor() as cur:
        cur.execute("UPDATE segment_scores SET crash_norm = 0.0")
    db_conn.commit()

    # Run --source crash via subprocess (mirrors operator workflow).
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--source", "crash"],
        capture_output=True, text=True, cwd=REPO_ROOT,
        env={**os.environ},
    )
    assert result.returncode == 0, (
        f"compute_scores.py --source crash failed: {result.stderr}"
    )

    # Pin: ≥1 segment has crash_norm > 0 after the UPDATE (D-10-09).
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM segment_scores WHERE crash_norm > 0"
        )
        row = cur.fetchone()
        n_nonzero = row["count"] if isinstance(row, dict) else row[0]
    assert n_nonzero >= 1, (
        f"--source crash produced 0 segments with crash_norm > 0; "
        f"expected ≥1 (crash_records has {n_rows} rows)."
    )

    # Pin: clip to [0, 1] (D-10-08).
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT MAX(crash_norm) AS max_v, MIN(crash_norm) AS min_v "
            "FROM segment_scores"
        )
        row = cur.fetchone()
        max_v = row["max_v"] if isinstance(row, dict) else row[0]
        min_v = row["min_v"] if isinstance(row, dict) else row[1]
    assert 0.0 <= min_v, f"crash_norm went negative: {min_v}"
    assert max_v <= 1.0, f"crash_norm exceeded 1.0: {max_v}"


@pytest.mark.smoke
@pytest.mark.integration
def test_crash_norm_histogram_not_bimodal(db_conn):
    """≥50% of crash-bearing segments have crash_norm in [0.05, 0.5] (D-10-20).

    Pitfall 5 verification: bimodal saturation at 0/1 would indicate the
    academic 100:10:1 anti-pattern leaked back in. The 8:3:1 ratio (D-10-04)
    + p95 cap (D-10-08) should produce a long-tailed distribution.

    Includes a Pitfall 7 degenerate-DB guard:
        skip if `len(crash_bearing) < 100` (full LA City fixture should
        snap-match enough rows to clear this; if it doesn't, the test
        skips cleanly rather than trivially passing on a tiny set).
    """
    # Wave-0 step: ensure crash_records has rows.
    with db_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM crash_records")
        row = cur.fetchone()
        n_rows = row["count"] if isinstance(row, dict) else row[0]
    if n_rows == 0:
        pytest.skip(
            "crash_records is empty; run "
            "scripts/ingest_crashes.py --source lacity --csv "
            "data/crashes_la/lacity_fixture.csv first."
        )

    # Run --source crash to populate crash_norm.
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--source", "crash"],
        capture_output=True, text=True, cwd=REPO_ROOT,
        env={**os.environ},
    )
    assert result.returncode == 0, result.stderr

    # Fetch all crash-bearing segments (crash_norm > 0).
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT crash_norm FROM segment_scores WHERE crash_norm > 0 "
            "ORDER BY crash_norm"
        )
        rows = cur.fetchall()
    crash_bearing = [
        (r["crash_norm"] if isinstance(r, dict) else r[0])
        for r in rows
    ]

    # Pitfall 7 guard: skip cleanly if too few crash-bearing segments to draw
    # a meaningful histogram. The full LA City fixture (197 rows) snaps to
    # ~23 unique segments — well below this threshold; in production at
    # Phase 12 the live LA City Socrata pull (~10k+ rows / year) will easily
    # clear it. The skip path keeps this test honest at the unit-test layer
    # while still functioning as the operator-runbook gate at the deploy layer.
    if len(crash_bearing) < 100:
        pytest.skip(
            f"Only {len(crash_bearing)} crash-bearing segments found; "
            "need ≥100 for a meaningful histogram. Re-ingest a larger "
            "crash_records dataset (full live Socrata pull, not the "
            "205-row fixture) and rerun."
        )

    # D-10-20: ≥50% in [0.05, 0.5] — non-bimodal target distribution.
    in_range = [v for v in crash_bearing if 0.05 <= v <= 0.5]
    fraction_in_range = len(in_range) / len(crash_bearing)
    assert fraction_in_range >= 0.50, (
        f"Histogram bimodal: only {fraction_in_range:.1%} of "
        f"{len(crash_bearing)} crash-bearing segments in [0.05, 0.5]. "
        f"Min={min(crash_bearing):.3f}, max={max(crash_bearing):.3f}. "
        f"Suspect Pitfall 5 (academic 100:10:1 weights) regression."
    )


@pytest.mark.integration
def test_source_all_runs_crash_branch(db_conn):
    """`--source all` runs the crash UPDATE in addition to the existing
    synthetic+mapillary INSERT (D-10-10 sequential, D-10-12 unchanged paths).

    Pinned because D-10-10 says 'sequential' and D-10-12 says
    'mapillary/synthetic paths unchanged'. Regression guard for
    accidentally short-circuiting one of the two paths.
    """
    with db_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM crash_records")
        row = cur.fetchone()
        n_rows = row["count"] if isinstance(row, dict) else row[0]
    if n_rows == 0:
        pytest.skip("crash_records is empty; re-ingest fixture first.")

    # Reset crash_norm so we can detect that the UPDATE actually ran.
    with db_conn.cursor() as cur:
        cur.execute("UPDATE segment_scores SET crash_norm = 0.0")
    db_conn.commit()

    # Run --source all.
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--source", "all"],
        capture_output=True, text=True, cwd=REPO_ROOT,
        env={**os.environ},
    )
    assert result.returncode == 0, result.stderr

    # Pin 1: crash_norm UPDATE happened (≥1 segment > 0).
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM segment_scores WHERE crash_norm > 0"
        )
        row = cur.fetchone()
        n_nonzero = row["count"] if isinstance(row, dict) else row[0]
    assert n_nonzero >= 1, (
        "--source all did NOT run the crash branch "
        "(crash_norm > 0 count is 0)"
    )

    # Pin 2: synthetic+mapillary path also still ran (D-10-12 invariant —
    # segment_scores still has a row per road_segments).
    with db_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM segment_scores")
        row = cur.fetchone()
        n_total = row["count"] if isinstance(row, dict) else row[0]
    assert n_total >= 209000, (
        f"segment_scores row count {n_total} < 209k expected; "
        "synthetic+mapillary INSERT path may have regressed."
    )
