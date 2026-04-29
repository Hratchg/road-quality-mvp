"""Phase 7 Wave 0 RED test: bootstrap_ci_map50 contract pin. Per .planning/phases/07-la-trained-detector/07-VALIDATION.md (covers SC #2 -- non-overlapping CI on mAP@0.5)."""

from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from data_pipeline.eval import bootstrap_ci_map50  # noqa: E402  # Phase 7 Plan 07-02 implements


class TestBootstrapCiMap50:
    """Contract pin for bootstrap_ci_map50 (Plan 07-02 implements; RED until then)."""

    def test_returns_valid_range(self):
        """Test 1: For 20 perfectly-matched GT+pred pairs, returns (low, point, high)
        with 0.0 <= low <= point <= high <= 1.0 and point > 0.5."""
        pairs = [
            {
                "gt_boxes": [(0.5, 0.5, 0.3, 0.3)],
                "pred_boxes": [(0.5, 0.5, 0.3, 0.3, 0.9, "pothole")],
            }
        ] * 20
        low, point, high = bootstrap_ci_map50(pairs, n_resamples=100, seed=42)
        assert 0.0 <= low <= point <= high <= 1.0, (
            f"Expected 0.0 <= low <= point <= high <= 1.0, got ({low}, {point}, {high})"
        )
        assert point > 0.5, (
            f"Expected point > 0.5 for perfectly matched pairs, got point={point}"
        )

    def test_degenerate_no_gt(self):
        """Test 2: For 5 images each with empty gt_boxes and empty pred_boxes,
        point must be 0.0; CI may be (nan, 0.0, nan) or (0.0, 0.0, 0.0)."""
        import math
        pairs = [{"gt_boxes": [], "pred_boxes": []}] * 5
        low, point, high = bootstrap_ci_map50(pairs, n_resamples=100, seed=42)
        assert point == 0.0, f"Expected point == 0.0 for degenerate input, got {point}"
        # Either nan or 0.0 bounds are acceptable
        assert math.isnan(low) or low == 0.0, f"Expected nan or 0.0 for low, got {low}"
        assert math.isnan(high) or high == 0.0, f"Expected nan or 0.0 for high, got {high}"

    def test_deterministic_with_same_seed(self):
        """Test 3: Two calls with identical input + seed=42 return identical tuples.
        Mirrors TestBootstrapCiDeterministic.test_same_input_same_output from
        backend/tests/test_eval_detector.py:74-78."""
        pairs = [
            {
                "gt_boxes": [(0.5, 0.5, 0.3, 0.3)],
                "pred_boxes": [(0.5, 0.5, 0.3, 0.3, 0.9, "pothole")],
            }
        ] * 20
        r1 = bootstrap_ci_map50(pairs, n_resamples=100, seed=42)
        r2 = bootstrap_ci_map50(pairs, n_resamples=100, seed=42)
        assert r1 == r2, f"Expected identical output with same seed, got {r1} vs {r2}"

    def test_default_seed_is_42(self):
        """Test 4: bootstrap_ci_map50 default seed must be 42 (Phase 2 D-08).
        Mirrors test_default_seed_is_42 at backend/tests/test_eval_detector.py:104."""
        sig = inspect.signature(bootstrap_ci_map50)
        assert sig.parameters["seed"].default == 42, (
            f"Expected default seed=42, got {sig.parameters['seed'].default}"
        )
