#!/usr/bin/env python3
"""Phase 7 trained-model eval: hratcho/road-quality-la-yolov8@<sha-from-07-05-HF-SHA.txt>
on the Phase 7 LA test split. Mirrors scripts/eval_baseline_phase7.py
shape so both Phase 7 eval JSONs share the same schema by construction
(D-11 win-check requires identical key sets including `map50_ci_95`).

yolov8s.pt detection base supports val() too, but predict() keeps the
schema match with the baseline eval.

Phase 2 D-07/D-08 conventions inherited: IoU=0.5, 1000 image-level
bootstrap resamples, seed=42.

Usage:
    /tmp/rq-venv/bin/python scripts/eval_trained_phase7.py \\
        --data data/eval_la/data.yaml \\
        --split test \\
        --hf-sha-file .planning/phases/07-la-trained-detector/07-05-HF-SHA.txt \\
        --json-out .planning/phases/07-la-trained-detector/eval_results_trained.json
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

TRAINED_REPO = "hratcho/road-quality-la-yolov8"
TRAINED_FILE = "best.pt"
DEFAULT_HF_SHA_FILE = Path(".planning/phases/07-la-trained-detector/07-05-HF-SHA.txt")

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
    ap.add_argument(
        "--hf-sha-file", type=Path, default=DEFAULT_HF_SHA_FILE,
        help="Path to file containing the HF revision SHA for the trained "
             "model (default: 07-05-HF-SHA.txt produced by Plan 07-05 GATE B).",
    )
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

    if not args.hf_sha_file.exists():
        print(f"ERROR: HF SHA file not found: {args.hf_sha_file}", file=sys.stderr)
        return 3
    trained_revision = args.hf_sha_file.read_text().strip()
    if not trained_revision:
        print(f"ERROR: HF SHA file is empty: {args.hf_sha_file}", file=sys.stderr)
        return 3

    logger.info("Loading trained model %s @ %s ...", TRAINED_REPO, trained_revision)
    model_path = hf_hub_download(
        repo_id=TRAINED_REPO,
        filename=TRAINED_FILE,
        revision=trained_revision,
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
        "model_path": f"{TRAINED_REPO}@{trained_revision}",
        "model_repo": TRAINED_REPO,
        "model_revision": trained_revision,
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
            "Phase 7 trained-model eval. Mirrors eval_baseline_phase7.py "
            "shape (predict() + match_predictions + bootstrap_ci/map50) so "
            "both Phase 7 eval JSONs share the same schema by construction. "
            "yolov8s.pt detection base supports val() too, but predict() "
            "keeps the schema match with the baseline eval."
        ),
    }

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
