---
phase: 02-real-data-detector-accuracy
fixed_at: 2026-04-23T00:00:00Z
review_path: .planning/phases/02-real-data-detector-accuracy/02-REVIEW.md
iteration: 1
findings_in_scope: 6
fixed: 6
skipped: 0
status: all_fixed
---

# Phase 02: Code Review Fix Report

**Fixed at:** 2026-04-23T00:00:00Z
**Source review:** `.planning/phases/02-real-data-detector-accuracy/02-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 6 (all 6 Warnings; 0 Critical; 5 Info out of scope)
- Fixed: 6
- Skipped: 0

All Warning-level findings were applied cleanly. The pre-fix baseline of
47 tests (across `test_detector_factory.py`, `test_mapillary.py`,
`test_fetch_eval_data.py`, `test_finetune_detector.py`) grew to 51
passing tests after WR-05 and WR-06 added regression coverage. No Critical
issues were raised in the review.

## Fixed Issues

### WR-01: `_build_model_card` crashes if `eval_metrics` contains string "TBD" sentinels

**Files modified:** `scripts/finetune_detector.py`
**Commit:** b26ac39
**Applied fix:** Replaced the self-contradictory `.get('k', 'TBD'):.3f`
pattern with a type-guarded `_fmt(v)` helper inside `_build_model_card`
that returns `f"{v:.3f}"` only when `v` is numeric and falls back to
`"TBD"` otherwise. The function now survives a partial `eval_metrics`
dict without `TypeError`.

### WR-02: `--build` does NOT overwrite existing label files, contradicting its docstring

**Files modified:** `scripts/fetch_eval_data.py`
**Commit:** 170fc0b
**Applied fix:** Rewrote the module docstring to accurately describe
`--build` behavior (preserves existing hand-labels; stale images remain
on disk across re-runs) and added a new `--clean` CLI flag that
`shutil.rmtree`s `<root>/images/` and `<root>/labels/` before the
download loop, giving operators an explicit way to get a bit-for-bit
fresh state. The `if not label_path.exists()` gate is retained (now
properly documented) and moved behind the opt-in `--clean` flag.

### WR-03: `_build_fresh` silently writes an empty manifest if zero sequences survive

**Files modified:** `scripts/fetch_eval_data.py`
**Commit:** a349238
**Applied fix:** Added two post-download assertions before the manifest
write: (1) reject zero-manifest_entries with a Pitfall-5-aware error
message and `return EXIT_OTHER`; (2) reject `n_total < 3` sequences
(since a D-09 70/20/10 split cannot populate all three splits with
fewer). Both branches exit with code 1 so a CI pipeline trusting exit
code 0 no longer "verifies OK" a dead-end dataset on the next step.

### WR-04: Mutex `--verify-only` / `--build` has no effect because `default=True`

**Files modified:** `scripts/fetch_eval_data.py`
**Commit:** 8eaef1d
**Applied fix:** Dropped `default=True` from `--verify-only` so argparse's
`add_mutually_exclusive_group` actually enforces at-most-one-explicit-
flag. The existing `if args.build: _build_fresh(...) else: _verify(...)`
main() branch preserves the "verify by default" behavior when neither
flag is passed, and `--help` still lists both flags so the
`test_help_exits_0_and_lists_modes` contract is unchanged.

### WR-05: `_BBOX_AREA_TOLERANCE` in `mapillary.py` is asymmetric and under-tested

**Files modified:** `data_pipeline/mapillary.py`,
`backend/tests/test_mapillary.py`
**Commit:** d169f4f
**Applied fix:** Tightened `_BBOX_AREA_TOLERANCE` from `1e-9` to `1e-15`
(still comfortably above the demonstrated ~2e-18 IEEE-754 artifact, but
tight enough to reject a genuine 1e-8 deg² overrun). Documented the
unit (`deg²`) and the reasoning inline. Added two regression tests:
`test_bbox_tolerance_ceiling_pins_dos_guard` (asserts half-tolerance
passes and two-tolerances fails) and
`test_bbox_tolerance_is_tight_enough_to_catch_genuine_overrun`
(asserts a bbox 1e-8 over MAX is rejected — the exact attack case the
old 1e-9 slop permitted). The pre-existing
`test_bbox_at_limit_ok((0.0, 0.0, 0.1, 0.1))` still passes because
`0.010000000000000002 - 0.01 ≈ 1.7e-18 < 1e-15`.

### WR-06: `_resolve_model_path` accepts `foo/bar.pt` as an HF repo id

**Files modified:** `data_pipeline/detector_factory.py`,
`backend/tests/test_detector_factory.py`
**Commit:** 77419e2
**Applied fix:** Short-circuited the HF-resolution branch with
`or repo_id.endswith(".pt")` so any `user/repo.pt` value is treated as
a local path — `YOLOv8Detector` then raises a clear
`FileNotFoundError` instead of `hf_hub_download` being called with a
user-controlled repo id (T-02-01 pickle-ACE vector). Added two
regression tests: `test_local_path_without_prefix_not_treated_as_hf`
(asserts `models/latest.pt` is NOT downloaded) and
`test_any_repo_id_ending_pt_is_rejected_as_hf` (asserts
`user/weights.pt` is also refused, closing the ambiguity entirely).

---

_Fixed: 2026-04-23T00:00:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
