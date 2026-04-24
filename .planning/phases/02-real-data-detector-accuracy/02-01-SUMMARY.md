---
phase: 02-real-data-detector-accuracy
plan: 01
subsystem: ml
tags: [python, ml, config, detector, huggingface, yolov8, env-var]

# Dependency graph
requires:
  - phase: 01-mvp-integrity-cleanup
    provides: "Stable .env.example convention (section header + Consumed by + explanation style) and StubDetector/YOLOv8Detector protocol frozen"
provides:
  - "_resolve_model_path() callable from data_pipeline.detector_factory (imported by Plan 02 eval_detector.py and Plan 05 docs references)"
  - "_DEFAULT_HF_REPO constant (keremberke/yolov8s-pothole-segmentation) for docs references"
  - "YOLO_MODEL_PATH env var surface (HF repo or local path) — CONCERNS.md hardcoded-path finding resolved"
  - "huggingface_hub + scipy runtime deps in data_pipeline/requirements.txt (scipy needed by Plan 02 eval bootstrap)"
affects: [02-02-eval-harness, 02-03-la-dataset, 02-04-finetune, 02-05-publish-writeup]

# Tech tracking
tech-stack:
  added: [huggingface_hub>=0.24,<1.0, scipy>=1.13]
  patterns: ["Env-driven model path resolution with explicit HF-vs-local fork", "Factory-level hf_hub_download (D-14: ultralytics does NOT auto-resolve HF repo names)"]

key-files:
  created:
    - backend/tests/test_detector_factory.py
  modified:
    - data_pipeline/detector_factory.py
    - data_pipeline/requirements.txt
    - .env.example
    - backend/tests/test_yolo_detector.py

key-decisions:
  - "Factory performs HF download explicitly via huggingface_hub.hf_hub_download, then passes resolved local path to YOLOv8Detector (D-14 correction; ultralytics.YOLO() does not auto-resolve HF repo names)"
  - "Precedence: explicit model_path arg > YOLO_MODEL_PATH env > _DEFAULT_HF_REPO"
  - "YOLOv8Detector constructor default left unchanged for backward compat (factory always supplies resolved path at runtime)"
  - "MAPILLARY_ACCESS_TOKEN deliberately NOT added here (deferred to Plan 03 per plan scope)"

patterns-established:
  - "Env-var at module top: YOLO_MODEL_PATH_ENV = os.environ.get('YOLO_MODEL_PATH') — matches backend/app/db.py convention"
  - "_HF_REPO_PATTERN regex (^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(@...)?$) distinguishes HF repo ids from local paths"
  - "Test reload dance: importlib.reload(detector_factory) re-reads YOLO_MODEL_PATH_ENV under pytest's monkeypatch"
  - "HF download mock: patch('huggingface_hub.hf_hub_download', return_value='/tmp/...') — no network at test time"

requirements-completed: [REQ-real-data-accuracy]

# Metrics
duration: 3min
completed: 2026-04-24
---

# Phase 2 Plan 01: Detector Config Surface Summary

**Env-driven YOLO model resolution with explicit HF-vs-local fork via huggingface_hub.hf_hub_download — removes CWD-relative hardcoded path and wires YOLO_MODEL_PATH for operator control**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-04-24T02:10:23Z
- **Completed:** 2026-04-24T02:13:10Z
- **Tasks:** 3
- **Files modified:** 4 (3 modified, 1 created)

## Accomplishments

- Added `_resolve_model_path(value)` to `data_pipeline/detector_factory.py` handling four input shapes: None → default HF repo, `"user/repo"` / `"user/repo:file.pt"` / `"user/repo@rev"` → `hf_hub_download`, and `"./..."` / `"/..."` / `"../..."` → passthrough local path.
- `get_detector(use_yolo=True)` now resolves its model from the `YOLO_MODEL_PATH` env var (with explicit-arg override), closing the CONCERNS.md CWD-relative hardcoded path finding.
- Added `huggingface_hub>=0.24,<1.0` and `scipy>=1.13` to `data_pipeline/requirements.txt`; `.env.example` now documents `YOLO_MODEL_PATH=` and `HUGGINGFACE_TOKEN=` placeholders with matching Phase 1 section-header style.
- 11 new unit tests in `backend/tests/test_detector_factory.py` + 3 extension tests in `backend/tests/test_yolo_detector.py`. All 21 tests green; no network required (huggingface_hub and ultralytics are both mocked).
- Public `get_detector(use_yolo, model_path)` signature preserved exactly (verified via AST); `data_pipeline/detector.py` PotholeDetector protocol + Detection dataclass untouched.

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire YOLO_MODEL_PATH env-var resolution into detector_factory.py** — `34b6fff` (feat)
2. **Task 2: Add hf_hub_download + scipy to requirements.txt and extend .env.example** — `5d0b62d` (chore)
3. **Task 3: Author backend/tests/test_detector_factory.py + extend test_yolo_detector.py** — `a985e67` (test)

## Files Created/Modified

