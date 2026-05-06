# Phase 7 Plan 07-06 — Win-Check Report

**Generated:** 2026-05-06
**Test split:** 136 images (33 ground-truth bboxes)
**SHA pinned:** `hratcho/road-quality-la-yolov8@af7af59ad138554c67e774bd48cfe60e04193909`

## Side-by-side numbers (test split, IoU=0.5)

| Metric | Baseline (keremberke@d6d5df4) | Trained (hratcho/road-quality-la-yolov8@af7af59a...) | Δ point | CIs overlap? |
|--------|-------------------------------|--------------------------------------------------------|---------|--------------|
| Precision | 0.0217 [0.0000, 0.0217, 0.0682] | 0.0000 [NaN, 0.0000, NaN] | -0.0217 | ? |
| Recall | 0.0303 [0.0000, 0.0303, 0.0968] | 0.0000 [0.0000, 0.0000, 0.0000] | -0.0303 | Y |
| mAP@0.5 | 0.0005 [0.0000, 0.0005, 0.0047] | 0.0000 [0.0000, 0.0000, 0.0000] | -0.0005 | Y |

**Counts:**
- Baseline: TP=1, FP=45, FN=32, n_pred=46
- Trained:  TP=0, FP=0, FN=33, n_pred=0

## D-11 decision

**Status: NEGATIVE — TRAINED MODEL COLLAPSED**

Per Phase 7 D-11, a WIN requires non-overlapping 95% CI on at least one of {Precision, Recall, mAP@0.5} with the trained model better. Not only is there no win — **the trained model is strictly worse than the baseline on every metric**.

The trained model emits **zero predictions across all 136 test images** even at `conf=0.01` (verified by direct smoke test). This is a textbook YOLOv8 fine-tuning collapse, not a marginal underperform. Likely root cause: 171 positive bboxes spread across 1322 images (~13% positive rate) gave the loss landscape a strong "predict nothing" attractor that the default optimizer settings couldn't escape.

## D-12 floor (P >= 0.5)

Trained precision: 0.0000. **BELOW FLOOR (NaN-CI: model emits no predictions, so P/R are undefined except by convention).**

## D-13 contingency recommendation

**ITERATE ONCE.** This is iteration 1 of 2 allowed per D-13. Concrete fixes ranked by expected impact:

1. **Lower learning rate** — `--lr0 0.001` (default 0.01 is likely too aggressive for the sparse-positive shape of this dataset)
2. **Increase image size** — `--imgsz 800` (default 640) — many LA potholes are small in the frame; more pixels per object helps
3. **Smaller batch + more epochs** — `--batch 16 --epochs 100` — more gradient updates per epoch, less averaging away of the rare positive signal
4. **Class-positive oversampling** — add `single_cls=True` (might already be set via data.yaml nc=1) and consider filtering training set to images with bboxes for first 20 epochs, then introduce negatives for last 30 epochs
5. **Cosine LR schedule** — `--cos-lr` (helps prevent early collapse)

**Recommended retry invocation (combine 1+2+3):**

```bash
python scripts/finetune_detector.py \
    --data data/eval_la/data.yaml \
    --base yolov8s.pt \
    --device 0 \
    --epochs 100 \
    --batch 16 \
    --imgsz 800 \
    --lr0 0.001 \
    --patience 30 \
    --cos-lr \
    --push-to-hub hratcho/road-quality-la-yolov8 \
    --verbose
```

Note: `--lr0`, `--imgsz`, `--cos-lr` may need to be added to `scripts/finetune_detector.py`'s argparse if not already supported.

## ⚠ Plan 07-07 GUARDRAIL

**DO NOT proceed with Plan 07-07 Part 2 (production re-ingestion) on this trained model.** Re-ingesting with `--wipe-mapillary` while the trained detector emits zero predictions would wipe all 12 LA zones' pothole data and replace them with empty results — actively degrading the live demo from "real Mapillary detections" back to "no signal."

D-17 says "re-ingest with trained model regardless." That decision presumes the trained model is at least directionally functional. A model emitting 0 predictions is not functional. **D-17 must be deferred until iteration 2 produces a model with non-zero predictions.**

If iteration 2 also collapses, D-13 says close as documented negative result — leave production on the keremberke baseline and document the loss honestly in `docs/DETECTOR_EVAL.md`.

## Raw eval JSONs

- `.planning/phases/07-la-trained-detector/eval_results_baseline.json`
- `.planning/phases/07-la-trained-detector/eval_results_trained.json`

## Forward references

- **Plan 07-07** is BLOCKED until iteration 2 trained model exists. Do NOT swap `_DEFAULT_HF_REPO` to a non-functional model SHA.
- **Plan 07-08** (docs closure) can run AFTER iteration 2 either succeeds (substitute new numbers) or fails (record honest negative + keep baseline in prod).
