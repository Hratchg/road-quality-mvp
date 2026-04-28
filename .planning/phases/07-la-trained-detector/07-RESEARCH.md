# Phase 7: LA-Trained Detector — Research

**Researched:** 2026-04-28
**Domain:** YOLOv8 fine-tuning on LA Mapillary imagery; mAP@0.5 bootstrap CI methodology; EC2 g5.xlarge training setup; CVAT at 1500-image scale; idempotent prod re-ingestion with wipe-mapillary
**Confidence:** MEDIUM-HIGH (stack verified from official sources and existing codebase; EC2 timing and Mapillary quality_score are LOW confidence; mAP bootstrap methodology is MEDIUM)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Imagery Sourcing**
- D-01: Source = Mapillary, LA-only. No RDD2020, no Roboflow Universe.
- D-02: Coverage = both more zones AND denser sampling. 8-10 spread zones + 1-2 known-bad-pavement zones. 0.005-deg sub-tile grid preserved (fixes the Mapillary 500-error issue).
- D-03: Target ~1500 candidate images.
- D-04: Zone selection = spread + known-bad-pavement (Mid-City east of La Brea, Boyle Heights, parts of South LA).
- D-05: Image filtering = Claude's discretion (quality_score quartile drop + captured_at >= 2023 recommended; planner confirms during research).
- D-06: Phase 6's 158 images / 17 hand-labels can be carried forward OR fully replaced. Planner picks based on zone overlap. If not reused, archived as data/eval_la_phase6/.

**Compute / Training**
- D-07: Training compute = EC2 g5.xlarge (Recipe C). ~$1-2 total estimated cost.
- D-08: Iteration budget = Claude's discretion. Recommended 2-3 runs.
- D-09: Apple Silicon MPS = NOT used (Pitfall 1 still unresolved).

**"Beat Baseline" Criterion**
- D-10: Comparison = re-eval public baseline on the NEW test split + report mAP@0.5 alongside P/R.
- D-11: Win = non-overlapping 95% CI on at least one of {Precision, Recall, mAP@0.5}.
- D-12: Absolute floors = Claude's discretion. Recommended P >= 0.5.
- D-13: Contingency = hybrid iterate-once-then-close. Hard cap on calendar time.

**Production Re-Ingestion**
- D-14: Wipe ALL synthetic + ALL mapillary; production becomes real-data-only.
- D-15: Add --wipe-mapillary flag mirroring wipe_synthetic_rows() pattern.
- D-16: Coverage = training zones + adjacent expansions. Caveat in DETECTOR_EVAL.md.
- D-17: Always re-ingest with trained model, even if it underperforms baseline.
- D-18: wipe-then-ingest order; flyctl proxy is fine for INSERT traffic.

### Claude's Discretion

