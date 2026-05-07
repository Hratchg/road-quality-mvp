---
phase: 07-la-trained-detector
status: closed-negative
tags: [phase-07, milestone-m1, d-11-negative, d-13-iteration-cap]
plans_total: 8
plans_executed: 7
plans_skipped: 1  # 07-07 per D-13 negative path
duration_total: ~12 hours operator + ~3 hours Claude
completed: 2026-05-07
---

# Phase 7 Summary — LA-Trained Detector

**Goal (per ROADMAP):** Beat the public-baseline detector numbers measured in Phase 6 with a YOLOv8 fine-tuned on a substantially larger LA dataset.

**Outcome: NEGATIVE.** Both trained iterations failed the D-11 win-check (non-overlapping 95% CI, trained > baseline) on the held-out test split. Phase 7 closes as a documented negative result per D-13. Production retains the public baseline `keremberke/yolov8s-pothole-segmentation`.

## Plans

| Plan | Status | Output |
|------|--------|--------|
| 07-01 | ✅ executed | Wave-0 RED tests for `bootstrap_ci_map50`, `wipe_mapillary_rows`, `_DEFAULT_HF_REPO` pin |
| 07-02 | ✅ executed | `bootstrap_ci_map50` impl + `_DEFAULT_LA_BBOXES` expansion to 12 zones / 48 sub-tiles + `start_captured_at` recency filter |
| 07-03 | ✅ executed | `--wipe-mapillary` CLI flag + `wipe_mapillary_rows()` helper + shared `--force-wipe` safety latch |
| 07-04 | ✅ executed | 1164 Mapillary images downloaded across 12 LA zones, prelabeled, **GATE A operator hand-labeling: 171 positive bboxes (33 in test, SC #1 met)** |
| 07-05 | ✅ executed | `FINETUNE.md` Recipe C v0.2.0 + **GATE B operator EC2/Colab training run + HF SHA capture** |
| 07-06 | ✅ executed | Re-eval'd baseline + iter-1 (collapsed) + iter-2 (drift) + WIN-CHECK NEGATIVE |
| 07-07 | 🚫 **SKIPPED** | Per D-13 negative path: constant swap + production cutover would degrade live demo |
| 07-08 | ✅ executed | DETECTOR_EVAL.md v0.3.0 + README detector disclosure + MAPILLARY_INGEST.md --wipe-mapillary doc |

## Success Criteria

| SC | Required | Status |
|----|----------|--------|
| 1  | ≥150 positive bboxes total, ≥30 in test split | ✅ 171 total, 33 test |
| 2  | Trained detector beats baseline on test split (non-overlapping 95% CI) | ❌ NEGATIVE both iterations |
| 3  | Trained model published to HF at `hratcho/road-quality-la-yolov8@<sha>` | ✅ both iter-1 (af7af59a) and iter-2 (84a874c2) public on HF |
| 4  | `_DEFAULT_HF_REPO` updated to trained model | ❌ INTENTIONALLY SKIPPED per D-13 negative |
| 5  | Production DB re-ingested with trained-detector detections | ❌ INTENTIONALLY SKIPPED per D-13 negative |
| 6  | `docs/DETECTOR_EVAL.md` updated; old baseline preserved | ✅ v0.3.0 documents Phase 7 attempt + preserves Phase 6 + adds Phase 7 re-eval'd baseline |
| 7  | README updated to reflect new detector status | ✅ truthful disclosure: keremberke in prod, Phase 7 attempted-and-documented |

SCs 2/4/5 fail by design under the D-13 negative path; SCs 6/7 explicitly land the negative narrative.

## Two failure modes documented

**Iteration 1 — collapse.** Default lr=0.01 + 13%-positive dataset → "predict nothing" attractor; model emits zero predictions on every split. Diagnosed via direct smoke test at conf=0.01.

**Iteration 2 — train/test drift.** Tuned hyperparameters (`--lr0 0.001 --imgsz 800 --batch 16 --cos-lr --epochs 100`) produced real training (val P=0.184, R=0.071) but model emits 0 predictions on the held-out test split. Likely root cause: operator labeling-style drift across CVAT splits — test labeled first with least experience, train labeled last with most. The model learned the train/val style but doesn't recognize potholes in the earlier-pass test style.

## What ships net-net (despite negative outcome)

Real, useful infrastructure that survives Phase 7:

1. **`--wipe-mapillary` flag + safety latch** in `scripts/ingest_mapillary.py` (re-usable for any future detector swap)
2. **`bootstrap_ci_map50`** in `data_pipeline/eval.py` (image-level mAP@0.5 with bootstrap CI, ships in production code)
3. **`scripts/eval_baseline_phase7.py`** + **`scripts/eval_trained_phase7.py`** (val()-bypass eval scripts, byte-identical schema, re-usable)
4. **`docs/FINETUNE.md` Recipe C v0.2.0** (EC2 g5.xlarge runbook, applies to any future training)
5. **`--lr0` and `--cos-lr` flags** in `scripts/finetune_detector.py` (hyperparameter overrides not in original Phase 2 argparse)
6. **Hand-labeled dataset**: 1322 LA Mapillary images / 171 positive bboxes / 12 zones, committed to git
7. **Phase 7 re-eval'd baseline** (P=0.022, R=0.030 on 33-positive test split) — canonical baseline replacing Phase 6's 3-positive numbers
8. **FUTURE-FINETUNE-OPTIONS.md** — 5-tier ranked menu of fix paths for any future re-attempt
9. **Two trained model artifacts public on HF** at `hratcho/road-quality-la-yolov8` (iter-1: collapse traceability; iter-2: drift traceability)

## Production impact

**Zero.** Live demo at https://road-quality-frontend.fly.dev/ is unchanged. Same keremberke detector, same Mapillary detections, same routing behavior.

## What's next

**Phase 8 — Routing Performance.** `pgr_ksp` cross-LA latency (currently 20–90s for long trips) needs the GiST-pre-filter fix documented in ROADMAP.md. This is the high-value next phase that's been gated on Phase 7 closure.

## Honest portfolio framing

Phase 7's lesson is more valuable than its planned win would have been. "I attempted to fine-tune YOLOv8 on a 171-bbox LA dataset, hit a textbook sparse-positive collapse on iter-1, fixed it with hyperparameter tuning, then discovered train/val/test labeling-style drift on iter-2 — documented both failure modes honestly, kept the public baseline in production rather than deploying a broken model" is a stronger interview talking point than "I fine-tuned a YOLOv8 detector and it slightly beat the baseline."

The dataset, scripts, and trained weights all survive for any future re-attempt.
