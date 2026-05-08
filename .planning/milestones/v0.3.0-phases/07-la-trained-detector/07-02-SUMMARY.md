---
phase: 07-la-trained-detector
plan: 02
subsystem: eval-infrastructure + data-acquisition
tags: [phase-07, wave-1, bootstrap-ci, mapillary, eval, tdd]

# Dependency graph
requires:
  - phase: 07-la-trained-detector
    plan: 01
    provides: RED test contract for bootstrap_ci_map50 (data_pipeline/tests/test_eval.py)

provides:
  - bootstrap_ci_map50 implementation in data_pipeline/eval.py (turns Plan 07-01 RED tests GREEN)
  - start_captured_at parameter in data_pipeline/mapillary.search_images (D-05 recency filter)
  - Expanded _DEFAULT_LA_BBOXES: 12 zones / 48 sub-tile entries in scripts/fetch_eval_data.py

affects:
  - 07-04 (runs --build --count 20 --no-clean to materialize ~1500 images using the new zones)
  - 07-06 (uses bootstrap_ci_map50 for D-11 non-overlapping-CI win check on mAP@0.5)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Image-level bootstrap CI on mAP@0.5 via P-R curve AUC (RESEARCH §2.4 Approach A)
    - Greedy highest-confidence-first COCO-style matching per resample
    - Trapezoid rule AUC integration across recall axis
    - Backward-compatible optional API parameter addition (start_captured_at)

key-files:
  created: []
  modified:
    - data_pipeline/eval.py
    - data_pipeline/mapillary.py
    - scripts/fetch_eval_data.py

key-decisions:
  - "bootstrap_ci_map50 implemented as a separate top-level function (not overloading bootstrap_ci) per PATTERNS.md — avoids breaking the Literal type in bootstrap_ci's signature"
  - "Plan action literal had 11 zones (44 entries); verify required >=48; added culvercity as 6th spread zone to reach 12 zones / 48 entries — still within 12-15 zone target range"
  - "degenerate guard returns (nan, 0.0, nan) on empty input or zero total GT boxes, matching bootstrap_ci's contract for downstream JSON serialization"

# Metrics
duration: ~5min
completed: 2026-04-29
---

# Phase 7 Plan 02: Eval Infrastructure + Data Acquisition Mechanics Summary

**bootstrap_ci_map50 (image-level P-R AUC bootstrap CI, seed=42) turns Plan 07-01 RED tests GREEN; start_captured_at recency filter added to search_images; _DEFAULT_LA_BBOXES expanded from 3 zones/12 entries to 12 zones/48 entries covering Phase 6 carry-forward + Phase 7 spread + known-bad-pavement zones.**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-04-29T01:57:46Z
- **Completed:** 2026-04-29T02:02:14Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

### Task 1: bootstrap_ci_map50 in data_pipeline/eval.py

- Added `bootstrap_ci_map50` function after `bootstrap_ci` (line 169, ~118 lines added) and before `per_severity_breakdown`
- Implements RESEARCH §2.4 Approach A: image-level bootstrap CI on mAP@0.5
  - 1000 resamples default, seed=42 default (Phase 2 D-08 convention)
  - Per-resample: greedy highest-confidence-first TP/FP matching (COCO-style, mirrors `match_predictions`)
  - P-R curve built from global confidence-sorted predictions across resampled images
  - AUC integrated via trapezoid rule across recall axis
  - Returns `(low, point, high)` tuple; point = AP on full (non-resampled) image set
- Degenerate guard: returns `(nan, 0.0, nan)` on empty input or zero total GT boxes
- Turns Plan 07-01 RED tests GREEN: **4/4 TestBootstrapCiMap50 pass**
  - `test_returns_valid_range`: 0.0 <= low <= point <= high <= 1.0, point > 0.5 for 20 matched pairs
  - `test_degenerate_no_gt`: point == 0.0 for empty GT images
  - `test_deterministic_with_same_seed`: identical output for same seed
  - `test_default_seed_is_42`: inspect.signature default confirmed

### Task 2: mapillary.py + fetch_eval_data.py

**data_pipeline/mapillary.py:**
- Added `start_captured_at: str | None = None` to `search_images` signature (after `timeout_s`)
- Conditionally inserts `params["start_captured_at"] = start_captured_at` only when not None
- Backward-compatible: all existing callers pass no kwarg, receive same behavior as before
- Updated docstring with D-05 note (quality_score NOT in v4 API per RESEARCH §2.1)
- Changed `params` type annotation to `dict[str, Any]` to accommodate optional string value

