---
phase: 07-la-trained-detector
plan: 01
subsystem: testing
tags: [pytest, tdd, wave-0, bootstrap-ci, yolov8, hf-hub, mapillary]

# Dependency graph
requires:
  - phase: 03-mapillary-ingestion-pipeline
    provides: wipe_synthetic_rows pattern + TestPlan04Flags analog tests
  - phase: 02-real-data-detector-accuracy
    provides: bootstrap_ci reference impl, DEFAULT_SEED=42 convention, HF revision-pin pattern

provides:
  - RED test scaffold for bootstrap_ci_map50 (data_pipeline/tests/test_eval.py)
  - RED test scaffold for wipe_mapillary_rows + --wipe-mapillary CLI flag (backend/tests/test_ingest_mapillary.py)
  - RED test scaffold asserting _DEFAULT_HF_REPO starts with Hratchg/road-quality-la-yolov8@ (backend/tests/test_detector_factory.py)

affects:
  - 07-02 (must implement bootstrap_ci_map50 to turn test_eval.py GREEN)
  - 07-03 (must implement wipe_mapillary_rows + --wipe-mapillary to turn test_ingest_mapillary.py GREEN)
  - 07-07 (must swap _DEFAULT_HF_REPO constant to turn test_detector_factory.py GREEN)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Wave-0 RED-first TDD scaffold: tests written before implementation, import-fails-at-collection pattern
    - data_pipeline/tests/ package created as empty __init__.py to enable pytest collection

key-files:
  created:
    - data_pipeline/tests/__init__.py
    - data_pipeline/tests/test_eval.py
  modified:
    - backend/tests/test_ingest_mapillary.py
    - backend/tests/test_detector_factory.py

key-decisions:
  - "Wave 0 RED tests are intentional — ImportError/AttributeError/AssertionError are the contract, not bugs"
  - "4 new wipe_mapillary tests appended to TestPlan04Flags (not TestCLISmokes) — plan name was ambiguous but TestPlan04Flags is where the analog wipe_synthetic tests live"
  - "test_default_hf_repo_pin_contains_sha placed before test_hf_repo_id_calls_hf_hub_download in TestResolveModelPath for logical ordering"

patterns-established:
  - "RED test contract pin: from module.submod import not_yet_existing_fn — ImportError is the signal"
  - "Wave-0 test placement: new wave tests appended after existing final method in the relevant class"

requirements-completed:
  - REQ-trained-la-detector

# Metrics
duration: ~15min
completed: 2026-04-29
---

# Phase 7 Plan 01: LA-Trained Detector Wave 0 RED Tests Summary

**Three pytest contract pins written before any Phase 7 implementation: bootstrap_ci_map50 (ImportError), wipe_mapillary_rows (AttributeError), and _DEFAULT_HF_REPO Hratchg pin (AssertionError) — all intentionally RED, turned GREEN by Plans 07-02, 07-03, and 07-07 respectively.**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-04-29T01:38:00Z
- **Completed:** 2026-04-29T01:53:29Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- Created `data_pipeline/tests/` package (new directory + empty `__init__.py`) so pytest can collect tests alongside the module
- Created `data_pipeline/tests/test_eval.py` with `TestBootstrapCiMap50` (4 methods): valid range, degenerate no-GT, deterministic seed=42, default seed=42 assertion — fails with `ImportError: cannot import name 'bootstrap_ci_map50'`
- Extended `backend/tests/test_ingest_mapillary.py` with 4 RED methods in `TestPlan04Flags`: helper exists, hardcoded WHERE literal (T-07-04 mitigation), rowcount+commit mock, `--wipe-mapillary` CLI flag — all fail with `AttributeError` / assertion failures
- Extended `backend/tests/test_detector_factory.py`: flipped existing `test_none_returns_default_hf_repo_via_hf_hub_download` to assert `Hratchg/road-quality-la-yolov8` + revision present; added `test_default_hf_repo_pin_contains_sha` asserting `@<sha>` format — both fail with `AssertionError` against current `keremberke/...` constant

## Task Commits

Each task was committed atomically:

1. **Task 1: Create data_pipeline/tests/ + RED test for bootstrap_ci_map50** - `f51f951` (test)
2. **Task 2: Add RED tests for wipe_mapillary_rows** - `364612b` (test)
3. **Task 3: Update test_detector_factory.py to pin Hratchg + SHA assertion** - `00c114c` (test)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `data_pipeline/tests/__init__.py` - Empty file; makes data_pipeline/tests/ a collectable pytest package
- `data_pipeline/tests/test_eval.py` - TestBootstrapCiMap50 with 4 test methods; RED via ImportError on bootstrap_ci_map50
- `backend/tests/test_ingest_mapillary.py` - 4 new methods appended to TestPlan04Flags; RED via AttributeError (wipe_mapillary_rows absent) + missing CLI flag
- `backend/tests/test_detector_factory.py` - Existing test flipped to Hratchg assertion + new test_default_hf_repo_pin_contains_sha; RED via AssertionError (keremberke still in place)

