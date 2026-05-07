# Future Fine-Tuning Options (deferred from Phase 7)

Phase 7 closed as a documented negative result after 2 trained runs hit
the D-13 iteration cap (iter-1 collapsed; iter-2 train/test labeling
drift). The hand-labeled dataset, eval scripts, and HF repo all remain
intact for any future re-attempt.

If the LA-trained detector becomes a real priority again, ranked options
by effort vs. expected payoff:

## Tier 1 — Cheapest, highest expected value (label-side fixes)

The iter-2 root cause was operator labeling-style drift across splits
(test labeled first with least experience, train labeled last with most).
Fix the labels, re-eval the existing iter-2 model, you may already win.

| Approach | Effort | Notes |
|----------|--------|-------|
| Re-label test split for consistency | 1–2 hr CVAT | Re-eval iter-2 on consistent test labels — could flip the win-check **without retraining** |
| Single consistent labeling pass on all 3 splits | 4–6 hr CVAT | Establish a written rubric, label all splits in one session, re-eval iter-2 |
| Pseudo-labeling pre-pass | 2–3 hr | Run keremberke at conf=0.1, manually approve/reject in CVAT — yields 3–5× more labels with consistent style, then retrain |

## Tier 2 — Add external pre-training data

| Approach | Effort | Notes |
|----------|--------|-------|
| RDD2022 pre-training | 4–6 hr | ~26k road-damage images, free academic license. Pre-train on RDD2022 → fine-tune on LA labels. Domain adaptation, the standard play |
| Roboflow Universe pothole datasets | 2–3 hr | Several public pothole datasets, varying quality. Merge with LA set, retrain |
| GoPro dashcam captures | 8–12 hr | Drive LA with phone-mounted camera. Better viewing angle than Mapillary's oblique 2D shots |

## Tier 3 — Different model / architecture

| Approach | Effort | Notes |
|----------|--------|-------|
| YOLO-World zero-shot | 1 hr | Prompt with "pothole in road surface", no fine-tuning |
| OWL-ViT zero-shot | 2 hr | Open-vocab detection from Google |
| YOLOv11s instead of v8s | 1 hr | Newer architecture, often 5–10% better mAP |
| RT-DETR | 3–4 hr | Transformer-based, more sample-efficient on small datasets |

## Tier 4 — Smarter training on existing data

| Approach | Effort | Notes |
|----------|--------|-------|
| Class-balanced batch sampling | 1 hr code + 2 hr Colab | Force ≥30% positive images per batch — addresses iter-1 collapse mode |
| Heavy augmentation (mosaic, mixup, copy-paste) | 0.5 hr code + 2 hr Colab | Synthetic data multiplies 171 bboxes effectively |
| Cross-validation ensemble | 2 hr code + 6 hr Colab | Train 5 models on different folds, ensemble at inference |

## Tier 5 — Pragmatic shortcuts

| Approach | Effort | Notes |
|----------|--------|-------|
| Use existing fine-tuned pothole detector from HF | 30 min | Search HF for "pothole-detection", swap `_DEFAULT_HF_REPO`. Honest framing: "evaluated and selected best public detector for LA imagery" |
| Stay on keremberke + keep improving non-detector layers | 0 hr | Frame the project as "data pipeline + routing infra" rather than "I personally fine-tuned" |

## Recommendation if revisited

**Tier 1 row 3 (pseudo-labeling) + Tier 2 row 1 (RDD2022)** combined.
Total effort: 8–12 hours. Likelihood of producing a model that genuinely
beats keremberke on a consistent test set: 60–70%.

If only 1–2 hours available: **Tier 1 row 1** (just re-label test) is the
cheapest experiment to verify the labeling-drift hypothesis.

## Existing artifacts that survive Phase 7 closure

- Hand-labeled dataset: `data/eval_la/` (1322 images, 171 positive bboxes,
  committed to git)
- Iter-2 trained weights: `hratcho/road-quality-la-yolov8@84a874c2...`
  on HuggingFace (val P=0.184, useless on test split)
- Iter-1 collapsed weights: `hratcho/road-quality-la-yolov8@af7af59a...`
  on HuggingFace (preserved for traceability)
- Eval scripts: `scripts/eval_baseline_phase7.py`,
  `scripts/eval_trained_phase7.py`
- Training runbook: `docs/FINETUNE.md` Recipe C v0.2.0
- `bootstrap_ci_map50` in `data_pipeline/eval.py`

Any future attempt picks up from here.
