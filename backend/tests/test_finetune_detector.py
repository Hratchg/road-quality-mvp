"""Smoke tests for scripts/finetune_detector.py.

These do NOT run training (ultralytics is heavy, GPU-bound). They validate:
  - --help exits 0 and lists all required flags
  - missing data.yaml -> exit 3
  - --push-to-hub without HUGGINGFACE_TOKEN -> exit 1 with actionable error
  - default seed is 42 (project convention)
  - default device is cpu (Pitfall 1: Apple Silicon MPS broken)

All tests shell out via subprocess so the __main__ path is exercised end-
to-end. No ultralytics / torch import at test time.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest  # noqa: F401  (used via collection conventions; present for future fixtures)

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
SCRIPT = os.path.join(REPO_ROOT, "scripts", "finetune_detector.py")


class TestFinetuneDetectorCLI:
    def test_help_lists_all_flags(self):
        result = subprocess.run(
            [sys.executable, SCRIPT, "--help"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0, result.stderr
        for flag in [
            "--data",
            "--base",
            "--epochs",
            "--batch",
            "--imgsz",
            "--device",
            "--patience",
            "--seed",
            "--project",
            "--name",
            "--push-to-hub",
        ]:
            assert flag in result.stdout, f"Missing flag {flag}"

    def test_missing_data_exits_3(self, tmp_path):
        result = subprocess.run(
            [sys.executable, SCRIPT, "--data", str(tmp_path / "none.yaml")],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 3
        assert "fetch_eval_data.py --build" in result.stderr

    def test_push_without_token_exits_1(self):
        """T-02-22: fail fast on --push-to-hub without HUGGINGFACE_TOKEN.

        Must exit 1 BEFORE training starts (no ultralytics call made).
        """
        env = os.environ.copy()
        env.pop("HUGGINGFACE_TOKEN", None)
        # Use a real existing yaml so we don't hit the exit-3 path first.
        # Reuse the committed fixture from Plan 02.
        fixture = os.path.join(
            REPO_ROOT, "backend/tests/fixtures/eval_fixtures/data.yaml"
        )
        result = subprocess.run(
            [
                sys.executable,
                SCRIPT,
                "--data",
                fixture,
                "--push-to-hub",
                "user/test",
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env=env,
        )
        assert result.returncode == 1, (
            f"expected exit 1, got {result.returncode}; stderr={result.stderr}"
        )
        assert "HUGGINGFACE_TOKEN" in result.stderr
        # Token failure must be surfaced BEFORE training starts (fail-fast)
        stderr_lower = result.stderr.lower()
        assert (
            "write scope" in stderr_lower
            or "huggingface.co/settings/tokens" in stderr_lower
        )

    def test_default_seed_is_42(self):
        result = subprocess.run(
            [sys.executable, SCRIPT, "--help"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0, result.stderr
        assert "default 42" in result.stdout

    def test_default_device_is_cpu(self):
        """Pitfall 1: default should be 'cpu', never 'mps' on Apple Silicon."""
        result = subprocess.run(
            [sys.executable, SCRIPT, "--help"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0, result.stderr
        # device help should mention cpu
        assert "cpu" in result.stdout.lower()

    def test_token_never_logged_in_stderr_on_fast_fail(self):
        """T-02-22 reinforcement: even when we set HUGGINGFACE_TOKEN, the fast-
        fail output on other error paths (missing data) must not echo it.

        Runs the missing-data path with the token set in env; confirms the
        script does not print the token into stderr (it never reads it in this
        path, but this test guards against future regressions).
        """
        env = os.environ.copy()
        env["HUGGINGFACE_TOKEN"] = "hf_TOTALLY_FAKE_SECRET_DO_NOT_PANIC"
        result = subprocess.run(
            [sys.executable, SCRIPT, "--data", "/nonexistent.yaml"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env=env,
        )
        assert result.returncode == 3
        assert "hf_TOTALLY_FAKE_SECRET_DO_NOT_PANIC" not in result.stderr
        assert "hf_TOTALLY_FAKE_SECRET_DO_NOT_PANIC" not in result.stdout
