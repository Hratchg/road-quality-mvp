#!/usr/bin/env python3
"""Pre-label data/eval_la/images/ with the public pretrained pothole model.

Generates YOLO-format auto-suggested labels for every image in
data/eval_la/images/{train,val,test}/ by running the public pretrained
``keremberke/yolov8s-pothole-segmentation`` model and writing
``<class_id=0> <x_center> <y_center> <width> <height>`` lines (all
normalized 0-1, space-separated) to
data/eval_la/labels/<split>/<image_id>.txt.

Operator workflow: open these auto-labels in CVAT and CORRECT them
(delete wrong boxes, add missed boxes) rather than creating from
scratch. Typical 3-5x speedup vs from-scratch hand-labeling.

This is Plan 06-02 of Phase 6. The model used here is the same base
model the project will fine-tune from in Plan 06-05 (per Phase 2
D-11). Pre-labeling does NOT modify detector_factory or commit any
model artifact — purely a one-shot inference pass to populate
training-time labels.

Usage:
    /tmp/rq-venv/bin/python scripts/prelabel.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
IMAGES_ROOT = REPO_ROOT / "data" / "eval_la" / "images"
LABELS_ROOT = REPO_ROOT / "data" / "eval_la" / "labels"

# Confidence threshold: 0.25 is YOLO's default for predict(). Lower
# would surface more false positives for the operator to delete; higher
# would miss more potholes the operator has to add. 0.25 picked as the
# balance point matching ultralytics defaults.
CONF_THRESHOLD = 0.25

# Public model: keremberke/yolov8s-pothole-segmentation. Per Phase 2
# D-11, this is the base model the LA fine-tune starts from. The
# segmentation variant is fine here — every segmentation result has an
# underlying bbox we can read off result.boxes.
MODEL_REPO = "keremberke/yolov8s-pothole-segmentation"
MODEL_FILE = "best.pt"


def main() -> int:
    try:
        from huggingface_hub import hf_hub_download
        from ultralytics import YOLO
    except ImportError as e:
        print(f"ERROR: missing dependency {e.name}. "
              "Install with: /tmp/rq-venv/bin/python -m pip install "
              "--break-system-packages ultralytics huggingface_hub",
              file=sys.stderr)
        return 1

    print(f"Downloading model {MODEL_REPO}/{MODEL_FILE} via huggingface_hub ...")
    model_path = hf_hub_download(repo_id=MODEL_REPO, filename=MODEL_FILE)
    print(f"  model cached at: {model_path}")

    print(f"Loading YOLO from {model_path} ...")
    model = YOLO(model_path)
    print(f"  model task: {getattr(model, 'task', 'unknown')}")

    splits = ["train", "val", "test"]
    grand_total_images = 0
    grand_total_boxes = 0

    for split in splits:
        img_dir = IMAGES_ROOT / split
        label_dir = LABELS_ROOT / split
        label_dir.mkdir(parents=True, exist_ok=True)

        images = sorted(img_dir.glob("*.jpg"))
        if not images:
            print(f"  {split}: 0 images, skipping")
            continue

        split_boxes = 0
        for i, img_path in enumerate(images, start=1):
            results = model.predict(
                str(img_path), conf=CONF_THRESHOLD, verbose=False
            )
            boxes_yolo: list[str] = []
            for r in results:
                if r.boxes is None or len(r.boxes) == 0:
                    continue
                # xywhn = normalized [x_center, y_center, width, height]
                for row in r.boxes.xywhn.tolist():
                    xc, yc, w, h = row
                    boxes_yolo.append(
                        f"0 {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}"
                    )
            label_path = label_dir / f"{img_path.stem}.txt"
            # Empty file when no detection — operator sees the image
            # came back clean per the public model and only needs to
            # add a box if they spot a missed pothole.
            label_path.write_text("\n".join(boxes_yolo))
            split_boxes += len(boxes_yolo)

            if i % 20 == 0 or i == len(images):
                print(f"  {split}: {i}/{len(images)} images, "
                      f"{split_boxes} boxes so far")

        print(f"  {split} DONE: {len(images)} images, {split_boxes} boxes")
        grand_total_images += len(images)
        grand_total_boxes += split_boxes

    print(f"\nTotal: {grand_total_images} images pre-labeled, "
          f"{grand_total_boxes} pothole boxes suggested")
    print("Operator next step: open data/eval_la/images/ in CVAT, import "
          "the YOLO labels from data/eval_la/labels/, CORRECT (don't "
          "rewrite from scratch), export, commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
