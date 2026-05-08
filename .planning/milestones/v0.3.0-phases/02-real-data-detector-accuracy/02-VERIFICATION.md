---
phase: 02-real-data-detector-accuracy
verified: 2026-04-23T00:00:00Z
status: human_needed
score: 4/4 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Run scripts/fetch_eval_data.py --build with a real MAPILLARY_ACCESS_TOKEN, hand-label the ~300 Mapillary LA images, then run scripts/finetune_detector.py on the train split"
    expected: "End-to-end dataset build + fine-tune succeeds; runs/detect/la_pothole/weights/best.pt is produced"
    why_human: "Requires a free Mapillary developer token, 300-image hand-labelling with CVAT, and hours of training compute — explicitly factored as a post-merge operator task by CONTEXT.md and every plan SUMMARY. Tooling is verified; end-to-end execution is not."
  - test: "Run scripts/eval_detector.py --data data/eval_la/data.yaml --split test --json-out eval_report.json against a real fine-tuned model"
    expected: "eval_report.json is produced with real precision/recall/mAP@0.5 numbers + image-level bootstrap 95% CIs; per-severity counts populated"
    why_human: "Requires ultralytics + torch installed (requirements-train.txt, ~2.5GB) AND a populated data/eval_la/ AND a fine-tuned .pt. All tests mock ultralytics; the production eval path is exercised only in manual operator runs."
  - test: "Substitute the TBD placeholders in docs/DETECTOR_EVAL.md Sections TL;DR and 2 (Results) with the real numbers from eval_report.json, then bump version to v0.2.0 and update Changelog"
    expected: "Writeup cites honest numbers (not TBD) before the public demo (Phase 6) links to it"
    why_human: "Manual doc substitution per operator runbook documented in 02-05-SUMMARY.md. SC #4 reads 'honest enough to cite in the public demo' — TBD placeholders are honest about methodology + deferred numbers, but Phase 6 will need real numbers before public launch."
  - test: "Update _DEFAULT_HF_REPO in data_pipeline/detector_factory.py to point at the published fine-tune with a pinned @<commit_sha> revision (Pitfall 8 discipline)"
    expected: "The default HF repo tracks the actually-shipped weights, pinned to a commit so silent swaps cannot happen"
    why_human: "Follow-up commit after the operator publishes the first fine-tune to HF via scripts/finetune_detector.py --push-to-hub. Security-review action, not a Phase 2 deliverable."
---

# Phase 2: Real-Data Detector Accuracy Verification Report

