# Phase 2: Real-Data Detector Accuracy — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in `02-CONTEXT.md` — this log preserves the alternatives considered.

**Date:** 2026-04-23
**Phase:** 02-real-data-detector-accuracy
**Areas discussed:** Eval dataset — source & storage; Metrics & defensible bar; Model strategy & asset storage; Config surface & eval script shape

---

## Eval dataset — source & storage

User initially asked a framing question ("this is to prove YOLOv8 works correctly?") which led to reframing rigor in LA-specific terms once user clarified "the whole goal is to show that it works on streets in Los Angeles."

| Option | Description | Selected |
|--------|-------------|----------|
| A. LA smoke test (~1h) | ~20 Mapillary LA images, qualitative demo, no metrics | |
| B. LA demo-grade (~half day) | ~100 hand-labelled Mapillary LA images, precision/recall, docs writeup | |
| C. LA + generalization (~1 day) | B + 200-image RDD2020 subset for generalization | |
| D. Rigorous LA eval (~2–3 days) | 300+ labelled LA images, CIs, fine-tuning | ✓ |

**User's choice:** D — Rigorous LA eval, 300+ labelled images, CIs, fine-tuning included
**Notes:** No public pre-labelled LA pothole dataset exists. Dataset must be built from scratch using Mapillary images + hand-labelling.

---

### Sub-question: Low-score fallback

| Option | Description | Selected |
|--------|-------------|----------|
| Publish honestly + note limitations | Report whatever numbers come out, with caveats | |
| Include a fine-tuning step | Fine-tune on half the LA set, eval on other half | ✓ |
| Raise confidence threshold | Tune threshold to trade recall for precision | |

**User's choice:** Include a fine-tuning step.

---

### Sub-question: Dataset storage location

| Option | Description | Selected |
|--------|-------------|----------|
| External bucket + manifest + fetch script | Cloud bucket URL in manifest.json with SHA256; scripts/fetch_eval_data.py downloads | ✓ |
| Git LFS | Commit images + labels via LFS | |
| Committed small + manifest for rest | ~20 images inline, manifest for full set | |
| HuggingFace Datasets | Publish as HF dataset | |

**User's choice:** External bucket + manifest + fetch script.

---

## Metrics & defensible bar

### Q1: Primary metrics

| Option | Description | Selected |
|--------|-------------|----------|
| Precision + Recall | Core pair, ROADMAP requirement | ✓ |
| mAP@0.5 | Standard YOLO benchmark metric | ✓ |
| Per-severity breakdown | Moderate vs severe split | ✓ |
| False-positives-per-image | Deployment-relevant FP rate | |

**User's choice:** Precision + Recall + mAP@0.5 + Per-severity breakdown (FPPI skipped).

### Q2: IoU threshold

| Option | Description | Selected |
|--------|-------------|----------|
| IoU ≥ 0.5 | COCO/YOLO standard | ✓ |
| IoU ≥ 0.3 | Lenient | |
| COCO 0.5:0.95 | Stricter averaged | |

**User's choice:** IoU ≥ 0.5.

### Q3: Statistical rigor

| Option | Description | Selected |
|--------|-------------|----------|
| Bootstrap CIs | 1000 resamples, 95% CI | ✓ |
| Point estimates only | Single numbers, no CIs | |
| Bootstrap CIs + train/test split | Option 1 + explicit held-out test | |

**User's choice:** Bootstrap CIs.

### Q4: Writeup location

| Option | Description | Selected |
|--------|-------------|----------|
| docs/DETECTOR_EVAL.md new file | Dedicated doc | ✓ |
| Append to docs/PRD.md | Add to PRD implemented section | |
| New README section + CLI output | Lighter doc, heavier CLI | |

**User's choice:** docs/DETECTOR_EVAL.md new file.

---

## Model strategy & asset storage

### Q1: Base model

| Option | Description | Selected |
|--------|-------------|----------|
| Pothole-finetuned YOLOv8 from HF/Ultralytics Hub | HF-hosted pothole model as starting point | ✓ |
| Generic YOLOv8 COCO weights | yolov8n/s/m.pt, no pothole priors | |
| Compare both | Baseline both + fine-tune the winner | |

