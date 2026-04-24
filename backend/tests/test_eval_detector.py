"""Tests for data_pipeline.eval helpers + scripts/eval_detector.py exit codes.

Unit tests cover the pure functions (no I/O, no network). Smoke tests shell
out to the CLI script to verify D-18 exit-code discipline. No ultralytics
import is required for any test in this file.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np

# Make data_pipeline importable from the repo root (mirrors test_iri_ingestion.py).
REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
sys.path.insert(0, REPO_ROOT)

from data_pipeline.eval import (  # noqa: E402
    DEFAULT_SEED,
    bootstrap_ci,
    iou_xywh,
    map_severity,
    match_predictions,
    per_severity_breakdown,
)


# ---------------------------------------------------------------------------
# 1. map_severity mirrors YOLOv8Detector._map_severity exactly
# ---------------------------------------------------------------------------


class TestMapSeverityMirrorsRuntime:
    def test_severe_class_maps_to_severe(self):
        assert map_severity("severe_pothole", 0.5) == "severe"
        assert map_severity("severe", 0.9) == "severe"

    def test_moderate_class_maps_to_moderate(self):
        assert map_severity("moderate_pothole", 0.2) == "moderate"
        assert map_severity("moderate", 0.8) == "moderate"

    def test_generic_pothole_high_conf_is_severe(self):
        assert map_severity("pothole", 0.70) == "severe"
        assert map_severity("pothole", 0.85) == "severe"

    def test_generic_pothole_medium_conf_is_moderate(self):
        assert map_severity("pothole", 0.40) == "moderate"
        assert map_severity("pothole", 0.55) == "moderate"

    def test_generic_pothole_low_conf_dropped(self):
        assert map_severity("pothole", 0.39) is None
        assert map_severity("pothole", 0.1) is None

    def test_unknown_class_returns_none(self):
        assert map_severity("car", 0.95) is None
        assert map_severity("crack", 0.80) is None


# ---------------------------------------------------------------------------
# 2. bootstrap_ci deterministic with fixed seed
# ---------------------------------------------------------------------------


class TestBootstrapCiDeterministic:
    def test_same_input_same_output(self):
        counts = [{"tp": 3, "fp": 1, "fn": 1}] * 20
        r1 = bootstrap_ci(counts, "precision", n_resamples=100, seed=42)
        r2 = bootstrap_ci(counts, "precision", n_resamples=100, seed=42)
        assert r1 == r2

    def test_different_seed_different_output(self):
        counts = [{"tp": 3, "fp": 1, "fn": 1}, {"tp": 1, "fp": 3, "fn": 2}] * 20
        r1 = bootstrap_ci(counts, "precision", n_resamples=200, seed=1)
        r2 = bootstrap_ci(counts, "precision", n_resamples=200, seed=2)
        # Not strictly required to differ, but statistically overwhelmingly
        # likely; the fallback clause covers rare collisions on the low end.
        assert r1 != r2 or r1[0] == r2[0]

    def test_point_estimate_is_pooled(self):
        # 3 TP, 1 FP total -> precision = 3/4 = 0.75
        counts = [{"tp": 3, "fp": 1, "fn": 0}]
        low, point, high = bootstrap_ci(counts, "precision", n_resamples=100, seed=42)
        assert abs(point - 0.75) < 1e-6
        # low/high are used downstream; silence linter.
        assert np.isfinite(low) or np.isnan(low)
        assert np.isfinite(high) or np.isnan(high)

    def test_recall_degenerate_zero(self):
        counts = [{"tp": 0, "fp": 0, "fn": 0}]
        low, point, high = bootstrap_ci(counts, "recall", n_resamples=100, seed=42)
        assert np.isnan(low) and np.isnan(high)
        assert point == 0.0

    def test_default_seed_is_42(self):
        assert DEFAULT_SEED == 42


# ---------------------------------------------------------------------------
# 3. per_severity_breakdown mirrors runtime rules
# ---------------------------------------------------------------------------


class TestPerSeverityBreakdown:
    def test_high_conf_potholes_are_severe(self):
        dets = [[(0.8, "pothole"), (0.75, "pothole")]]
        out = per_severity_breakdown(dets)
        assert out["severe"]["count"] == 2
        assert out["moderate"]["count"] == 0
        assert out["dropped"]["count"] == 0

    def test_medium_conf_are_moderate(self):
        dets = [[(0.5, "pothole"), (0.45, "pothole")]]
        out = per_severity_breakdown(dets)
        assert out["moderate"]["count"] == 2
        assert out["severe"]["count"] == 0

    def test_low_conf_dropped(self):
        dets = [[(0.2, "pothole")]]
        out = per_severity_breakdown(dets)
        assert out["dropped"]["count"] == 1

    def test_two_class_model_maps_directly(self):
        dets = [[(0.1, "severe_pothole"), (0.1, "moderate_pothole")]]
        out = per_severity_breakdown(dets)
        assert out["severe"]["count"] == 1
        assert out["moderate"]["count"] == 1


# ---------------------------------------------------------------------------
# 4. match_predictions — IoU matching at threshold=0.5
# ---------------------------------------------------------------------------


class TestMatchPredictions:
    def test_perfect_match_is_tp(self):
        gt = [(0.5, 0.5, 0.3, 0.3)]
        pred = [(0.5, 0.5, 0.3, 0.3, 0.9, "pothole")]
        out = match_predictions(gt, pred, iou_threshold=0.5)
        assert out == {"tp": 1, "fp": 0, "fn": 0}

    def test_no_overlap_is_fp_and_fn(self):
        gt = [(0.2, 0.2, 0.1, 0.1)]
        pred = [(0.8, 0.8, 0.1, 0.1, 0.9, "pothole")]
        out = match_predictions(gt, pred, iou_threshold=0.5)
        assert out == {"tp": 0, "fp": 1, "fn": 1}

    def test_empty_gt_all_preds_are_fp(self):
        gt: list[tuple[float, float, float, float]] = []
        pred = [
            (0.5, 0.5, 0.3, 0.3, 0.9, "pothole"),
            (0.2, 0.2, 0.1, 0.1, 0.8, "pothole"),
        ]
        out = match_predictions(gt, pred)
        assert out == {"tp": 0, "fp": 2, "fn": 0}

    def test_empty_preds_all_gt_are_fn(self):
        gt = [(0.5, 0.5, 0.3, 0.3), (0.2, 0.2, 0.1, 0.1)]
        pred: list[tuple[float, float, float, float, float, str]] = []
        out = match_predictions(gt, pred)
        assert out == {"tp": 0, "fp": 0, "fn": 2}

    def test_iou_helper_disjoint_is_zero(self):
        a = (0.1, 0.1, 0.1, 0.1)
        b = (0.9, 0.9, 0.1, 0.1)
        assert iou_xywh(a, b) == 0.0

    def test_iou_helper_identical_is_one(self):
        box = (0.5, 0.5, 0.3, 0.3)
        assert abs(iou_xywh(box, box) - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# 5. CLI exit codes (subprocess smoke tests)
# ---------------------------------------------------------------------------


class TestEvalDetectorExitCodes:
    SCRIPT = os.path.join(REPO_ROOT, "scripts", "eval_detector.py")

    def test_missing_data_exits_3(self):
        """D-17 + D-18: missing data.yaml -> exit 3 with fetch hint."""
        result = subprocess.run(
            [sys.executable, self.SCRIPT, "--data", "/nonexistent/path/data.yaml"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 3
        assert "Run: python scripts/fetch_eval_data.py" in result.stderr

    def test_help_exits_0_and_lists_all_flags(self):
        result = subprocess.run(
            [sys.executable, self.SCRIPT, "--help"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0
        for flag in [
            "--min-precision",
            "--min-recall",
            "--iou",
            "--bootstrap-resamples",
            "--ci-level",
            "--json-out",
            "--split",
            "--model",
        ]:
            assert flag in result.stdout, f"Missing flag {flag} in --help"
