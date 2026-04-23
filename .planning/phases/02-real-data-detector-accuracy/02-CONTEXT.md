# Phase 2: Real-Data Detector Accuracy — Context

**Gathered:** 2026-04-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Prove YOLOv8 works on **Los Angeles street-level imagery specifically** with honest, reproducible precision/recall/mAP numbers that the public demo can cite without embarrassment. Phase 2 builds a reproducible eval harness, ships a hand-labelled LA dataset (first of its kind since no public LA pothole dataset exists), fine-tunes the detector on real LA data, publishes metrics with confidence intervals, and wires the detector path to an environment variable.

**In scope:**
- Pull ~300 Mapillary images of LA streets, hand-label potholes
- Fine-tune an existing pothole-focused YOLOv8 model on the LA set
- Build reproducible eval harness (`scripts/eval_detector.py`, `scripts/finetune_detector.py`, `scripts/fetch_eval_data.py`)
- Publish fine-tuned weights to HuggingFace Hub
- Publish eval methodology + numbers in `docs/DETECTOR_EVAL.md`
- Make `model_path` configurable via `YOLO_MODEL_PATH` env var (fixes CONCERNS.md hardcoded-path finding)

**Out of scope (deferred to other phases):**
- Mapillary ingestion pipeline — Phase 3
- Production detector deployment — Phase 5
- Public demo UI wiring — Phase 6
- Paper-grade statistical rigor (multi-dataset cross-validation, baselines, ablations) — explicitly rejected as overkill for MVP

</domain>

<decisions>
## Implementation Decisions

### Eval Dataset — Source & Storage
- **D-01:** Rigor level = **Rigorous LA eval**. ~300+ hand-labelled Mapillary LA images is the target. Goal is LA-specific proof, not global road-damage performance.
- **D-02:** No public pre-labelled LA pothole dataset exists — dataset is **built from scratch in this phase**. Mapillary is the image source.
- **D-03:** If pretrained scores are low on the LA set (< ~50% precision), **fine-tune on the LA training split** rather than publishing weak numbers or tweaking thresholds to hide weakness.
- **D-04:** Dataset storage = **external bucket + `data/eval_la/manifest.json` + `scripts/fetch_eval_data.py`**. Manifest pins SHA256 hashes of each image + label file for integrity. Specific bucket (S3/GCS/Backblaze/HF Datasets) is **Claude's discretion** — pick based on repro friction, not infra preference.
- **D-05:** Label format = **YOLO .txt** (one `.txt` per image, each line `class_id cx cy w h` normalized). Native to YOLOv8, zero conversion. Researcher confirms after surveying dataset tools.

### Metrics & Defensible Bar
- **D-06:** Primary metrics = **Precision + Recall + mAP@0.5 + per-severity breakdown (moderate vs severe)**. These are the ROADMAP SC #1 requirement plus the per-severity breakdown that exercises `yolo_detector.py`'s existing severity-mapping logic.
- **D-07:** IoU threshold = **0.5** (COCO/YOLO standard). Not 0.3 (too lenient, weakens claim), not 0.5:0.95 (rigor overkill for 300 images).
- **D-08:** Statistical rigor = **Bootstrap CIs**, 1000 resamples, 95% interval. Standard for <500-image eval sets. Reported alongside point estimates.
- **D-09:** Train/val/test split = **70/20/10 with held-out test set**. Test set is never used during fine-tuning; all published numbers come from test set only. Val set used for early-stopping / hyperparameter tuning.
- **D-10:** Writeup location = **`docs/DETECTOR_EVAL.md`** (new file). Linked from README. Contains: methodology, dataset description, per-metric tables with CIs, caveats/limitations, reproduction instructions.