## RED Test Error Inventory

| Test | File | Error Type | Turns GREEN in |
|------|------|------------|----------------|
| TestBootstrapCiMap50 (all 4) | data_pipeline/tests/test_eval.py | ImportError: cannot import name 'bootstrap_ci_map50' | Plan 07-02 |
| test_wipe_mapillary_rows_helper_exists | backend/tests/test_ingest_mapillary.py | AttributeError: module has no attribute 'wipe_mapillary_rows' | Plan 07-03 |
| test_wipe_mapillary_rows_uses_hardcoded_where | backend/tests/test_ingest_mapillary.py | AssertionError: literal not in script | Plan 07-03 |
| test_wipe_mapillary_rows_returns_rowcount_and_commits | backend/tests/test_ingest_mapillary.py | AttributeError: module has no attribute 'wipe_mapillary_rows' | Plan 07-03 |
| test_help_lists_wipe_mapillary_flag | backend/tests/test_ingest_mapillary.py | AssertionError: --wipe-mapillary not in stdout | Plan 07-03 |
| test_none_returns_default_hf_repo_via_hf_hub_download | backend/tests/test_detector_factory.py | AssertionError: repo_id == 'keremberke/...' not 'Hratchg/...' | Plan 07-07 |
| test_default_hf_repo_pin_contains_sha | backend/tests/test_detector_factory.py | AssertionError: does not start with 'Hratchg/road-quality-la-yolov8@' | Plan 07-07 |

## Decisions Made

- Appended the 4 `wipe_mapillary_rows` tests to `TestPlan04Flags` rather than `TestCLISmokes`. The plan text referenced `TestCLISmokes` but specified placement "after `test_trigger_recompute_invokes_compute_scores_py`" which lives in `TestPlan04Flags`. `TestPlan04Flags` is also where the analog `wipe_synthetic_rows` tests live, making it the correct location by structural symmetry.
- No new imports added to `test_ingest_mapillary.py` — `MagicMock`, `subprocess`, `sys`, `SCRIPT`, `REPO_ROOT`, `ing` were all already imported at module level.
- No production files modified (`data_pipeline/eval.py`, `scripts/ingest_mapillary.py`, `data_pipeline/detector_factory.py` all untouched).

## Deviations from Plan

None — plan executed exactly as written. The one class-name ambiguity (`TestCLISmokes` vs `TestPlan04Flags`) was resolved by following the structural context (placement after `test_trigger_recompute_invokes_compute_scores_py`) rather than the class name literal, which is consistent with the plan's intent.

## Issues Encountered

The `backend/tests/conftest.py` fails to load under Python 3.9 (system default on this machine) due to `dict | None` union syntax requiring Python 3.10+. This is a pre-existing issue unrelated to this plan — it was already present before any Wave 0 edits. All three RED conditions were verified directly via `python3 -c` import checks and CLI runs rather than through the full pytest runner, which produced equivalent signal.

## Known Stubs

None — this plan creates test-only files; no production code or UI-rendering data paths were added.

## Threat Flags

No new network endpoints, auth paths, file access patterns, or schema changes introduced. Tests are pure-Python unit scaffolds with no I/O beyond `subprocess.run` to check `--help` output.

## Next Phase Readiness

- Plan 07-02 can immediately implement `bootstrap_ci_map50` in `data_pipeline/eval.py` — the test contract is locked
- Plan 07-03 can immediately implement `wipe_mapillary_rows` + `--wipe-mapillary` in `scripts/ingest_mapillary.py` — the test contract is locked
- Plan 07-07 can immediately swap `_DEFAULT_HF_REPO` in `data_pipeline/detector_factory.py` after the HF model push — the test contract is locked
- No blockers for downstream Wave 1+ plans

## Self-Check

Files exist:
- data_pipeline/tests/__init__.py: FOUND
- data_pipeline/tests/test_eval.py: FOUND
- backend/tests/test_ingest_mapillary.py: FOUND (modified)
- backend/tests/test_detector_factory.py: FOUND (modified)

Commits:
- f51f951: FOUND (test(07-01): RED scaffold for bootstrap_ci_map50 contract pin)
- 364612b: FOUND (test(07-01): RED scaffold for wipe_mapillary_rows contract pin)
- 00c114c: FOUND (test(07-01): RED scaffold for _DEFAULT_HF_REPO Hratchg pin + SHA assertion)

## Self-Check: PASSED

---
*Phase: 07-la-trained-detector*
*Completed: 2026-04-29*
