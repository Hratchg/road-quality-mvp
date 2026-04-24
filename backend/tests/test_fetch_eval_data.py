"""Smoke tests for scripts/fetch_eval_data.py exit codes.

Verifies the D-18 exit-code contract without requiring a real
MAPILLARY_ACCESS_TOKEN or network access. All tests shell out to the
script via subprocess so the __main__ path is exercised end-to-end.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
SCRIPT = os.path.join(REPO_ROOT, "scripts", "fetch_eval_data.py")


class TestFetchEvalDataExitCodes:
    def test_help_exits_0_and_lists_modes(self):
        result = subprocess.run(
            [sys.executable, SCRIPT, "--help"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0
        for flag in [
            "--build",
            "--verify-only",
            "--root",
            "--manifest",
            "--count",
            "--split-train",
            "--split-val",
            "--split-test",
        ]:
            assert flag in result.stdout, f"Missing flag {flag}"

    def test_missing_manifest_exits_3(self, tmp_path):
        """D-17, D-18: missing dataset -> exit 3 with --build hint."""
        # Ensure MAPILLARY_ACCESS_TOKEN is NOT set so --verify-only is the
        # path under test regardless of caller env.
        env = os.environ.copy()
        env.pop("MAPILLARY_ACCESS_TOKEN", None)
        result = subprocess.run(
            [
                sys.executable,
                SCRIPT,
                "--manifest",
                str(tmp_path / "none.json"),
                "--root",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env=env,
        )
        assert result.returncode == 3
        assert "--build" in result.stderr

    def test_verify_ok_on_empty_manifest(self, tmp_path):
        """Committed skeleton (version 1.0, files=[]) must verify OK."""
        manifest = {
            "version": "1.0",
            "source_bucket": "test",
            "license": "CC-BY-SA 4.0",
            "files": [],
        }
        mf = tmp_path / "manifest.json"
        mf.write_text(json.dumps(manifest))
        result = subprocess.run(
            [
                sys.executable,
                SCRIPT,
                "--manifest",
                str(mf),
                "--root",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0, result.stderr

    def test_build_without_token_exits_1(self, tmp_path):
        """--build without MAPILLARY_ACCESS_TOKEN must exit 1 with hint."""
        env = os.environ.copy()
        env.pop("MAPILLARY_ACCESS_TOKEN", None)
        result = subprocess.run(
            [sys.executable, SCRIPT, "--build", "--root", str(tmp_path)],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env=env,
        )
        assert result.returncode == 1
        assert "MAPILLARY_ACCESS_TOKEN" in result.stderr
