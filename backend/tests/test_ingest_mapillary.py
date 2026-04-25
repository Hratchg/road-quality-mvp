"""Test scripts/ingest_mapillary.py -- target resolution, injection defense,
snap-match logic, retry, CLI smokes. Mirrors the Phase 2 test patterns:

- Subprocess CLI smokes (no DB needed) follow scripts/test_finetune_detector.py.
- Pure-unit tests (target parse, --where validation, aggregate, retry) follow
  backend/tests/test_mapillary.py mocked-requests style.
- Live-DB snap-match tests use db_conn fixture (auto-skip when DB down).

Wave-0 file per .planning/phases/03-mapillary-ingestion-pipeline/03-VALIDATION.md.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

# Pattern S-3: project-root importable so scripts.* + data_pipeline.* resolve
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

# Import functions from the script for unit tests. Note that the script's
# main() guard on MAPILLARY_TOKEN runs only inside main(); module-level imports
# don't require the token.
from scripts import ingest_mapillary as ing  # noqa: E402

from data_pipeline.detector import Detection  # noqa: E402

SCRIPT = REPO_ROOT / "scripts" / "ingest_mapillary.py"


# ---------- CLI smokes (no DB) ----------

class TestCLISmokes:
    def test_help_lists_all_flags(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        assert result.returncode == 0, result.stderr
        for flag in [
            "--segment-ids", "--segment-ids-file", "--where",
            "--snap-meters", "--pad-meters", "--limit-per-segment",
            "--cache-root", "--no-keep", "--json-out",
        ]:
            assert flag in result.stdout, f"missing flag {flag}"

    def test_missing_token_exits_1(self):
        env = {**os.environ}
        env.pop("MAPILLARY_ACCESS_TOKEN", None)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--segment-ids", "1"],
            capture_output=True, text=True, cwd=REPO_ROOT, env=env,
        )
        assert result.returncode == 1
        assert "MAPILLARY_ACCESS_TOKEN" in result.stderr

    def test_no_target_mode_exits_2(self):
        # argparse mutex group with required=True -> no flag -> exit 2.
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        assert result.returncode == 2


# ---------- Target resolution (pure unit) ----------

class TestTargetResolution:
    def test_parse_segment_ids_csv_valid(self):
        assert ing.parse_segment_ids_csv("1,2,3") == [1, 2, 3]

    def test_parse_segment_ids_csv_with_whitespace(self):
        assert ing.parse_segment_ids_csv(" 1 , 2 , 3 ") == [1, 2, 3]

    def test_parse_segment_ids_csv_empty_raises(self):
        with pytest.raises(ValueError):
            ing.parse_segment_ids_csv("")
        with pytest.raises(ValueError):
            ing.parse_segment_ids_csv(",,,")

    def test_parse_segment_ids_csv_non_int_raises(self):
        with pytest.raises(ValueError, match="non-integer"):
            ing.parse_segment_ids_csv("1,abc,3")

    def test_parse_segment_ids_file(self, tmp_path):
        f = tmp_path / "ids.txt"
        f.write_text("# header\n1\n\n2\n# comment\n3\n")
        assert ing.parse_segment_ids_file(f) == [1, 2, 3]

    def test_parse_segment_ids_file_missing_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ing.parse_segment_ids_file(tmp_path / "missing.txt")


# ---------- --where injection defense (pure unit) ----------

class TestWhereInjection:
    @pytest.mark.parametrize("predicate", [
        "DROP TABLE foo",
        "a > 1; DELETE FROM users",
        "DELETE FROM segment_defects",
        "UPDATE road_segments SET id = 0",
        "INSERT INTO road_segments VALUES (1)",
        "ALTER TABLE foo DROP COLUMN x",
        "CREATE TABLE x (id INT)",
        "GRANT ALL ON foo TO public",
        "REVOKE ALL ON foo FROM public",
        "EXECUTE proc",
        "TRUNCATE foo",
        "COPY foo TO '/tmp/x'",
        "EXEC sp_proc",
    ])
    def test_validate_where_rejects_forbidden_token(self, predicate):
        with pytest.raises(ValueError):
            ing.validate_where_predicate(predicate)

    def test_validate_where_rejects_semicolon(self):
        with pytest.raises(ValueError, match=";"):
            ing.validate_where_predicate("a > 1; SELECT 1")

    def test_validate_where_rejects_dash_dash_comment(self):
        with pytest.raises(ValueError, match="comment"):
            ing.validate_where_predicate("a > 1 -- evil")

    def test_validate_where_rejects_block_comment(self):
        with pytest.raises(ValueError, match="comment"):
            ing.validate_where_predicate("a > 1 /* evil */")

    def test_validate_where_rejects_pg_introspection(self):
        with pytest.raises(ValueError, match="forbidden"):
            ing.validate_where_predicate("id IN (SELECT * FROM pg_user)")

    def test_validate_where_rejects_information_schema(self):
        with pytest.raises(ValueError, match="forbidden"):
            ing.validate_where_predicate(
                "id IN (SELECT * FROM information_schema.tables)"
            )

    def test_validate_where_accepts_safe_predicate(self):
        cleaned = ing.validate_where_predicate(
            "iri_norm > 0.5 ORDER BY iri_norm DESC LIMIT 10"
        )
        assert cleaned == "iri_norm > 0.5 ORDER BY iri_norm DESC LIMIT 10"


# ---------- Snap-match (live DB) ----------

@pytest.mark.integration
class TestSnapMatch:
    def test_snap_match_within_radius_returns_segment_id(self, db_conn):
        # Find any seeded segment + its centroid; query with generous radius.
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT id, ST_X(ST_Centroid(geom)) AS lon, "
                "ST_Y(ST_Centroid(geom)) AS lat "
                "FROM road_segments ORDER BY id LIMIT 1"
            )
            row = cur.fetchone()
        if not row:
            pytest.skip("No seeded road_segments")
        if isinstance(row, dict):
            seg_id, lon, lat = row["id"], row["lon"], row["lat"]
        else:
            seg_id, lon, lat = row[0], row[1], row[2]

        with db_conn.cursor() as cur:
            matched = ing.snap_match_image(cur, lon, lat, snap_meters=100.0)
        # Some nearby segment must match (the one we picked OR a close
        # neighbor sharing an endpoint — pgRouting topology can produce
        # adjacent segments at vertex 0/1).
        assert matched is not None
        assert isinstance(matched, int)

    def test_snap_match_outside_radius_returns_none(self, db_conn):
        # Pacific Ocean, well offshore from LA -- no segments within 25m.
        with db_conn.cursor() as cur:
            matched = ing.snap_match_image(
                cur, lon=-120.0, lat=33.0, snap_meters=25.0
            )
        assert matched is None


# ---------- aggregate_detections (pure unit) ----------

class TestAggregateDetections:
    def test_aggregate_groups_by_severity(self):
        dets = [
            Detection(severity="moderate", confidence=0.4),
            Detection(severity="moderate", confidence=0.6),
            Detection(severity="severe", confidence=0.9),
        ]
        out = ing.aggregate_detections(dets, "image_42")
        # Convert to dict for stable comparison.
        by_sev = {row[1]: row for row in out}
        assert by_sev["moderate"] == ("image_42", "moderate", 2, 1.0)
        assert by_sev["severe"] == ("image_42", "severe", 1, 0.9)

    def test_aggregate_empty_returns_empty(self):
        assert ing.aggregate_detections([], "image_x") == []


# ---------- with_retry (pure unit) ----------

class TestRetry:
    def _http_error(self, status: int) -> requests.HTTPError:
        resp = MagicMock()
        resp.status_code = status
        return requests.HTTPError(response=resp)

    def test_retry_on_429_succeeds_eventually(self, monkeypatch):
        monkeypatch.setattr(ing.time, "sleep", lambda *_: None)
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            if calls["n"] <= 2:
                raise self._http_error(429)
            return "ok"

        assert ing.with_retry(fn, max_attempts=3, base_delay=0.0) == "ok"
        assert calls["n"] == 3

    def test_retry_on_500_succeeds_eventually(self, monkeypatch):
        monkeypatch.setattr(ing.time, "sleep", lambda *_: None)
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            if calls["n"] == 1:
                raise self._http_error(500)
            return "ok"

        assert ing.with_retry(fn, max_attempts=3, base_delay=0.0) == "ok"
        assert calls["n"] == 2

    def test_retry_on_400_raises_immediately(self, monkeypatch):
        monkeypatch.setattr(ing.time, "sleep", lambda *_: None)
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            raise self._http_error(400)

        with pytest.raises(requests.HTTPError):
            ing.with_retry(fn, max_attempts=3, base_delay=0.0)
        assert calls["n"] == 1

    def test_retry_max_attempts_exceeded_raises(self, monkeypatch):
        monkeypatch.setattr(ing.time, "sleep", lambda *_: None)
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            raise self._http_error(429)

        with pytest.raises(requests.HTTPError):
            ing.with_retry(fn, max_attempts=3, base_delay=0.0)
        assert calls["n"] == 3


# ---------- Empty-target -> exit 2 (Pitfall 9, integration) ----------

@pytest.mark.integration
class TestEmptyTargetExits2:
    def test_where_matches_zero_segments_exits_2(self, db_conn):
        # Use an impossibly-restrictive predicate.
        env = {**os.environ}
        # Token must be present or test_missing_token_exits_1 would fire first.
        env.setdefault("MAPILLARY_ACCESS_TOKEN", "dummy_token_for_test")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--where", "id = -999999"],
            capture_output=True, text=True, cwd=REPO_ROOT, env=env,
        )
        assert result.returncode == 2
        combined = (result.stdout + result.stderr).lower()
        assert "0 segments" in combined or "matched 0" in combined


# ---------- Plan 03-04: --wipe-synthetic / --no-recompute / --force-wipe (pure unit) ----------

class TestPlan04Flags:
    """Plan 03-04: new flags appear in --help and the helpers are importable.

    Pure-unit checks; integration coverage of the flag *behavior* lives in
    backend/tests/test_integration.py (Task 2 of plan 03-04).
    """

    def test_help_lists_wipe_synthetic_flag(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        assert result.returncode == 0, result.stderr
        assert "--wipe-synthetic" in result.stdout

    def test_help_lists_no_recompute_flag(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        assert result.returncode == 0, result.stderr
        assert "--no-recompute" in result.stdout

    def test_help_lists_force_wipe_flag(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        assert result.returncode == 0, result.stderr
        assert "--force-wipe" in result.stdout

    def test_wipe_synthetic_rows_helper_exists(self):
        """The helper must be importable as a public function on the module."""
        assert hasattr(ing, "wipe_synthetic_rows")
        assert callable(ing.wipe_synthetic_rows)

    def test_trigger_recompute_helper_exists(self):
        assert hasattr(ing, "trigger_recompute")
        assert callable(ing.trigger_recompute)

    def test_wipe_synthetic_rows_uses_hardcoded_where(self):
        """T-03-18 mitigation: the WHERE clause is a hard-coded literal —
        no parameterization, no operator-controllable extension. We verify
        the source contains the exact literal string."""
        src = SCRIPT.read_text()
        assert "DELETE FROM segment_defects WHERE source = 'synthetic'" in src

    def test_trigger_recompute_invokes_compute_scores_py(self):
        """The recompute hook must reference compute_scores.py and use
        sys.executable (not /bin/sh, not shell=True) so PATH cannot be
        hijacked (T-03-20 mitigation)."""
        src = SCRIPT.read_text()
        assert "compute_scores.py" in src
        assert "sys.executable" in src
        # No shell=True anywhere in the file (a regression on this would
        # silently re-introduce the PATH-hijack threat).
        assert "shell=True" not in src
