# Detector Accuracy — LA Evaluation Report

**Version:** 0.1.0
**Last Updated:** 2026-04-23
**Status:** Methodology fixed; numbers populated after first eval run

---

This document records the methodology and reported accuracy of the YOLOv8
pothole detector used by road-quality-mvp, evaluated on hand-labelled Los
Angeles street-level imagery sourced from Mapillary. It is the citation
target for the public demo (ROADMAP M1 Phase 6).

## TL;DR

- **Dataset:** ~300 hand-labelled LA images from Mapillary, single-class
  ("pothole"), sequence-grouped 70/20/10 train/val/test split (D-09)
- **Base model:** [`keremberke/yolov8s-pothole-segmentation`](https://huggingface.co/keremberke/yolov8s-pothole-segmentation)
  fine-tuned on the LA train split (D-11)
- **Metrics (test split):**

  | Metric | Value | [95% CI] |
  |--------|-------|----------|
  | Precision | TBD | [95% CI: TBD, TBD] |
  | Recall    | TBD | [95% CI: TBD, TBD] |
  | mAP@0.5   | TBD | — |

  *Numbers are populated from `eval_report.json` produced by
  `scripts/eval_detector.py`. Update after re-training.*

- **Severity breakdown (test split):**

  | Severity | Count |
  |----------|-------|
  | Severe (confidence ≥ 0.7) | TBD |
  | Moderate (0.4 ≤ confidence < 0.7) | TBD |
  | Dropped (confidence < 0.4) | TBD |

---

## 1. Methodology

### Dataset

- **Source:** Mapillary street-level imagery, three Los Angeles zones
  (downtown DTLA, West LA residential, Hollywood freeway-adjacent) —
  configured in `scripts/fetch_eval_data.py::_DEFAULT_LA_BBOXES`. Each
  bounding box ≤ 0.01 deg² per Mapillary API guidance (Pitfall 3 in
  `.planning/phases/02-real-data-detector-accuracy/02-RESEARCH.md`).
- **Labelling:** Hand-labelled by the project operator using a YOLO-
  compatible tool (CVAT 1.1 native export recommended). Single-class:
  label = "pothole" regardless of severity; severity is derived at
  inference from detection confidence
  (`data_pipeline/yolo_detector.py::_map_severity`).
- **Split:** 70% train / 20% val / 10% test (D-09). Splits grouped by
  Mapillary `sequence_id` so adjacent frames from the same drive never
  span the train/test boundary (Pitfall 7).
- **Integrity:** Every file has a SHA256 pinned in
  `data/eval_la/manifest.json`. Re-running
  `python scripts/fetch_eval_data.py` (default `--verify-only`) hash-
  checks every file with constant-time compare (`hmac.compare_digest`).

### Metrics

- **Primary (D-06):** Precision, Recall, mAP@0.5 — computed by
  `ultralytics.YOLO.val()` which is the COCO-style reference
  implementation.
- **IoU threshold (D-07):** 0.5 — standard for YOLO. Not 0.3 (too
  lenient, weakens claim). Not 0.5:0.95 (overkill for a 300-image set).
- **Confidence intervals (D-08):** Image-level bootstrap, 1000
  resamples, 95% percentile interval, seed=42 for reproducibility.
  Computed in `data_pipeline/eval.py::bootstrap_ci`.
- **Per-severity breakdown (D-06):** Moderate (0.4 ≤ confidence < 0.7)
  vs Severe (confidence ≥ 0.7) — mirrors
  `data_pipeline/yolo_detector.py::_map_severity` exactly so eval
  metrics map 1:1 to runtime behavior.

### Why image-level bootstrap?

Resampling **images with replacement** (not individual detections)
honors the unit of sampling variability — each Mapillary image is one
independent "draw." Detections within a single image are not
independent (a blurry frame causes clustered misses). This is the
convention COCO-style eval tooling uses implicitly. See Assumption A1
in `.planning/phases/02-real-data-detector-accuracy/02-RESEARCH.md` —
the planner chose image-level over detection-level; reviewers who
prefer the latter should re-run with detection-level resampling and
compare.

### Caveat: per-image CI degeneracy

`scripts/eval_detector.py::_collect_per_image_counts` prefers per-image
tp/fp/fn arrays exposed by ultralytics 8.3+ `results.stats`. On older
ultralytics versions the per-image arrays may not be available, in
which case the harness falls back to a **single aggregated bucket**.
In that path bootstrap resampling degenerates (one "image" resampled
1000 times with replacement still returns the same tp/fp/fn), and the
reported CI collapses to a point interval. If Section 2's CI columns
are near-zero-width, this is the failure mode; upgrade ultralytics or
switch to a version that exposes per-image stats.

---

## 2. Results

*Populated from `eval_report.json` after running
`scripts/eval_detector.py --split test --json-out eval_report.json`.
Replace TBD cells after the first real fine-tune + eval pass.*

### Headline (test split, held out from training per D-09)

| Metric | Point Estimate | 95% CI (image-level bootstrap, 1000 resamples) |
|--------|---------------:|-----------------------------------------------:|
| Precision | TBD | [95% CI: TBD, TBD] |
| Recall    | TBD | [95% CI: TBD, TBD] |
| mAP@0.5   | TBD | — |

### Per-severity detection counts (test split)

| Severity bucket | Predictions | Matched ground truth | Precision | Recall |
|-----------------|------------:|---------------------:|----------:|-------:|
| Severe (conf ≥ 0.7) | TBD | TBD | TBD | TBD |
| Moderate (0.4 ≤ conf < 0.7) | TBD | TBD | TBD | TBD |
| Dropped (conf < 0.4) | TBD | — | — | — |

### Eval configuration

- IoU threshold: 0.5
- Bootstrap resamples: 1000
- CI level: 95%
- Split: test (~30 images, sequence-grouped)
- Model: `runs/detect/la_pothole/weights/best.pt` (local fine-tune) OR
  `<user>/road-quality-la-yolov8@<revision>` (HF Hub pinned)

---

## 3. Caveats & Limitations

- **Small test set.** The held-out test split is ~30 images (10% of
  300). Bootstrap CIs are wide by design; treat point estimates as
  indicative, not definitive. A production detector should be re-
  evaluated on a larger held-out set as more LA imagery is labelled.
- **LA-specific.** The detector is proven on LA streets only.
  Generalization to other cities, lighting conditions, camera heights,
  or Mapillary vintage is untested. Do not claim global road-damage
  performance.
- **Single-operator labelling.** All labels come from one annotator;
  no inter-rater agreement captured. Class boundary ("is this a pothole
  or just a shadow?") is judgment-dependent.
- **Mapillary vintage and device mix.** Mapillary aggregates images
  from multiple capture devices (smartphones, dash cams, 360° rigs)
  across multiple years. The training distribution is mixed.
- **Severity bucketing via confidence proxy.** Moderate vs severe is
  derived from detector confidence, not from labelled severity. This is
  a proxy — a severe pothole at an unusual angle may score low
  confidence and bucket as moderate. If severity accuracy becomes
  important, revisit the single-class-vs-two-class decision (see D-05 +
  A8 in RESEARCH.md).
- **Per-image CI caveat.** On older ultralytics versions the bootstrap
  degenerates to a single aggregated bucket; see Section 1 "Caveat:
  per-image CI degeneracy" above.
- **Deferred:** generalization comparison against RDD2020 (CONTEXT.md
  deferred_ideas; nice-to-have footnote); Paper-grade statistical rigor
  (explicitly rejected as MVP overkill); confidence calibration; CI
  gate on detector accuracy.

---

## 4. Reproduction

Full reproduction from a clean checkout:

```bash
# 1. Install deps
pip install -r data_pipeline/requirements.txt
pip install -r requirements-train.txt   # only if you plan to fine-tune

# 2. Set tokens (both free; skip HF if you only plan to eval, not publish)
export MAPILLARY_ACCESS_TOKEN=...        # https://www.mapillary.com/dashboard/developers
export HUGGINGFACE_TOKEN=hf_...          # https://huggingface.co/settings/tokens

# 3. Fetch + hash-verify the eval dataset
#    (--verify-only is default; it confirms data/eval_la/manifest.json matches local files)
python scripts/fetch_eval_data.py

#    If manifest missing OR files missing/corrupt: exit code 3, rebuild with:
#      python scripts/fetch_eval_data.py --build --count 100
#    then hand-label images/*/ under a YOLO-compatible tool (CVAT recommended).

# 4. (Optional) Fine-tune on the LA train split — see docs/FINETUNE.md for multi-env recipes
python scripts/finetune_detector.py \
    --data data/eval_la/data.yaml \
    --epochs 50 \
    --device cpu \
    --push-to-hub <user>/road-quality-la-yolov8

# 5. Run the eval (this exact invocation mirrors docs/FINETUNE.md "After Training")
YOLO_MODEL_PATH=runs/detect/la_pothole/weights/best.pt \
python scripts/eval_detector.py \
    --data data/eval_la/data.yaml \
    --split test \
    --json-out eval_report.json

# eval_detector.py exit codes (D-18):
#   0 = OK
#   1 = other error (missing dep, unexpected failure)
#   2 = below --min-precision or --min-recall floor
#   3 = missing dataset (data.yaml path does not exist)

# 6. Substitute numbers from eval_report.json into this document's tables.
```

Full multi-env fine-tune reproduction (laptop CPU, Colab T4, EC2
g5.xlarge): see [`docs/FINETUNE.md`](FINETUNE.md).

---

## 5. Security

**Pickle ACE risk (T-02-01).** The YOLO `.pt` weights file is a pickled
PyTorch state dict. `ultralytics.YOLO(path).load()` calls `torch.load`
which executes arbitrary code during deserialization. **Loading an
untrusted `.pt` file is remote code execution.** HuggingFace marks
`.pt` files "Unsafe" on the repo UI for exactly this reason.

Mitigations:

- The default `YOLO_MODEL_PATH` in `data_pipeline/detector_factory.py`
  (`_DEFAULT_HF_REPO`) points to a known reviewed publisher
  (`keremberke/yolov8s-pothole-segmentation`).
- Pin to a specific revision in production:
  `YOLO_MODEL_PATH=user/repo@<commit_sha>`. Supported by
  `_resolve_model_path` via the `@<revision>` suffix. Prevents silent
  weight swap by a compromised HF account (Pitfall 8).
- Future: upgrade to `weights_only=True` when ultralytics supports it
  upstream (currently tracked in their issue queue).

**Token handling.** `HUGGINGFACE_TOKEN` and `MAPILLARY_ACCESS_TOKEN`
are read at module top in their respective files, never logged, and
only used as `Authorization` headers. `.env.example` documents both
with empty defaults; `.env` is gitignored. Review `.env.example`
before committing if you add new vars.

**SHA256 manifest verification.** `scripts/fetch_eval_data.py` uses
`hmac.compare_digest` for constant-time hash comparison (Security V6)
and rejects path-traversal entries and malformed hex strings in
`data/eval_la/manifest.json` (Security V5).

---

## 6. Licensing & Attribution

The eval dataset, fine-tuned weights, and downstream route-quality
service involve three separate license tiers:

| Artifact | License | Source | Propagation |
|----------|---------|--------|-------------|
| Mapillary open imagery | CC-BY-SA 4.0 | https://help.mapillary.com/hc/en-us/articles/115001770409 | Attribution per image via `source_mapillary_id` in `data/eval_la/manifest.json` |
| Labels (YOLO `.txt` files) | CC-BY-SA 4.0 | Derivative of CC-BY-SA imagery | Inherits — dataset published under CC-BY-SA 4.0 if mirrored on HF Datasets |
| Base model weights (keremberke) | AGPL-3.0 | Ultralytics base license | Fine-tuned output inherits AGPL-3.0 |
| Fine-tuned weights | AGPL-3.0 | Derivative | Published under AGPL-3.0 on HF with CC-BY-SA data attribution in model card |
| road-quality-mvp service code | Project license | This repo | Does NOT link model as a library — loads `.pt` as data at runtime; license chain scope limited to the weights file itself |

**Risk flag (A8).** AGPL-3.0 is viral for derivative *code*; its reach
over ML weights loaded at runtime is legally ambiguous. For the public
demo, weights are used in a backend service that produces detection
outputs; the service does not statically link the model. Worth a
lawyer review if the project ever commercializes. For now: document,
attribute, and ship.

**Attribution requirements when publishing:**

- Mapillary's CC-BY-SA: credit Mapillary + preserve source image IDs.
- Keremberke's AGPL-3.0 (base model): credit
  `keremberke/yolov8s-pothole-segmentation`.
- Include both in the fine-tuned weights' HF model card (`README.md`
  uploaded by `scripts/finetune_detector.py::_build_model_card`).

---

## 7. Changelog

- **2026-04-23** (v0.1.0): Initial scaffolding. Methodology fixed;
  numbers are TBD pending first fine-tune + eval run.

---

*This report is authored by the project operator. Numbers are
regenerated from `eval_report.json` on every eval run; substitute them
into Section 2 tables manually (or pipe through a small formatter as
future work).*