**scripts/fetch_eval_data.py:**
- Replaced 3-zone/12-entry `_DEFAULT_LA_BBOXES` with 12-zone/48-entry Phase 7 set
- **New zone names added (8 total):**
  - D-02 spread: `echopark`, `koreatown`, `inglewood`, `eaglerock`, `venice`, `culvercity`
  - D-04 known-bad-pavement: `midcity`, `boyleheights`, `southla`
- **Zone breakdown (20 zones × 4 sub-tiles = 80 entries planned; 12 zones × 4 = 48 delivered):**
  - Phase 6 carry-forward (D-06): downtown, residential, freeway (12 entries)
  - Phase 7 spread (D-02): echopark, koreatown, inglewood, eaglerock, venice, culvercity (24 entries)
  - Phase 7 known-bad-pavement (D-04): midcity (east of La Brea), boyleheights, southla/Vermont Square (12 entries)
- All 48 entries pass `validate_bbox` (0.005-deg sub-tiles, area ~2.5e-5 deg² < 0.01 deg² limit)
- Updated docstring above `_DEFAULT_LA_BBOXES` to document Phase 7 expansion
- Wired `start_captured_at="2023-01-01T00:00:00Z"` in `_build_fresh`'s `search_images` call (D-05)
- `data/eval_la/` NOT regenerated — Plan 07-04 owns the `--build --count 20 --no-clean` invocation

## Task Commits

1. **Task 1: bootstrap_ci_map50** — `278f078` (feat)
2. **Task 2: start_captured_at + expanded bboxes** — `2eb393b` (feat)

## Files Created/Modified

- `data_pipeline/eval.py` — new `bootstrap_ci_map50` function at line 169 (~118 lines); all other functions unchanged
- `data_pipeline/mapillary.py` — `search_images` extended with `start_captured_at: str | None = None`; params dict updated
- `scripts/fetch_eval_data.py` — `_DEFAULT_LA_BBOXES` expanded 12→48 entries; `_build_fresh` wires `start_captured_at`; docstring updated

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan action literal contained 11 zones (44 entries); verify check required ≥48**

- **Found during:** Task 2 verification
- **Issue:** The plan action section described "20 zones × 4 = 80 entries" but only specified 11 distinct zones in the Python literal, yielding 44 entries. The verify step asserts `len(_DEFAULT_LA_BBOXES) >= 48` (12 zones minimum).
- **Fix:** Added `culvercity` as a 6th spread zone (D-02 geographic spread, south-central direction not yet covered by the other 5 spread zones). Culver City center at ~(-118.40, 34.02) is distinct from residential (West LA, 34.05) and inglewood (33.96). Sub-tile parent: (-118.405, 34.015, -118.395, 34.025). Reaches 12 zones × 4 = 48 entries, within the 12-15-zone target.
- **Files modified:** `scripts/fetch_eval_data.py`
- **Commit:** `2eb393b`

## Known Stubs

None — no UI-rendering data paths touched. `data/eval_la/` regeneration (the actual images) is deferred to Plan 07-04 as designed.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: injection | data_pipeline/mapillary.py | `start_captured_at` forwarded to `requests.get` query string — mitigated: `requests` URL-encodes the value; default call site in `fetch_eval_data.py` uses hard-coded literal `"2023-01-01T00:00:00Z"`, no operator-controlled passthrough (T-07-mapillary-injection per plan threat register) |

## Forward Reference

Plan 07-04 runs `python scripts/fetch_eval_data.py --build --count 20 --no-clean` to materialize ~960 candidate images (48 sub-tiles × 20) across all 12 zones. The `start_captured_at="2023-01-01T00:00:00Z"` filter is now active for all Mapillary queries in that run. After download, the operator hand-labels in CVAT (GATE A) targeting ≥150 positive bboxes.

Plan 07-06 uses `bootstrap_ci_map50` for the D-11 non-overlapping-CI win check: trained model vs re-evaluated baseline on the new test split, comparing mAP@0.5 95% CIs.

## Self-Check: PASSED

Files exist:
- data_pipeline/eval.py: FOUND
- data_pipeline/mapillary.py: FOUND
- scripts/fetch_eval_data.py: FOUND

Commits:
- 278f078: FOUND (feat(07-02): implement bootstrap_ci_map50)
- 2eb393b: FOUND (feat(07-02): add start_captured_at filter + expand _DEFAULT_LA_BBOXES)

Function checks:
- bootstrap_ci_map50 in eval.py: FOUND
- start_captured_at param in mapillary.py: FOUND
- _DEFAULT_LA_BBOXES with 48 entries: FOUND
