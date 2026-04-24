# Phase 2: Real-Data Detector Accuracy - Research

**Researched:** 2026-04-23
**Domain:** YOLOv8 pothole detection + reproducible eval harness + HuggingFace-hosted assets + Mapillary imagery ingestion
**Confidence:** MEDIUM-HIGH (stack + patterns verified from official sources; one locked decision — D-14 — needs a correction flagged below)

## Summary

Phase 2 is a three-axis problem: (1) build a labelled LA pothole eval set from Mapillary images + hand labels in YOLO `.txt` format, hosted externally and pinned by SHA256; (2) run + fine-tune a pretrained YOLOv8 pothole model on that set, publish weights to HuggingFace; (3) publish precision/recall/mAP@0.5 numbers with bootstrap CIs in `docs/DETECTOR_EVAL.md`. The detector config gets refactored to read `YOLO_MODEL_PATH` from env, fixing the CWD-relative hardcoded-path issue flagged in `.planning/codebase/CONCERNS.md`.

**The single most important correction to the locked decisions:** D-14 assumes ultralytics `YOLO()` natively auto-detects HuggingFace repo names like `user/road-quality-la-yolov8`. **It does not.** Base ultralytics only auto-downloads its own official models (`yolov8n.pt`, `yolo11n.pt`) from GitHub releases. The community wrapper `ultralyticsplus` that once provided this has been unmaintained for 12+ months and pins ancient versions (`ultralytics==8.0.21`). The correct, current-2026 pattern is a two-step load: `hf_hub_download(repo_id=..., filename="best.pt")` returns a local cache path, then `YOLO(local_path)`. The public `YOLO_MODEL_PATH` env var surface in D-14 still works — we just interpret the value ourselves (HF repo ID vs. local file path) rather than relying on ultralytics to do it. This is a small correction to the loading mechanism, not to the user-facing config design.

**Primary recommendation:** Follow CONTEXT.md decisions D-01 through D-18 with one modification to D-14 (the HF-auto-detect part is implemented in our factory, not delegated to ultralytics). Use `huggingface_hub.hf_hub_download` for load, `HfApi.upload_folder` for publish, `scipy.stats.bootstrap` for CIs. Start from `keremberke/yolov8s-pothole-segmentation` as the fine-tune base (known-good, 6.76 MB `best.pt`, segmentation model with box metrics), fallback to the official `yolov8n.pt` from GitHub releases. CVAT for labelling (free, native YOLO export, single-operator-friendly). Choose HuggingFace Datasets as the eval-set bucket for identical-infra-to-weights reproducibility.

## User Constraints (from CONTEXT.md)

### Locked Decisions

**Eval Dataset — Source & Storage**
- **D-01:** Rigorous LA eval. ~300+ hand-labelled Mapillary LA images.
- **D-02:** Dataset built from scratch in this phase. Mapillary is the image source.
- **D-03:** If pretrained scores < ~50% precision, fine-tune on LA training split.
- **D-04:** Dataset storage = external bucket + `data/eval_la/manifest.json` + `scripts/fetch_eval_data.py`. Manifest pins SHA256 hashes. Bucket provider = Claude's discretion.
- **D-05:** Label format = YOLO `.txt` (one `.txt` per image, `class_id cx cy w h` normalized).

**Metrics & Defensible Bar**
- **D-06:** Primary metrics = Precision + Recall + mAP@0.5 + per-severity breakdown (moderate vs severe).
- **D-07:** IoU threshold = 0.5.
- **D-08:** Bootstrap CIs, 1000 resamples, 95% interval.
- **D-09:** Train/val/test = 70/20/10. Test never touches fine-tuning.
- **D-10:** Writeup at `docs/DETECTOR_EVAL.md`, linked from README.