- Detection-only vs segmentation-base model choice (Phase 7 must decide; see Critical Finding #2)
- Pre-labeling workflow (reuse scripts/prelabel.py or stronger model)
- AWS region / instance lifecycle / S3 bucket / dataset transit on EC2
- HF token handling on training instance
- Mapillary --count per sub-tile (currently 25; need ~30-40 for ~1500 across 12-15 zones)
- Whether to publish labeled dataset to HF Datasets
- Augmentation recipe for fine-tuning

### Deferred Ideas (OUT OF SCOPE)

- Multi-city support (M2)
- RDD2020 / Roboflow Universe supplementation (rejected)
- Iterating beyond 2 trained runs
- Apple Silicon MPS re-test (M2)
- Continuous eval / CI gate on detector accuracy
- Confidence calibration / temperature scaling
- Frontend disclosure UI for trained-zone vs uncovered-zone
- HF Datasets publish of labeled dataset (unless trivially cheap)
- Inter-rater agreement for hand labels
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REQ-trained-la-detector | YOLOv8 fine-tuned on LA dataset measurably beats public baseline (non-overlapping 95% CIs on P, R, or mAP@0.5) and replaces the baseline in production | Detection-only base model recommendation (CRQ #2); mAP bootstrap CI via image-level resampling (CRQ #4); EC2 g5.xlarge setup (CRQ #3); CVAT workflow at scale (CRQ #5); wipe-mapillary code pattern (CRQ #6); Mapillary quality_score filter (CRQ #1) |
</phase_requirements>

---

## Summary

Phase 7 is an operator-intensive data-acquisition + ML training phase. The codebase already has all the right scaffolding: `finetune_detector.py` supports `--device 0` for CUDA, `fetch_eval_data.py` has sequence-grouped splitting, `eval.py` has image-level bootstrap CI, and `detector_factory.py` has the HF revision pin pattern. The primary open questions are (1) the base model choice (detection vs segmentation — critical because segmentation breaks `eval_detector.py`'s `val()` path), and (2) whether Mapillary's v4 API exposes `quality_score` filtering for the D-05 image filter.

The biggest risk is data acquisition: Phase 6 yielded only 17 positive bboxes from 158 images (10.7% positive rate). At ~1500 images with the same rate, Phase 7 projects ~160 positives — just above the ≥150 SC #1 floor. If LA Mapillary imagery has a genuinely low pothole positive rate (due to camera angle, image quality, or low-severity surface damage), the dataset target may require further expansion. The zone selection strategy (8-10 spread + 1-2 known-bad-pavement) hedges this risk.

The second structural issue is the `ultralytics.YOLO.val()` incompatibility with segmentation-base + bbox-only labels, discovered in Phase 6 Plan 06-05. This forces a decision: switch to a detection-only base (`yolov8s.pt` COCO-pretrained) which makes `val()` work cleanly and gives access to built-in mAP computation, or continue with keremberke's segmentation base and reuse the manual eval bypass. **The recommendation is detection-only base** — it eliminates the `val()` crash, gives `metrics.box.map50` directly for D-11, and sidesteps AGPL-3.0 inheritance from the keremberke weights (though the AGPL chain is already in place via Phase 6 baseline use).

**Primary recommendation:** Switch to `yolov8s.pt` COCO-pretrained detection base. This makes `scripts/eval_detector.py` work cleanly, gives direct access to `metrics.box.map50`, and eliminates the segmentation-vs-detection task mismatch. The re-evaluation of the Phase 6 baseline (keremberke segmentation model on the new test split) still uses the Plan 06-05 manual bypass since that model cannot be coerced into detection mode.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Mapillary image acquisition (eval + prod) | `scripts/fetch_eval_data.py` (eval) / `scripts/ingest_mapillary.py` (prod) | `data_pipeline/mapillary.py` (shared client) | Existing pattern; client is framework-agnostic |
| CVAT hand-labeling | Operator workstation (external tool) | `scripts/prelabel.py` (pre-label assist) | CVAT is external; pre-label runs locally |
| YOLOv8 fine-tuning | `scripts/finetune_detector.py` on EC2 | `data_pipeline/detector_factory.py` (model resolution) | Script is already EC2-aware via `--device 0` |
| mAP@0.5 + P/R eval | `scripts/eval_detector.py` | `data_pipeline/eval.py::bootstrap_ci` | Same as Phase 2; bootstrap CI is reusable |
| Re-eval public baseline on new test split | Inline manual bypass (Plan 06-05 pattern) | `data_pipeline/eval.py::bootstrap_ci` | keremberke segmentation model can't use val() |
| HF model publish | `scripts/finetune_detector.py --push-to-hub` | `huggingface_hub.HfApi` | Existing --push-to-hub flag; SHA capture via HfApi().model_info |
| `_DEFAULT_HF_REPO` update | `data_pipeline/detector_factory.py` (1-line edit) | — | Existing pattern; Phase 7 swaps repo constant |
| wipe-mapillary | `scripts/ingest_mapillary.py` (new `--wipe-mapillary` flag + `wipe_mapillary_rows()`) | — | Mirrors wipe_synthetic_rows() at line 332 |
| Prod re-ingestion | `scripts/ingest_mapillary.py` via `flyctl proxy 15432:5432` | `scripts/compute_scores.py` | INSERT traffic; proxy is correct (Phase 5 anti-pattern applies only to long DDL) |
| DETECTOR_EVAL.md + README update | `docs/DETECTOR_EVAL.md` (v0.2.0 → v0.3.0), `README.md` | — | Documentation tier; manual substitution from eval_results.json |

---

## Critical Findings

### CRQ #1: Mapillary v4 API Current Capabilities

**quality_score field:** NOT exposed in the v4 search API. [VERIFIED: Mapillary API documentation at mapillary.com/developer/api-documentation — no quality_score filter listed in image search parameters. Forum post from January 2026 indicates the feature was surfaced as "quality score" in the UI but not available as an API filter.] [CITED: https://forum.mapillary.com/t/quality-score-automated-image-quality-estimation/5009]

**Implication for D-05:** The quality_score filter (first half of the D-05 recommended approach) is not available via the v4 API. The `captured_at >= 2023` filter IS available.

**captured_at filter syntax:** Use `start_captured_at` parameter in ISO 8601 format: `"2023-01-01T00:00:00Z"`. Returns data in `captured_at` field as unix milliseconds. The existing `search_images()` in `data_pipeline/mapillary.py` does not pass this parameter — Phase 7 needs to add it to the `params` dict. [VERIFIED: Mapillary official API docs; confirmed ISO 8601 not unix timestamp for filters]

**Revised D-05 approach:** Since quality_score is not API-filterable, the planner should either:
  a) Accept all images and manually discard obvious low-quality ones during CVAT labeling (operator review step)
  b) Add post-download quality filtering using local image metrics (e.g., blur detection via OpenCV's Laplacian variance, image size check)
  Recommendation: option (a) for simplicity — labelers will naturally skip blank/blurry images during annotation.

**Pagination:** The v4 images search endpoint does NOT support general pagination. Pagination with `after` cursor is supported ONLY when filtering by `creator_username`. For bbox-based search (Phase 7's approach), Mapillary returns up to the limit in one shot. At `--count 100` per 0.005-deg sub-tile, this is well under the practical cap. [CITED: Mapillary Community Forum — pagination support for images endpoint]

**bbox size limit:** 0.005-deg sub-tiles (0.000025 deg²) are well within the 0.01 deg² guard in `data_pipeline/mapillary.py::validate_bbox`. The 0.005-deg grid that fixed Phase 6 500 errors remains the correct approach. [VERIFIED: `data_pipeline/mapillary.py` code read — `MAX_BBOX_AREA_DEG2 = 0.01`]

**Rate limits:** Search API (bbox queries): 10,000 requests/minute per app. Entity API: 60,000 requests/minute per app. Tile API: 50,000/day. [VERIFIED: mapillary.com/developer/api-documentation]

**At 12-15 new zone bboxes + each expanded to 4 sub-tiles = ~60 sub-tile searches:** Well within rate limits. Adding `start_captured_at=2023-01-01T00:00:00Z` to `search_images()` call is a 1-line param addition.

---

### CRQ #2: YOLOv8 Base Model Decision (Detection vs Segmentation)

**The core issue confirmed:** `keremberke/yolov8s-pothole-segmentation` is a segmentation model (confirmed by HuggingFace model card: mAP@0.5(mask) = 0.928, model type "Image Segmentation"). Ultralytics `val()` auto-runs the segmentation pipeline which expects mask tensors — bbox-only labels crash with `IndexError: index is out of bounds for dimension with size 0`. [VERIFIED: Phase 6 Plan 06-05 SUMMARY — exact error documented; VERIFIED: HuggingFace model page for keremberke/yolov8s-pothole-segmentation]

**Fix: switch to detection-only base.** YOLOv8 detection models (`yolov8n.pt`, `yolov8s.pt`) are COCO-pretrained, use no `-seg` suffix, and fully support `val()` with bbox-only labels. [CITED: docs.ultralytics.com/models/yolov8 — detection vs segmentation variants]

**Model size recommendation: `yolov8s.pt`** (small). [ASSUMED: based on Phase 2 RESEARCH Alternatives Considered — `yolov8s` was noted as the better balance of speed vs mAP50 compared to `yolov8n`. COCO pretrained means global-object priors; pothole-specific features come from fine-tuning.]

**Why not arnabdhar pothole detection?** [VERIFIED: search results] The `arnabdhar` HuggingFace model is for face detection, not pothole detection. No actively-maintained detection-only pothole model on HuggingFace was found that clearly surpasses the keremberke baseline. `peterhdd/pothole-detection-yolov8` exists but has no documented eval metrics. Generic COCO-pretrained `yolov8s.pt` is the cleaner starting point for a fine-tune because it doesn't inherit a third-party fine-tune's potential distribution biases.

**Implication for keremberke re-eval (D-10):** Even if Phase 7 trains on a detection-only base, the re-evaluation of the Phase 6 baseline (`keremberke/yolov8s-pothole-segmentation`) on the new test split MUST still use the Plan 06-05 manual bypass (`.predict()` + manual IoU + bootstrap). There is no way to force `val()` on the segmentation model with bbox-only labels. This means two code paths coexist during the re-eval plan:
  - keremberke baseline re-eval: `model.predict()` + `data_pipeline/eval.py::bootstrap_ci` + manual IoU (reuse Plan 06-05 inline script)
  - trained-LA-detector eval: `scripts/eval_detector.py` (val()-based path works for detection model)

**AGPL-3.0 chain update:** Switching to `yolov8s.pt` as the base still uses ultralytics which is AGPL-3.0. The license chain is identical. No difference from keremberke's base. [CITED: ultralytics license; DETECTOR_EVAL.md Section 6]

**Single-class "pothole" + severity-from-confidence:** This works identically for detection-only base models. `data_pipeline/yolo_detector.py::_map_severity` and `data_pipeline/eval.py` are already written for single-class models. No code change needed. [VERIFIED: yolo_detector.py code read]

---

### CRQ #3: EC2 g5.xlarge Training Setup

**Instance specs:** g5.xlarge = 4 vCPUs, 1x NVIDIA A10G GPU (24 GB VRAM), 16 GiB RAM. [VERIFIED: aws.amazon.com/ec2/instance-types/g5]

**On-demand cost:** ~$1.006/hr. [VERIFIED: AWS pricing search result]

**Recommended AMI:** AWS Deep Learning OSS AMI GPU PyTorch (Ubuntu 22.04 or Amazon Linux 2023). Current versions include PyTorch 2.5-2.8 with CUDA 12.4-12.9. The AMI comes with NVIDIA drivers pre-installed. Note: G4Dn/G5 instances use a dynamic proprietary driver loaded at boot due to a kernel change — the DLAMI handles this automatically. [CITED: docs.aws.amazon.com/dlami/latest/devguide/aws-deep-learning-ami-gpu-pytorch-2.5-ubuntu-22-04.html]

**CUDA compatibility with ultralytics 8.4.41:** ultralytics requires PyTorch >= 1.8.0 (with torch != 2.4.0). Current DLAMI ships PyTorch 2.5-2.8 with CUDA 12.4-12.9 — fully compatible. [VERIFIED: ultralytics PyPI page shows version 8.4.41; CITED: ultralytics/ultralytics pyproject.toml constraint `torch!=2.4.0,>=1.8.0`]

**Dataset transit:** Phase 7 target is ~1500 images at ~100-300KB each = ~300MB-450MB total (significantly smaller than the 3-5GB estimate in the CONTEXT.md — Mapillary's `thumb_2048_url` images are 2048px JPEGs averaging ~200KB). `scp` from laptop is fine at this size (~5-10 min on typical broadband). S3 sync adds setup complexity with no material benefit. [ASSUMED: image size estimate based on JPEG compression of 2048px images; Phase 6's 158 images should give a ground-truth per-image size reference. Operator can check: `du -sh data/eval_la/images/`]

**HF token handling on EC2:** Set `HUGGINGFACE_TOKEN` as environment variable via SSH-then-export (safest, no UserData logging). `finetune_detector.py` already reads it at module top. Never inject into UserData (visible in AWS console logs). [VERIFIED: finetune_detector.py code read — `HUGGINGFACE_TOKEN = os.environ.get("HUGGINGFACE_TOKEN")`]

**Estimated training time on A10G:**
- Phase 2's Recipe B (Colab T4) estimated "15-20 min for 300 images × 50 epochs." [CITED: docs/FINETUNE.md]
- A10G is ~3.3x faster than T4 for ML training. [CITED: aws.amazon.com/blogs/aws/new-ec2-instances-g5-with-nvidia-a10g-tensor-core-gpus]
- 1500 images × 50 epochs: ~5x images vs 300 → estimated ~75-100 min on T4 → ~25-30 min on A10G.
- Including 3 iterations (train + eval each): ~90-120 min total GPU time.
- Cost: ~$1.00-$1.20 total. The CONTEXT.md "~$1-2" estimate is accurate. [ASSUMED: scaling linear with dataset size is approximate; mosaic augmentation generates synthetic combinations so effective samples per epoch > raw image count]

**FINETUNE.md Recipe C update needed:** Recipe C references `--epochs 100 --batch 64`. For 1500-image fine-tune from detection base, `--epochs 50 --batch 32 --patience 15` is a reasonable starting point. Bump to 100 epochs with `--patience 20` if early stopping fires before reasonable convergence.

---

### CRQ #4: mAP@0.5 with Bootstrap CI

**Bootstrap CI on mAP@0.5 — methodology:**
mAP@0.5 is computed by integrating the precision-recall curve. Unlike precision and recall (which can be computed per image via TP/FP/FN), mAP requires rank-ordering all predictions by confidence across the full test set — this is an aggregate metric, not per-image.

There are two bootstrap approaches:

**Approach A (image-level bootstrap on TP/FP/FN, then recompute mAP per resample):**
- Resample images with replacement → for each resample, collect all predictions + GT boxes → recompute P-R curve across the resampled images → compute area under curve (mAP@0.5)
- This is the methodologically correct approach. "Bootstrap CI on mAP" in recent YOLOv8 literature means resampling the full detection output (images) and recomputing the metric per resample. [CITED: MDPI 2025 paper — "bootstrap resampling with 1,000 iterations, subsets of the test dataset repeatedly sampled with replacement, mAP@0.5 recalculated for each resample"]
- **Implementation gap:** `data_pipeline/eval.py::bootstrap_ci` currently only supports `metric="precision"` or `metric="recall"`. It does NOT support mAP@0.5.

**Approach B (ultralytics built-in val() mAP, no per-image breakdown):**
- `scripts/eval_detector.py` uses `ultralytics.YOLO.val()` which returns `results.box.map50` (aggregate scalar).
- The per-image breakdown for bootstrap would need `results.stats` per-image arrays exposed in ultralytics 8.3+. `DETECTOR_EVAL.md` section 1 already documents this: "if ultralytics 8.3+ stats are available, harness uses per-image arrays; otherwise degenerates to single aggregated bucket."
- For mAP bootstrap specifically: `results.box.map50` is a single float — no per-image breakdown is exposed by val(). Bootstrap on val() would require calling val() 1000 times on different image subsets, which is prohibitively slow (~30s × 1000 = 8+ hours).

**Recommendation for Phase 7:** Add `metric="map50"` support to `data_pipeline/eval.py::bootstrap_ci` using Approach A. The implementation collects per-image `(pred_boxes, gt_boxes)` pairs, resamples image indices, recomputes precision-recall curve via greedy matching at IoU=0.5 for each resample, and integrates the area. This is consistent with the existing `match_predictions()` function but adds the P-R curve integration step. [ASSUMED: this is more work than just re-running val() but gives methodologically sound CIs consistent with the paper citations above]

**Statistical defensibility at N≥30:**
Image-level bootstrap at N=30 test images gives "honest uncertainty quantification" but not paper-grade rigor. At N=30 with (say) 50 ground-truth positives, the 95% CI on mAP@0.5 will be ~±0.10-0.15 (wide). Non-overlapping CIs at this sample size still require a meaningful gap between the two models — the criterion is achievable but not guaranteed. This is exactly why D-11 uses "at least one of {P, R, mAP@0.5}" — more metrics means more chances for one to show separation. [ASSUMED: CI width estimate based on bootstrap theory for N=30; actual width depends on model behavior]

**Current `bootstrap_ci` signature gap:** The function signature is `metric: Literal["precision", "recall"]`. Phase 7 must add `"map50"` support via a new code path. This is a Wave 0 or Wave 1 code task (small, ~30 lines).

---

### CRQ #5: CVAT Workflow at 1500-Image Scale

**CVAT cloud (app.cvat.ai) capacity:** CVAT cloud's free tier supports up to 20 tasks with up to 5,000 files per task. 1500 images in a single task is well within limits. [ASSUMED: based on general CVAT cloud documentation; verify at signup. The free tier has changed over time.]

**Recommendation: shard into 3-4 CVAT tasks** (~400 images each) rather than one 1500-image task. Reasons: (1) labeling fatigue — 400 images per session is more manageable, (2) easier to track progress zone-by-zone, (3) if CVAT cloud connection drops mid-session, smaller tasks reduce rework.

**CVAT export format for YOLO:**
Phase 6 Plan 06-04 used CVAT-XML export + a conversion script to get YOLO 1.1 format. This was the Phase 6 approach. 

In CVAT 2.x, **Ultralytics YOLO format export** is now available natively. [VERIFIED: docs.cvat.ai/docs/dataset_management/formats/format-yolo-ultralytics/ — CVAT exports to Ultralytics YOLO format directly without conversion scripts. The export generates `data.yaml` + images + `.txt` labels in normalized format.] 

However, the existing `scripts/fetch_eval_data.py --build` already creates the directory structure and `data.yaml` that ultralytics expects (`images/train/`, `images/val/`, `images/test/` + `labels/train/`, etc.). The CVAT export ZIP just needs to be unpacked into `data/eval_la/labels/<split>/` matching the image IDs. If using Ultralytics YOLO export from CVAT 2.x, no conversion script is needed. [VERIFIED: format-yolo-ultralytics doc — "no conversion required, direct export to YOLO format"]

**Pre-label import into CVAT:** `scripts/prelabel.py` runs inference and outputs pre-labeled images. CVAT natively imports YOLO format annotations — upload as "Upload annotations → YOLO 1.1" (or Ultralytics YOLO in newer CVAT). The pre-label output from `prelabel.py` is YOLO format, so the import is direct without conversion. [VERIFIED: docs.cvat.ai/docs/dataset_management/formats/format-yolo/ — "You can upload annotations by clicking the Upload annotation button, choosing YOLO 1.1"]

**CVAT Ultralytics YOLO integration (2025):** CVAT announced native Ultralytics YOLO model integration in October 2025 for auto-annotation. This means CVAT can run the local YOLOv8 model directly inside the CVAT UI for auto-suggestions, without running `prelabel.py` externally first. [CITED: cvat.ai/resources/changelog/ultralytics-yolo-agentic-labeling] However, this requires setting up a CVAT AI agent — for a one-operator workflow, the existing `prelabel.py`→CVAT import path is simpler.

**CVAT vs Phase 6 workflow:** Phase 6's CVAT-XML → conversion-script path can be fully replaced by CVAT's native Ultralytics YOLO export in Phase 7. The planner should update the annotation plan to use the simpler export path and avoid the conversion script overhead.

---

### CRQ #6: Idempotent Prod Re-Ingestion

**wipe_mapillary_rows() implementation spec:**
The exact pattern from `wipe_synthetic_rows()` at `scripts/ingest_mapillary.py:332`:
```python
def wipe_mapillary_rows(conn) -> int:
    """D-15: DELETE FROM segment_defects WHERE source = 'mapillary'.
    Returns the deleted row count. Hard-coded WHERE clause — no parameterization
    (T-03-18 mitigation). CHECK constraint bounds source to literals only.
    """
    with conn.cursor() as cur:
        cur.execute("DELETE FROM segment_defects WHERE source = 'mapillary'")
        deleted = cur.rowcount
    conn.commit()
    logger.info("--wipe-mapillary: deleted %d rows", deleted)
    return deleted
```

The `segment_defects_source_check` constraint in `db/migrations/002_mapillary_provenance.sql` already ensures `source IN ('synthetic', 'mapillary')` — the hard-coded WHERE clause is safe by construction. [VERIFIED: 002_mapillary_provenance.sql code read]

**--wipe-mapillary flag wiring:**
Add to argparse alongside the existing `--wipe-synthetic` flag (lines 521-529 of `scripts/ingest_mapillary.py`). Add `wipe_mapillary_applied` to the run summary JSON. The safety latch (abort if 0 detections and no `--force-wipe`) from `--wipe-synthetic` should apply to `--wipe-mapillary` as well — you generally don't want to delete all mapillary rows with nothing to replace them. [VERIFIED: ingest_mapillary.py:595-637 code read — wipe_planned guard already does this for synthetic]

**D-14 full-wipe workflow:**
The Phase 7 re-ingestion runs both flags together:
```bash
python scripts/ingest_mapillary.py \
    --where "1=1" \  # or explicit --segment-ids for training-zone segments
    --wipe-synthetic \
    --wipe-mapillary \
    [--force-wipe if needed for first-time wipe-then-ingest on a fresh DB]
```
The actual invocation will use bbox-based ingestion, not --where, since the pipeline is bbox-driven (D-16).

**Note on ingest_mapillary.py mode:** The existing `ingest_mapillary.py` takes `--segment-ids` or `--where` to select road segments, then pads and searches Mapillary around those segments. For Phase 7's bbox-driven coverage (D-16), the operator will want to ingest against the training-zone + adjacent-expansion bboxes rather than specific segment IDs. [ASSUMED: there may be a workflow mismatch; the existing script is segment-centric, not bbox-centric. The fetch_eval_data.py uses bbox-driven search. Phase 7 planner should decide whether to (a) add bbox-mode to ingest_mapillary.py or (b) identify segments within each training bbox and pass their IDs.]

**Adjacent expansion bbox count:** 8-10 spread zones + 1-2 known-bad zones = 10-12 zones × 4 sub-tiles each = 40-48 sub-tiles. Adjacent expansion adds perhaps 1-2 sub-tiles per original zone = 60-70 total sub-tiles. At ~50 images per sub-tile, prod ingestion = ~3000-3500 Mapillary API calls. Within the 10,000/min rate limit this is ~20 seconds of API time total (ignoring image download latency). [ASSUMED: sub-tile count estimate; actual depends on bbox layout decisions made during data-sourcing plan]

**flyctl proxy for INSERT traffic:** Confirmed safe per Phase 5 Lessons Learned. Long DDL (pgr_createTopology) uses `flyctl ssh console`; INSERT-heavy workloads use `flyctl proxy 15432:5432`. Phase 7 re-ingestion is INSERT-heavy. [VERIFIED: 05-LESSONS-LEARNED.md BLOCKING anti-pattern section]

---

### CRQ #7: Validation Architecture

See the dedicated Validation Architecture section below.

---

## Standard Stack

### Core (no changes from Phase 2/6 — inherited)

| Library | Version | Purpose | Status |
|---------|---------|---------|--------|
| `ultralytics` | `>=8.3.0,<9.0` (current: 8.4.41) | YOLO training, val(), predict() | Already in data_pipeline/requirements.txt. For Phase 7, ensure >=8.3 for per-image stats in val(). [VERIFIED: pypi.org/project/ultralytics] |
| `huggingface_hub` | `>=0.24,<1.0` | HfApi, hf_hub_download, upload_file, model_info for SHA capture | Already in requirements-train.txt |
| `torch` + `torchvision` | PyTorch >=2.4.1 (CUDA wheel on EC2) | GPU training on A10G | DLAMI ships 2.5-2.8; install CUDA wheel: `pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121` |
| `numpy` | `>=2.2` | Array ops for bootstrap CI | Already present |
| `scipy` | `>=1.13` | Not used for bootstrap (we use our own numpy impl) | Present but not load-bearing for bootstrap |

### New for Phase 7

| Library | Version | Purpose | Notes |
|---------|---------|---------|-------|
| `opencv-python-headless` | `>=4.8` | Optional post-download quality filtering (blur detection via Laplacian variance) | Already in requirements; only needed if quality_score filter is implemented locally |

### Detection-Only Base Model

| Model | Source | Size | Why |
|-------|--------|------|-----|
| `yolov8s.pt` | Auto-downloaded by ultralytics on first `YOLO("yolov8s.pt")` call from GitHub releases | ~21MB | COCO-pretrained detection model; val() compatible with bbox-only labels; no segmentation task ambiguity |

**Installation for EC2:**
```bash
pip install -r requirements-train.txt
# CUDA wheel (DLAMI may already have torch; verify with: python -c "import torch; print(torch.cuda.is_available())")
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
```

---

## Architecture Patterns

### System Architecture Diagram

```
[Operator] ---bbox list---> [fetch_eval_data.py --build]
                                     |
                         [Mapillary v4 API bbox search]
                         (add start_captured_at=2023-01-01)
                                     |
                         [Download thumb_2048_url images]
                                     |
                         [Sequence-grouped train/val/test split]
                                     |
                         [data/eval_la/images/{train,val,test}/]
                                     |
                          [scripts/prelabel.py] (keremberke model
                           auto-suggest; FP-heavy, good starting point)
                                     |
                             [CVAT cloud] <--- upload pre-labels
                            (hand-correct; YOLO 1.1 export)
                                     |
                         [data/eval_la/labels/{train,val,test}/]
                                     v
                         [scripts/finetune_detector.py]
                         --base yolov8s.pt --device 0 (EC2 A10G)
                         --push-to-hub Hratchg/road-quality-la-yolov8
                                     |
                         [HuggingFace Hub: best.pt + model card]
                                     |
                         [HfApi().model_info(repo).sha] --> capture SHA
                                     |
                              [eval detector]
                              /               \
              [scripts/eval_detector.py]  [Plan 06-05 manual bypass]
              (trained LA model)          (keremberke re-eval for D-10)
              val()-based; mAP50 OK       predict()-based; bootstrap CI
                                     |
                         [data_pipeline/eval.py::bootstrap_ci]
                         (P, R, mAP@0.5 with 95% CI)
                                     |
                         [Non-overlapping CIs? D-11 check]
                         YES: "win"; NO: iterate or close (D-13)
                                     |
                    [detector_factory.py _DEFAULT_HF_REPO update]
                    "Hratchg/road-quality-la-yolov8@<sha>"
                                     |
              [scripts/ingest_mapillary.py --wipe-synthetic --wipe-mapillary]
              (via flyctl proxy 15432:5432; training-zone + adjacent bboxes)
                                     |
                    [scripts/compute_scores.py --source all]
                                     |
                    [docs/DETECTOR_EVAL.md v0.3.0 + README update]
```

### Recommended Project Structure (Phase 7 additions)

```
data/
├── eval_la/                # Phase 7 regenerates this (--build --clean)
│   ├── images/{train,val,test}/  # ~1500 images
│   ├── labels/{train,val,test}/  # >=150 positive bboxes
│   ├── manifest.json       # SHA256 pins
│   └── data.yaml           # single-class pothole, nc:1
├── eval_la_phase6/         # Archive of Phase 6's 158 images / 17 labels
│   └── ...                 # (if Phase 6 zones don't overlap Phase 7)
docs/
├── DETECTOR_EVAL.md        # v0.2.0 → v0.3.0; new numbers + "Previous baseline"
└── FINETUNE.md             # Recipe C update for 1500-image run
runs/
└── detect/
    └── la_pothole/
        └── weights/best.pt # Local fine-tuned weights (not committed)
```

### Pattern 1: wipe_mapillary_rows() — Mirror of wipe_synthetic_rows()

**What:** DELETE FROM segment_defects WHERE source = 'mapillary'
**When to use:** Phase 7 re-ingestion (D-14 full wipe before real-data-only state)

```python
# Source: scripts/ingest_mapillary.py:332 (wipe_synthetic_rows pattern)
def wipe_mapillary_rows(conn) -> int:
    """D-15: DELETE FROM segment_defects WHERE source = 'mapillary'.
    Hard-coded WHERE clause -- no parameterization (T-03-18 mitigation).
    """
    with conn.cursor() as cur:
        cur.execute("DELETE FROM segment_defects WHERE source = 'mapillary'")
        deleted = cur.rowcount
    conn.commit()
    logger.info("--wipe-mapillary: deleted %d rows", deleted)
    return deleted
```

### Pattern 2: captured_at filter in search_images()

**What:** Add `start_captured_at` to the existing Mapillary API params dict
**When to use:** Phase 7 image acquisition (D-05 recency filter)

```python
# Source: data_pipeline/mapillary.py::search_images() — MODIFICATION
params = {
    "bbox": ",".join(str(c) for c in bbox),
    "fields": "id,thumb_2048_url,computed_geometry,captured_at,sequence_id",
    "limit": limit,
    "start_captured_at": "2023-01-01T00:00:00Z",  # D-05: >= 2023 filter
}
```

Note: This adds a filter to `search_images()` — either as a new optional parameter or as part of a Phase 7 invocation override. The function signature change must be backward-compatible (add `start_captured_at: str | None = None`, pass to params only when set). [VERIFIED: ISO 8601 format confirmed from Mapillary API docs]

### Pattern 3: SHA capture after HF push

**What:** Capture the exact commit SHA after pushing to HF, then pin in `_DEFAULT_HF_REPO`
**When to use:** After `--push-to-hub` completes

```python
# Source: data_pipeline/detector_factory.py comment block
from huggingface_hub import HfApi
api = HfApi(token=HUGGINGFACE_TOKEN)
info = api.model_info("Hratchg/road-quality-la-yolov8")
sha = info.sha  # Pin this in _DEFAULT_HF_REPO
```

Then update `detector_factory.py`:
```python
_DEFAULT_HF_REPO = "Hratchg/road-quality-la-yolov8@<sha>"
```

### Anti-Patterns to Avoid

- **Running wipe-mapillary via flyctl ssh psql:** INSERT/DELETE for production re-ingestion goes via `flyctl proxy`, not `flyctl ssh`. The Phase 5 BLOCKING anti-pattern applies to multi-minute DDL only; wipe DELETE + re-INSERT is fine via proxy. [VERIFIED: 05-LESSONS-LEARNED.md]
- **Calling val() on keremberke segmentation model with bbox-only labels:** Will crash with `IndexError`. Use the Plan 06-05 manual bypass (`model.predict()` + manual IoU + `eval.py::bootstrap_ci`). [VERIFIED: 06-05-SUMMARY.md]
- **Floating _DEFAULT_HF_REPO without @sha:** Pickle-ACE risk. Always pin revision SHA. [VERIFIED: detector_factory.py comment block]
- **Using quality_score as a Mapillary API filter:** The field does not exist in v4 search API. [VERIFIED: Mapillary API docs — no quality_score filter]
- **Force --device mps on training:** MPS bug #23140 closed as "not planned" — X-coordinate corruption persists. Always use `--device 0` (CUDA) on EC2 or `--device cpu` on Apple Silicon. [VERIFIED: GitHub issue #23140 status]

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| mAP@0.5 P-R curve integration | Custom AP computation | ultralytics val() `metrics.box.map50` (for trained detection model) | ultralytics implements COCO-standard greedy matching + trapezoid rule integration; edge cases around tied confidence scores are handled correctly |
| Bootstrap CI for P/R | Hand-rolled percentile loop | `data_pipeline/eval.py::bootstrap_ci` | Already exists, seed=42, image-level resampling, 1000 resamples per Phase 2 D-08 |
| Sequence-grouped split | Custom grouping | `scripts/fetch_eval_data.py::_build_fresh` | Already implements sequence_id grouping with seed=42; pass new bbox set, it handles the rest |
| HF model SHA capture | Parsing git log | `HfApi().model_info(repo).sha` | Returns the exact commit SHA atomically after upload |
| Image ID filename sanitization | Custom regex | `data_pipeline/mapillary.py::download_image` | Already enforces digits-only T-02-20 mitigation |
| Idempotent INSERT | Custom upsert | `ON CONFLICT (segment_id, source_mapillary_id, severity) DO NOTHING` | Already in ingest_mapillary.py; covers resume after partial failure |

---

## Runtime State Inventory

Phase 7 is a data-swap phase. These runtime state items exist and are directly affected by the production re-ingestion:

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| Stored data | `segment_defects` rows with `source='synthetic'` (seed_data.py output, ~125k rows per Phase 5 seeding) | wipe via `--wipe-synthetic` |
| Stored data | `segment_defects` rows with `source='mapillary'` (Phase 6 Plan 06-03 ingestion; unknown row count but covers 3 zones × 12 sub-tiles) | wipe via `--wipe-mapillary` (NEW) |
| Stored data | `segment_scores` rows | auto-recomputed by `compute_scores.py --source all` after wipe + re-ingest |
| Live service config | `data_pipeline/detector_factory._DEFAULT_HF_REPO` (Python module constant, in-memory after import) | code edit + Fly.io backend redeploy to pick up new constant |
| Secrets/env vars | `HUGGINGFACE_TOKEN` — needed on EC2 for `--push-to-hub`; already in .env.example | no new secret needed; set on EC2 via SSH export |
| Secrets/env vars | `MAPILLARY_ACCESS_TOKEN` — needed for fetch_eval_data.py --build and ingest_mapillary.py | no new secret; already in .env |
| Secrets/env vars | `YOLO_MODEL_PATH` — currently unset in prod (uses `_DEFAULT_HF_REPO` default) | no change at deploy time; updating `_DEFAULT_HF_REPO` constant + redeploy is sufficient |
| Build artifacts | Local `runs/detect/la_pothole/weights/best.pt` on EC2 — sunk cost after HF upload | terminate EC2 instance after successful push; no persistent state |
| Build artifacts | `data/eval_la/` local dataset | not committed; operator retains locally; SHA256 manifest in manifest.json pins integrity |

**Nothing found in category:** OS-registered state (no cron, pm2, or launchd jobs; Fly.io manages the app lifecycle). Build artifacts in registries (the Fly.io Docker image for `backend` will be rebuilt after `_DEFAULT_HF_REPO` update — standard `fly deploy`).

---

## Common Pitfalls

### Pitfall 1: Apple Silicon MPS Coordinate Corruption (Phase 2 Pitfall 1 — STILL ACTIVE)
**What goes wrong:** Inference on MPS device returns corrupted bounding box X-coordinates (`[y2, y1, garbage, y2]` instead of `[x1, y1, x2, y2]`). Detection results are completely wrong.
**Why it happens:** ultralytics issue #23140 — closed as "not planned" as of January 2026. The bug is not fixed.
**How to avoid:** Always `--device cpu` on Apple Silicon. `--device 0` on EC2 (CUDA). Never `--device mps` on a production training run.
**Warning signs:** Bboxes clustered at the left edge of all images; confidence scores normal but positions wrong.
[VERIFIED: GitHub issue #23140 — "closed as not planned"; last updated January 7, 2026]

### Pitfall 2: val() Crash on Segmentation Base with bbox-only Labels
**What goes wrong:** `ultralytics.YOLO.val()` crashes with `IndexError: index is out of bounds for dimension with size 0` when running a segmentation model against bbox-only labels (no mask files).
**Why it happens:** Segmentation augmentation pipeline expects mask tensors. keremberke model is task=segment; this cannot be overridden at load time.
**How to avoid:** Use detection-only base (`yolov8s.pt`) for Phase 7 training. For re-evaluation of the keremberke baseline (D-10), use the Plan 06-05 manual bypass (`model.predict()` + manual IoU matching).
**Warning signs:** Error traceback from `ultralytics/data/augment.py` line referencing `cls_tensor[masks[0].long() - 1]`.
[VERIFIED: 06-05-SUMMARY.md exact error + root cause documented]

### Pitfall 3: Sequence-Group Contamination at 1500-Image Scale
**What goes wrong:** Adjacent Mapillary frames from the same drive appear in both train and test splits, leaking ground truth. Test metrics are inflated.
**Why it happens:** Naive random split by image ignores that frames from a single drive run are highly correlated.
**How to avoid:** `scripts/fetch_eval_data.py::_build_fresh` already implements sequence_id grouping (seed=42, Pitfall 7 from Phase 2). At 1500 images, the same code works without change — the sequence count will be larger, improving split quality. No code change needed; just pass the Phase 7 bbox set.
**Warning signs:** Test precision ≈ val precision (suspicious identity); or very narrow CI bands inconsistent with the test set size.
[VERIFIED: fetch_eval_data.py code read — sequence grouping at lines 167-183]

### Pitfall 4: Mapillary bbox 500 Error at > 0.01 deg²
**What goes wrong:** Mapillary v4 search returns HTTP 500 for bboxes larger than ~0.01 deg² in dense imagery areas.
**Why it happens:** Underlying Mapillary tile dataset overflows on dense areas (LA has years of coverage). Verified empirically in Phase 6: 0.01-deg bboxes → 500; 0.005-deg bboxes → 200 OK.
**How to avoid:** `data_pipeline/mapillary.py::validate_bbox` enforces ≤ 0.01 deg² guard. Use the established 0.005-deg sub-tile grid for Phase 7 zone expansion (each original zone → 4 × 0.005-deg sub-tiles).
**Warning signs:** HTTP 500 during `fetch_eval_data.py --build`; log line "Mapillary search bbox=... returned 0 images" after retry.
[VERIFIED: fetch_eval_data.py docstring + validate_bbox code]

### Pitfall 5: quality_score as API Filter
**What goes wrong:** D-05 recommended dropping bottom-quartile by Mapillary `quality_score` IF exposed in the v4 API. The field does not exist in the API.
**Why it happens:** quality_score is a Mapillary UI feature but was never exposed as a search filter in v4.
**How to avoid:** Skip the API-based quality filter. Either (a) rely on operator judgment during CVAT labeling to skip blank/blurry images, or (b) implement local blur detection post-download via `cv2.Laplacian(image, cv2.CV_64F).var()` and discard images below a threshold.
**Warning signs:** `AttributeError` or empty response when adding `quality_score` to search_images params.
[VERIFIED: Mapillary API docs — field not in search endpoint; community forum January 2026]

### Pitfall 6: mAP@0.5 Bootstrap via Aggregate val() (New — Phase 7)
**What goes wrong:** Attempting to bootstrap mAP@0.5 by running `val()` 1000 times on different image subsets. Takes 8+ hours.
**Why it happens:** val() performs a full forward pass on all test images each time.
**How to avoid:** Pre-collect per-image `(pred_boxes, gt_boxes)` arrays by running `model.predict()` once on the full test set. Then bootstrap by resampling image indices and recomputing the P-R curve + AUC analytically (no model forward passes). Add `metric="map50"` to `bootstrap_ci` in `data_pipeline/eval.py`.
**Warning signs:** Training completed but bootstrap CI computation is still running after 30+ minutes.

### Pitfall 7: Pickle-ACE on Floating HF Reference
**What goes wrong:** Deploying without `@<sha>` in `_DEFAULT_HF_REPO`. A compromised HF token allows silent replacement of `best.pt` with a malicious payload. Subsequent service restarts load the malicious weights.
**Why it happens:** `huggingface_hub.hf_hub_download` without a `revision` parameter fetches the latest HEAD.
**How to avoid:** Always capture SHA via `HfApi().model_info(repo).sha` immediately after `--push-to-hub` completes. Update `_DEFAULT_HF_REPO` with `@<sha>`.
**Warning signs:** `_DEFAULT_HF_REPO` doesn't contain `@` character in production.
[VERIFIED: detector_factory.py comment block — existing pattern for keremberke pin]

---

## Implementation Approach (Sequencing for Planner)

Phase 7 has a clear dependency graph with one user-gated bottleneck (the hand-labeling step). The planner should structure plans around this.

### Recommended Plan Sequence

**Plan 07-01: Data Acquisition — Expanded bbox fetch**
- Add `start_captured_at` param to `data_pipeline/mapillary.py::search_images()`
- Define 12-15 new zone bboxes (8-10 spread + 1-2 known-bad-pavement + expansions)
- Update `scripts/fetch_eval_data.py::_DEFAULT_LA_BBOXES` with the new zones
- Run `fetch_eval_data.py --build --count 35 --clean` (target ~1500 images)
- Archive Phase 6 dataset as `data/eval_la_phase6/` if zones don't overlap
- **SC covered:** Precondition for SC #1

**Plan 07-02: Pre-labeling + CVAT import**
- Run `scripts/prelabel.py` on the new image set (keremberke model, FP-heavy suggestions OK)
- Export pre-labels in YOLO format, structure into CVAT upload ZIPs
- Set up CVAT tasks (3-4 tasks × ~400 images each)
- **Operator gate: hand-correction in CVAT.** This plan ends with "upload to CVAT and hand-correct; return when ≥150 positive bboxes are labelled across train+val+test."

**Plan 07-03: mAP bootstrap CI extension**
- Add `metric="map50"` support to `data_pipeline/eval.py::bootstrap_ci`
- Unit tests for the new mAP path
- **SC covered:** Enables D-11 "non-overlapping CIs on mAP@0.5" check

**Plan 07-04: Training on EC2 g5.xlarge**
- Launch g5.xlarge, select DLAMI, scp dataset
- Run `finetune_detector.py --base yolov8s.pt --device 0 --epochs 50 --push-to-hub Hratchg/road-quality-la-yolov8`
- Capture SHA: `HfApi().model_info("Hratchg/road-quality-la-yolov8").sha`
- Terminate EC2 instance
- **SC covered:** SC #3 (HF publish)
- **Depends on:** Plan 07-02 (labels complete)

**Plan 07-05: Eval — both baseline re-eval (D-10) and trained model**
- Re-eval keremberke on new test split: Plan 06-05 manual bypass
- Eval trained LA model: `scripts/eval_detector.py` (val()-based, detection model)
- Compute CIs for P, R, mAP@0.5 for both models
- Check D-11 non-overlapping CIs
- If iteration needed (D-13): adjust hyperparams, repeat Plan 07-04
- **SC covered:** SC #1, SC #2
- **Depends on:** Plan 07-04

**Plan 07-06: wipe-mapillary flag + prod re-ingestion**
- Add `wipe_mapillary_rows()` + `--wipe-mapillary` to `scripts/ingest_mapillary.py`
- Update `data_pipeline/detector_factory._DEFAULT_HF_REPO` to trained model + SHA
- Run prod re-ingestion via flyctl proxy: `--wipe-synthetic --wipe-mapillary` + re-ingest training-zone + adjacent bboxes
- Trigger `compute_scores.py --source all`
- Redeploy Fly.io backend to pick up new `_DEFAULT_HF_REPO` constant
- **SC covered:** SC #4, SC #5

**Plan 07-07: Docs update (DETECTOR_EVAL.md + README)**
- DETECTOR_EVAL.md v0.2.0 → v0.3.0: new numbers, "Previous baseline" section, trained-zone coverage caveat (D-16)
- README: replace "public baseline" disclosure with "LA-trained detector" status
- docs/FINETUNE.md: Recipe C update for 1500-image run
- docs/MAPILLARY_INGEST.md: add `--wipe-mapillary` doc
- **SC covered:** SC #6, SC #7

### Dependency Graph

```
07-01 (data fetch) --> [OPERATOR GATE: hand-label] --> 07-04 (training)
                                                           |
07-03 (mAP CI ext) ----+                                   v
                        +--------> 07-05 (eval + CI check)
                                           |
                                   07-06 (prod re-ingest)
                                           |
                                   07-07 (docs)
```

Plans 07-01 and 07-03 can run in parallel. Plan 07-02 (pre-labeling + CVAT setup) runs after 07-01 but before the operator gate. Plan 07-04 cannot start until the operator gate completes.

### Critical Path

The longest sequential dependency chain is:
`07-01 → 07-02 → [OPERATOR GATE: hand-label in CVAT] → 07-04 → 07-05`

The operator hand-labeling gate (1500 images, ~400 per CVAT session) is the phase's longest-duration step. With pre-labeling assist from `prelabel.py`, the operator is correcting suggestions rather than labeling from scratch. Estimated time: 4-8 hours spread across multiple sessions.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (existing; `backend/tests/` + `data_pipeline/tests/`) |
| Config file | None — run via `pytest` from repo root |
| Quick run command | `pytest data_pipeline/tests/ -x -q` |
| Full suite command | `pytest -x -q` (skips DB-dependent tests when DB unreachable) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REQ-trained-la-detector (SC #1) | Dataset has ≥150 positive bboxes; test split has ≥30 | unit | `pytest data_pipeline/tests/test_fetch_eval_data.py -x` — test that `_build_fresh` produces label files and sequence-grouped splits | ✅ existing test file; no new test for positive-count (manual SC gate) |
| REQ-trained-la-detector (SC #2) | Non-overlapping 95% CI on P/R/mAP@0.5 | unit | `pytest data_pipeline/tests/test_eval.py::test_bootstrap_ci_map50 -x` | ❌ Wave 0 gap — `map50` metric not yet in bootstrap_ci |
| REQ-trained-la-detector (SC #3) | Model published to HF at `Hratchg/road-quality-la-yolov8@<sha>` | manual smoke | `python -c "from huggingface_hub import HfApi; info = HfApi().model_info('Hratchg/road-quality-la-yolov8'); print(info.sha)"` | N/A (HF network; not in CI) |
| REQ-trained-la-detector (SC #4) | `_DEFAULT_HF_REPO` updated with trained model + SHA | unit | `pytest backend/tests/test_detector_factory.py::test_default_hf_repo_pin -x` — assert `@` in constant and repo matches `Hratchg/road-quality-la-yolov8` | ❌ Wave 0 gap — test currently checks for keremberke; needs update to trained model check |
| REQ-trained-la-detector (SC #5) | wipe_mapillary_rows() correct SQL; --wipe-mapillary safety latch | unit | `pytest backend/tests/test_ingest_mapillary.py::test_wipe_mapillary_rows -x` | ❌ Wave 0 gap — function does not exist yet |
| REQ-trained-la-detector (SC #6) | DETECTOR_EVAL.md v0.3.0 with numbers | manual gate | `grep "Previous baseline" docs/DETECTOR_EVAL.md && grep "0.3.0" docs/DETECTOR_EVAL.md` | N/A (doc check) |
| REQ-trained-la-detector (SC #7) | README no longer says "public baseline" | manual gate | `grep -v "public baseline" README.md` | N/A (doc check) |

### Sampling Rate

- **Per task commit:** `pytest data_pipeline/tests/ -x -q`
- **Per wave merge:** `pytest -x -q` (full suite)
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `data_pipeline/tests/test_eval.py` — add `test_bootstrap_ci_map50`: verify the `metric="map50"` path in bootstrap_ci returns a (low, point, high) tuple with `0 ≤ low ≤ point ≤ high ≤ 1` for known-good input (covers Plan 07-03)
- [ ] `backend/tests/test_ingest_mapillary.py` — add `test_wipe_mapillary_rows`: mock psycopg2 cursor, verify DELETE SQL uses hard-coded `WHERE source = 'mapillary'`, verify return is rowcount, verify conn.commit() called (covers Plan 07-06)
- [ ] `backend/tests/test_detector_factory.py` — update `test_default_hf_repo_pin` to verify `_DEFAULT_HF_REPO` starts with `Hratchg/road-quality-la-yolov8@` after Phase 7 constant update (covers SC #4)

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| keremberke segmentation base for fine-tuning | Detection-only base (yolov8s.pt) | Phase 7 recommendation | Eliminates val() crash; gives clean mAP@0.5 from val() |
| Phase 6 baseline on 3-positive test set (CIs = [0,1]) | Re-eval baseline on ≥30-positive test set | Phase 7 D-10 | Tighter CIs enable D-11 non-overlapping check |
| No quality filter on Mapillary images (Phase 6) | captured_at >= 2023 filter (quality_score not available via API) | Phase 7 D-05 update | Recency filter only; quality screening deferred to CVAT labeling |
| CVAT-XML export + conversion script (Phase 6) | Native Ultralytics YOLO export from CVAT 2.x | Phase 7 | Eliminates conversion script step |
| keremberke (segmentation, AGPL-3.0, 2023-trained) | Hratchg/road-quality-la-yolov8 (detection, AGPL-3.0, trained on LA) | Phase 7 | "LA-trained" narrative; honest production claim |

**Deprecated/outdated:**
- CVAT-XML → YOLO conversion script from Phase 6 Plan 06-04: Replace with native CVAT Ultralytics YOLO export. Keep the old script in git for reference but do not use for Phase 7 labeling.

---

## Open Questions

1. **Ingest_mapillary.py bbox-mode gap**
   - What we know: `ingest_mapillary.py` is segment-centric (`--segment-ids`, `--where`). Phase 7 prod re-ingestion (D-16) is bbox-driven (training zones + adjacent expansion).
   - What's unclear: Whether to (a) add a `--bbox` mode to `ingest_mapillary.py` that bypasses segment selection and directly searches a bbox, or (b) derive segment IDs within each training bbox via a DB spatial query and pass them to the existing `--where` path.
   - Recommendation: Option (b) is less code — run `SELECT id FROM road_segments WHERE ST_Within(geom, ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326))` and pass the segment IDs. The existing ingest pipeline handles the per-segment bbox search correctly. But at 60-70 sub-tiles × many segments per bbox, the segment list could be large — add a `--where "segment_id IN (SELECT id FROM ...)"` subquery instead. Planner decides.

2. **Phase 6 dataset reuse decision (D-06)**
   - What we know: Phase 6's 158 images came from 3 zones (downtown_*, residential_*, freeway_*). Phase 7 expands to 8-10 new spread zones + 1-2 bad-pavement zones. If the new zones geographically overlap the Phase 6 zones, the old labels can be incorporated.
   - What's unclear: The geographic definition of the 8-10 new zones (not yet specified). Until the operator specifies the Phase 7 bbox list (Plan 07-01), it's unknown whether Phase 6's downtown/residential/Hollywood zones are included or replaced.
   - Recommendation: Plan 07-01's first decision is whether to include Phase 6's 3 zones in the Phase 7 bbox set. If yes, carry forward the 17 existing labels (they'll merge in naturally via `--build` without `--clean`). If no, run `--build --clean` for a fresh start and archive Phase 6 labels as `data/eval_la_phase6/`.

3. **wipe-mapillary + ingest ordering on Fly.io**
   - What we know: Phase 5 Lessons Learned says INSERT traffic via proxy is fine. The wipe (DELETE) + re-ingest (INSERT) sequence is analogous.
   - What's unclear: Whether a DELETE of potentially large mapillary rowsets (Phase 6 ingested data from ~3000 segments across 3 zones) is fast enough to complete cleanly via the proxy without the wireguard timeout triggering.
   - Recommendation: Pre-test with a `--wipe-mapillary --force-wipe --where "1=0"` dry-run that just does the DELETE and reports the row count. If the DELETE completes quickly (< 30s for typical mapillary row counts), proceed. If slow, consider batching the DELETE or using `flyctl ssh console` for the wipe step only (while keeping the INSERT via proxy).

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `yolov8s.pt` COCO-pretrained is the best detection-only base for pothole fine-tuning (vs `yolov8n.pt` or a third-party pothole detection model) | CRQ #2 | Lower training accuracy if a domain-adapted base would have given better transfer; mitigation: small s→n choice is low-risk, first iteration reveals quickly |
| A2 | 1500 images at ~200KB each = ~300MB total (scp feasible without S3) | CRQ #3 | If images are larger (500KB+) scp takes 10-15 min not 5; still feasible, S3 adds no real benefit unless > 10GB |
| A3 | Training time on A10G scales approximately linearly with dataset size relative to T4 benchmarks | CRQ #3 | If augmentation (mosaic) creates many synthetic combinations, effective epoch time grows super-linearly; 30-50 min estimate could be 60-90 min |
| A4 | CVAT cloud free tier supports 1500 images per task | CRQ #5 | If cap is lower, shard into multiple tasks (already recommended approach) |
| A5 | Bootstrap CI on mAP@0.5 via image-level resampling + P-R curve recomputation is "standard" enough for the demo's defensibility claim | CRQ #4 | If reviewers require more rigorous CI methodology (BCa vs percentile), revisit; for demo purposes percentile bootstrap is widely accepted |
| A6 | Phase 6 mapillary rows are present in the Fly.io production DB (Phase 6 Plan 06-03 ran the initial ingestion) | CRQ #6 | If Phase 6 ingestion didn't complete, `--wipe-mapillary` deletes 0 rows and `--force-wipe` is needed |

**Claims that were verified and are NOT assumed:**
- MPS bug #23140 still open/closed-not-planned: VERIFIED
- quality_score not in Mapillary v4 search API: VERIFIED
- captured_at filter uses ISO 8601 start_captured_at parameter: VERIFIED
- wipe_synthetic_rows() exact pattern at line 332: VERIFIED
- val() crash on segmentation model + bbox labels: VERIFIED (Phase 6 SUMMARY)
- Detection-only base eliminates val() crash: VERIFIED (ultralytics docs — task=detect uses bbox pipeline only)

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12+ | finetune_detector.py, eval.py | ✓ | /tmp/rq-venv (Python 3.12) | — |
| ultralytics | Training, eval | ✓ (in rq-venv) | >=8.3.0 (8.4.41 current) | — |
| huggingface_hub | HF push + SHA capture | ✓ | >=0.24 | — |
| MAPILLARY_ACCESS_TOKEN | fetch_eval_data.py --build | ✓ (in .env) | — | — |
| HUGGINGFACE_TOKEN | finetune_detector.py --push-to-hub | ✓ (operator has account) | — | — |
| AWS g5.xlarge (EC2) | Training (D-07) | Operator must launch | CUDA 12.x via DLAMI | Colab T4 (Recipe B; free but session-limited) |
| CVAT cloud | Hand-labeling | ✓ (free tier) | app.cvat.ai | — |
| flyctl proxy | Prod re-ingestion | ✓ | Current Fly CLI | — |

**Missing dependencies with no fallback:**
- None that block execution, but the EC2 launch requires operator AWS account access and key pair.

---

## References

### Primary (HIGH confidence)
- `data_pipeline/eval.py` — bootstrap_ci implementation, match_predictions, iou_xywh [VERIFIED: code read]
- `data_pipeline/detector_factory.py` — _DEFAULT_HF_REPO, _resolve_model_path, HF-vs-local detection [VERIFIED: code read]
- `data_pipeline/mapillary.py` — search_images(), validate_bbox(), MAX_BBOX_AREA_DEG2, existing params dict [VERIFIED: code read]
- `scripts/ingest_mapillary.py:332` — wipe_synthetic_rows() pattern [VERIFIED: code read]
- `scripts/fetch_eval_data.py` — _DEFAULT_LA_BBOXES, _build_fresh, sequence-grouped split [VERIFIED: code read]
- `scripts/finetune_detector.py` — --device 0, --push-to-hub, exit codes [VERIFIED: code read]
- `db/migrations/002_mapillary_provenance.sql` — source CHECK constraint, literal vocabulary [VERIFIED: code read]
- `.planning/phases/06-public-demo-launch/06-05-SUMMARY.md` — val() crash root cause, manual bypass methodology [VERIFIED: file read]
- `.planning/phases/05-cloud-deployment/05-LESSONS-LEARNED.md` — BLOCKING anti-pattern: long DDL via flyctl ssh [VERIFIED: file read]
- `docs/DETECTOR_EVAL.md` — Phase 6 baseline numbers, methodology, version 0.2.0 [VERIFIED: file read]
- `docs/FINETUNE.md` — Recipe C EC2 g5.xlarge instructions [VERIFIED: file read]

### Secondary (MEDIUM confidence)
- Mapillary API documentation: quality_score not in search API; start_captured_at uses ISO 8601; rate limits (10k/min search) [CITED: mapillary.com/developer/api-documentation; verified against code's existing params]
- ultralytics PyPI page — version 8.4.41 current as of research date [CITED: pypi.org/project/ultralytics]
- AWS DLAMI docs — PyTorch 2.5 AMI ships CUDA 12.4; G5 instances use proprietary driver via dynamic loading [CITED: docs.aws.amazon.com/dlami]
- CVAT docs — Ultralytics YOLO format export (no conversion needed); YOLO 1.1 import via Upload annotations [CITED: docs.cvat.ai/docs/dataset_management/formats/format-yolo-ultralytics]
- MDPI 2025 comparison paper — bootstrap CI on mAP@0.5 via 1000 resamples methodology [CITED: mdpi.com/2673-9941/5/1/6]

### Tertiary (LOW confidence — marked ASSUMED in Assumptions Log)
- EC2 A10G training time estimate: derived from FINETUNE.md Recipe B T4 time + AWS "3.3x faster than T4" claim + linear scaling assumption
- CVAT cloud free tier limits for task size: stated general guidance; verify at signup
- Image size estimate (~200KB/image): assumed from JPEG 2048px compression; measure actual from data/eval_la/ to confirm

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries verified in existing codebase + PyPI
- Architecture patterns: HIGH — all patterns derived from verified existing code
- Mapillary API (quality_score): HIGH — confirmed NOT available; captured_at format confirmed
- EC2 training time: LOW — scaled estimate from T4 benchmarks
- mAP bootstrap methodology: MEDIUM — verified approach in literature; implementation gap in eval.py confirmed
- CVAT scale limits: LOW — assumed; verify at signup

**Research date:** 2026-04-28
**Valid until:** 2026-06-01 (stable stack; Mapillary API changes infrequently; ultralytics release cadence is ~monthly)
