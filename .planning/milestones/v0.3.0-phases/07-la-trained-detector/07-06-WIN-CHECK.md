# Phase 7 Plan 07-06 — Win-Check Report

**Generated:** 2026-05-07 (iteration 2 — final)
**Test split:** 136 images (33 ground-truth bboxes)
**SHA pinned:** `hratcho/road-quality-la-yolov8@84a874c2a5e7b08a9a701d31492bf7808356b0e0`

## D-11 verdict: NEGATIVE (final, both iterations)

Per Phase 7 D-11, a WIN requires non-overlapping 95% CIs on at least one of {Precision, Recall, mAP@0.5} with the trained model better. **Neither iteration produced a win.** Phase 7 is at its D-13 cap of 2 trained runs and closes as a documented negative result.

## Side-by-side numbers (test split, IoU=0.5)

| Metric | Baseline (keremberke@d6d5df4) | Trained iter-2 (hratcho@84a874c2) |
|--------|-------------------------------|------------------------------------|
| Precision | 0.0217 [0.0000, 0.0682] | 0.0000 [NaN, NaN] |
| Recall | 0.0303 [0.0000, 0.0968] | 0.0000 [0.0000, 0.0000] |
| mAP@0.5 | 0.0005 [0.0000, 0.0047] | 0.0000 [0.0000, 0.0000] |

**Counts:**
- Baseline: TP=1, FP=45, FN=32, n_pred=46
- Trained:  TP=0, FP=0, FN=33, n_pred=0

## Iteration history

### Iteration 1 (run 1) — full collapse
- **SHA:** `hratcho/road-quality-la-yolov8@af7af59ad138554c67e774bd48cfe60e04193909`
- **Hyperparams:** `--epochs 50 --batch 32 --imgsz 640 --patience 15` (default lr=0.01)
- **Outcome:** Model emitted **zero predictions on every split** even at conf=0.01. Loss landscape on 13% positive rate gave a strong "predict nothing" attractor; default lr=0.01 too aggressive.

### Iteration 2 (run 2) — trained but didn't generalize to test
- **SHA:** `hratcho/road-quality-la-yolov8@84a874c2a5e7b08a9a701d31492bf7808356b0e0` (current)
- **Hyperparams:** `--epochs 100 --batch 16 --imgsz 800 --lr0 0.001 --patience 30 --cos-lr`
- **Internal val metrics (during training):** P=0.184, R=0.0714, mAP@0.5=0.0619 — real learning visible
- **External eval on test split:** P=0.000, R=0.000, mAP=0.000 — model emits 0 predictions on test even at conf=0.001
- **Diagnostic:** smoke test on first 5 images per split at conf=0.001:
  - Train: 7, 4, 57, 1, 3 predictions (model knows train well)
  - Val:   0, 6, 0, 25, 9 predictions (decent density)
  - Test:  0, 3, 0, 0, 0 predictions (essentially blind)

## Likely root cause: train/val/test labeling-style drift

Operator labeled CVAT splits in this order: **test → val → train**. Test was the operator's *first* labeling pass with the least-experienced eye; train was the *most-experienced* pass after labeling ~500 images. The model learned the train/val labeling style but the same potholes annotated in the earlier-pass test style aren't recognized.

This is a real labeling-quality phenomenon, not a model defect. It also means the test split isn't a fair evaluation of the trained model's detection capability — train/val numbers are likely the "truer" picture of the model's actual performance, but using val for both training validation AND final evaluation is leak-prone.

## D-13 contingency executed

D-13 cap: 2 trained runs total. Both spent. Per D-13: **close as documented negative result**.

## Plan 07-07 BLOCKED (intentional)

Per `WIN-CHECK.md` guardrail and D-13 negative path, Plan 07-07 (constant swap + production re-ingestion) is **NOT executed**. Re-ingesting prod with `--wipe-mapillary` against a model that emits zero predictions on the held-out test split would actively degrade the live demo.

`data_pipeline/detector_factory.py::_DEFAULT_HF_REPO` stays on `keremberke/yolov8s-pothole-segmentation@d6d5df4...`. Production unchanged.

## What ships from Phase 7 regardless

- **`scripts/ingest_mapillary.py --wipe-mapillary` flag + safety latch** (Plan 07-03 — useful infrastructure regardless of model outcome)
- **`scripts/eval_baseline_phase7.py`** (Plan 07-06 — re-eval'd keremberke baseline on the new ≥30-positive test split, replacing Phase 6's 3-positive numbers as the canonical baseline)
- **`scripts/eval_trained_phase7.py`** (Plan 07-06 — generic trained-eval script, ready for any future fine-tune attempt)
- **`docs/FINETUNE.md` Recipe C** (Plan 07-05 — EC2 g5.xlarge runbook, useful for any future training)
- **`bootstrap_ci_map50`** (Plan 07-02 — mAP@0.5 with image-level bootstrap CI, ships in `data_pipeline/eval.py`)
- **Hand-labeled 1322 LA Mapillary images / 171 positive bboxes** (Plan 07-04 — committed to git, available for any future re-attempt)

## Forward references

- Plan 07-08 (DETECTOR_EVAL.md update) substitutes the Phase 7 negative-result narrative into the public docs
- Plan 07-07 SUMMARY documents the intentional skip
- Future fine-tuning options preserved at `.planning/phases/07-la-trained-detector/FUTURE-FINETUNE-OPTIONS.md`

## Raw eval JSONs

- `.planning/phases/07-la-trained-detector/eval_results_baseline.json`
- `.planning/phases/07-la-trained-detector/eval_results_trained.json` (iter-2)
