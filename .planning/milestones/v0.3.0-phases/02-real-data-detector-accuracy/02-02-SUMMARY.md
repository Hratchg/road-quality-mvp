---
phase: 02-real-data-detector-accuracy
plan: 02
subsystem: ml
tags: [python, ml, eval, metrics, testing, bootstrap, argparse, cli]

# Dependency graph
requires:
  - phase: 02-real-data-detector-accuracy (Plan 01)
    provides: "_resolve_model_path() + YOLO_MODEL_PATH env surface in data_pipeline.detector_factory; huggingface_hub + scipy runtime deps"
provides:
  - "scripts/eval_detector.py CLI (D-18 exit codes 0/1/2/3, 10 argparse flags, JSON report schema)"
  - "data_pipeline/eval.py pure helpers: bootstrap_ci (image-level, seed=42 deterministic per D-08), per_severity_breakdown (mirrors YOLOv8Detector._map_severity per D-06), match_predictions (IoU 0.5 greedy per D-07), iou_xywh, map_severity, DEFAULT_SEED"
  - "backend/tests/fixtures/eval_fixtures/ — 3 tiny JPEGs + YOLO label files + data.yaml for unit and subprocess smoke tests (reusable by Plans 03–05)"
  - "JSON report schema (model_path, split, precision, recall, map50, precision_ci_95, recall_ci_95, per_severity{moderate,severe,dropped}.count, eval_config{iou,bootstrap_resamples,ci_level,num_images}) — consumed by Plan 05 docs/DETECTOR_EVAL.md"
affects: [02-03-la-dataset, 02-04-finetune, 02-05-publish-writeup, 05-production-readiness, 06-public-demo]

# Tech tracking
tech-stack:
  added: []  # Runtime deps (numpy, scipy) were already declared in Plan 01
  patterns:
    - "Pure-function math module (data_pipeline/eval.py) with no ultralytics/cv2/torch imports — callable from unit tests without the heavy stack"
    - "CLI exit-code discipline: constants at module top (EXIT_OK/EXIT_OTHER/EXIT_BELOW_FLOOR/EXIT_MISSING_DATA) mapped to D-18 contract"
    - "Subprocess-smoke tests via subprocess.run(cwd=REPO_ROOT) for CLI exit codes — no ultralytics import at test time"
    - "Committed YOLO fixture tree under backend/tests/fixtures/eval_fixtures/ — tiny PIL-generated JPEGs + normalized-bbox label files + data.yaml that reuses splits so ultralytics does not complain about missing splits"
    - "Image-level bootstrap resampling with numpy default_rng(seed) — deterministic across reruns"

key-files:
  created:
    - data_pipeline/eval.py
    - scripts/eval_detector.py
    - backend/tests/test_eval_detector.py
    - backend/tests/fixtures/eval_fixtures/data.yaml
    - backend/tests/fixtures/eval_fixtures/images/test/img_001.jpg
    - backend/tests/fixtures/eval_fixtures/images/test/img_002.jpg
    - backend/tests/fixtures/eval_fixtures/images/test/img_003.jpg
    - backend/tests/fixtures/eval_fixtures/labels/test/img_001.txt
    - backend/tests/fixtures/eval_fixtures/labels/test/img_002.txt
    - backend/tests/fixtures/eval_fixtures/labels/test/img_003.txt
  modified: []

key-decisions:
  - "eval.py re-declares severity class sets rather than importing yolo_detector.py — eval-only code paths stay pure (no ultralytics/cv2/torch). Paired with a TestMapSeverityMirrorsRuntime suite to catch drift (D-06)."
  - "_collect_per_image_counts falls back to a single aggregated bucket when ultralytics' results.stats does not expose per-image arrays — bootstrap still runs; CI will be near-degenerate in that path and docs/DETECTOR_EVAL.md (Plan 05) will call out the caveat."
  - "JSON report splits precision_ci_95 and recall_ci_95 as 3-tuples (low, point, high) so downstream consumers never have to rerun bootstrap — only read the pre-computed CI."
  - "Per-severity breakdown runs over a single detection bucket because the severity rule is per-detection, not per-image. Keeps the code simple and matches runtime behavior."