**Phase Goal:** Prove the YOLOv8 detector is usable against real LA street-level imagery, with honest precision/recall numbers — so the demo has something defensible to claim.
**Verified:** 2026-04-23T00:00:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth (SC) | Status | Evidence |
|---|-----------|--------|----------|
| 1 | A reproducible eval script (`scripts/eval_detector.py`) runs the detector on a labelled eval set and prints precision, recall, and per-severity counts | VERIFIED | `scripts/eval_detector.py` exists (325 lines); `--help` lists all 10 flags (`--data`, `--split`, `--iou`, `--bootstrap-resamples`, `--ci-level`, `--min-precision`, `--min-recall`, `--json-out`, `--model`, `-v`); `_print_human_summary` prints precision/recall with 95% CIs, mAP@0.5, and per-severity buckets (moderate/severe/dropped); JSON report schema produced by `--json-out`. Helper module `data_pipeline/eval.py` exports `bootstrap_ci`, `per_severity_breakdown`, `match_predictions`, `iou_xywh`, `map_severity`. 23 tests in `test_eval_detector.py` pass. |
| 2 | `get_detector(use_yolo=True, model_path=...)` loads a real (pretrained or fine-tuned) model from a configurable path, not a hardcoded one | VERIFIED | `data_pipeline/detector_factory.py::get_detector` signature preserved as `(use_yolo=False, model_path=None)` (AST-verified). Precedence: explicit `model_path` arg > `YOLO_MODEL_PATH` env var > `_DEFAULT_HF_REPO = "keremberke/yolov8s-pothole-segmentation"`. `_resolve_model_path()` handles HF repo ids (`user/repo`, `user/repo:file.pt`, `user/repo@revision`) via `hf_hub_download` AND local paths (`./`, `/`, `../`). 14 factory tests (11 in `test_detector_factory.py` + 3 in `test_yolo_detector.py`) pass. |
| 3 | The model path resolves from an environment variable (not CWD-relative), fixing the concerns from `.planning/codebase/CONCERNS.md` | VERIFIED | `YOLO_MODEL_PATH_ENV = os.environ.get("YOLO_MODEL_PATH")` read at module top (line 49 of `detector_factory.py`, matches `backend/app/db.py` convention). `.env.example` documents `YOLO_MODEL_PATH=` and `HUGGINGFACE_TOKEN=` placeholders. No CWD-relative hardcoded default anywhere — `_DEFAULT_HF_REPO` is an HF repo id, not a filesystem path. `test_env_var_path_resolution` + `TestGetDetectorEnvVar.test_env_var_is_used_when_model_path_arg_none` confirm env-var consumption. |
| 4 | A short writeup in `docs/` records the eval methodology and current numbers, honest enough to cite in the public demo | VERIFIED (with TBD placeholders) | `docs/DETECTOR_EVAL.md` exists (291 lines) with 7 numbered sections + TL;DR: Methodology (fixed), Results (TBD cells clearly labelled), Caveats (7 bullets incl. per-image CI degeneracy), Reproduction (all 3 CLIs + docs/FINETUNE.md link), Security (pickle ACE + token handling + SHA256), Licensing (5-row CC-BY-SA + AGPL chain table), Changelog. 14 TBD placeholders are methodology-honest (explicitly labelled "Populated from eval_report.json after re-training"). README.md has "## Detector Accuracy" section linking to DETECTOR_EVAL.md + FINETUNE.md. |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `data_pipeline/detector_factory.py` | env-driven HF-vs-local resolution via `_resolve_model_path()` | VERIFIED | Contains `_DEFAULT_HF_REPO`, `_HF_REPO_PATTERN`, `YOLO_MODEL_PATH_ENV`, `_resolve_model_path`, `get_detector`. Public signature preserved. |
| `data_pipeline/eval.py` | Pure math helpers | VERIFIED | 198 lines, 5 public functions (`bootstrap_ci`, `per_severity_breakdown`, `match_predictions`, `iou_xywh`, `map_severity`) + `DEFAULT_SEED=42`. Zero ultralytics/cv2/torch imports. |
| `data_pipeline/mapillary.py` | Mapillary API v4 client | VERIFIED | Shared client for Phase 2 + Phase 3; 5 public functions; constant-time SHA256 compare (`hmac.compare_digest`); `MAX_BBOX_AREA_DEG2 = 0.01` DoS guard. |
| `data_pipeline/requirements.txt` | huggingface_hub + scipy deps | VERIFIED | Lists `ultralytics>=8.1`, `opencv-python-headless>=4.8`, `huggingface_hub>=0.24,<1.0`, `scipy>=1.13`. |
| `scripts/eval_detector.py` | CLI with argparse, D-18 exit codes, JSON report | VERIFIED | 325 lines. All 10 flags present in `--help`. Exit codes 0/1/2/3 wired. Verified: missing `--data` path → exit 3 with fetch hint. |
| `scripts/fetch_eval_data.py` | `--verify-only` default + `--build` modes | VERIFIED | 332 lines. All 8 flags in `--help`. Verified: missing manifest → exit 3 with `--build` hint. |
| `scripts/finetune_detector.py` | CLI wrapping YOLO.train() + HF upload | VERIFIED | 354 lines. 11 flags in `--help` incl. `--push-to-hub`. Default `SEED=42`, default device `cpu` (Pitfall 1). Verified: `--push-to-hub` without `HUGGINGFACE_TOKEN` → exit 1 with actionable error. |
| `requirements-train.txt` | torch>=2.4.1 excluding 2.4.0 | VERIFIED | Contains `-r data_pipeline/requirements.txt`, `torch>=2.4.1,<2.10`, `torchvision>=0.19,<0.25`, `pyyaml>=6.0`. Comment calls out Pitfall 2. |
| `docs/DETECTOR_EVAL.md` | Methodology + numbers + caveats + repro + security + licensing | VERIFIED (placeholders acceptable) | 291 lines, all 7 sections present, CC-BY-SA + AGPL tabled, pickle ACE documented, 5 CLI invocations present, FINETUNE.md cross-linked. TBD cells in Results clearly labelled as post-op substitution. |
| `docs/FINETUNE.md` | Laptop/Colab/EC2 recipes | VERIFIED | 208 lines, all 3 Recipe sections (A/B/C), Apple Silicon MPS caveat, troubleshooting, `scripts/finetune_detector.py` invocations. |
| `README.md` | "## Detector Accuracy" section linking to writeup | VERIFIED | Section placed between `## API Endpoints` and `## Frontend Pages`; Documentation section gains 2 new bullets (DETECTOR_EVAL.md + FINETUNE.md); YOLO_MODEL_PATH configuration pointer. |
| `data/eval_la/data.yaml` | Single-class YOLO schema (nc=1, names[0]=pothole) | VERIFIED | 21 lines. `nc: 1`, `names: {0: pothole}`, train/val/test paths. NOT gitignored (confirmed via `git check-ignore` exit=1). |
| `data/eval_la/manifest.json` | Committed skeleton version 1.0 with empty files | VERIFIED | `{"version": "1.0", "source_bucket": "placeholder...", "license": "CC-BY-SA 4.0...", "files": []}`. |
| `.env.example` | YOLO_MODEL_PATH + HUGGINGFACE_TOKEN + MAPILLARY_ACCESS_TOKEN | VERIFIED | All three entries present with empty defaults and Phase 1-style section headers. CC-BY-SA 4.0 comment on Mapillary section. |
| `.gitignore` | exclude data/eval_la/* but keep manifest.json + data.yaml + .gitkeep | VERIFIED | `data/eval_la/*` exclusion with `!` un-ignore rules for all three tracked files. |
| `backend/tests/fixtures/eval_fixtures/` | 3 tiny JPEGs + labels + data.yaml | VERIFIED | All fixtures committed; data.yaml, 3 images, 3 label files. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `detector_factory.py::get_detector` | `_resolve_model_path` | internal call | WIRED | Line 120 of detector_factory.py: `resolved = _resolve_model_path(explicit_value)`. |
| `detector_factory.py::_resolve_model_path` | `huggingface_hub.hf_hub_download` | lazy import | WIRED | Line 78: `from huggingface_hub import hf_hub_download` then `hf_hub_download(**kwargs)` at line 83. |
| `scripts/eval_detector.py` | `data_pipeline.eval.bootstrap_ci` | import + call | WIRED | Line 48: `from data_pipeline.eval import bootstrap_ci, per_severity_breakdown`; called at lines 239, 245, 271. |
| `scripts/eval_detector.py` | `data_pipeline.detector_factory._resolve_model_path` | import + call | WIRED | Line 215: `from data_pipeline.detector_factory import _resolve_model_path`; called at line 227. |
| `data_pipeline/eval.py::per_severity_breakdown` | `yolo_detector.py::_map_severity` | mirrors rules exactly | WIRED | Thresholds `confidence >= 0.7` and `confidence >= 0.4` present in both; parity test `TestMapSeverityMirrorsRuntime` (6 tests) confirms behavior mirrored. |
| `scripts/fetch_eval_data.py` | `data_pipeline.mapillary.search_images` / `verify_manifest` | import + call | WIRED | Line 66-74: `from data_pipeline.mapillary import ...`; used in `_build_fresh` and `_verify`. |
| `scripts/finetune_detector.py` | `ultralytics.YOLO.train` | lazy import | WIRED | Line 150 inside `_run_training`: `from ultralytics import YOLO`; `model.train(...)` call at line 167. |
| `scripts/finetune_detector.py` | `huggingface_hub.HfApi.upload_file` | `--push-to-hub` branch | WIRED | Line 213: `from huggingface_hub import HfApi, create_repo`; `api.upload_file(...)` at line 224 with `path_in_repo="best.pt"`. |
| `docs/DETECTOR_EVAL.md` | `scripts/eval_detector.py` | reproduction one-liner | WIRED | 5 grep matches for `python scripts/eval_detector.py` / `python scripts/fetch_eval_data.py` / `python scripts/finetune_detector.py`. |
| `docs/DETECTOR_EVAL.md` | `docs/FINETUNE.md` | markdown cross-ref | WIRED | Section 4 (Reproduction) and TL;DR both link to FINETUNE.md. |
| `README.md` | `docs/DETECTOR_EVAL.md` | markdown link in new section | WIRED | 2 occurrences (one in "## Detector Accuracy" section, one in Documentation list). |

### Data-Flow Trace (Level 4)

Not applicable at Phase 2 — no dynamic rendering artifacts (no UI, no API-to-DB chain added by this phase). All artifacts are CLIs, libraries, config, and docs. The `--json-out eval_report.json` data flow is verified structurally (schema stable, helper functions produce real metrics) but end-to-end execution requires ultralytics + a real model (human verification item).

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| bootstrap_ci deterministic with seed=42 | `python -c "from data_pipeline.eval import bootstrap_ci; c=[{'tp':3,'fp':1,'fn':1}]*20; r1=bootstrap_ci(c,'precision',n_resamples=500,seed=42); r2=bootstrap_ci(c,'precision',n_resamples=500,seed=42); assert r1==r2"` | Deterministic | PASS |
| map_severity mirrors yolo_detector runtime thresholds | `python -c "from data_pipeline.eval import map_severity; assert map_severity('pothole',0.75)=='severe'; assert map_severity('pothole',0.5)=='moderate'; assert map_severity('pothole',0.3) is None"` | All three bucket cases pass | PASS |
| get_detector factory fallback works | `python -c "from data_pipeline.detector_factory import get_detector; d=get_detector(use_yolo=False); assert type(d).__name__=='StubDetector'"` | Returns StubDetector | PASS |
| eval_detector.py --help lists all required flags | `python scripts/eval_detector.py --help` | 10 flags: --data, --split, --iou, --bootstrap-resamples, --ci-level, --min-precision, --min-recall, --json-out, --model, -v | PASS |
| eval_detector.py missing data → exit 3 with fetch hint | `python scripts/eval_detector.py --data /nonexistent/path.yaml` | exit=3; stderr contains "Run: python scripts/fetch_eval_data.py" | PASS |
| fetch_eval_data.py missing manifest → exit 3 with --build hint | `python scripts/fetch_eval_data.py --manifest /nonexistent.json --root /tmp/nope` | exit=3; stderr contains "Run: python scripts/fetch_eval_data.py --build" | PASS |
| finetune_detector.py --push-to-hub without HUGGINGFACE_TOKEN → fail-fast exit 1 | `HUGGINGFACE_TOKEN= python scripts/finetune_detector.py --data <fixture> --push-to-hub user/test` | exit=1; stderr contains "HUGGINGFACE_TOKEN env var" + "write scope" | PASS |
| data/eval_la/data.yaml parses + tracked | `python -c "import yaml; d=yaml.safe_load(open('data/eval_la/data.yaml')); assert d['nc']==1 and d['names'][0]=='pothole'"` + `git check-ignore` | Schema OK; NOT ignored | PASS |
| Phase 2 test suite | `/tmp/rq-venv/bin/pytest backend/tests/test_detector_factory.py test_eval_detector.py test_fetch_eval_data.py test_finetune_detector.py test_mapillary.py test_yolo_detector.py -q` | 80 passed in 0.63s | PASS |

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|---------------|-------------|--------|----------|
| REQ-real-data-accuracy | 02-01, 02-02, 02-03, 02-04, 02-05 (all 5 plans) | `YOLOv8Detector` runs end-to-end on a curated set of real LA street-level images with reported precision/recall on a labelled eval set. Acceptance: reproducible eval script, non-synthetic model wired via configurable path, metrics documented in docs/ | SATISFIED (tooling) / NEEDS HUMAN (numbers) | All 4 SCs VERIFIED at tooling level (eval script reproducible, `get_detector` configurable via env, eval doc exists with methodology + reproduction). Actual 300-image hand-labelling + fine-tune + number substitution is the operator runbook documented in 02-05-SUMMARY.md (post-merge activity, explicitly factored that way in CONTEXT.md + every plan SUMMARY). |

No orphaned requirements. REQUIREMENTS.md maps REQ-real-data-accuracy to Phase 2 only; all 5 plans in Phase 2 declare `requirements: [REQ-real-data-accuracy]`.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| data_pipeline/detector_factory.py | 36 | `pass` inside `if TYPE_CHECKING:` block | Info | Normal Python idiom (typing-only import placeholder). Not a stub. |
| docs/DETECTOR_EVAL.md | multiple | 14 "TBD" placeholder strings in Results tables | Info | Intentional, methodology-honest design: cells explicitly labelled "Populated from eval_report.json after re-training". Matches operator note in task prompt ("TBD placeholders are acceptable if the structure is honest"). |

No Blocker or Warning anti-patterns. No dead code, no empty implementations, no console.log-only handlers, no hardcoded empty data that flows to user-visible output. Review findings in 02-REVIEW.md (0 Critical, 6 Warning, 5 Info) are advisory — none block goal achievement:

- WR-01/02/03/04/05/06 are edge-case latent bugs in code paths that execute only in real `--build` / training flows (not in the CI-tested paths). They are listed in 02-REVIEW.md for operator attention; the structural code paths this phase delivers all work as specified.
- IN-01 through IN-05 are polish items.

### Human Verification Required

Detector accuracy is an inherently operator-run system: the full pipeline requires Mapillary API access, hours of human labelling, and training compute. Phase 2 delivers **reproducible tooling** and **a citation-target writeup with placeholder numbers**. The following items are explicitly deferred to the post-merge operator runbook (per CONTEXT.md `deferred_ideas` + 02-05-SUMMARY.md "Operator Runbook"):

### 1. End-to-End Dataset Build + Fine-Tune

**Test:** Run `scripts/fetch_eval_data.py --build` with a real `MAPILLARY_ACCESS_TOKEN`, hand-label the ~300 Mapillary LA images (CVAT recommended), then run `scripts/finetune_detector.py` on the train split.
**Expected:** `runs/detect/la_pothole/weights/best.pt` is produced; no errors in search → download → label → train pipeline.
**Why human:** Requires a free Mapillary developer token, ~300-image hand-labelling (multi-hour operator effort), and training compute (4-6 hours CPU or ~15 min Colab T4). Explicitly factored as a post-merge operator task.

### 2. Real Eval Run

**Test:** Run `YOLO_MODEL_PATH=runs/detect/la_pothole/weights/best.pt python scripts/eval_detector.py --data data/eval_la/data.yaml --split test --json-out eval_report.json` against the fine-tuned model.
**Expected:** `eval_report.json` is produced with real precision/recall/mAP@0.5 + image-level bootstrap 95% CIs; per-severity counts populated.
**Why human:** Requires `pip install -r requirements-train.txt` (~2.5 GB torch) AND a populated `data/eval_la/` AND a fine-tuned `.pt`. All phase-2 tests mock ultralytics; the live eval path is only exercised by the operator.

### 3. Writeup Number Substitution

**Test:** Substitute TBD placeholders in `docs/DETECTOR_EVAL.md` Sections TL;DR and 2 (Results) with the real numbers from `eval_report.json`; bump version to v0.2.0; add Changelog entry.
**Expected:** Writeup cites honest numbers (not TBD) before Phase 6 links to it.
**Why human:** Manual doc substitution per operator runbook in 02-05-SUMMARY.md. SC #4 says "honest enough to cite in the public demo" — TBD placeholders are honest about methodology + deferred numbers (structure satisfies SC #4), but Phase 6 will need real numbers before public launch.

### 4. Production Pin (`@<revision>`)

**Test:** Update `_DEFAULT_HF_REPO` in `data_pipeline/detector_factory.py` to point at the published fine-tune with a pinned `@<commit_sha>` revision (Pitfall 8 discipline).
**Expected:** The default HF repo tracks the actually-shipped weights, pinned to a commit so silent swaps cannot happen.
**Why human:** Follow-up commit after the operator publishes the first fine-tune to HF via `scripts/finetune_detector.py --push-to-hub`. Security-review action, not a Phase 2 code deliverable.

### Gaps Summary

**No gaps.** All four ROADMAP Success Criteria are verified at the tooling and methodology level. The phase goal — "Prove the YOLOv8 detector is usable against real LA street-level imagery, with honest precision/recall numbers — so the demo has something defensible to claim" — is achieved in the structural sense that:

- The detector CAN now be loaded from a configurable real path (env var + HF repo resolution) — **defensible**
- The eval harness CAN produce reproducible precision/recall/CIs from a labelled set — **defensible**
- The methodology IS documented honestly (including TBD labels where numbers are pending) — **cite-able**
- The reproduction path IS documented end-to-end in FINETUNE.md + DETECTOR_EVAL.md — **reproducible**

Actual LA number substitution is an operator runbook item, deliberately factored as post-merge per CONTEXT.md: "Plan 03 delivers *tooling*, not dataset content" + Plan 04's `user_setup` block + Plan 05's explicit TBD design. This is goal achievement by structure + methodology fixity; number generation is the next operator loop.

Status is `human_needed` (not `passed`) because items 1-4 above require human execution before Phase 6 (public demo) can link to populated numbers. No blocking gaps were identified; all structural must-haves pass.

---

_Verified: 2026-04-23T00:00:00Z_
_Verifier: Claude (gsd-verifier)_