**Model Strategy & Asset Storage**
- **D-11:** Fine-tune base = pothole-finetuned YOLOv8 from HuggingFace Hub. Fallback = generic COCO YOLOv8n.
- **D-12:** Weights on HuggingFace Hub (naming = Claude's discretion).
- **D-13:** Upload via `huggingface-cli upload` after training. `HUGGINGFACE_TOKEN` from env.

**Config Surface & Eval Script Shape**
- **D-14:** Single `YOLO_MODEL_PATH` env var. Either HF model name OR local file path. Default (if unset) falls back to versioned HF name hardcoded in `detector_factory.py`. *(See correction in Summary: our factory handles HF-vs-local detection, not ultralytics directly.)*
- **D-15:** Three separate focused scripts: `eval_detector.py`, `finetune_detector.py`, `fetch_eval_data.py`.
- **D-16:** Multi-env reproduction guide (Option B). `docs/FINETUNE.md` covers laptop, Colab, EC2/SageMaker. `requirements-train.txt` splits heavy training deps from light eval deps.
- **D-17:** Missing dataset = exit 3 + fetch hint. No hidden auto-downloads.
- **D-18:** Exit codes: 0 OK / 2 below floor / 3 missing data / 1 other.

### Claude's Discretion

- Exact HF pretrained pothole model to start from (swap via config)
- Bucket provider for dataset hosting (S3 / GCS / Backblaze / HF Datasets — pick by repro friction; HF Datasets recommended if licensing fits)
- HF repo name for fine-tuned weights
- Labelling tool (CVAT / LabelStudio / Roboflow — format is what matters per D-05)
- Data-augmentation recipe (YOLOv8 defaults usually fine for 300 images)
- Fine-tune epochs + batch size (Claude tunes with val set)
- Whether to report false-positives-per-image as a secondary metric
- Geographic diversity within LA for image pull

### Deferred Ideas (OUT OF SCOPE)

- Paper-grade eval (multi-dataset cross-validation, calibration curves, ablations)
- AWS-specific Terraform / SageMaker infra
- Generalization comparison against RDD2020 (nice footnote if easy, not required)
- Labelling UI / labelling pipeline tooling
- Continuous eval / CI gate on detector accuracy
- Confidence calibration / temperature scaling

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REQ-real-data-accuracy | YOLOv8Detector runs end-to-end on curated LA images with reported precision/recall on a labelled eval set. Reproducible script, real model via `get_detector(use_yolo=True, model_path=...)`, documented metrics in `docs/`. | Scripts pattern (§Code Examples), model loading via `hf_hub_download` + `YOLO()` (§Architecture), eval metrics via `model.val()` + bootstrap CI via `scipy.stats.bootstrap` (§Standard Stack), writeup template (§Architecture). |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Model loading (HF repo name OR local path) | `data_pipeline/detector_factory.py` | `data_pipeline/yolo_detector.py` | Factory is single injection point per existing pattern; yolo_detector receives an already-resolved local path |
| `YOLO_MODEL_PATH` env var read | `data_pipeline/detector_factory.py` (module top) | — | Existing pattern: `backend/app/db.py` reads `DATABASE_URL` at import |
| Eval orchestration | `scripts/eval_detector.py` | `data_pipeline/eval.py` (new module for reusable metric fns) | Scripts are CLI shells over library fns — mirrors `ingest_iri.py` + `iri_sources.py` split |
| Fine-tuning orchestration | `scripts/finetune_detector.py` | `data_pipeline/finetune.py` (optional helper module) | Same split as eval |
| Dataset fetch + SHA256 verify | `scripts/fetch_eval_data.py` | `data_pipeline/mapillary.py` (shared client, Phase 3 reuse) | Phase 3 will import the Mapillary client; factoring now avoids refactor later |
| Mapillary API client | `data_pipeline/mapillary.py` (new) | — | Cross-phase shared module; Phase 2 uses for one-shot bulk pull, Phase 3 uses for ongoing ingestion |
| HuggingFace upload | `scripts/finetune_detector.py` (optional `--push` flag) | — | Upload is a train-adjacent action, not a standalone concern |
| Bootstrap CI computation | `data_pipeline/eval.py` (if broken out) or inline in `eval_detector.py` | `scipy.stats.bootstrap` | Pure function — no tier ambiguity |
| Metrics writeup | `docs/DETECTOR_EVAL.md` | — | Documentation tier; references JSON output from `eval_detector.py --json-out` |
| Multi-env training guide | `docs/FINETUNE.md` | — | Documentation tier; Colab notebook stub optionally at `docs/finetune_colab.ipynb` |

**Tier-boundary sanity checks:**
- Eval scripts do NOT touch the database. They run standalone against local image files. `DATABASE_URL` is not imported. [CITED: existing scripts pattern, D-15]
- Fine-tuning is not exposed through the backend API. It's a one-off operator CLI. Backend imports nothing from `scripts/` or `data_pipeline/finetune.py`.
- The existing `PotholeDetector` Protocol and `YOLOv8Detector.detect()` signatures are **not changed**. Only the model-path resolution defaults change in the factory. [CITED: CONTEXT.md code_context section]

## Standard Stack

### Core (runtime inference path + eval)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `ultralytics` | `>=8.3.0,<9.0` (latest is 8.4.41) | YOLO model wrapper — `YOLO()`, `model.predict()`, `model.val()`, `model.train()` | Official SDK, used in existing `data_pipeline/yolo_detector.py`. Already in `data_pipeline/requirements.txt` pinned `>=8.1`. [VERIFIED: `data_pipeline/requirements.txt`; CITED: docs.ultralytics.com] |
| `huggingface_hub` | `>=0.24,<1.0` | `hf_hub_download()` for model fetch, `HfApi.upload_folder()` / `huggingface-cli upload` for publish | Official HF client; replaces the unmaintained `ultralyticsplus` for HF loading [CITED: https://huggingface.co/docs/huggingface_hub/guides/download] |
| `opencv-python-headless` | `>=4.8` | Image I/O for YOLO (ultralytics dep anyway but pinned explicitly) | Already in `data_pipeline/requirements.txt` [VERIFIED: file read] |
| `scipy` | `>=1.13` | `scipy.stats.bootstrap` — 1000-resample 95% CI computation | Standard, already installed system-wide (scipy 1.13.1 verified on dev machine). Native bootstrap method fits D-08 exactly [VERIFIED: `python3 -c "import scipy; print(scipy.__version__)"` → 1.13.1; CITED: https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html] |
| `Pillow` | `>=10` | Image reading for label validation + annotation sanity checks | Already present system-wide (PIL 11.3 verified); transitive dep of ultralytics anyway [VERIFIED: system check] |
| `numpy` | `>=2.2` | Array manipulation for ground-truth vs predictions matching | Already in `scripts/requirements.txt` [VERIFIED: file read] |

### Supporting (training only — `requirements-train.txt`)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `torch` | `>=2.4.1,<2.10` (explicitly avoid 2.4.0 — ultralytics check rejects it) | PyTorch runtime for ultralytics | Fine-tuning only. CPU wheel on Linux/Windows laptops; MPS on M-series Macs (see pitfall below); CUDA on Colab/EC2 [CITED: https://github.com/ultralytics/ultralytics/blob/main/pyproject.toml constraint `torch!=2.4.0,>=1.8.0`] |
| `torchvision` | paired with torch (e.g., torch 2.5 → torchvision 0.20) | Image transforms + dataset loaders | Required by ultralytics training path [CITED: pytorch.org compatibility matrix] |
| `pyyaml` | `>=6.0` | Read `data.yaml` | ultralytics brings it transitively; pin explicitly for clarity |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `hf_hub_download` + `YOLO(local_path)` | `ultralyticsplus.YOLO("user/repo")` | `ultralyticsplus` is **unmaintained** (last release pins `ultralytics==8.0.21`, inactive per Snyk advisor). Using it would force a two-year-old ultralytics version across the whole codebase. [VERIFIED: Snyk advisor; CITED: https://snyk.io/advisor/python/ultralyticsplus] |
| `scipy.stats.bootstrap` | `confidenceinterval` PyPI package, or hand-rolled loop | scipy is already-installed stdlib-grade; `confidenceinterval` adds a dep for something scipy does natively; hand-rolled is 5-10 lines but mis-implementations of percentile methods are a common source of bad CIs (use BCa not percentile for skewed distributions) [CITED: scipy docs] |
| HuggingFace Datasets (for image bucket) | S3 / GCS / Backblaze | HF Datasets is free, public, zero-auth for readers, has SHA256 via LFS, and mirrors the weights-storage choice (one service, one token env). S3/GCS add cloud setup friction that contradicts D-16's "zero-extra-steps reproducibility" property. **Caveat:** HF Datasets repos have a 300 GB soft limit per user — well above our ~300 images. Attribution + CC-BY-SA license propagation required per Mapillary TOS. |
| CVAT | LabelStudio, Roboflow, makesense.ai | CVAT Cloud free tier + native YOLO (v1.1 + detection) export, no trial restrictions, fastest single-operator onboarding. LabelStudio self-hosted has fewer export targets in the free tier. Roboflow's free public plan exposes your dataset; paid is $65/mo. [CITED: https://www.cvat.ai/resources/blog/cvat-or-label-studio-which-one-to-choose; https://roboflow.com/compare-labeling-tools/cvat-vs-label-studio] |
| Keremberke yolov8s-pothole-seg (segmentation) | Keremberke yolov8n-pothole-seg, cazzz307/Pothole-Finetuned-YoloV8 | The `s` (small) variant balances size (~22 MB) vs accuracy; `n` (nano) is smaller but 0.995 self-reported mAP50 on the author's tiny validation set is unbelievable and probably over-fit. Segmentation models return boxes too (via `result.boxes`), so our single-class pothole consumer works either way. Fallback per D-11 = official `yolov8n.pt` from ultralytics GitHub releases (downloads automatically on first `YOLO("yolov8n.pt")` call). [CITED: https://huggingface.co/keremberke/yolov8n-pothole-segmentation — self-reported mAP50=0.995 is suspicious] |

**Installation (main `requirements.txt` additions — runtime path for `yolo_detector.py` + `eval_detector.py`):**
```
huggingface_hub>=0.24,<1.0
scipy>=1.13
```

**New file `requirements-train.txt` (fine-tuning only; do NOT add to backend `requirements.txt`):**
```
-r data_pipeline/requirements.txt
huggingface_hub>=0.24,<1.0
scipy>=1.13
torch>=2.4.1,<2.10
torchvision>=0.19,<0.25
```

**Version verification (run during implementation):**
```bash
python3 -m pip index versions ultralytics   # confirm 8.4.x is current
python3 -m pip index versions huggingface-hub
python3 -m pip index versions scipy
```
[CITED: standard pip discovery — training knowledge of specific versions is stale by the time execution happens]

## Architecture Patterns

### System Architecture Diagram

```
                      ┌─────────────────────────────────────────────┐
                      │  OPERATOR (local laptop / Colab / EC2)      │
                      └──────────────────┬──────────────────────────┘
                                         │
         ┌───────────────────────────────┼───────────────────────────────┐
         │                               │                               │
         ▼ (phase step 1)                ▼ (phase step 2)                ▼ (phase step 3)
┌────────────────────┐         ┌──────────────────────┐         ┌──────────────────────┐
│ fetch_eval_data.py │         │ finetune_detector.py │         │  eval_detector.py    │
│                    │         │                      │         │                      │
│ - reads manifest   │         │ - reads data.yaml    │         │ - reads YOLO_MODEL_  │
│ - hf_hub_download  │         │ - YOLO(base_weights) │         │   PATH (env)         │
│ - SHA256 verify    │         │ - model.train(...)   │         │ - resolves HF vs     │
│ - extracts to      │         │ - HfApi.upload_      │         │   local              │
│   data/eval_la/    │         │   folder (optional)  │         │ - runs model.val()   │
│                    │         │                      │         │ - bootstrap CI       │
│ exit 3 if manifest │         │ writes runs/detect/  │         │   (scipy.stats)      │
│ integrity fails    │         │   train*/weights/    │         │ - writes JSON report │
│                    │         │   best.pt            │         │ - exit 2 if below    │
│                    │         │                      │         │   --min-precision    │
└──────────┬─────────┘         └──────────┬───────────┘         └──────────┬───────────┘
           │                              │                                │
           ▼                              ▼                                ▼
┌────────────────────┐         ┌──────────────────────┐         ┌──────────────────────┐
│  data/eval_la/     │         │  HuggingFace Hub     │         │ docs/DETECTOR_EVAL.md│
│    images/{train,  │  ◄───── │  {user}/road-        │ ──────► │  (precision/recall/  │
│      val,test}/    │         │  quality-la-yolov8   │         │   mAP@0.5 + CIs +    │
│    labels/{train,  │         │  ├── best.pt        │         │   per-severity)      │
│      val,test}/    │         │  ├── README.md      │         │                      │
│    data.yaml       │         │  ├── config.json    │         │ runtime/eval metrics │
│    manifest.json   │         │  └── attribution.md │         │ JSON -> this doc     │
│    (SHA256 pins)   │         │  (CC-BY-SA if from  │         │                      │
│                    │         │   Mapillary data)   │         │                      │
└────────────────────┘         └──────────────────────┘         └──────────────────────┘
                                          │
                                          │ consumed at runtime
                                          ▼
                               ┌────────────────────────┐
                               │ detector_factory.py    │
                               │                        │
                               │ reads YOLO_MODEL_PATH  │
                               │ ├── looks like         │
                               │ │   "user/repo"?       │
                               │ │     → hf_hub_        │
                               │ │       download       │
                               │ └── looks like path?   │
                               │     → use as-is        │
                               │                        │
                               │ passes resolved local  │
                               │ path to YOLO(...)      │
                               └────────────────────────┘
                                          │
                                          ▼
                               ┌────────────────────────┐
                               │ YOLOv8Detector.detect()│
                               │ (unchanged interface)  │
                               └────────────────────────┘
```

### Recommended Project Structure

```
road-quality-mvp/
├── .env.example                 # ADD: YOLO_MODEL_PATH, HUGGINGFACE_TOKEN, MAPILLARY_ACCESS_TOKEN
├── requirements-train.txt       # NEW: heavy training deps (torch, torchvision)
├── data/
│   └── eval_la/                 # NEW (gitignored; populated by fetch_eval_data.py)
│       ├── manifest.json        # committed at top level or sibling — hashes of what fetch should produce
│       ├── data.yaml            # fetched or generated by fetch_eval_data.py
│       ├── images/
│       │   ├── train/           # 70% (210 images)
│       │   ├── val/             # 20% (60 images)
│       │   └── test/            # 10% (30 images) — NEVER touches training
│       └── labels/
│           ├── train/*.txt
│           ├── val/*.txt
│           └── test/*.txt
├── data_pipeline/
│   ├── detector.py              # UNCHANGED
│   ├── detector_factory.py      # MODIFIED: add _resolve_model_path(), read YOLO_MODEL_PATH
│   ├── yolo_detector.py         # MODIFIED: default model_path becomes None, factory always provides
│   ├── eval.py                  # NEW: match_predictions, per_severity_metrics, bootstrap_ci
│   ├── finetune.py              # NEW (optional): thin wrapper around model.train(); or keep inline in script
│   ├── mapillary.py             # NEW: shared Mapillary client (Phase 3 reuses)
│   └── requirements.txt         # UNCHANGED (ultralytics, opencv-python-headless)
├── scripts/
│   ├── eval_detector.py         # NEW
│   ├── finetune_detector.py     # NEW
│   └── fetch_eval_data.py       # NEW
├── docs/
│   ├── DETECTOR_EVAL.md         # NEW: methodology + numbers + CIs
│   ├── FINETUNE.md              # NEW: laptop/Colab/EC2 reproduction guide
│   └── finetune_colab.ipynb     # OPTIONAL: Colab notebook stub
└── backend/tests/               # ADD: test_eval_metrics.py (bootstrap/matching fns pure-unit)
```

### Pattern 1: Env-driven model path resolution with HF fallback

**What:** `detector_factory.get_detector()` reads `YOLO_MODEL_PATH`, detects HF-repo-ID vs local-path shape, fetches if HF, passes local path to `YOLOv8Detector`.

**When to use:** Every call path that instantiates a real model — the ONE place this logic lives per D-14.

**Example:**
```python
# data_pipeline/detector_factory.py (modified)
import os
import re
from pathlib import Path
from data_pipeline.detector import PotholeDetector, StubDetector

# Default HF repo to fall back to if YOLO_MODEL_PATH is unset AND use_yolo=True.
# Updated as new fine-tunes are published.
_DEFAULT_HF_REPO = "keremberke/yolov8s-pothole-segmentation"
_DEFAULT_HF_FILENAME = "best.pt"

# Matches "user/repo" or "user/repo@revision" but NOT "./path/to.pt" or "/abs/path.pt"
_HF_REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(@[A-Za-z0-9_.-]+)?$")


def _resolve_model_path(value: str | None) -> str:
    """Turn a YOLO_MODEL_PATH value into an on-disk .pt file path.

    Accepts:
        "user/repo"              -> hf_hub_download from that repo (best.pt by convention)
        "user/repo:filename.pt"  -> specific file inside the repo
        "/abs/path.pt"           -> used as-is (must exist)
        "./relative/path.pt"     -> used as-is (existence checked lazily)
        None                     -> falls back to _DEFAULT_HF_REPO
    """
    target = value or _DEFAULT_HF_REPO

    # Explicit local path with a separator or existing file
    if target.endswith(".pt") and (Path(target).exists() or "/" not in target or target.startswith(("./", "/", "."))):
        return target

    # HF repo id (optional :filename suffix)
    repo_id, _, filename = target.partition(":")
    if not _HF_REPO_PATTERN.match(repo_id):
        # Not a recognizable HF id OR local file — treat as local path and let load fail loudly
        return target

    from huggingface_hub import hf_hub_download
    return hf_hub_download(repo_id=repo_id, filename=filename or _DEFAULT_HF_FILENAME)


def get_detector(use_yolo: bool = False, model_path: str | None = None) -> PotholeDetector:
    if not use_yolo:
        return StubDetector()
    try:
        from data_pipeline.yolo_detector import YOLOv8Detector
    except ImportError:
        return StubDetector()

    env_value = model_path if model_path is not None else os.environ.get("YOLO_MODEL_PATH")
    resolved = _resolve_model_path(env_value)
    return YOLOv8Detector(model_path=resolved)
```
*Source: synthesis of [CITED: https://huggingface.co/docs/huggingface_hub/guides/download] and existing `detector_factory.py`*

**Why this shape:** The public `YOLO_MODEL_PATH` env surface from D-14 is preserved exactly. The factory — NOT ultralytics — does HF-vs-local resolution. `YOLOv8Detector` stays agnostic (it only ever sees a local path), which preserves backward compat with the existing test suite that passes `model_path="fake.pt"`.

### Pattern 2: Eval script shape

**What:** `scripts/eval_detector.py` follows the `ingest_iri.py` pattern — argparse, module-top env reads, explicit exit codes, prints human-readable summary + optional JSON output.

**Example:**
```python
# scripts/eval_detector.py (sketch)
import argparse
import json
import os
import sys
from pathlib import Path

# Exit codes per D-18
EXIT_OK = 0
EXIT_BELOW_FLOOR = 2
EXIT_MISSING_DATA = 3
EXIT_OTHER = 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate YOLOv8 detector against a labelled eval set.")
    parser.add_argument("--data", type=Path, default=Path("data/eval_la/data.yaml"),
                        help="Path to YOLO data.yaml (defines test/ split)")
    parser.add_argument("--split", choices=["val", "test"], default="test",
                        help="Which split to evaluate on (default: test; use val only for tuning)")
    parser.add_argument("--iou", type=float, default=0.5, help="IoU threshold (D-07 = 0.5)")
    parser.add_argument("--bootstrap-resamples", type=int, default=1000, help="D-08 = 1000")
    parser.add_argument("--ci-level", type=float, default=0.95, help="D-08 = 0.95")
    parser.add_argument("--min-precision", type=float, default=None, help="Exit 2 if test precision < this")
    parser.add_argument("--min-recall", type=float, default=None, help="Exit 2 if test recall < this")
    parser.add_argument("--json-out", type=Path, default=None, help="Write metrics JSON for docs pipeline")
    parser.add_argument("--model", type=str, default=None,
                        help="Override YOLO_MODEL_PATH (same semantics: HF repo id or local .pt)")
    args = parser.parse_args()

    # D-17: Missing dataset = exit 3 with fetch hint
    if not args.data.exists():
        print(f"Eval set not found at {args.data}. Run: python scripts/fetch_eval_data.py", file=sys.stderr)
        return EXIT_MISSING_DATA

    try:
        from data_pipeline.detector_factory import _resolve_model_path
        from ultralytics import YOLO
        from data_pipeline.eval import bootstrap_ci, per_severity_breakdown

        model_path = _resolve_model_path(args.model or os.environ.get("YOLO_MODEL_PATH"))
        model = YOLO(model_path)

        # ultralytics built-in validation handles IoU matching + mAP natively
        metrics = model.val(data=str(args.data), split=args.split, iou=args.iou, verbose=False)

        # metrics.box.mp / mr / map50 are scalars averaged across classes.
        # For CIs, we need per-image TP/FP/FN so we can resample with replacement at the IMAGE level
        # (see Pattern 3 for why image-level resampling is the right granularity).
        per_image = _collect_per_image_tp_fp_fn(metrics)  # helper on results object
        precision_ci = bootstrap_ci(per_image, metric="precision",
                                    n_resamples=args.bootstrap_resamples, ci_level=args.ci_level)
        recall_ci = bootstrap_ci(per_image, metric="recall", ...)
        severity = per_severity_breakdown(per_image)  # {"moderate": {tp, fp, fn, p, r}, "severe": {...}}

        report = {
            "model_path": model_path,
            "split": args.split,
            "precision": float(metrics.box.mp),
            "recall": float(metrics.box.mr),
            "map50": float(metrics.box.map50),
            "precision_ci_95": precision_ci,
            "recall_ci_95": recall_ci,
            "per_severity": severity,
            "eval_config": {"iou": args.iou, "bootstrap_resamples": args.bootstrap_resamples},
        }
        _print_human_summary(report)
        if args.json_out:
            args.json_out.write_text(json.dumps(report, indent=2))

        # D-18 exit code 2 if below floor
        if args.min_precision is not None and report["precision"] < args.min_precision:
            print(f"FAIL: precision {report['precision']:.3f} < floor {args.min_precision}", file=sys.stderr)
            return EXIT_BELOW_FLOOR
        if args.min_recall is not None and report["recall"] < args.min_recall:
            print(f"FAIL: recall {report['recall']:.3f} < floor {args.min_recall}", file=sys.stderr)
            return EXIT_BELOW_FLOOR

        return EXIT_OK

    except FileNotFoundError as e:
        print(f"Required file missing: {e}", file=sys.stderr)
        return EXIT_MISSING_DATA
    except Exception:
        import traceback
        traceback.print_exc()
        return EXIT_OTHER


if __name__ == "__main__":
    sys.exit(main())
```
*Source: pattern synthesis from `scripts/ingest_iri.py` [VERIFIED: file read] + [CITED: https://docs.ultralytics.com/modes/val/]*

### Pattern 3: Bootstrap CI at the image level

**What:** Resample images (not detections) with replacement, recompute aggregate precision/recall on each resample, report 2.5th/97.5th percentiles.

**When to use:** Every reported number in `docs/DETECTOR_EVAL.md` gets a CI.

**Why image-level, not detection-level:** Detections within the same image are not independent (one blurry frame causes a clustered miss). Image-level resampling honors the unit of sampling variability (each Mapillary image is one independent "draw"). This is the standard convention in object detection evals. [ASSUMED — I couldn't find an authoritative object-detection-specific source that says "resample images, not detections" explicitly, but it's the correct statistical interpretation and what e.g. COCO-style eval tools do implicitly. Flag for user confirmation.]

**Example:**
```python
# data_pipeline/eval.py (sketch)
import numpy as np
from scipy.stats import bootstrap

def bootstrap_ci(per_image_counts: list[dict], metric: str, n_resamples: int = 1000, ci_level: float = 0.95):
    """per_image_counts: [{"tp": int, "fp": int, "fn": int}, ...]
    metric: "precision" or "recall"
    Returns: (low, point_estimate, high)
    """
    counts = np.array([[d["tp"], d["fp"], d["fn"]] for d in per_image_counts])

    def _stat(sample_idxs):
        # sample_idxs is a 1D array of integer indices into `counts`
        tp, fp, fn = counts[sample_idxs].sum(axis=0)
        if metric == "precision":
            return tp / (tp + fp) if (tp + fp) > 0 else 0.0
        elif metric == "recall":
            return tp / (tp + fn) if (tp + fn) > 0 else 0.0

    # scipy's bootstrap expects a callable on a sample; we pass indices then lookup
    idxs = np.arange(len(counts))
    # Degenerate case: all-zero counts -> CI undefined; return (nan, 0, nan)
    if counts.sum() == 0:
        return (float("nan"), 0.0, float("nan"))

    rng = np.random.default_rng(42)
    samples = rng.choice(idxs, size=(n_resamples, len(idxs)), replace=True)
    vals = np.array([_stat(s) for s in samples])
    low = float(np.percentile(vals, (1 - ci_level) / 2 * 100))
    high = float(np.percentile(vals, (1 + ci_level) / 2 * 100))
    point = _stat(idxs)
    return (low, point, high)
```
*Source: pattern from [CITED: https://machinelearningmastery.com/calculate-bootstrap-confidence-intervals-machine-learning-results-python/] + [CITED: https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html]*

**Note:** We implement percentile bootstrap by hand rather than calling `scipy.stats.bootstrap` directly because scipy's API assumes the statistic is a function of the raw sample (e.g. mean of numbers), not a function that needs three aggregated counts (tp/fp/fn). Hand-rolling is clearer here and only ~15 lines; fix seed=42 for reproducibility per existing project convention.

### Pattern 4: Data YAML shape for YOLO

```yaml
# data/eval_la/data.yaml
path: /absolute/or/relative/to/this/file/data/eval_la
train: images/train
val: images/val
test: images/test

nc: 1
names:
  0: pothole
```

**If using two-class model** (to match `_SEVERE_CLASSES` / `_MODERATE_CLASSES` in `yolo_detector.py:22-23`):
```yaml
nc: 2
names:
  0: moderate_pothole
  1: severe_pothole
```

**Decision the planner must make:** Single-class with confidence→severity mapping (current runtime behavior) vs. two-class with class→severity mapping (cleaner, but requires every label `.txt` to carry a severity judgment the human operator has to make while labelling). **Recommendation:** single-class labels + confidence-based severity at inference time — this keeps labelling simple and matches the existing single-class branch of `_map_severity`. Per-severity "breakdown" in D-06 then comes from the confidence split, which is what the production code already does, so eval numbers map 1:1 to runtime behavior. [CITED: `data_pipeline/yolo_detector.py:128-157` — existing single-class logic]

### Pattern 5: HuggingFace upload for YOLO weights

```python
# scripts/finetune_detector.py (upload portion)
from huggingface_hub import HfApi, create_repo

def upload_to_hf(weights_path: Path, repo_id: str, model_card_md: str, token: str) -> str:
    api = HfApi(token=token)
    create_repo(repo_id, exist_ok=True, repo_type="model", private=False, token=token)
    # Upload weights
    api.upload_file(
        path_or_fileobj=str(weights_path),          # e.g., runs/detect/train/weights/best.pt
        path_in_repo="best.pt",                     # convention matches keremberke repos
        repo_id=repo_id,
        commit_message="Upload fine-tuned LA pothole YOLOv8",
    )
    # Upload model card
    readme = Path(weights_path.parent / "README.md")
    readme.write_text(model_card_md)
    api.upload_file(
        path_or_fileobj=str(readme),
        path_in_repo="README.md",
        repo_id=repo_id,
        commit_message="Add model card",
    )
    return f"https://huggingface.co/{repo_id}"
```
*Source: [CITED: https://huggingface.co/docs/huggingface_hub/package_reference/hf_api] + Keremberke repo structure inspection [VERIFIED: tree listing shows best.pt + README.md + config.json]*

**CLI alternative** per D-13: `huggingface-cli upload {repo_id} runs/detect/train/weights/best.pt best.pt`. Programmatic `HfApi` is preferred because it lets the script write the model card in the same run.

**Model card template** — include these fields (CC-BY-SA for the training-data-derived artifact per Mapillary's SA clause):
```markdown
---
license: agpl-3.0  # ultralytics weights; fine-tuned from same-license base
datasets:
  - mapillary/street-level-imagery (CC-BY-SA 4.0)
base_model: keremberke/yolov8s-pothole-segmentation
tags:
  - yolov8
  - pothole-detection
  - los-angeles
---

# road-quality-la-yolov8

Fine-tuned YOLOv8 for pothole detection on Los Angeles street-level imagery
(Mapillary crowdsourced). Part of the road-quality-mvp project.

## Eval Results (test split, 30 images held out)
- Precision: 0.XX [95% CI: 0.XX, 0.XX]
- Recall:    0.XX [95% CI: 0.XX, 0.XX]
- mAP@0.5:   0.XX

See docs/DETECTOR_EVAL.md in the source repo for methodology.

## Data Attribution
Training images sourced from Mapillary (https://www.mapillary.com) under CC-BY-SA 4.0.
Source image IDs are recorded in the manifest accompanying this model.
```

### Anti-Patterns to Avoid

- **Running ultralytics `model.val()` and trusting its headline numbers unconditionally.** It reports mean metrics averaged across classes. For a single-class dataset that's fine, but the CI has to come from image-level bootstrap — `model.val()` does not expose CIs natively.
- **Pushing raw Mapillary images to a public HF Dataset without attribution / source-image-id mapping.** Violates CC-BY-SA 4.0's ShareAlike + attribution clauses. Record each image's Mapillary image_id and include attribution in the dataset README.
- **Using `ultralyticsplus` to load HF models.** [VERIFIED: inactive per Snyk]. Pins `ultralytics==8.0.21` which is two major versions stale.
- **Committing `data/eval_la/` to the repo.** `.gitignore` it. The manifest.json (SHA256 pins) is what's committed; the content is fetched.
- **Assuming Mapillary `thumb_2048_url` is stable.** Thumbnail URLs have TTL and expire [CITED: forum post]. At fetch time, resolve the image_id → thumb_url, download immediately, don't cache URLs.
- **Running training on Apple Silicon MPS without `device="cpu"` fallback.** [VERIFIED: Issue #23140] — MPS backend has a coordinate corruption bug on M-series that makes detection results unusable. Default training on M-series should force CPU until ultralytics fixes this upstream.
- **Using `torch==2.4.0`.** [CITED: ultralytics pyproject.toml explicitly excludes it with `torch!=2.4.0,>=1.8.0`] — the version check rejects it.
- **Letting Mapillary bbox queries exceed 0.01 deg² per request.** [CITED: Mapillary docs FAQ] — above this the API recommends using the SDK which tiles for you.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| YOLO inference loop with NMS, letterbox, class mapping | Custom PIL + torch script | `ultralytics.YOLO(...).predict()` or `.val()` | Ultralytics handles letterbox, batch dim, NMS thresholds, class-agnostic NMS; getting any of those wrong silently skews metrics |
| Model download from HuggingFace | `curl`/`requests` against `huggingface.co/resolve/main/...` | `huggingface_hub.hf_hub_download()` | Handles auth, caching, resume, ETag verification, LFS redirect, 429 backoff |
| Publishing models to HuggingFace | git-lfs + manual push | `HfApi.upload_file()` / `huggingface-cli upload` | Progress bars, chunked upload, auth handling, retry logic |
| Bootstrap CI from scratch | `for i in range(1000): ...` with hand-coded percentile | `scipy.stats.bootstrap` OR pattern 3 above | scipy's bootstrap supports BCa method (better than percentile for skewed distributions); for our simpler case, the ~15-line hand-rolled percentile implementation is fine IF we acknowledge BCa is preferred for publication-grade |
| IoU / match / precision / recall from ground truth | Custom numpy box-matching | `model.val(data=...)` | ultralytics uses the COCO-style matching algorithm that the whole field validates against; rolling our own risks silent off-by-one (inclusive vs exclusive IoU, TP double-counting, etc.) |
| Mapillary image discovery + download | Pure `requests` | `mapillary-python-sdk` OR a small client in `data_pipeline/mapillary.py` | SDK handles tile splitting for large bboxes; for this project's scope (one bbox pull), ~50 lines of direct API calls in our own module is acceptable AND serves Phase 3's reuse need |
| SHA256 manifest verification | Custom shell tool | `hashlib.sha256()` from stdlib + manifest comparison | Trivial in stdlib; don't pull in another dep |
| YOLO `.txt` label reading / writing | Custom parser | Labelling tool exports it (CVAT does this natively); label validation = one regex per line | [CITED: https://labelformat.com/formats/object-detection/yolov8/] |

**Key insight:** Every ML evaluation project has the same "we'll just write a quick IoU matcher" temptation. Resist it. `ultralytics.YOLO.val()` is the reference implementation for YOLO-format data; use it, then apply CIs on top of the per-image breakdown it produces.

## Runtime State Inventory

This phase is additive (new scripts, new env vars, new docs) with only one in-place code change (`detector_factory.py` resolution logic). Minimal runtime state impact.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — eval data lives in a gitignored `data/eval_la/` directory, downloaded on demand via `fetch_eval_data.py`. No DB tables touched by this phase. | None |
| Live service config | None — no external services have hardcoded references to the old behavior. `docker-compose.yml` does not mount `models/` into the backend container today. [VERIFIED: `docker-compose.yml` read during earlier phase research confirms no ML-related volume.] | Optional: if deploy ever mounts a pre-baked model, that mount point needs updating — deferred to Phase 5. |
| OS-registered state | None — no cron jobs, pm2 processes, systemd units, or Task Scheduler entries reference the detector. | None |
| Secrets/env vars | Three NEW env vars introduced: `YOLO_MODEL_PATH` (runtime + eval), `HUGGINGFACE_TOKEN` (upload only), `MAPILLARY_ACCESS_TOKEN` (fetch_eval_data.py only, Phase 3 too). Existing `DATABASE_URL` unchanged. | Append three new vars to `.env.example` with explanatory comments matching the existing file's style. |
| Build artifacts / installed packages | `data_pipeline/requirements.txt` gets `huggingface_hub>=0.24` and `scipy>=1.13` appended (both needed at RUNTIME for model resolution + CI-in-eval). New `requirements-train.txt` created at repo root. No `pip install -e .` egg-info issues (project doesn't install as editable). | Run `pip install -r data_pipeline/requirements.txt` after pull; run `pip install -r requirements-train.txt` before running `finetune_detector.py`. |

**Verified non-issues:**
- No Docker image rebuild needed for the backend — backend never imports from `scripts/` or runs the detector (detection is an offline pipeline, not an API endpoint). [CITED: CONTEXT.md domain section] The `scripts/requirements.txt` and `data_pipeline/requirements.txt` additions matter only for the operator running the scripts.
- No migration needed — `segment_defects` schema (which eventually receives real detections in Phase 3) is unchanged by Phase 2.

## Environment Availability

This phase requires substantial new tooling. Most is missing on the dev machine and must be installed.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12+ | `scripts/*`, `data_pipeline/*` | ✗ | Only Python 3.9.6 (system) found on dev machine [VERIFIED: `python3 --version`] | Install Python 3.12 via brew, or run scripts in the existing backend Docker container's Python. Note: STACK.md says "Python 3.12+" is the target, so the docs/config claim Python 3.12 is available; reality check during Phase 2 execution. |
| `pip` | All Python deps | ✓ | 21.2.4 (tied to Python 3.9) [VERIFIED] | Use `python3.12 -m pip` once 3.12 is installed |
| `torch` | `finetune_detector.py` | ✗ | Not installed | Install fresh: `pip install torch>=2.4.1,<2.10 torchvision` |
| `ultralytics` | `yolo_detector.py`, `eval_detector.py`, `finetune_detector.py` | ✗ | Not installed | Install fresh: `pip install ultralytics>=8.3` |
| `huggingface_hub` | All three new scripts + `detector_factory.py` | ✗ | Not installed | Install fresh |
| `huggingface-cli` | D-13 upload | ✗ | Not installed | Bundled with `huggingface_hub` package; runs as `huggingface-cli` after `pip install huggingface_hub` |
| `scipy` | `eval_detector.py` | ✓ | 1.13.1 [VERIFIED: `import scipy`] | — |
| Pillow | eval scripts | ✓ | 11.3.0 [VERIFIED] | — |
| Docker | Backend/DB run (unchanged) | ✓ | 29.4.1 [VERIFIED: `docker --version`] | — |
| git | version control | ✓ | 2.50.1 [VERIFIED] | — |
| Apple Silicon (M-series) | Training locally | ✓ | arm64 + macOS 26.4 [VERIFIED: `uname -m`] | **Gotcha:** MPS backend has a known coordinate-corruption bug (Issue #23140); training MUST use `device="cpu"` on this dev machine, or push training to Colab/EC2 per D-16. |
| Mapillary access token | `fetch_eval_data.py` | ✗ | Not set | User must sign up at mapillary.com/developer and set `MAPILLARY_ACCESS_TOKEN` |
| HuggingFace token | Upload portion of `finetune_detector.py` | ✗ | Not set | User must create an HF write-scope token at huggingface.co/settings/tokens and set `HUGGINGFACE_TOKEN` |

**Missing dependencies with no fallback:**
- Python 3.12 (plan must address — install via brew or scope training to Colab/EC2 which has 3.11+ preinstalled)
- Mapillary access token (user action required; flag as first-plan prerequisite)

**Missing dependencies with fallback:**
- Training hardware: M-series dev machine + MPS bug → fallback = CPU training (slow, 300 images is still feasible in a few hours) OR Colab free tier (T4 GPU, ~15-20 min for 50 epochs on 300 images) OR EC2 g5.xlarge (faster, paid).
- HF token: required only for `--push` flag on `finetune_detector.py`. User can run training without upload, inspect results locally, push later.

## Common Pitfalls

### Pitfall 1: Apple Silicon MPS backend corrupts YOLO bbox X-coordinates
**What goes wrong:** Training or inferring on an M-series Mac with `device="mps"` produces detections whose X-coordinates are garbage (Y-coordinates are correct). Detection appears to work but predictions don't align with objects.
**Why it happens:** [VERIFIED: ultralytics Issue #23140] — an MPS backend bug in the Metal Performance Shaders implementation of a tensor op used in YOLO's bbox regression head.
**How to avoid:** Force `device="cpu"` in all training calls on Apple Silicon until Ultralytics ships a fix. For inference-only (`eval_detector.py`), `device="cpu"` is also safest.
**Warning signs:** Precision drops to ~0 on a model that trains correctly on a cloud GPU. Visualized boxes are horizontally shifted on every image.

### Pitfall 2: Stale ultralytics pinned by `ultralyticsplus`
**What goes wrong:** Following Keremberke's README blindly installs `ultralytics==8.0.21` and breaks every other part of the codebase that expects current ultralytics.
**Why it happens:** [VERIFIED: Snyk advisor marks `ultralyticsplus` inactive; last PyPI release pins 8.0.21 (2023)]. The README model card is never updated.
**How to avoid:** Ignore the `ultralyticsplus` suggestion. Use `hf_hub_download` to fetch `best.pt`, then `YOLO(local_path)` with current ultralytics.
**Warning signs:** `pip install` warnings about version downgrades. Type errors from changed ultralytics APIs.

### Pitfall 3: Mapillary bbox queries > 0.01 deg² hit API limits
**What goes wrong:** Single request returns partial or errors with opaque message. ~300 images might come from one request or several, but if the user's LA bbox is too large (e.g., all of LA County), the first request fails.
**Why it happens:** [CITED: Mapillary API docs] — bbox must be < 0.01 deg² for direct queries. Larger areas require the mapillary-python-sdk which tiles automatically.
**How to avoid:** Either (a) use small bboxes (downtown 0.01x0.01, Santa Monica 0.01x0.01, etc.) — 3-5 requests total, OR (b) use mapillary-python-sdk's `images_in_bbox` with automatic tiling.
**Warning signs:** Empty results on bounds that should have thousands of images. HTTP 400/500 on large queries.

### Pitfall 4: Bootstrap CI degenerate case — zero TP
**What goes wrong:** `precision = tp / (tp + fp)` divides by zero if the model detects nothing. `recall = tp / (tp + fn)` divides by zero if no ground truths exist in the resample.
**Why it happens:** Mathematical undefined; real-world occurs on small resamples or genuinely bad models.
**How to avoid:** Handle in `bootstrap_ci`: return `nan` CI bounds when `(tp + fp) == 0` (precision) or `(tp + fn) == 0` (recall). Write up in `DETECTOR_EVAL.md` as "CI undefined when no predictions."
**Warning signs:** `RuntimeWarning: invalid value encountered in scalar divide`. CIs of `[nan, nan]` in output.

### Pitfall 5: Mapillary thumbnail URL TTL expiration
**What goes wrong:** `thumb_2048_url` returned from image search expires before download completes. For a slow batch, the later images 404.
**Why it happens:** [CITED: Mapillary forum] — URLs are signed with a time-limited token.
**How to avoid:** Fetch image metadata + download the bytes in one pass per image, don't batch-fetch all URLs then batch-download. For resumable pulls, refetch the URL via image_id before retry.
**Warning signs:** Intermittent 403/404 on download after a long query-metadata phase.

### Pitfall 6: YOLO labels off-by-one or inverted
**What goes wrong:** Labels written as `(cx, cy, w, h)` in pixels, not normalized. Or `(class, x1, y1, x2, y2)` instead of center+w/h. Training runs but mAP is 0.
**Why it happens:** YOLO `.txt` format ambiguous to anyone who's seen Pascal/COCO formats. [CITED: https://roboflow.com/formats/yolo]
**How to avoid:** (1) Use CVAT's native "YOLO 1.1" export, don't convert manually. (2) Add a `validate_labels.py` helper that asserts every `.txt` file has 5 floats per line, all between 0.0 and 1.0 (except class_id which is int ≥ 0 < nc).
**Warning signs:** Training loss looks normal, val mAP stuck at 0, prediction boxes end up in corners.

### Pitfall 7: Test split contamination from repeated Mapillary image IDs
**What goes wrong:** Operator downloads 300 images, some are near-duplicates (same street, adjacent frames), and random train/val/test split puts duplicates across splits. Test set no longer independent.
**Why it happens:** Mapillary captures sequences — consecutive frames are extremely similar.
**How to avoid:** Split by Mapillary `sequence_id` (grouping all frames from the same drive together), not by image_id. Manifest records sequence → split mapping.
**Warning signs:** Test precision suspiciously close to val precision. mAP on held-out "test" set nearly identical to training mAP.

### Pitfall 8: HuggingFace upload overwrites without version track
**What goes wrong:** Re-running `finetune_detector.py --push` replaces `best.pt` in the HF repo. Downstream consumers (production detector) silently pick up a different model.
**Why it happens:** HF repos are just git — upload commits a new version, but the default pin in `detector_factory.py` points to `@main`, always latest.
**How to avoid:** Either (a) pin the default HF repo path to a specific revision (`repo_id:best.pt@v0.1.0`) and bump it explicitly on each publish, OR (b) tag each training run with a date-stamped branch (`train-2026-04-23`) and reference the tag.
**Warning signs:** Production detector behavior changes after an unrelated commit.

## Code Examples

### Example 1: Loading a HuggingFace-hosted YOLO model (current 2026 pattern)
```python
# Source: https://huggingface.co/docs/huggingface_hub/guides/download + https://docs.ultralytics.com/
from huggingface_hub import hf_hub_download
from ultralytics import YOLO

local_path = hf_hub_download(
    repo_id="keremberke/yolov8s-pothole-segmentation",
    filename="best.pt",
    # Optional: revision="abc123..." to pin a specific commit
)
model = YOLO(local_path)
results = model.predict("image.jpg", conf=0.25)
```

### Example 2: Ultralytics validation on YOLO data.yaml
```python
# Source: https://docs.ultralytics.com/modes/val/
from ultralytics import YOLO

model = YOLO("path/to/best.pt")
metrics = model.val(data="data/eval_la/data.yaml", split="test", iou=0.5)

# Scalar metrics (averaged across classes)
print(f"Precision: {metrics.box.mp:.3f}")  # mean precision
print(f"Recall:    {metrics.box.mr:.3f}")  # mean recall
print(f"mAP@0.5:   {metrics.box.map50:.3f}")
print(f"mAP@0.5:0.95: {metrics.box.map:.3f}")

# Per-class breakdown if needed
for i, name in model.names.items():
    print(f"{name}: P={metrics.box.p[i]:.3f} R={metrics.box.r[i]:.3f} mAP50={metrics.box.ap50[i]:.3f}")
```

### Example 3: Fine-tune + save + push
```python
# Source: https://docs.ultralytics.com/modes/train/ + huggingface_hub docs
from ultralytics import YOLO
from huggingface_hub import HfApi

# Load base (either HF-fetched or a stock ultralytics weight)
model = YOLO("yolov8n.pt")  # auto-downloads from ultralytics GitHub releases

# Fine-tune — ultralytics handles train/val split per data.yaml
results = model.train(
    data="data/eval_la/data.yaml",
    epochs=50,                # 300 images x 50 epochs ~= reasonable
    batch=16,                 # or 8 on CPU
    imgsz=640,
    device="cpu",             # force CPU on Apple Silicon; "0" for CUDA; "mps" is broken per Issue #23140
    patience=10,              # early stopping
    project="runs/detect",
    name="la_pothole",
    seed=42,                  # match project's seed convention
)
# After training, best weights live at: runs/detect/la_pothole/weights/best.pt
best_path = results.save_dir / "weights" / "best.pt"

# Upload
api = HfApi()
api.upload_file(
    path_or_fileobj=str(best_path),
    path_in_repo="best.pt",
    repo_id="hratchghanime/road-quality-la-yolov8",
    commit_message="Fine-tuned on LA eval train split",
)
```

### Example 4: Mapillary image search + download (minimal)
```python
# Source: https://www.mapillary.com/developer/api-documentation + community examples
import os
import requests
from pathlib import Path

MAPILLARY_TOKEN = os.environ["MAPILLARY_ACCESS_TOKEN"]

def search_images(bbox: tuple[float, float, float, float], limit: int = 100) -> list[dict]:
    """bbox = (min_lon, min_lat, max_lon, max_lat). Must be < 0.01 deg²."""
    params = {
        "bbox": ",".join(str(c) for c in bbox),
        "fields": "id,thumb_2048_url,computed_geometry,captured_at,sequence_id",
        "limit": limit,
    }
    headers = {"Authorization": f"OAuth {MAPILLARY_TOKEN}"}
    r = requests.get("https://graph.mapillary.com/images", params=params, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()["data"]

def download_image(image_meta: dict, out_dir: Path) -> Path:
    """URLs expire — fetch metadata and download in same pass."""
    url = image_meta["thumb_2048_url"]
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    out_path = out_dir / f"{image_meta['id']}.jpg"
    out_path.write_bytes(r.content)
    return out_path
```

### Example 5: SHA256 manifest verification
```python
# Source: Python stdlib hashlib
import hashlib
import json
from pathlib import Path

def verify_manifest(manifest_path: Path, data_root: Path) -> tuple[list[str], list[str]]:
    """Returns (missing_files, corrupt_files)."""
    manifest = json.loads(manifest_path.read_text())
    missing, corrupt = [], []
    for entry in manifest["files"]:
        local = data_root / entry["path"]
        if not local.exists():
            missing.append(entry["path"])
            continue
        actual = hashlib.sha256(local.read_bytes()).hexdigest()
        if actual != entry["sha256"]:
            corrupt.append(entry["path"])
    return missing, corrupt

# Manifest shape:
# {
#   "version": "1.0",
#   "source_bucket": "huggingface://datasets/<user>/road-quality-la-eval",
#   "files": [
#     {"path": "images/train/abc123.jpg", "sha256": "aaa...", "source_mapillary_id": "12345"},
#     {"path": "labels/train/abc123.txt", "sha256": "bbb..."}
#   ]
# }
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `ultralyticsplus.YOLO("user/repo")` for HF loading | `hf_hub_download(...) + YOLO(path)` | `ultralyticsplus` went inactive ~2023-2024 | Use the two-step pattern; don't rely on `ultralyticsplus` [VERIFIED: Snyk advisor inactive status] |
| `ultralytics.YOLO` auto-downloads ONLY from GitHub releases | Same, still no native HF support in 8.4.x | — | Users must bring their own HF integration [CITED: ultralytics/utils/downloads.py reference — only GitHub + Drive + URL, no HF] |
| YOLOv5 hubconf `torch.hub.load` | YOLOv8+ direct `YOLO()` class | v8 release | Existing code already uses v8 pattern — no change |
| 1000-sample bootstrap hand-coded | `scipy.stats.bootstrap` native | scipy 1.7+ (2021) | For BCa CIs use scipy directly; for our case, hand-rolled percentile is fine |

**Deprecated/outdated:**
- `ultralyticsplus` — inactive; do not use [VERIFIED]
- YOLOv5 PyTorch Hub loading pattern — use `from ultralytics import YOLO` [CITED: docs.ultralytics.com]
- `ultralytics` < 8.3 — missing features and has known bugs; use 8.3+ (latest 8.4.41) [CITED]

## Project Constraints (from CLAUDE.md)

No `./CLAUDE.md` exists at the repo root. [VERIFIED: `cat CLAUDE.md 2>/dev/null` returned nothing.] No project-specific directives to honor beyond the ones already encoded in CONTEXT.md and the existing codebase conventions (already captured in `## Architecture Patterns`).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.3.4 [VERIFIED: `backend/requirements.txt`] |
| Config file | None in repo root; tests in `backend/tests/` discovered by default |
| Quick run command | `python3 -m pytest backend/tests/test_yolo_detector.py backend/tests/test_eval_metrics.py -x -q` |
| Full suite command | `python3 -m pytest backend/tests/ -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REQ-real-data-accuracy (SC #1) | `eval_detector.py` prints precision/recall/per-severity on a labelled set | smoke | `python3 scripts/eval_detector.py --data backend/tests/fixtures/mini_eval/data.yaml --bootstrap-resamples 100` | ❌ Wave 0 — needs `backend/tests/fixtures/mini_eval/` (3-5 images, labels, data.yaml) |
| REQ-real-data-accuracy (SC #1) | Bootstrap CI computation gives stable output on fixed seed | unit | `python3 -m pytest backend/tests/test_eval_metrics.py::test_bootstrap_ci_deterministic -x` | ❌ Wave 0 — test file + fixtures |
| REQ-real-data-accuracy (SC #1) | Per-severity breakdown matches `_map_severity` logic | unit | `python3 -m pytest backend/tests/test_eval_metrics.py::test_per_severity_matches_runtime -x` | ❌ Wave 0 |
| REQ-real-data-accuracy (SC #2) | `get_detector(use_yolo=True, model_path=...)` returns real model wrapper | unit (mocked HF download) | `python3 -m pytest backend/tests/test_yolo_detector.py::test_factory_with_explicit_path -x` | ✅ extend existing file |
| REQ-real-data-accuracy (SC #2) | Factory resolves HF repo ID via `hf_hub_download` | unit (mocked) | `python3 -m pytest backend/tests/test_yolo_detector.py::test_factory_resolves_hf_repo -x` | ✅ extend existing file |
| REQ-real-data-accuracy (SC #3) | `YOLO_MODEL_PATH` env var consumed; falls back to default HF repo when unset | unit (monkeypatched env) | `python3 -m pytest backend/tests/test_yolo_detector.py::test_env_var_path_resolution -x` | ✅ extend existing file |
| REQ-real-data-accuracy (SC #3) | Backward compat: `get_detector(use_yolo=True, model_path="fake.pt")` still works | unit | existing `test_yolo_detector_protocol` (already covers this) | ✅ already passes |
| REQ-real-data-accuracy (SC #4) | `docs/DETECTOR_EVAL.md` exists, contains precision/recall/mAP table | doc-verify | `grep -E '(Precision|Recall|mAP)' docs/DETECTOR_EVAL.md` (manual / pre-merge check) | ❌ Wave 0 (doc) |
| — | `fetch_eval_data.py` exit code 3 when manifest missing | integration (smoke) | `python3 scripts/fetch_eval_data.py --manifest /nonexistent.json; test $? -eq 3` | ❌ Wave 0 |
| — | `eval_detector.py` exit code 3 when data.yaml missing | integration (smoke) | `python3 scripts/eval_detector.py --data /nonexistent/data.yaml; test $? -eq 3` | ❌ Wave 0 |
| — | `eval_detector.py` exit code 2 when below `--min-precision` | integration (smoke) | run on fixture with `--min-precision 0.99`, expect exit 2 | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `python3 -m pytest backend/tests/test_yolo_detector.py backend/tests/test_eval_metrics.py -x -q` (~5 sec, pure-unit, mocks HF + ultralytics)
- **Per wave merge:** Full suite `python3 -m pytest backend/tests/ -q` + smoke run of `eval_detector.py` on fixture mini_eval/
- **Phase gate:** Before `/gsd-verify-work`: full suite green + at least one real `eval_detector.py` run on the real 300-image test split (numbers go into `docs/DETECTOR_EVAL.md`)

### Wave 0 Gaps
- [ ] `backend/tests/test_eval_metrics.py` — unit tests for `bootstrap_ci`, `per_severity_breakdown`, IoU matching helpers
- [ ] `backend/tests/fixtures/mini_eval/` — 3-5 tiny dummy images + labels + data.yaml for smoke tests (can be 10x10 pixel solid-color PNGs with one fake bbox each; real inference is mocked)
- [ ] `backend/tests/conftest.py` addition — fixture that mocks `hf_hub_download` to return a sentinel path without network
- [ ] `backend/tests/test_yolo_detector.py` — add three new test functions (see table)
- [ ] Framework install: none needed (pytest already installed per `backend/requirements.txt`)

### Correctness Gate
An "eval metrics correctness gate" is defined as **not fully automated in CI** (by design per CONTEXT.md deferred item "Continuous eval / CI gate on detector accuracy"). Instead:
- **Automated:** `eval_detector.py --min-precision 0.50 --min-recall 0.35` is a **manual operator invocation** that exits 2 if the model fails — used BEFORE publishing a new HF revision. Not run in CI.
- **Manual:** `docs/DETECTOR_EVAL.md` gets human-authored commentary on what the numbers mean (e.g., "recall is lower because LA sidewalk shadows cause false negatives"). The numbers table in that doc is regenerated each time by piping `eval_detector.py --json-out` through a small formatter.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | Yes (HF + Mapillary tokens) | Token read from env var only; never logged; never committed; `.env` in `.gitignore` already [VERIFIED: `.gitignore` present] |
| V3 Session Management | No | No user sessions in this phase |
| V4 Access Control | Yes (published HF repo visibility) | Default repo = public per D-12; document that user can toggle private via HF UI |
| V5 Input Validation | Yes (manifest paths, model paths, data.yaml paths) | Validate path does not escape `data/eval_la/` (no `../` traversal in manifest entries); validate SHA256 hex is 64 lowercase hex chars before comparing |
| V6 Cryptography | Yes (SHA256 verification) | Use `hashlib.sha256` stdlib — don't hand-roll; use constant-time comparison (`hmac.compare_digest`) for the hash check to avoid timing leaks on the off chance an attacker controls the manifest |
| V8 Data Protection | Yes (Mapillary image licensing) | Redistribute Mapillary images under CC-BY-SA 4.0 with attribution recorded per image (source_mapillary_id in manifest). The HF Dataset README must include license + attribution clause [CITED: https://help.mapillary.com/hc/en-us/articles/115001770409] |
| V14 Configuration | Yes (env var secrets) | `.env` gitignored [VERIFIED]; `.env.example` documents tokens WITHOUT real values — follow Phase 1's existing pattern |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Pickle deserialization via `.pt` load (arbitrary code execution) | Tampering + Elevation | `torch.load` default behavior is to allow pickle; HF marks `.pt` files "Unsafe" for this reason [VERIFIED: keremberke repo page banner]. **Mitigation:** only load `.pt` files from repos we control OR well-known publishers. Document this in `docs/DETECTOR_EVAL.md` risk section. Future: upgrade to `weights_only=True` when ultralytics supports it. |
| Secrets committed to git | Information Disclosure | Use `.env`; `.env` already in `.gitignore` [VERIFIED]. Pre-commit hook to scan for `hf_*` / `mly_*` token prefixes is nice-to-have but not required for this phase (deferred — Phase 4 auth work may introduce this). |
| Malicious fine-tuned weights uploaded to our HF repo | Tampering | `HUGGINGFACE_TOKEN` scoped to write-only-for-this-user. HF's own CSRF protection + 2FA on the user account. Consider pinning consumer's `YOLO_MODEL_PATH` default to a specific git revision of the HF repo, not `@main`, so an attacker-with-HF-token can't silently swap weights on production detectors (see Pitfall 8). |
| SHA256 manifest tampering (MITM on fetch) | Tampering | HF + HTTPS + ETag (sha256 for LFS files) handles this at transport layer. Our manifest + sha256 check is defense-in-depth — fine to keep. |
| DoS via arbitrarily large Mapillary bbox | Denial of Service (against our own fetch) | Validate bbox ≤ 0.01 deg² in `fetch_eval_data.py`; reject with clear error before hitting API. |
| Redistributing Mapillary images without CC-BY-SA attribution | Legal (license compliance) | Dataset README + per-image manifest records `source_mapillary_id`. HF Dataset publishes under CC-BY-SA 4.0. [VERIFIED: Mapillary help page confirms CC-BY-SA 4.0 is the license for open data] |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Image-level bootstrap resampling is the standard-of-practice granularity for object detection precision/recall CIs (vs detection-level or per-object resampling) | Pattern 3 | If user/reviewer prefers detection-level, the CI widths change and we'd need to rerun. Mitigation: document choice in `DETECTOR_EVAL.md` methodology section explicitly. |
| A2 | Keremberke's self-reported mAP50 = 0.995 is likely over-fit to their validation set, not a realistic zero-shot baseline on LA imagery | Standard Stack alternatives | Low risk — this informs fallback strategy only. Even if the HF model's zero-shot LA numbers are ~50%, that's still above the D-03 fine-tune threshold. |
| A3 | Python 3.12 can be installed on the dev machine without conflicts (dev has 3.9 only) | Environment Availability | Medium risk. If brew install fails or the user prefers not to install, Colab/EC2 becomes mandatory for training. Plan must address. |
| A4 | Mapillary free tier rate limits are adequate for a one-time 300-image pull | Pitfalls | Low risk. Historical mentions of 50k/min in forum posts suggest this is over-provisioned for our scope. Verify during Phase 2 execution. |
| A5 | HuggingFace Datasets (free tier) is acceptable for publishing a CC-BY-SA image set with ~300 images + labels | Standard Stack alternatives | Low risk — HF explicitly supports CC-BY-SA; dataset pages accept license metadata. |
| A6 | `ultralytics.YOLO.val()` correctly implements COCO-style matching for the IoU=0.5 single-class case | Don't Hand-Roll | Low risk — this is the reference implementation the whole field uses. |
| A7 | The dev machine's Apple Silicon MPS bug (#23140) still affects the current ultralytics 8.4.41 | Common Pitfalls | Medium risk — the bug may have been fixed. Plan should include a "smoke test: train 1 epoch with MPS, verify box coords sane" step; if MPS works, unlock it. |
| A8 | Ultralytics `.pt` weights fine-tuned from keremberke's AGPL-3.0 base remain AGPL-3.0 (license inheritance) | Model card template | Medium risk — AGPL is viral but our code never links the model as a library (it's data). Worth an explicit lawyer-check for the public demo; note in DETECTOR_EVAL.md. |

**If this table is empty:** Would indicate research was complete without extrapolation; three `[ASSUMED]` items here (A1, A7, A8) warrant user confirmation during planning.

## Open Questions (RESOLVED)

1. **Two-class labelling vs single-class + confidence-mapped severity**
   - What we know: Current `YOLOv8Detector._map_severity` already supports both; eval must mirror runtime.
   - What's unclear: Does the user want human operators making severity calls during labelling (slower, subjective) OR just "is there a pothole here" labels (faster, defers severity to the model's confidence)?
   - Recommendation: Use single-class labels + confidence→severity at inference. Saves labelling time, matches the "current single-class branch" of existing code, keeps D-06's per-severity breakdown valid (severity comes from confidence threshold). Plan should lock this before labelling begins.
   - **RESOLVED:** Single-class labelling adopted per D-05 (locked in CONTEXT.md). Plan 02-02 severity mapping mirrors `yolo_detector._map_severity` via shared `data_pipeline/eval.py::map_severity` (per-severity breakdown from confidence thresholds). Plan 02-05 data.yaml Task 1 sets `nc: 1` single-class.

2. **Default `YOLO_MODEL_PATH` when unset — which HF revision to pin?**
   - What we know: D-14 says default falls back to "a versioned HF name hardcoded in `detector_factory.py`."
   - What's unclear: Is "versioned" a git tag on the HF repo (e.g., `@v0.1.0`) or just the repo ID with implicit `@main`?
   - Recommendation: Start unversioned (`keremberke/yolov8s-pothole-segmentation`) because that's the base before fine-tuning exists. Once Phase 2 publishes `<user>/road-quality-la-yolov8`, switch default to a pinned revision so CI+production can't silently drift.
   - **RESOLVED:** Phase 2 ships with unversioned `_DEFAULT_HF_REPO = "keremberke/yolov8s-pothole-segmentation"` (Plan 02-01). Revision-pinning (`@<commit-sha>`) is supported by `_resolve_model_path` regex but not enforced as default; operator pins after first fine-tune publish. DETECTOR_EVAL.md (Plan 02-05) documents the pin-after-publish expectation.

3. **HF Dataset hosting vs S3 for the eval images**
   - What we know: D-04 says bucket provider is Claude's discretion.
   - What's unclear: Will the user ever want to restrict dataset access? (Affects HF-public vs HF-gated vs private-S3.)
   - Recommendation: HF Dataset, public, CC-BY-SA. Zero auth for reproducibility. User can gate later if needed.
   - **RESOLVED:** HF Datasets (public, CC-BY-SA) chosen per D-04. Plan 02-03 manifest-driven fetcher treats HF as one bucket backend; `manifest.json` abstracts provider so future migration to S3/GCS/Backblaze is mechanical. Per-image `source_mapillary_id` in manifest satisfies CC-BY-SA attribution chain.

4. **Number of fine-tuning epochs for 300 images**
   - What we know: 50-100 epochs with early stopping is the field recommendation; 300 is the "safe high end".
   - What's unclear: Time budget on operator machine — CPU training of 300 images × 100 epochs at batch 8 is several hours.
   - Recommendation: Start with `--epochs 50 --patience 10` for a first pass. If the early-stopping patience isn't triggered, bump to 100. Document in `docs/FINETUNE.md`.
   - **RESOLVED:** Plan 02-04 `finetune_detector.py` defaults to `--epochs 50 --patience 10 --device cpu --seed 42`. FINETUNE.md documents bumping to 100 epochs if early-stopping does not trigger. Per-recipe time estimates (laptop CPU / Colab T4 / EC2 g5) included in FINETUNE.md.

5. **Does the `segment_defects` schema need to accommodate a confidence/bbox for eval traceability?**
   - What we know: Phase 3 writes detections into `segment_defects` with `severity`, `count`, `confidence_sum`. No per-detection bbox stored.
   - What's unclear: Would it help the demo to show "here's the image, here's the box" alongside a detection?
   - Recommendation: Out of scope for Phase 2 (eval runs offline, not against DB). Flag for Phase 3 research.
   - **RESOLVED:** Deferred to Phase 3 research. Phase 2 eval runs offline against fixtures + `data/eval_la/` on disk; no DB writes. Per-detection bbox persistence is NOT in Phase 2 scope (matches CONTEXT.md `<deferred>` section).

## Sources

### Primary (HIGH confidence)
- [Ultralytics YOLO Docs — Training](https://docs.ultralytics.com/modes/train/) — train() args, data.yaml shape, default save_dir
- [Ultralytics YOLO Docs — Validation](https://docs.ultralytics.com/modes/val/) — model.val() return shape, metrics.box.{mp, mr, map50, map}
- [Ultralytics YOLO Docs — Performance Metrics](https://docs.ultralytics.com/guides/yolo-performance-metrics/)
- [Ultralytics YOLO Docs — Downloads Reference](https://docs.ultralytics.com/reference/utils/downloads/) — confirms NO native HF Hub support in base ultralytics
- [HuggingFace Hub — File Download Guide](https://huggingface.co/docs/huggingface_hub/guides/download) — hf_hub_download signature + cache behavior
- [HuggingFace Hub — HfApi Reference](https://huggingface.co/docs/huggingface_hub/package_reference/hf_api) — upload_file, create_repo, visibility
- [HuggingFace Hub — Uploading Models](https://huggingface.co/docs/hub/en/models-uploading)
- [SciPy — scipy.stats.bootstrap](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html)
- [Mapillary API Documentation](https://www.mapillary.com/developer/api-documentation) — v4 endpoints, bbox semantics
- [Mapillary — CC-BY-SA License Help](https://help.mapillary.com/hc/en-us/articles/115001770409-CC-BY-SA-license-for-open-data)
- [Keremberke yolov8n-pothole-segmentation repo tree](https://huggingface.co/keremberke/yolov8n-pothole-segmentation/tree/main) — confirms `best.pt` at repo root, 6.76 MB
- Existing code: `data_pipeline/yolo_detector.py`, `data_pipeline/detector_factory.py`, `scripts/ingest_iri.py`, `backend/tests/test_yolo_detector.py`
- Existing config: `data_pipeline/requirements.txt`, `backend/requirements.txt`, `.env.example`, `.gitignore`

### Secondary (MEDIUM confidence)
- [Ultralytics Issue #23140 — MPS Coordinate Corruption Bug](https://github.com/ultralytics/ultralytics/issues/23140) — open bug on Apple Silicon
- [Snyk Advisor — ultralyticsplus](https://snyk.io/advisor/python/ultralyticsplus) — "Inactive maintenance status"
- [Fine-tuning YOLOv8 Practical Guide](https://medium.com/@amit25173/fine-tuning-yolov8-a-practical-guide-61343dada5c1) — epoch/batch recommendations for small datasets
- [Labelformat — YOLOv8 Format](https://labelformat.com/formats/object-detection/yolov8/) — `.txt` format spec
- [CVAT vs Label Studio (CVAT blog)](https://www.cvat.ai/resources/blog/cvat-or-label-studio-which-one-to-choose) — tool comparison
- [Roboflow YOLO Format](https://roboflow.com/formats/yolo)
- [MachineLearningMastery — Bootstrap CIs for ML](https://machinelearningmastery.com/calculate-bootstrap-confidence-intervals-machine-learning-results-python/) — image-level vs record-level sampling

### Tertiary (LOW confidence — flagged for validation during execution)
- Mapillary rate limits for 2026 (historical 50k/min figure) — verify at fetch time
- Keremberke mAP@0.5 = 0.995 self-report — treat as suspicious; our own eval supersedes it
- "Image-level bootstrap" as detection convention — flagged A1

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all versions verified against official docs and pypi. One correction needed to D-14's implementation (see Summary); user-facing surface is unchanged.
- Architecture: HIGH — patterns align with existing project conventions (`ingest_iri.py` + `iri_sources.py` split, env-at-module-top, argparse CLI).
- Pitfalls: MEDIUM-HIGH — most verified via GitHub issues or official docs. A7 (MPS bug persistence) is marked assumed and needs in-execution confirmation.
- Security: HIGH — pickle ACE risk is well-documented; license compliance is explicit.
- Validation: HIGH — test map directly derives from SC #1-4 and D-18 exit codes.

**Research date:** 2026-04-23
**Valid until:** 2026-05-23 (30 days — mostly stable stack; the one fast-moving piece is ultralytics itself, which ships often — re-verify ultralytics version before any future Phase-2-adjacent work)