patterns-established:
  - "Pure-math eval module: data_pipeline/eval.py imports only numpy + stdlib; no network, no I/O. Callable from unit tests without mocking."
  - "YOLO fixture tree: tiny PIL-generated JPEGs (~690 bytes each) + normalized-bbox .txt labels + data.yaml. Reusable for any test that needs an 'ultralytics-looking' directory structure."
  - "Subprocess CLI smoke tests: capture stdout/stderr/returncode via subprocess.run(cwd=REPO_ROOT). Asserts exit codes + literal hint strings without importing the CLI module."

requirements-completed: [REQ-real-data-accuracy]

# Metrics
duration: ~5min
completed: 2026-04-24
---

# Phase 2 Plan 02: Detector Eval Harness Summary

**Deterministic, pure-Python eval harness with seed=42 bootstrap CIs, D-18 exit-code discipline, per-severity breakdown mirroring YOLOv8Detector runtime rules, and a tiny committed YOLO fixture tree for unit + subprocess-smoke tests.**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-04-24T02:17:38Z
- **Completed:** 2026-04-24T02:22:13Z
- **Tasks:** 3
- **Files created:** 10 (1 Python module, 1 CLI script, 1 test file, 1 data.yaml, 3 JPEG fixtures, 3 label files)
- **Files modified:** 0

## Accomplishments

- `scripts/eval_detector.py` CLI accepts all 10 required flags (`--data`, `--split`, `--iou`, `--bootstrap-resamples`, `--ci-level`, `--min-precision`, `--min-recall`, `--json-out`, `--model`, `--verbose`); exit codes map 1:1 to D-18 (0=OK, 1=other, 2=below floor, 3=missing dataset). Missing `data.yaml` emits the literal `Run: python scripts/fetch_eval_data.py` hint to stderr before exiting 3 (D-17).
- `data_pipeline/eval.py` delivers 5 pure helpers (`bootstrap_ci`, `per_severity_breakdown`, `match_predictions`, `iou_xywh`, `map_severity`) + `DEFAULT_SEED = 42`. Severity thresholds (0.7 → severe, 0.4 → moderate, below → dropped) are re-declared here to avoid pulling in ultralytics on eval-only paths and are covered by a parity test suite.
- `backend/tests/fixtures/eval_fixtures/` ships 3 tiny (~690 bytes each, ~2.5 KB total apparent) PIL-generated JPEGs, 3 YOLO label files (one intentionally empty as a negative example), and a `data.yaml` that reuses `images/test` for all splits so ultralytics does not complain about missing splits.
- 23 new unit + subprocess-smoke tests green in ~0.13s. Adjacent 21 tests in `test_detector_factory.py` + `test_yolo_detector.py` remain green (44 total in that suite).
- JSON report schema finalized: `{model_path, split, precision, recall, map50, precision_ci_95: [low,point,high], recall_ci_95: [low,point,high], per_severity: {moderate,severe,dropped}.{count}, eval_config: {iou, bootstrap_resamples, ci_level, num_images}}` — consumed by Plan 05.

## Task Commits

Each task was committed atomically:

1. **Task 1: Author `data_pipeline/eval.py` + eval fixture tree** — `f77364e` (feat)
2. **Task 2: Author `scripts/eval_detector.py` CLI with D-18 exit codes** — `d205f39` (feat)
3. **Task 3: Author `backend/tests/test_eval_detector.py`** — `7aeec27` (test)

## Files Created/Modified

### Created

