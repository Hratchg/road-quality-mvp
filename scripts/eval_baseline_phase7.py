#!/usr/bin/env python3
"""Phase 7 D-10 baseline re-eval: keremberke segmentation model on the
Phase 7 LA test split (>=30 positives), using the manual val() bypass
methodology from Plan 06-05.

Why a separate script (vs scripts/eval_detector.py): val()-based path
crashes on segmentation-model + bbox-only labels (Plan 06-05 SUMMARY
documents the exact error). This script uses the predict()-based fallback
that worked in Phase 6: model.predict() -> manual match_predictions ->
bootstrap_ci (P/R) + bootstrap_ci_map50 (mAP).

Output JSON schema is a SUPERSET of scripts/eval_detector.py — same Phase 2
keys plus `map50_ci_95` (Plan 07-02 ship) which Phase 7's D-11 win-check
requires. scripts/eval_trained_phase7.py is a near-copy of this file
(same predict()-based shape, just different model constants) so both
Phase 7 eval JSONs share the same schema by construction.

Phase 2 D-07/D-08 conventions inherited: IoU=0.5, 1000 image-level
bootstrap resamples, seed=42.

Usage:
    /tmp/rq-venv/bin/python scripts/eval_baseline_phase7.py \\
        --data data/eval_la/data.yaml \\
        --split test \\
        --json-out .planning/phases/07-la-trained-detector/eval_results_baseline.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_pipeline.eval import (
    bootstrap_ci,
    bootstrap_ci_map50,
    match_predictions,
)

BASELINE_REPO = "keremberke/yolov8s-pothole-segmentation"
BASELINE_REVISION = "d6d5df4ac1a9e40b0180635b03198ddec88c4875"
BASELINE_FILE = "best.pt"

CONF_THRESHOLD = 0.25
IOU_THRESHOLD = 0.5
BOOTSTRAP_RESAMPLES = 1000
SEED = 42

logger = logging.getLogger(__name__)


def _load_yolo_label_file(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            cx, cy, w, h = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
        except ValueError:
            continue
        out.append((cx, cy, w, h))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=Path("data/eval_la/data.yaml"))
    ap.add_argument("--split", default="test", choices=["train", "val", "test"])
    ap.add_argument("--json-out", type=Path, required=True)
    ap.add_argument("--bootstrap-resamples", type=int, default=BOOTSTRAP_RESAMPLES)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if not args.data.exists():
        print(f"ERROR: data.yaml not found at {args.data}", file=sys.stderr)
        return 3

    try:
        from huggingface_hub import hf_hub_download
        from ultralytics import YOLO
    except ImportError as e:
        print(f"ERROR: missing dep {e.name}", file=sys.stderr)
        return 1

    logger.info(
        "Loading baseline %s @ %s ...", BASELINE_REPO, BASELINE_REVISION
    )
    model_path = hf_hub_download(
        repo_id=BASELINE_REPO,
        filename=BASELINE_FILE,
        revision=BASELINE_REVISION,
    )
    model = YOLO(model_path)

    img_dir = (Path.cwd() / "data/eval_la/images" / args.split).resolve()
    lbl_dir = (Path.cwd() / "data/eval_la/labels" / args.split).resolve()
    if not img_dir.exists():
        print(f"ERROR: image dir not found: {img_dir}", file=sys.stderr)
        return 3

    images = sorted(img_dir.glob("*.jpg"))
    logger.info("Evaluating %d images in %s split", len(images), args.split)

    per_image_counts = []
    per_image_pairs = []

    for img_path in images:
        image_id = img_path.stem
        gt_boxes = _load_yolo_label_file(lbl_dir / f"{image_id}.txt")
        results = model.predict(
            source=str(img_path),
            conf=CONF_THRESHOLD,
            verbose=False,
        )
        r = results[0]
        pred_boxes = []
        if r.boxes is not None and len(r.boxes) > 0:
            xywhn = r.boxes.xywhn.cpu().numpy()
            confs = r.boxes.conf.cpu().numpy()
            clss = r.boxes.cls.cpu().numpy()
            names = r.names if hasattr(r, "names") else {0: "pothole"}
            for i in range(len(confs)):
                cx = float(xywhn[i, 0])
                cy = float(xywhn[i, 1])
                w = float(xywhn[i, 2])
                h = float(xywhn[i, 3])
                cls_id = int(clss[i])
                cls_name = names.get(cls_id, f"cls_{cls_id}")
                conf = float(confs[i])
                pred_boxes.append((cx, cy, w, h, conf, cls_name))
        counts = match_predictions(gt_boxes, pred_boxes, iou_threshold=IOU_THRESHOLD)
        per_image_counts.append(counts)
        per_image_pairs.append({"gt_boxes": gt_boxes, "pred_boxes": pred_boxes})

    tp = sum(c["tp"] for c in per_image_counts)
    fp = sum(c["fp"] for c in per_image_counts)
    fn = sum(c["fn"] for c in per_image_counts)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0

    prec_ci = bootstrap_ci(
        per_image_counts, "precision",
        n_resamples=args.bootstrap_resamples, seed=SEED,
    )
    rec_ci = bootstrap_ci(
        per_image_counts, "recall",
        n_resamples=args.bootstrap_resamples, seed=SEED,
    )
    map_ci = bootstrap_ci_map50(
        per_image_pairs,
        n_resamples=args.bootstrap_resamples,
        seed=SEED,
        iou_threshold=IOU_THRESHOLD,
    )

    report = {
        "model_path": f"{BASELINE_REPO}@{BASELINE_REVISION}",
        "model_repo": BASELINE_REPO,
        "model_revision": BASELINE_REVISION,
        "split": args.split,
        "n_images": len(images),
        "n_gt_bboxes": sum(len(p["gt_boxes"]) for p in per_image_pairs),
        "n_pred_bboxes": sum(len(p["pred_boxes"]) for p in per_image_pairs),
        "iou_threshold": IOU_THRESHOLD,
        "tp": tp, "fp": fp, "fn": fn,
        "precision": precision,
        "precision_ci_95": list(prec_ci),
        "recall": recall,
        "recall_ci_95": list(rec_ci),
        "map50": map_ci[1],
        "map50_ci_95": list(map_ci),
        "bootstrap_resamples": args.bootstrap_resamples,
        "bootstrap_seed": SEED,
        "method_note": (
            "Phase 7 D-10 baseline re-eval. Manual val() bypass "
            "(predict() + match_predictions + bootstrap_ci) because "
            "keremberke is a segmentation model and val() crashes on "
            "bbox-only labels (Plan 06-05 SUMMARY exact error documented)."
        ),
    }

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
