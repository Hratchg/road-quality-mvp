"""Eval helpers: precision/recall/bootstrap CI/per-severity breakdown.

These functions are pure — no DB, no I/O, no network. ``scripts/eval_detector.py``
orchestrates the CLI; this module does the math.

Severity rules MUST mirror ``data_pipeline/yolo_detector.py::_map_severity`` so
eval metrics map 1:1 to runtime behavior (Phase 2 D-06).

Decisions honored:
    D-06: primary metrics include per-severity breakdown driven by runtime rules
    D-07: IoU threshold 0.5 (COCO/YOLO standard)
    D-08: Bootstrap CIs, 1000 resamples, 95% interval (image-level resampling)
"""

from __future__ import annotations

import logging
from typing import Literal

import numpy as np

logger = logging.getLogger(__name__)

# Mirrors yolo_detector.py constants — re-declared here to avoid pulling in
# ultralytics on eval-only code paths. If yolo_detector.py's class lists ever
# change, update both sides in lockstep (D-06).
_SEVERE_CLASSES = {"severe_pothole", "severe"}
_MODERATE_CLASSES = {"moderate_pothole", "moderate"}
_GENERIC_CLASSES = {"pothole"}

# Project seed convention (scripts/seed_data.py uses SEED = 42).
DEFAULT_SEED = 42


def map_severity(class_name: str, confidence: float) -> str | None:
    """Mirrors YOLOv8Detector._map_severity exactly. DO NOT diverge.

    Two-class models:
        "severe_pothole" / "severe"   -> "severe"
        "moderate_pothole" / "moderate" -> "moderate"

    Single-class ("pothole") confidence buckets:
        confidence >= 0.7 -> "severe"
        confidence >= 0.4 -> "moderate"
        below 0.4         -> None (dropped)

    Unknown classes return None.
    """
    name = class_name.lower().strip()
    if name in _SEVERE_CLASSES:
        return "severe"
    if name in _MODERATE_CLASSES:
        return "moderate"
    if name in _GENERIC_CLASSES:
        if confidence >= 0.7:
            return "severe"
        if confidence >= 0.4:
            return "moderate"
        return None
    return None


def iou_xywh(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    """IoU for two normalized YOLO boxes expressed as ``(cx, cy, w, h)``.

    All coordinates are assumed to be in ``[0, 1]`` (normalized YOLO format).
    Returns 0.0 when the boxes are disjoint or when the union is empty.
    """
    ax1, ay1 = a[0] - a[2] / 2, a[1] - a[3] / 2
    ax2, ay2 = a[0] + a[2] / 2, a[1] + a[3] / 2
    bx1, by1 = b[0] - b[2] / 2, b[1] - b[3] / 2
    bx2, by2 = b[0] + b[2] / 2, b[1] + b[3] / 2
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return 0.0 if union <= 0 else inter / union


def match_predictions(
    gt_boxes: list[tuple[float, float, float, float]],
    pred_boxes: list[tuple[float, float, float, float, float, str]],
    iou_threshold: float = 0.5,
) -> dict[str, int]:
    """Per-image TP/FP/FN counting at a fixed IoU threshold (D-07 default 0.5).

    Greedy, highest-confidence-first matching (COCO-style). Each ground-truth
    box can only be matched once; any unmatched GT counts as a false negative.

    Args:
        gt_boxes: list of ``(cx, cy, w, h)`` normalized ground-truth boxes.
        pred_boxes: list of ``(cx, cy, w, h, confidence, class_name)`` predictions.
        iou_threshold: IoU threshold for a match (D-07 = 0.5).

    Returns:
        ``{"tp": int, "fp": int, "fn": int}``
    """
    matched_gt: set[int] = set()
    tp = fp = 0
    # Greedy highest-confidence-first matching (COCO-style)
    preds_sorted = sorted(enumerate(pred_boxes), key=lambda e: -e[1][4])
    for _, pred in preds_sorted:
        best_iou, best_j = 0.0, -1
        for j, gt in enumerate(gt_boxes):
            if j in matched_gt:
                continue
            iou = iou_xywh(pred[:4], gt)
            if iou > best_iou:
                best_iou, best_j = iou, j
        if best_iou >= iou_threshold and best_j >= 0:
            matched_gt.add(best_j)
            tp += 1
        else:
            fp += 1
    fn = len(gt_boxes) - len(matched_gt)
    return {"tp": tp, "fp": fp, "fn": fn}


def bootstrap_ci(
    per_image_counts: list[dict[str, int]],
    metric: Literal["precision", "recall"],
    n_resamples: int = 1000,
    ci_level: float = 0.95,
    seed: int = DEFAULT_SEED,
) -> tuple[float, float, float]:
    """Image-level bootstrap CI (D-08 = 1000 resamples, 95%).

    Args:
        per_image_counts: list of ``{"tp": ..., "fp": ..., "fn": ...}``, one
            dict per image.
        metric: ``"precision"`` or ``"recall"``.
        n_resamples: number of bootstrap resamples (D-08 default 1000).
        ci_level: confidence level (D-08 default 0.95).
        seed: RNG seed for reproducibility (project convention = 42).

    Returns:
        ``(low, point, high)``. Returns ``(nan, 0.0, nan)`` on degenerate
        zero-count input so downstream JSON serialization never sees a raw
        exception.
    """
    counts = np.array([[d["tp"], d["fp"], d["fn"]] for d in per_image_counts])
    if counts.size == 0 or counts.sum() == 0:
        return (float("nan"), 0.0, float("nan"))

    def _stat(idxs: np.ndarray) -> float:
        tp, fp, fn = counts[idxs].sum(axis=0)
        if metric == "precision":
            return float(tp / (tp + fp)) if (tp + fp) > 0 else float("nan")
        return float(tp / (tp + fn)) if (tp + fn) > 0 else float("nan")

    idxs = np.arange(len(counts))
    rng = np.random.default_rng(seed)
    samples = rng.choice(idxs, size=(n_resamples, len(idxs)), replace=True)
    vals = np.array([_stat(s) for s in samples])
    vals = vals[~np.isnan(vals)]
    if len(vals) == 0:
        return (float("nan"), 0.0, float("nan"))
    alpha = (1 - ci_level) / 2
    low = float(np.percentile(vals, alpha * 100))
    high = float(np.percentile(vals, (1 - alpha) * 100))
    point = _stat(idxs)
    return (low, point, high)


def per_severity_breakdown(
    per_image_detections: list[list[tuple[float, str]]],
) -> dict[str, dict[str, float]]:
    """Aggregate detection counts bucketed by severity rule.

    Applies :func:`map_severity` to each ``(confidence, class_name)`` pair so
    the eval breakdown matches the runtime behavior in ``YOLOv8Detector``
    (D-06). Detections that ``map_severity`` drops (confidence below the
    single-class threshold, unknown classes) fall into the ``"dropped"``
    bucket.

    Args:
        per_image_detections: list of lists, one per image; each inner list
            contains ``(confidence, class_name)`` for each prediction on that
            image.

    Returns:
        ``{"moderate": {"count": int}, "severe": {"count": int},
           "dropped": {"count": int}}``.
    """
    buckets = {"moderate": 0, "severe": 0, "dropped": 0}
    for image_dets in per_image_detections:
        for conf, cls in image_dets:
            sev = map_severity(cls, conf)
            if sev is None:
                buckets["dropped"] += 1
            else:
                buckets[sev] += 1
    return {k: {"count": v} for k, v in buckets.items()}
