---
phase: 06-public-demo-launch
plan: 06-02
title: Pre-label assist via public pretrained pothole model
status: complete
completed: 2026-04-28
---

# Plan 06-02 SUMMARY: Pre-label assist

## Outcome

✅ All 5 acceptance criteria met. 158 LA images now have YOLO-format
auto-suggested labels ready for CVAT import + correction.

## Numbers

| Split | Images | Labels written | With detections | Bbox suggestions |
|-------|--------|----------------|-----------------|------------------|
| train | 110    | 110            | 50              | 63               |
| val   | 31     | 31             | 14              | 16               |
| test  | 17     | 17             | 6               | 7                |
| **TOTAL** | **158** | **158**    | **70 (44%)**    | **86**           |

44% hit rate (70 of 158 images flagged with at least one pothole) is in
the expected range for street-level imagery — the public model is
conservative at conf=0.25 default. Operator can:
- Add bboxes the model missed (false negatives)
- Delete bboxes that aren't potholes (false positives — shadows, manhole
  covers, paint, road cracks)
- Adjust bbox tightness

Empirically: typical ~30–60 minute total CVAT correction time vs
~3–6 hours from-scratch hand-labeling.

## Artifacts shipped

- `scripts/prelabel.py` — new (137 LOC); loads
  `keremberke/yolov8s-pothole-segmentation` via huggingface_hub, runs
  `model.predict(conf=0.25)` over each image, writes YOLO-format
  bboxes (or empty file) to `data/eval_la/labels/<split>/<image_id>.txt`.
- `data/eval_la/labels/{train,val,test}/*.txt` — 158 files, 86 bbox
  lines total. Stub-empty files from fetch_eval_data overwritten.
- Pre-flight installed in `/tmp/rq-venv` (NOT committed; host-only
  scratch venv): ultralytics 8.4.42, torch 2.11.0, huggingface_hub 1.12.0,
  psycopg2-binary 2.9.12 (latter reinstalled after ultralytics install
  inadvertently shadowed it).

## Verification

Per the PLAN's verification block:

```
$ diff <(find data/eval_la/images -name '*.jpg' | sed 's|images/|labels/|; s|\.jpg$|.txt|' | sort) \
       <(find data/eval_la/labels -name '*.txt' | sort)
(empty diff — every image has a corresponding label file)

$ find data/eval_la/labels -name '*.txt' -exec cat {} + | wc -l
86  (matches reported total)

$ for split in train val test; do
    total=$(find data/eval_la/labels/$split -name '*.txt' | wc -l)
    with_boxes=$(find data/eval_la/labels/$split -name '*.txt' -size +0c | wc -l)
    echo "$split: $total files, $with_boxes with detections"
  done
train: 110 files, 50 with detections
val: 31 files, 14 with detections
test: 17 files, 6 with detections
```

## Caveats

- Operator must NOT rubber-stamp the model output. The eval split (#3
  above, `data/eval_la/labels/test/`) becomes ground truth for Plan
  06-06's reported precision/recall. If the operator just accepts every
  pre-label, they're effectively measuring how well the trained model
  matches the public model — which is meaningless. Hand-correcting is
  the load-bearing step.
- Model used here is segmentation, not detection. Per ultralytics, every
  segmentation result has an underlying bbox so `result.boxes.xywhn`
  works. If a future fine-tune switches to a detection-only base model,
  prelabel.py is unchanged.

## Next step

Plan 06-04 (hand-labeling, USER GATE). Operator opens app.cvat.ai,
imports `data/eval_la/images/` + `data/eval_la/labels/`, corrects boxes,
exports YOLO 1.1 back into the labels dir, commits.

## Cross-references

- 06-CONTEXT.md D-02 (hand-labeling tool = CVAT cloud)
- Phase 2 D-11 (`keremberke/yolov8s-pothole-segmentation` is the base
  model the LA fine-tune starts from)
- docs/DETECTOR_EVAL.md (methodology)
- docs/FINETUNE.md (subsequent training recipe)