**User's choice:** Pothole-finetuned YOLOv8 from HF.

### Q2: Train/eval split

| Option | Description | Selected |
|--------|-------------|----------|
| 70/20/10 train/val/test | Gold-standard split with held-out test | ✓ |
| 80/20 train/test | Simpler, risk of overfitting | |
| k-fold cross-validation | Statistically strongest, ~5× compute | |

**User's choice:** 70/20/10.

### Q3: Model weight storage

Initial response asked "what would be best for reproducing on someone else's device?" — prompted Claude to explain HF vs local in depth.

| Option | Description | Selected |
|--------|-------------|----------|
| HuggingFace Hub | Base loaded by HF name, fine-tuned pushed to public HF repo | ✓ (after clarification) |
| Git-ignored + fetch script | Custom bucket + scripts/fetch_model.py | |
| Git LFS | Commit via LFS, needs lfs-install | |

**User's choice:** HuggingFace Hub — confirmed after Claude explained HF = URL-based model reference (ultralytics auto-downloads) vs local = file-on-disk with separate transport mechanism. HF won on zero-extra-steps reproducibility.

### Q4: Dataset storage (see also Area 1)

Answered as part of Area 1. Choice: External bucket + manifest + fetch script.

---

## Config surface & eval script shape

### Q1: Env var layout

| Option | Description | Selected |
|--------|-------------|----------|
| Single YOLO_MODEL_PATH | One var, accepts HF name or file path | ✓ |
| Layered YOLO_MODEL_NAME + YOLO_MODEL_PATH | Separate vars for HF vs local | |
| DetectorConfig dataclass | Env var + config object | |

**User's choice:** Single YOLO_MODEL_PATH.

### Q2: Eval CLI shape

| Option | Description | Selected |
|--------|-------------|----------|
| Separate focused scripts | Matches existing seed_data/compute_scores/ingest_iri pattern | ✓ |
| Single script with subcommands | Unified entry point | |
| Single script, many flags | One entrypoint | |

**User's choice:** Separate focused scripts.

### Q3: Fine-tuning workflow + cloud-readiness

User asked about running fine-tuning on AWS/cloud services. Prompted Claude to lay out cloud landscape (Colab, Ultralytics HUB, AWS EC2/SageMaker, Kaggle, RunPod) and 4 design options.

| Option | Description | Selected |
|--------|-------------|----------|
| B. Multi-env repro guide | Portable script + docs/FINETUNE.md (Laptop/Colab/EC2) + requirements-train.txt split | ✓ |
| A. Leave it open (no docs) | Just a portable script; no scaffolding | |
| C. Ultralytics HUB first | Use their cloud UI; skip most script work | |
| D. Full AWS Terraform/SageMaker | Full IaC training pipeline | |

**User's choice:** B. Multi-env repro guide.

### Q4: Missing-dataset default

| Option | Description | Selected |
|--------|-------------|----------|
| Fail loud with fetch hint | Exit 3, clear message pointing to fetch_eval_data.py | ✓ |
| Auto-fetch on first run | Eval auto-downloads if missing | |
| Mock tiny built-in dataset | Fallback to 5 committed images with banner | |

**User's choice:** Fail loud with fetch hint.

---

## Claude's Discretion

- Exact HF pretrained pothole model (researcher picks current best)
- Bucket provider for dataset hosting (S3/GCS/Backblaze/HF Datasets)
- Fine-tuned HF repo name (e.g., `<user>/road-quality-la-yolov8`)
- Labelling tool (CVAT / LabelStudio / Roboflow)
- Data-augmentation recipe during fine-tuning
- Fine-tune epochs + batch size (tuned via val set)
- Geographic spread within LA for Mapillary bbox selection
- Whether to report FPPI as a secondary metric

## Deferred Ideas

- Paper-grade eval with multi-dataset cross-validation, ablations, confidence calibration
- AWS-specific Terraform/SageMaker infra
- RDD2020 generalization footnote in DETECTOR_EVAL.md (optional)
- Labelling pipeline / UI tooling
- CI gate on detector accuracy
- Confidence calibration / temperature scaling