- `data_pipeline/eval.py` (193 lines) — pure-function math module:
  - `map_severity(class_name, confidence) -> "severe"|"moderate"|None` (mirrors `YOLOv8Detector._map_severity`)
  - `iou_xywh(a, b) -> float` (IoU on normalized cx/cy/w/h boxes)
  - `match_predictions(gt_boxes, pred_boxes, iou_threshold=0.5) -> {"tp","fp","fn"}` (greedy, highest-confidence-first, D-07)
  - `bootstrap_ci(per_image_counts, metric, n_resamples=1000, ci_level=0.95, seed=42) -> (low, point, high)` (D-08 image-level resampling; `(nan, 0.0, nan)` on degenerate zero input)
  - `per_severity_breakdown(per_image_detections) -> {moderate,severe,dropped}.{count}`
  - Constants: `_SEVERE_CLASSES`, `_MODERATE_CLASSES`, `_GENERIC_CLASSES` (declared here to break the ultralytics import chain), `DEFAULT_SEED = 42`
- `scripts/eval_detector.py` (324 lines) — argparse CLI:
  - `EXIT_OK=0`, `EXIT_OTHER=1`, `EXIT_BELOW_FLOOR=2`, `EXIT_MISSING_DATA=3` (D-18)
  - Reads `YOLO_MODEL_PATH` at module top (matches `backend/app/db.py` convention); per-call precedence `--model > YOLO_MODEL_PATH > _DEFAULT_HF_REPO` (delegated to Plan 01's `_resolve_model_path`)
  - `_collect_per_image_counts` pulls per-image stats when ultralytics exposes them and falls back to a single aggregated bucket otherwise
  - `_print_human_summary` renders point estimates + 95% CIs + per-severity counts for the console
  - `main()` returns an int; wired via `sys.exit(main())`
  - Docstring security note flags pickle-ACE surface of `YOLO(.pt)` loads (T-02-11 inherited mitigation)
- `backend/tests/test_eval_detector.py` (214 lines) — 23 tests across 5 class groups:
  - `TestMapSeverityMirrorsRuntime` (6 tests) — parity with `YOLOv8Detector._map_severity`
  - `TestBootstrapCiDeterministic` (5 tests) — same-seed equality, different-seed divergence, pooled point estimate, degenerate-zero handling, `DEFAULT_SEED == 42`
  - `TestPerSeverityBreakdown` (4 tests) — single-class + two-class breakdowns
  - `TestMatchPredictions` (6 tests) — perfect match, no overlap, empty gt/pred, IoU helper disjoint+identical
  - `TestEvalDetectorExitCodes` (2 tests) — subprocess smokes for exit=3 + fetch-hint literal + `--help` flag coverage
- `backend/tests/fixtures/eval_fixtures/data.yaml` — 1-class YOLO dataset config with all splits pointing at `images/test`
- `backend/tests/fixtures/eval_fixtures/images/test/img_{001,002,003}.jpg` — 64×64 solid-color PIL JPEGs, ~690 bytes each (quality=30)
- `backend/tests/fixtures/eval_fixtures/labels/test/img_001.txt` — 1 centered pothole bbox
- `backend/tests/fixtures/eval_fixtures/labels/test/img_002.txt` — 2 offset pothole bboxes
- `backend/tests/fixtures/eval_fixtures/labels/test/img_003.txt` — intentionally empty (negative example)

### Modified

None. `data_pipeline/detector_factory.py`, `data_pipeline/yolo_detector.py`, `data_pipeline/requirements.txt`, and `.env.example` all remain at their Plan 01 state — Plan 02 only consumes them.

## Decisions Made

- **Severity constants are re-declared in `eval.py` instead of imported.** Importing `data_pipeline.yolo_detector` (even just for `_SEVERE_CLASSES`) would drag `ultralytics`/`cv2`/`torch` into every eval unit test. Duplication is paid for with a `TestMapSeverityMirrorsRuntime` suite that pins the behavior. If yolo_detector.py's class lists ever change, both sides must be updated in lockstep — flagged in a docstring comment.
- **Aggregated-bucket fallback in `_collect_per_image_counts`.** Ultralytics' per-image stats layout varies across 8.x versions; rather than pinning a specific field path, the code tries `results.stats["tp"]` first and falls back to `box.tp.sum() / box.fp.sum() / box.nl - tp` as a single "image" so `bootstrap_ci` still runs. The CI will be near-degenerate in that path; `docs/DETECTOR_EVAL.md` (Plan 05) will call out the caveat.
- **JSON CIs are 3-tuples, not separate low/high fields.** `precision_ci_95: [low, point, high]` keeps the JSON structure compact and forces the point estimate to live next to its CI so no downstream consumer can mix up whose point goes with whose interval.
- **Per-severity breakdown uses a single aggregate bucket.** The severity rule is per-detection, not per-image, so aggregating predictions across all images before running `map_severity` is lossless and simpler than stratifying by image.
- **Empty-label file `img_003.txt` is zero bytes, not a single newline.** Matches YOLO's negative-example convention; the `wc -c` acceptance check confirms it.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking tooling gap] Installed pillow/numpy/scipy into the existing Python 3.12 venv before generating fixtures.**
- **Found during:** Task 1 (generating fixture JPEGs and running `bootstrap_ci` import check)
- **Issue:** The host's `/usr/bin/python3` is 3.9.6 and cannot import `data_pipeline.eval` (PEP 604 `dict | None` syntax). Plan 01's SUMMARY called out the same gap and created `/tmp/rq-venv` from the user's uv-managed 3.12 interpreter; that venv was still present but missing `pillow`, `numpy`, and `scipy`.
- **Fix:** `/tmp/rq-venv/bin/python -m pip install pillow numpy scipy` — same venv, additional test-time deps only.
- **Files modified:** None (test-tooling only; no project file touched).
- **Verification:** All three acceptance-level verification commands pass and 23 tests green in 0.13s.
- **Committed in:** N/A (tooling only, not a project change).

### Notes (not deviations)

- **Fixture dir size check is filesystem-dependent.** The plan's acceptance criterion `[ $(du -k backend/tests/fixtures/eval_fixtures/ | tail -1 | cut -f1) -le 10 ]` returns `24` on this macOS APFS volume because APFS allocates in 4 KB blocks and there are 7 files (3 JPEGs + 3 txts + 1 yaml) — even though the apparent byte total is only **2,501 bytes** (~2.5 KB). The plan's `<action>` section's "< 5 KB" intent is satisfied (by a comfortable margin); the `du` check is a filesystem-allocation artifact rather than a bloated fixture. No change made.

---

**Total deviations:** 1 environment/tooling adjustment (no project file changes), 1 filesystem-behavior note.
**Impact on plan:** Zero scope creep. All three tasks landed with their specified shapes, all 10 CLI flags present, all D-18 exit codes implemented, all 5 required pure helpers exposed, severity rules mirrored, bootstrap deterministic with seed=42.

## Issues Encountered

- **Python 3.9 on host default `python3`** (same gap Plan 01 flagged): worktree host's `/usr/bin/python3` is 3.9.6 and cannot parse PEP 604 `dict | None` syntax used in `backend/app/cache.py` (imported transitively through `backend/tests/conftest.py`). Resolution: reused `/tmp/rq-venv` (Python 3.12.13 from the user's uv install) created in Plan 01; only needed to add `pillow`, `numpy`, `scipy`. No project file touched.
- **Ultralytics not installed in test env** (intentional): Task 3's test file is explicitly designed to avoid ultralytics — it only imports `data_pipeline.eval` (pure numpy) and shells out to the CLI via `subprocess` to verify exit codes. This matches the plan's `no_ultralytics_import` acceptance criterion. Running the full eval pipeline end-to-end against a real model is deferred to Plan 04/05 (human-operator territory, requires ultralytics + torch install + actual model weights).