### Model Strategy & Asset Storage
- **D-11:** Fine-tune base = **pothole-finetuned YOLOv8 from HuggingFace Hub**. Researcher picks best candidate from HF (Keremberke/yolov8n-pothole-segmentation, arnabdhar variants, or current best). Fallback = generic COCO YOLOv8n if no HF pothole model is current and maintained.
- **D-12:** Model weight storage = **HuggingFace Hub**. Base model loaded by HF name (ultralytics `YOLO()` supports this natively). Fine-tuned weights pushed to a public HF repo (naming = Claude's discretion, e.g., `<user>/road-quality-la-yolov8`). Chosen for zero-extra-steps reproducibility across devices/contributors — no `git lfs install` trap, no fetch-script forgetting.
- **D-13:** Fine-tune upload = **`huggingface-cli upload`** after training completes. HF token read from env (`HUGGINGFACE_TOKEN`). Pushed repo is public unless user later restricts.

### Config Surface & Eval Script Shape
- **D-14:** Env var = **single `YOLO_MODEL_PATH`** holding either an HF model name (e.g., `user/road-quality-la-yolov8`) or a local file path (e.g., `./models/experiment.pt`). Ultralytics' `YOLO()` auto-detects which. Default (if unset) falls back to a versioned HF name hardcoded in `data_pipeline/detector_factory.py`.
- **D-15:** CLI shape = **separate focused scripts** matching the existing `scripts/` convention (seed_data.py / compute_scores.py / ingest_iri.py):
  - `scripts/eval_detector.py` — runs eval, prints metrics, writes JSON report
  - `scripts/finetune_detector.py` — fine-tunes, optionally pushes to HF
  - `scripts/fetch_eval_data.py` — downloads + verifies the LA eval set from the bucket
- **D-16:** Fine-tuning workflow = **multi-env reproduction guide** (Option B). Script stays portable (env-driven, no cloud-specific code). `docs/FINETUNE.md` documents 3 concrete paths: laptop, Colab (with notebook stub), and EC2/SageMaker (with launch commands). `requirements-train.txt` splits heavy training deps from light eval deps. Phase must NOT hardcode a cloud provider.
- **D-17:** Missing-dataset default = **fail loud with fetch hint**. `eval_detector.py` exits 3 with: `Eval set not found at <path>. Run: python scripts/fetch_eval_data.py`. No auto-downloads hidden inside eval. Explicit user action for network ops.
- **D-18:** Exit code discipline: eval exits 0 on success, 2 on metrics below `--min-precision` or `--min-recall` floor (if user sets one), 3 on missing dataset, 1 on any other error.

### Claude's Discretion
- Exact HF pretrained pothole model to start from (researcher picks current best; code must allow swap via config)
- Bucket provider for dataset hosting (S3, GCS, Backblaze, HF Datasets — pick whatever has best repro friction; HF Datasets is recommended if the labelled set is suitable for public citation)
- Exact name of the HF repo for fine-tuned weights
- Labelling tool choice (CVAT, LabelStudio, Roboflow, etc.) — doesn't affect the phase output as long as format matches D-05
- Data-augmentation recipe during fine-tuning (HSV jitter, mosaic, flip, etc.) — YOLOv8 defaults usually fine for 300 images
- Number of fine-tuning epochs + batch size (Claude tunes with val set)
- Whether to report false-positives-per-image as a secondary metric (can add if easy; user didn't require it but didn't reject it)
- Geographic diversity within LA for the image pull (Mapillary bboxes): Claude picks a reasonable spread (downtown, residential, freeway-adjacent) unless planner identifies a reason to constrain

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope + requirements
- `.planning/ROADMAP.md` — Phase 2 section (goal, dependencies, 4 success criteria)
- `.planning/REQUIREMENTS.md` — `REQ-real-data-accuracy` acceptance criteria
- `.planning/codebase/CONCERNS.md` — hardcoded YOLO model path issue (SC #3 fixes this)

### Existing detector code (must understand before touching)
- `data_pipeline/yolo_detector.py` — `YOLOv8Detector` class, `_load_model`, `_map_severity`, `Detection` dataclass, current `model_path` parameter
- `data_pipeline/detector_factory.py` — `get_detector(use_yolo=True, model_path=...)` signature that Phase 2 must preserve
- `data_pipeline/detector.py` — `PotholeDetector` protocol (interface contract)
- `backend/tests/test_yolo_detector.py` — existing test harness (mocks model); plans must extend without breaking

### Existing scripts pattern (follow this style)
- `scripts/seed_data.py` — standalone script pattern
- `scripts/compute_scores.py` — argparse + CLI conventions
- `scripts/ingest_iri.py` — external-source ingestion pattern; `fetch_eval_data.py` should mirror this

### Stack context
- `.planning/codebase/STACK.md` — Python 3.12, ultralytics library, existing deps
- `.planning/codebase/STRUCTURE.md` — `data_pipeline/`, `scripts/`, `docs/`, `backend/tests/` layout

### External docs (researcher should fetch current versions)
- Ultralytics YOLOv8 docs — training API, HF integration, metric computation
- HuggingFace Hub upload docs — `huggingface-cli upload` workflow, auth via `HUGGINGFACE_TOKEN`
- Mapillary API v4 docs — image search by bbox, downloading for offline use (Phase 3 will use the same API — coordinate with that phase's researcher)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `YOLOv8Detector` class (`data_pipeline/yolo_detector.py`): constructor already accepts `model_path`; Phase 2 changes the DEFAULT to read from env, not the constructor signature
- `PotholeDetector` protocol (`data_pipeline/detector.py`): the interface Phase 2 must not break — keep `detect(image_path) -> list[Detection]` stable
- `_map_severity()` (`data_pipeline/yolo_detector.py:129`): existing class-name → severity mapping. Eval's per-severity breakdown uses this same function so eval metrics match runtime behavior
- `Detection` dataclass: `severity`, `confidence`, `bbox` fields — eval's ground-truth format should match this so comparisons are apples-to-apples
- `backend/tests/test_yolo_detector.py`: existing test pattern — Phase 2 may add integration tests here (optional) but must not break current unit tests

### Established Patterns
- **Scripts are flat, argparse-based, standalone.** No framework. Each script handles its own argparse, logging setup, and exit codes. Follow this.
- **Env vars read at module top.** Existing `backend/app/db.py` reads `DATABASE_URL` at import. Eval scripts should do the same for `YOLO_MODEL_PATH`, `HUGGINGFACE_TOKEN`.
- **Docs in `docs/`.** `docs/PRD.md`, `docs/SETUP.md` pattern. `docs/DETECTOR_EVAL.md` and `docs/FINETUNE.md` fit naturally here.
- **Tests live under the module they test.** `backend/tests/` for backend, if Phase 2 adds training-related tests they go under `data_pipeline/tests/` (new dir) or as pytest tests in `backend/tests/` — planner to decide based on dependency weight.
- **`.env.example` is authoritative for env vars** (from Phase 1). Phase 2 MUST append `YOLO_MODEL_PATH` and `HUGGINGFACE_TOKEN` to `.env.example`.

### Integration Points
- `data_pipeline/detector_factory.py::get_detector()` — single injection point for the real model; Phase 2 updates the default resolution logic here
- `scripts/` dir — Phase 2 adds 3 new scripts alongside existing ones
- `docs/` dir — Phase 2 adds 2 new docs (DETECTOR_EVAL.md, FINETUNE.md)
- `.env.example` — Phase 2 appends 2 new vars
- `README.md` — links to DETECTOR_EVAL.md added under a "Detector" section; cite the headline numbers
- `requirements.txt` / `requirements-train.txt` split — new file introduced

### Cross-phase coordination
- **Phase 3 (Mapillary ingestion pipeline)** uses the same Mapillary API Phase 2 uses for image pull. Phase 2's `fetch_eval_data.py` and Phase 3's `ingest_mapillary.py` should share a Mapillary client module (`data_pipeline/mapillary.py` or similar) — flag this to Phase 3's researcher.
- **Phase 6 (Public demo)** cites the numbers from `docs/DETECTOR_EVAL.md`. Writeup needs a stable shortlink/anchor.

</code_context>

<specifics>
## Specific Ideas

- "The whole goal is to show that it works on streets in Los Angeles" — literal LA-specific proof is non-negotiable; global-dataset-only eval would miss the point
- User asked about cloud-based fine-tuning explicitly — hence D-16 builds in multi-env reproduction guide rather than assuming local-only
- User is thinking about reproducibility on other people's devices — hence HF Hub for weights (D-12) and external bucket + fetch script for data (D-04), both chosen over Git LFS for the zero-extra-steps property
- The ROADMAP requires "honest enough to cite in the public demo" — this became the phrase behind all metric/rigor decisions. Publish weak numbers honestly rather than tune thresholds to look strong

</specifics>

<deferred>
## Deferred Ideas

- **Paper-grade eval** (multi-dataset cross-validation, confidence calibration curves, ablations) — explicitly rejected as overkill for MVP. Would justify its own research phase if this project ever aims for publication.
- **AWS-specific Terraform/SageMaker infra** — considered, rejected. Cost and complexity not justified for a 300-image one-off fine-tune.
- **Generalization comparison against RDD2020** — could be a nice footnote in `DETECTOR_EVAL.md` if easy, but not required. Claude's discretion.
- **Labelling UI / labelling pipeline tooling** — out of scope. User hand-labels with an existing tool (CVAT/LabelStudio/Roboflow); plan doesn't build tooling.
- **Continuous eval / CI gate on detector accuracy** — future phase. For now, eval is run manually when fine-tune is updated.
- **Confidence calibration / temperature scaling** — out of scope for Phase 2; consider if production deploy (Phase 5) reveals FP issues.

</deferred>

---

*Phase: 02-real-data-detector-accuracy*
*Context gathered: 2026-04-23*
