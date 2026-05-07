---
phase: 07-la-trained-detector
plan: 08
subsystem: documentation
tags: [phase-07, wave-4, docs, closure, sc-6, sc-7]

# Dependency graph
requires:
  - phase: 07-la-trained-detector
    plan: 06
    provides: D-11 NEGATIVE verdict + iteration history + re-eval'd baseline numbers

provides:
  - docs/DETECTOR_EVAL.md v0.3.0 (Phase 7 attempt documented honestly, baseline + iteration history preserved)
  - README.md updated detector disclosure (truthful: keremberke baseline in prod, Phase 7 attempted twice and closed negative)
  - docs/MAPILLARY_INGEST.md --wipe-mapillary flag documented

affects:
  - Phase 7 closure (this is the last plan that ships)
  - Future Phase 8 (Routing Performance) is unblocked

# Tech tracking
tech-stack: {added: [], patterns: []}

key-files:
  modified:
    - docs/DETECTOR_EVAL.md (v0.2.0 → v0.3.0)
    - README.md (detector disclosure + current status)
    - docs/MAPILLARY_INGEST.md (--wipe-mapillary entry + Phase 7 cutover note)
  created:
    - .planning/phases/07-la-trained-detector/07-08-SUMMARY.md (this file)

requirements-completed:
  - SC #6 (DETECTOR_EVAL.md updated; preserves Phase 6 baseline + adds Phase 7 re-eval'd baseline + Phase 7 attempt narrative)
  - SC #7 (README detector status reflects reality: keremberke baseline in production, Phase 7 attempted-and-documented)

duration: ~30 min
completed: 2026-05-07
---

# Phase 7 Plan 08 Summary — docs closure (negative-result narrative)

**Three documentation files updated to reflect Phase 7's actual outcome (D-11 NEGATIVE) instead of the originally-anticipated "fine-tuned LA detector wins" narrative. Production state unchanged; docs now accurately describe what's actually shipping.**

## What changed

### docs/DETECTOR_EVAL.md (v0.2.0 → v0.3.0)
- Header status updated: "Phase 7 fine-tuning attempted (2 iterations) — closed as documented NEGATIVE result"
- Added "TL;DR — what's actually shipping in production" — explicit truthfulness table (what's true / what's not true)
- Added "Phase 7 fine-tuning attempt (NEGATIVE result, both iterations)" section: iteration history (collapse + drift), root cause analysis (train/val/test labeling-style drift), Phase 7 re-eval'd baseline numbers (replaces Phase 6's 3-positive numbers as canonical)
- Phase 6 baseline section preserved unchanged below the new content (relabeled "historical")

### README.md
- "Pipeline" detector bullet (line 17): replaced "YOLOv8 fine-tuned on hand-labelled LA Mapillary imagery" with truthful description: keremberke baseline in production, Phase 7 attempted twice and documented as negative. Both attempted models linked publicly on HF.
- "Current Status" line (line 25): replaced "LA-trained YOLOv8 pothole detector" with "public-baseline YOLOv8 pothole model" + reference to DETECTOR_EVAL.md retrospective.

### docs/MAPILLARY_INGEST.md
- Options table (line 106-107): added `--wipe-mapillary` row (Plan 07-03 ship); updated `--force-wipe` row to cover both wipe variants.
- Note on the `--wipe-mapillary` entry that it was NOT executed against production in Phase 7 (D-13 negative path).

## Why these docs matter for portfolio integrity

A common failure mode in ML portfolio projects is publishing aspirational numbers that don't match what's actually deployed. The previous README claim "LA-trained YOLOv8 pothole detector" was forward-looking when written (Phase 7 was supposed to deliver it) but became a misrepresentation once Phase 7 closed negative.

The honest update — keremberke in production, Phase 7 attempted-and-documented — is a stronger signal for technical interviewers than a polished claim that doesn't survive a five-minute investigation of the actual `_DEFAULT_HF_REPO` constant.

## Files NOT modified (intentional)

- `data_pipeline/detector_factory.py::_DEFAULT_HF_REPO` — STAYS on `keremberke/yolov8s-pothole-segmentation@d6d5df4...` (Plan 07-07 SKIPPED)
- `backend/tests/test_detector_factory.py` Phase 7 RED tests — STAY RED with skip markers (Plan 07-07 SKIPPED)
- `data/eval_la/` labels — STAY committed for any future re-attempt
- HF repo `hratcho/road-quality-la-yolov8` — both SHAs (iter-1, iter-2) STAY public for reproducibility

## What ships from Phase 7 net-net

Despite the negative training outcome, Phase 7 ships real infrastructure:

1. `--wipe-mapillary` flag + safety latch in `scripts/ingest_mapillary.py` (Plan 07-03)
2. `bootstrap_ci_map50` in `data_pipeline/eval.py` (Plan 07-02)
3. `scripts/eval_baseline_phase7.py` + `scripts/eval_trained_phase7.py` (Plan 07-06 — reusable for any future fine-tune)
4. `docs/FINETUNE.md` Recipe C v0.2.0 — EC2 g5.xlarge runbook (Plan 07-05)
5. `--lr0` and `--cos-lr` flags in `scripts/finetune_detector.py` (Plan 07-06 hotfix)
6. Hand-labeled dataset: 1322 LA Mapillary images, 171 positive bboxes, committed to git
7. The Phase 7 re-eval'd baseline (P=0.022, R=0.030 on 33-positive test split) replacing Phase 6's 3-positive numbers as the canonical measurement
8. `FUTURE-FINETUNE-OPTIONS.md` — 5-tier ranked menu of fix paths if a future re-attempt is undertaken

That's a productive phase even when the headline goal didn't land.