## Known Stubs

None. The CLI's `_collect_per_image_counts` aggregated-bucket fallback is intentional and documented (see Decisions Made); it is not a stub.

## Threat Flags

None. The plan's `<threat_model>` already enumerates T-02-07 through T-02-12; the implementation inherits Plan 01's T-02-11 mitigation (factory default HF repo) and adds a security note in `scripts/eval_detector.py`'s docstring warning operators about pickle-ACE surface of `YOLO(.pt)` loads. No new security-relevant surface introduced.

## User Setup Required

None — plan `user_setup: []` held. Operators already have `YOLO_MODEL_PATH` and `HUGGINGFACE_TOKEN` documented in `.env.example` (from Plan 01). To actually run `scripts/eval_detector.py` against a real model, operators need:
1. `pip install -r data_pipeline/requirements.txt` (ultralytics + huggingface_hub + scipy + numpy — all declared)
2. A populated `data/eval_la/` directory (delivered by Plan 03's `scripts/fetch_eval_data.py`)

Neither is a Plan-02 deliverable.

## Next Phase Readiness

- **Plan 03 (LA dataset)** can call `scripts/eval_detector.py --data data/eval_la/data.yaml --split test` once its `fetch_eval_data.py` populates the dataset — the CLI is ready and the missing-data exit code is wired to exactly the hint string Plan 03 will mint.
- **Plan 04 (fine-tune)** can run `scripts/eval_detector.py --min-precision 0.50` inside its harness to enforce a floor (exit 2) on the newly-trained weights before pushing to HF.
- **Plan 05 (writeup)** can consume `--json-out /path/report.json` directly — the JSON schema is stable (top-level `precision`, `recall`, `map50`, `precision_ci_95`, `recall_ci_95`, `per_severity`, `eval_config`).
- **Plan 03/04/05 tests** can reuse `backend/tests/fixtures/eval_fixtures/` — the data.yaml + bbox files are sized so any extension just needs to add more images without rebuilding the tree.
- **Per-image CI caveat:** operators should prefer ultralytics 8.3+ where `results.stats` exposes per-image arrays. On older versions the CI degenerates to a single-bucket point estimate; Plan 05's writeup should note this explicitly.

## Self-Check: PASSED

Verified post-write:

```
$ test -f data_pipeline/eval.py                            → FOUND
$ test -f scripts/eval_detector.py                         → FOUND
$ test -f backend/tests/test_eval_detector.py              → FOUND
$ test -f backend/tests/fixtures/eval_fixtures/data.yaml   → FOUND
$ ls backend/tests/fixtures/eval_fixtures/images/test/*.jpg | wc -l  → 3
$ ls backend/tests/fixtures/eval_fixtures/labels/test/*.txt | wc -l  → 3
$ git log --oneline | grep f77364e                         → FOUND (Task 1)
$ git log --oneline | grep d205f39                         → FOUND (Task 2)
$ git log --oneline | grep 7aeec27                         → FOUND (Task 3)
$ python scripts/eval_detector.py --help | grep -E "(--min-precision|--bootstrap-resamples|--json-out)"  → all three flags present
$ python scripts/eval_detector.py --data /nonexistent.yaml; echo $?  → exit 3, hint emitted to stderr
$ pytest backend/tests/test_eval_detector.py -x -q         → 23 passed in 0.13s
$ pytest backend/tests/test_eval_detector.py backend/tests/test_detector_factory.py backend/tests/test_yolo_detector.py -q  → 44 passed (no regressions)
$ python -c "from data_pipeline.eval import bootstrap_ci; c=[{'tp':3,'fp':1,'fn':1}]*20; assert bootstrap_ci(c,'precision',n_resamples=500,seed=42)==bootstrap_ci(c,'precision',n_resamples=500,seed=42)"  → deterministic
```

Structural checks from the plan's `<verification>` block all pass.

---

*Phase: 02-real-data-detector-accuracy*
*Completed: 2026-04-24*
