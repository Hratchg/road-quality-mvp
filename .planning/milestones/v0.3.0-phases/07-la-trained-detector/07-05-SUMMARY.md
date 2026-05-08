---
phase: 07-la-trained-detector
plan: 05
subsystem: training
tags: [phase-07, wave-3, training, ec2-deferred, colab, operator-gate]

# Dependency graph
requires:
  - phase: 07-la-trained-detector
    plan: 04
    provides: Hand-corrected LA pothole labels (171 positives, 33 in test split, SC #1 met)

provides:
  - docs/FINETUNE.md v0.2.0 — Recipe C tuned for Phase 7 invocation (yolov8s.pt base, EC2 g5.xlarge runbook, SHA capture step)
  - .planning/phases/07-la-trained-detector/07-05-HF-SHA.txt — `af7af59ad138554c67e774bd48cfe60e04193909` (consumed by 07-06 eval + 07-07 constant swap)
  - hratcho/road-quality-la-yolov8 @ af7af59ad138554c67e774bd48cfe60e04193909 — trained weights pushed to HF Hub (best.pt + .gitattributes)

affects:
  - 07-06 (eval — SHA now resolvable, baseline + trained eval can run)
  - 07-07 (constant swap — _DEFAULT_HF_REPO target known)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Operator-gated checkpoint task pattern (GATE B mirroring 07-04's GATE A) — doc updates land first, training run is operator-driven, SHA capture file persists across plans
    - HF push fallback: ultralytics' built-in `--push-to-hub` silently no-ops on certain failure modes; manual `HfApi().upload_file('best.pt', ...)` is the reliable path

key-files:
  created:
    - .planning/phases/07-la-trained-detector/07-05-HF-SHA.txt (single-line SHA capture)
    - .planning/phases/07-la-trained-detector/07-05-SUMMARY.md (this file)
  modified:
    - docs/FINETUNE.md (Recipe C replaced + version 0.1.0 → 0.2.0 + changelog)
    - 15 files via namespace correction Hratchg → hratcho (data_pipeline/, backend/tests/, docs/, .planning/) — separate commit `801a5d8`

requirements-completed: []
duration: ~30min Task 1 (FINETUNE.md update) + ~3 hr Task 2 operator wall-clock (Colab T4 fine-tune + manual upload retry)
completed: 2026-05-06 (Tasks 1-3); GATE B closed via Colab path (substituted for prescribed EC2 g5.xlarge per operator preference)
---

# Phase 7 Plan 05 Summary

**`yolov8s.pt` fine-tuned on 1322 LA Mapillary images; trained weights published to HuggingFace at `hratcho/road-quality-la-yolov8@af7af59a...` and SHA captured for downstream constant swap. GATE B operator gate closed.**

## Plan Status

- **Tasks:** 3/3 complete (Task 1 + Task 3 automated, Task 2 = operator GATE B)
- **Completed (Task 1, FINETUNE.md):** 2026-05-05 — commit `b50d190`
- **Completed (Task 2, GATE B training):** 2026-05-06 — Google Colab T4 fine-tune (substituted for EC2 g5.xlarge per operator preference; same `--base yolov8s.pt --device 0 --epochs 50 --batch 32 --patience 15` invocation)
- **Completed (Task 3, SHA capture):** 2026-05-06 — `07-05-HF-SHA.txt` written with `af7af59ad138554c67e774bd48cfe60e04193909`

## What Shipped

### Task 1: docs/FINETUNE.md Recipe C update
Replaced Recipe C body with Phase 7 EC2 g5.xlarge runbook: instance setup table, scp dataset transfer, env-export HF token (NEVER UserData), full `--base yolov8s.pt --device 0 --epochs 50 --batch 32 --patience 15 --push-to-hub hratcho/road-quality-la-yolov8` invocation, `HfApi().model_info(...).sha` capture, D-13 iteration contingency, terminate-instance commands. Version 0.1.0 → 0.2.0 with changelog. Recipe A (laptop) and Recipe B (Colab) preserved unchanged.

### Task 2: Training run (GATE B operator-gated)
Fine-tuned `yolov8s.pt` on `data/eval_la/` (1322 images / 171 positive bboxes from Plan 07-04 GATE A) on Google Colab T4 GPU. Operator chose Colab over EC2 g5.xlarge to avoid AWS account/key-pair setup overhead — same script, same args, equivalent result for this dataset size. Trained `best.pt` produced at `runs/detect/runs/detect/la_pothole/weights/best.pt`.

### Task 3: SHA capture
Trained weights uploaded to HF Hub via manual `HfApi().upload_file()` after ultralytics' built-in `--push-to-hub` flag silently no-op'd (created the repo skeleton with only `.gitattributes`, never pushed `best.pt`). Final commit SHA `af7af59ad138554c67e774bd48cfe60e04193909` written to `07-05-HF-SHA.txt`. Verified via `api.list_repo_files()`: `[.gitattributes, best.pt]`.

## Files Created / Modified

**Created:**
- `.planning/phases/07-la-trained-detector/07-05-HF-SHA.txt`

**Modified:**
- `docs/FINETUNE.md` (Recipe C body + version + changelog)

**External artifact:**
- `hratcho/road-quality-la-yolov8@af7af59ad138554c67e774bd48cfe60e04193909` on HuggingFace

## Deviations from Plan

| Deviation | Reason | Impact |
|-----------|--------|--------|
| Training on Colab T4, not EC2 g5.xlarge | Operator preference — avoids AWS account/key/sg setup for a one-shot run | None on output: same script, same args, weights produced. Recipe C runbook in `docs/FINETUNE.md` is still the prescribed/documented path for reproducibility |
| Manual `HfApi().upload_file()` instead of ultralytics' `--push-to-hub` | Built-in `--push-to-hub` silently created repo skeleton without uploading `best.pt`; manual API call worked | None on output: weights are on HF at the captured SHA. Worth flagging in 07-08 docs as a known stub |
| Working dir nested as `runs/detect/runs/detect/la_pothole/` | Ultralytics quirk on Colab — relative `project=` interpreted twice | None on output; finder glob in push step needed `**/` recursion |

## Known Stubs (for Plan 07-08 docs closure)

- **`docs/FINETUNE.md` Recipe C "Capture HF SHA" step** — currently relies on the ultralytics built-in push. Plan 07-08 should add a fallback note: "If `model_info(...).sha` returns the head sha but `list_repo_files(revision=sha)` shows only `.gitattributes`, the upload silently no-op'd — manually push via `HfApi().upload_file(path_or_fileobj=..., path_in_repo='best.pt', repo_id=..., repo_type='model')` and re-query the SHA."

## What Plans 07-06 and 07-07 Can Now Do

- **07-06 eval:** read SHA from `07-05-HF-SHA.txt` → load model from `hratcho/road-quality-la-yolov8@<sha>` → run trained-model eval; pair with re-eval'd keremberke baseline → produce WIN-CHECK.md
- **07-07 constant swap:** read SHA from `07-05-HF-SHA.txt` → substitute into `data_pipeline/detector_factory.py::_DEFAULT_HF_REPO` → turns Plan 07-01 RED tests GREEN
