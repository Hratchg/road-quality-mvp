---
phase: 07-la-trained-detector
plan: 06
subsystem: evaluation
tags: [phase-07, wave-3, eval, win-check, d-11, d-13-negative]

# Dependency graph
requires:
  - phase: 07-la-trained-detector
    plan: 05
    provides: Trained model SHA pinned at hratcho/road-quality-la-yolov8@<sha>

provides:
  - scripts/eval_baseline_phase7.py (manual val()-bypass eval for keremberke segmentation model)
  - scripts/eval_trained_phase7.py (trained model eval, byte-identical schema to baseline)
  - .planning/phases/07-la-trained-detector/eval_results_baseline.json (re-eval'd keremberke on 33-positive Phase 7 test split)
  - .planning/phases/07-la-trained-detector/eval_results_trained.json (iter-2 trained on same split)
  - .planning/phases/07-la-trained-detector/07-06-WIN-CHECK.md (D-11 NEGATIVE verdict, both iterations)
  - .planning/phases/07-la-trained-detector/FUTURE-FINETUNE-OPTIONS.md (deferred work memo)

affects:
  - 07-07 (constant swap + production cutover — INTENTIONALLY SKIPPED per D-13 negative path)
  - 07-08 (docs closure — picks up the negative narrative for DETECTOR_EVAL.md v0.3.0)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - val()-bypass eval pattern (predict() + match_predictions + bootstrap_ci) shared between baseline and trained scripts so JSON schemas match by construction (D-11 win-check requires identical key sets)
    - Hardcoded ground-truth/predict-pair tracking enables both bootstrap_ci (P/R) AND bootstrap_ci_map50 (mAP) without re-iterating images

key-files:
  created:
    - scripts/eval_baseline_phase7.py
    - scripts/eval_trained_phase7.py
    - .planning/phases/07-la-trained-detector/eval_results_baseline.json
    - .planning/phases/07-la-trained-detector/eval_results_trained.json
    - .planning/phases/07-la-trained-detector/07-06-WIN-CHECK.md
    - .planning/phases/07-la-trained-detector/FUTURE-FINETUNE-OPTIONS.md
    - .planning/phases/07-la-trained-detector/07-06-SUMMARY.md (this file)

requirements-completed: []
duration: ~2 hr eval (baseline + iter-1 + iter-2 runs locally) + ~6 hr Colab (iter-2 retraining) + analysis
completed: 2026-05-07 — closed as D-13 NEGATIVE
---

# Phase 7 Plan 06 Summary — D-11 NEGATIVE

**Both Phase 7 trained iterations failed to beat the public-baseline keremberke detector on the held-out test split. Phase 7 closes as a documented negative result per D-13 contingency. Production stays on keremberke; Plans 07-07 (constant swap + prod cutover) intentionally skipped.**

## Numbers

| Metric | Baseline (keremberke@d6d5df4) | Trained iter-2 (hratcho@84a874c2) |
|--------|-------------------------------|------------------------------------|
| Precision | 0.0217 [0, 0.068] | 0.0000 [NaN, NaN] |
| Recall    | 0.0303 [0, 0.097] | 0.0000 [0, 0] |
| mAP@0.5   | 0.0005 [0, 0.005] | 0.0000 [0, 0] |
| Predictions | 46 (TP=1, FP=45) | 0 (TP=0, FP=0) |

Both numbers on 136-image / 33-bbox test split (SC #1 met).

## Two distinct failure modes documented

**Iteration 1 (collapsed):** Default lr=0.01 too aggressive on 13%-positive dataset → model learned to predict nothing on every split. Detected via direct smoke test (0 preds at conf=0.01).

**Iteration 2 (overfit-to-train/val):** Tuned hyperparams (--lr0 0.001 --imgsz 800 --batch 16 --cos-lr --epochs 100) produced real training (val P=0.184, R=0.071) but model emits 0 predictions on test split. Per-split smoke test at conf=0.001 (5 images each):
- Train: 7, 4, 57, 1, 3 preds
- Val:   0, 6, 0, 25, 9 preds
- Test:  0, 3, 0, 0, 0 preds

Likely root cause: operator labeling-style drift (CVAT splits labeled in order test → val → train; operator skill improved across the session, so test labels are systematically less consistent with train labels than train/val are with each other).

## What was built

### Task 1: scripts/eval_baseline_phase7.py
val()-bypass eval for keremberke segmentation model on the new 33-positive test split. Replaces Phase 6's 3-positive baseline numbers (P=0.143, R=0.333) with apples-to-apples comparable Phase 7 numbers (P=0.022, R=0.030). The Phase 6 numbers were too sparse to be statistically usable; Phase 7's are still weak but defensible.

### Task 1.5: scripts/eval_trained_phase7.py
Near-copy of baseline script with `--hf-sha-file` flag pointing at `07-05-HF-SHA.txt`. Both scripts emit byte-identical JSON schemas by construction so the win-check can compare without schema-mismatch fallbacks.

### Task 2: Eval runs
Baseline + iter-2 trained both eval'd on the test split. JSONs committed to git for traceability.

### Task 3: 07-06-WIN-CHECK.md
D-11 verdict: NEGATIVE on both iterations. D-13 contingency executed (close as documented negative).

## Deviations from plan

| Deviation | Reason |
|-----------|--------|
| WIN-CHECK rewritten after iter-2 (was iter-1 only) | Iter-2 produced different failure mode (overfit) than iter-1 (collapse); both now documented in iteration history section |
| `--lr0` and `--cos-lr` flags added to `scripts/finetune_detector.py` | Iter-2 hyperparameters not exposed by Phase 2 argparse; flags shipped in commit `e1909f5` |
| Iter-2 weights pushed to HF via manual `HfApi().upload_file()` | ultralytics built-in `--push-to-hub` errored on model card YAML metadata validation (`datasets[0]: "mapillary/street-level-imagery (CC-BY-SA 4.0)"` not a valid HF dataset id). Documented as known issue in `_build_model_card`; weights uploaded successfully via direct API call |

## Known Stubs (non-blocking)

- **`scripts/finetune_detector.py::_build_model_card`** generates YAML with an invalid `datasets[0]` value. Future fine-tune attempts must either fix this or use the manual upload pattern documented in 07-05-SUMMARY. Tracked as deferred work in `FUTURE-FINETUNE-OPTIONS.md`.

## What gates next

**Plan 07-07 SKIPPED** per D-13 negative path. Constant swap + production re-ingestion would degrade live demo (model emits 0 preds on test → would emit ~0 preds on production imagery → wipe Mapillary signal).

**Plan 07-08 PROCEEDS** with negative-result documentation: DETECTOR_EVAL.md v0.3.0 documents both Phase 7 failure modes, preserves Phase 6 baseline + Phase 7 re-eval'd baseline as the canonical numbers; README.md keeps "ships with public baseline" disclosure with a one-line Phase 7 attempt note; MAPILLARY_INGEST.md documents the new --wipe-mapillary flag (Plan 07-03 ship, useful regardless of model outcome).