- `data_pipeline/detector_factory.py` — modified: added `_DEFAULT_HF_REPO`, `_DEFAULT_HF_FILENAME`, `_HF_REPO_PATTERN`, `YOLO_MODEL_PATH_ENV`, `_resolve_model_path()`; replaced body of `get_detector()` with env-aware resolution + explicit `hf_hub_download` call; preserved StubDetector + ImportError fallbacks. +71/-12 lines.
- `data_pipeline/requirements.txt` — modified: appended `huggingface_hub>=0.24,<1.0` and `scipy>=1.13`.
- `.env.example` — modified: appended `# ----- YOLOv8 Detector Model -----` and `# ----- HuggingFace Hub (fine-tune upload only) -----` sections with empty defaults and explanatory comments.
- `backend/tests/test_detector_factory.py` — created: 2 test classes, 11 tests (7 in `TestResolveModelPath`, 4 in `TestGetDetectorEnvVar`) covering all `_resolve_model_path` branches and env-var precedence.
- `backend/tests/test_yolo_detector.py` — modified: appended `test_factory_with_explicit_path` (SC #2), `test_factory_resolves_hf_repo` (D-14), `test_env_var_path_resolution` (SC #3). Existing 7 tests unchanged.
- `data_pipeline/yolo_detector.py` — intentionally NOT modified (plan notes default constructor string kept as-is for backward compat — factory always supplies resolved path).
- `data_pipeline/detector.py` — intentionally NOT modified (frozen Protocol + Detection dataclass).

## Decisions Made

- **One extra resolve case added:** `test_parent_relative_local_path_passthrough` (checking `../models/my.pt`). The plan specified minimum-10 tests across resolve + env-var cases, and `../` is one of the three local-path prefixes the helper accepts — covering it alongside `./` and `/abs/` closes the full local-path surface. Treat as additional test coverage, not a deviation.
- **System Python was 3.9.6** (lacks PEP 604 `dict | None` needed by backend/app/cache.py imported via conftest). Created `/tmp/rq-venv` using the user's existing uv-managed Python 3.12.13 to run pytest; this is a test-tooling choice only and did not change any project file. See "Issues Encountered" for details.

## Deviations from Plan

None — plan executed exactly as written. Task 1 (detector_factory.py + yolo_detector.py), Task 2 (requirements + env.example), and Task 3 (new + extended tests) all landed with their specified shapes. No Rule 1/2/3 auto-fixes triggered.

## Issues Encountered

- **Python 3.9 + psycopg2/fastapi/cachetools missing in base env:** The repo's existing `backend/tests/conftest.py` imports `fastapi.testclient.TestClient`, `psycopg2`, and transitively `cachetools` (used by `backend/app/cache.py`, which uses PEP 604 `dict | None` syntax). The default `/usr/bin/python3` on this worktree host is 3.9.6, which chokes on `dict | None` at conftest import time. Resolution: created a venv at `/tmp/rq-venv` from the user's existing `~/.local/share/uv/python/cpython-3.12.13` interpreter and installed `pytest psycopg2-binary fastapi cachetools pydantic httpx huggingface_hub` there. No project files were touched; only test tooling. Future executors on this host should reuse `/tmp/rq-venv` or create an equivalent 3.12 venv. No impact on CI (which picks up `data_pipeline/requirements.txt` directly).

## User Setup Required

None — plan `user_setup: []` held. Operators who want to override the default HF repo may optionally set `YOLO_MODEL_PATH` in `.env`; if unset, the factory falls back to `keremberke/yolov8s-pothole-segmentation` automatically.

## Next Phase Readiness

- `_resolve_model_path()` is callable for Plan 02's `eval_detector.py` (it needs to load the same model via the same resolution logic) — import as `from data_pipeline.detector_factory import _resolve_model_path`.
- `_DEFAULT_HF_REPO` constant is available for Plan 05's `docs/DETECTOR_EVAL.md` "Security & Licensing" section (cite the default publisher).
- `huggingface_hub` and `scipy` are now declared runtime deps — Plan 02 (`scripts/eval_detector.py`) can use `scipy.stats` for bootstrap CIs, Plan 04 (`scripts/finetune_detector.py --push`) can use `huggingface_hub.HfApi` for upload.
- `HUGGINGFACE_TOKEN` env var is documented; Plan 04 will read it in `finetune_detector.py` (factory does NOT — T-02-02 mitigation).

## Self-Check: PASSED

Verified post-write:

```
$ ls data_pipeline/detector_factory.py                     → FOUND
$ ls data_pipeline/requirements.txt                        → FOUND
$ ls .env.example                                          → FOUND
$ ls backend/tests/test_detector_factory.py                → FOUND
$ ls backend/tests/test_yolo_detector.py                   → FOUND
$ git log --oneline | grep 34b6fff                         → FOUND (Task 1)
$ git log --oneline | grep 5d0b62d                         → FOUND (Task 2)
$ git log --oneline | grep a985e67                         → FOUND (Task 3)
$ pytest backend/tests/test_detector_factory.py \
         backend/tests/test_yolo_detector.py -x -q         → 21 passed
```

Structural checks from the plan's `<verification>` block all pass:
- `grep -q _DEFAULT_HF_REPO data_pipeline/detector_factory.py` → ok
- `grep -q "def _resolve_model_path" data_pipeline/detector_factory.py` → ok
- `grep -q "^YOLO_MODEL_PATH=$" .env.example` → ok
- `grep -q "^HUGGINGFACE_TOKEN=$" .env.example` → ok
- `grep -q "^huggingface_hub>=" data_pipeline/requirements.txt` → ok
- `grep -q "^scipy>=" data_pipeline/requirements.txt` → ok
- Import smoke: `get_detector(use_yolo=False)` returns `StubDetector` → ok

---

*Phase: 02-real-data-detector-accuracy*
*Completed: 2026-04-24*
