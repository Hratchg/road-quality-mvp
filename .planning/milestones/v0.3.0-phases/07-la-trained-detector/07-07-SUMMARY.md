---
phase: 07-la-trained-detector
plan: 07
subsystem: production-cutover
tags: [phase-07, wave-4, production, intentionally-skipped, d-13-negative]

# Dependency graph
requires:
  - phase: 07-la-trained-detector
    plan: 06
    provides: D-11 win-check verdict (NEGATIVE both iterations)

provides:
  - (none — plan intentionally skipped per D-13 negative path)

affects:
  - Production state (UNCHANGED — _DEFAULT_HF_REPO stays at keremberke/yolov8s-pothole-segmentation@d6d5df4..., live demo unchanged)
  - Plan 07-01 RED tests (stay RED with skip markers — already documented as Phase 7 contingent in test_detector_factory.py)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - D-13 negative-path skip: when WIN-CHECK verdict is NEGATIVE on iteration cap, downstream production-cutover plans skip without execution. Documented here so future readers understand why no constant swap or prod re-ingest commit exists.

key-files: {}
requirements-completed: []
duration: 0 (skipped)
completed: 2026-05-07 — INTENTIONALLY SKIPPED per Plan 07-06 D-11 NEGATIVE verdict
---

# Phase 7 Plan 07 — INTENTIONALLY SKIPPED

**Plan 07-06 closed as D-11 NEGATIVE (both trained iterations failed test eval). Per D-13 contingency, Plan 07-07 (constant swap + production re-ingestion) is NOT executed because the trained model would actively degrade the live demo.**

## What 07-07 was supposed to do

1. **Part 1 (automated):** Swap `data_pipeline/detector_factory.py::_DEFAULT_HF_REPO` from `keremberke/yolov8s-pothole-segmentation@d6d5df4...` to `hratcho/road-quality-la-yolov8@<sha>`. Turns Plan 07-01 RED tests GREEN.
2. **Part 2 (operator-gated):** Run `scripts/ingest_mapillary.py --wipe-synthetic --wipe-mapillary` against production Fly DB via `flyctl proxy 15432:5432`, target the training-zone + adjacent-expansion bbox set (D-16), let auto-recompute refresh `segment_scores`. Then redeploy backend so the in-memory `_DEFAULT_HF_REPO` reflects the new constant.

## Why skipped

The trained iter-2 model emits **zero predictions** on the held-out test split (n_pred_bboxes=0 across 136 images at any confidence threshold including 0.001). Executing 07-07 would:

1. **Constant swap (Part 1)** — direct production traffic to a detector that produces 0 detections on real-world LA imagery. Backend would still serve `/segments` and `/route` but pothole_score signal would collapse to zero.
2. **Production re-ingestion (Part 2)** — `--wipe-mapillary` would DELETE all 12 zones' real Mapillary detections, then attempt to re-ingest with the broken detector, producing empty results. The live demo at `road-quality-frontend.fly.dev` would lose its core value proposition: "real LA pothole data informing routes" → "no pothole signal anywhere."

This is the exact failure mode D-13 negative path is designed to prevent.

## Production state preserved

| Component | Pre-Phase-7 | Post-Phase-7 (skipped 07-07) |
|-----------|-------------|------------------------------|
| `_DEFAULT_HF_REPO` | `keremberke/yolov8s-pothole-segmentation@d6d5df4...` | unchanged |
| Production Mapillary detections | 12 LA zones, real Mapillary signal | unchanged |
| Live demo | working with real pothole data | working with real pothole data |
| `backend/tests/test_detector_factory.py` Phase 7 RED tests | RED (skip-marked) | RED (skip-marked, unchanged) |

## Future re-attempt path

If a future fine-tune attempt produces a model with non-zero test-split predictions and a D-11 win, this plan re-opens:

1. Re-run Plan 07-05 GATE B with new training (per `FUTURE-FINETUNE-OPTIONS.md` recommendations)
2. Re-run Plan 07-06 eval + win-check
3. If WIN: execute this plan (07-07) per the original plan body

The plan file `07-07-PLAN.md` is preserved as-is for that purpose.

## Files created / modified

None. This SUMMARY exists only to document the intentional skip.
