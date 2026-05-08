---
phase: 02-real-data-detector-accuracy
plan: 03
subsystem: ml
tags: [python, mapillary, dataset, fetch, security, sha256, cli, pytest]

# Dependency graph
requires:
  - phase: 02-real-data-detector-accuracy
    provides: "Plan 02-01 added YOLO_MODEL_PATH + HUGGINGFACE_TOKEN to .env.example. Plan 03 preserves those sections and appends MAPILLARY_ACCESS_TOKEN in matching style."
provides:
  - "data_pipeline.mapillary.search_images / download_image — shared Mapillary API v4 client consumed by Phase 2 fetch_eval_data.py AND Phase 3 ingest_mapillary.py"
  - "data_pipeline.mapillary.validate_bbox — Pitfall-3 0.01-deg² DoS guard with IEEE-754 tolerance"
  - "data_pipeline.mapillary.verify_manifest / write_manifest — SHA256 manifest round-trip with constant-time compare, path-traversal guard, and hex-format validation"
  - "scripts/fetch_eval_data.py --verify-only (default) / --build CLI; D-18 exit codes 0/1/3"
  - "data/eval_la/manifest.json committed skeleton (version 1.0, empty files array) + data/eval_la/.gitkeep"
  - ".gitignore Phase 2 eval-dataset block: exclude data/eval_la/* but keep manifest.json, data.yaml, .gitkeep"
  - ".env.example MAPILLARY_ACCESS_TOKEN= block with CC-BY-SA 4.0 attribution note"
affects: [02-02-eval-harness, 02-04-finetune, 02-05-publish-writeup, 03-mapillary-ingestion]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Framework-agnostic Mapillary client in data_pipeline/ (matches scripts/iri_sources.py convention) — cross-phase reusable"
    - "SHA256 manifest round-trip with hmac.compare_digest (Security V6, constant-time compare)"
    - "Path-traversal guard via `'..' in Path(rel).parts` check (Security V5)"
    - "Bbox DoS pre-flight: validate_bbox fires before requests.get() in search_images"
    - "Split-by-sequence_id with random.Random(42) to avoid Mapillary test-set contamination (Pitfall 7)"
    - "Metadata+download in same pass to honor thumbnail URL TTL (Pitfall 5)"
    - "data/eval_la/ selective .gitignore (contents excluded, manifest/data.yaml/.gitkeep tracked)"

key-files:
  created:
    - data_pipeline/mapillary.py
    - scripts/fetch_eval_data.py
    - data/eval_la/manifest.json
    - data/eval_la/.gitkeep
    - backend/tests/test_mapillary.py
    - backend/tests/test_fetch_eval_data.py
  modified:
    - .env.example
    - .gitignore

key-decisions:
  - "Mapillary client lives in data_pipeline/mapillary.py (not scripts/) so Phase 3's ingest_mapillary.py can reuse it without a scripts-to-scripts import"
  - "validate_bbox guards 0.01 deg² with a 1e-9 IEEE-754 tolerance so corners whose product hits a float artifact (e.g. 0.1 * 0.1 = 0.010000000000000002) are not falsely rejected"
  - "Image id validation: re.fullmatch(r'[0-9]+', image_id) before using the id as a filename (T-02-20) rejects path-separator injection"
  - "SHA256 hex validated by re.compile(r'^[0-9a-f]{64}$') before hmac.compare_digest (T-02-15) — catches malformed manifests before the constant-time compare"
  - "Default LA bboxes: 3 zones (downtown, residential, freeway) each 0.01×0.01 deg²; ~100 images/zone × 3 = 300 image target matches D-09"
  - "_build_fresh writes empty .txt label stubs under labels/<split>/ for the operator to hand-label with CVAT — keeps YOLO directory layout contract intact"
  - "Subprocess smoke tests for CLI exit codes (test_fetch_eval_data.py) — new pattern in this repo; mirrors eventual CI pre-merge check"

patterns-established:
  - "Sibling-helper-module-to-a-script: CLI lives in scripts/fetch_eval_data.py, domain logic in data_pipeline/mapillary.py (same split as scripts/ingest_iri.py + scripts/iri_sources.py)"
  - "Module-top env read: MAPILLARY_TOKEN = os.environ.get(...) — matches backend/app/db.py and Plan 01's YOLO_MODEL_PATH_ENV"
  - "Phase 2 selective .gitignore: large-on-disk Mapillary-derived content excluded; single manifest.json + data.yaml + .gitkeep tracked for reproducibility"

requirements-completed: [REQ-real-data-accuracy]

# Metrics
duration: ~40min
completed: 2026-04-23
---

# Phase 2 Plan 03: LA Eval Dataset Tooling Summary

**Shared Mapillary v4 client + fetch_eval_data CLI with SHA256 constant-time manifest verify, bbox DoS guard, and sequence-grouped 70/20/10 splits for the LA pothole eval set.**

## Performance

- **Duration:** ~40 min
- **Started:** 2026-04-23T19:17:00Z (approximate; session start after worktree rebase)
- **Completed:** 2026-04-23T19:55:00Z
- **Tasks:** 3 of 3 complete
- **Files modified:** 8 (6 created, 2 modified)

## Accomplishments

- Shared `data_pipeline/mapillary.py` client (290 LOC) with 5 public functions — consumed by this plan's fetcher AND flagged in the module docstring as the Phase 3 `ingest_mapillary.py` entry point. Keeps framework-agnostic surface (no argparse / sys.exit).
- `scripts/fetch_eval_data.py` (332 LOC) CLI with `--verify-only` (default, safe) and `--build` (network + writes) modes, D-18 exit codes (0/1/3), default LA bboxes in three zones (downtown, residential, freeway-adjacent), sequence-grouped train/val/test split with seed=42, and empty-label stubs for the operator to hand-label.
- Security mitigations wired and tested: constant-time SHA256 compare via `hmac.compare_digest` (T-02-13, Security V6), path-traversal rejection (T-02-14, Security V5), malformed/uppercase SHA256 hex rejection (T-02-15), image-id injection guard (T-02-20), bbox DoS guard that fires before any network I/O (T-02-18, Pitfall 3).
- CC-BY-SA 4.0 attribution flow: `source_mapillary_id` recorded per file in every manifest, explicit license text in manifest skeleton, `.env.example` comment documents the requirement for downstream redistribution (T-02-19).
- 30 new tests (26 unit + 4 subprocess smoke), all green in 0.28s. No network I/O, no real MAPILLARY_ACCESS_TOKEN required, ultralytics not needed.
- `.gitignore` teaches git to track `data/eval_la/{manifest.json, data.yaml, .gitkeep}` while excluding the large image/label content — contributors can `fetch_eval_data.py --build` locally after configuring the token.

## Task Commits

Each task was committed atomically:

1. **Task 1: Author data_pipeline/mapillary.py — shared Mapillary client** — `98ed82e` (feat)
2. **Task 2: Author scripts/fetch_eval_data.py — CLI + manifest skeleton + .env/.gitignore updates** — `4b346f6` (feat)
3. **Task 3: Author test_mapillary.py + test_fetch_eval_data.py** — `407cfee` (test; also includes the Rule 1 bbox-tolerance fix)

Phase verification: all commits from base `cabecae` -> `407cfee`.

## Files Created/Modified

- `data_pipeline/mapillary.py` — **created** (290 LOC). `validate_bbox`, `search_images`, `download_image`, `verify_manifest`, `write_manifest`, plus private helpers `_sha256_of_file`, `_validate_manifest_path`. Module-top reads `MAPILLARY_ACCESS_TOKEN` env var at import (lazy — not required unless `search_images` is called).
- `scripts/fetch_eval_data.py` — **created** (332 LOC). Thin CLI over `data_pipeline.mapillary`. `_verify`, `_build_fresh`, `main` with argparse (mutually-exclusive `--verify-only` / `--build`), and D-18 exit constants (`EXIT_OK`, `EXIT_OTHER`, `EXIT_MISSING_DATA`).
- `data/eval_la/manifest.json` — **created**. Committed skeleton: `{"version": "1.0", "source_bucket": "placeholder…", "license": "CC-BY-SA 4.0 (…)", "files": []}`. Regenerated by `--build`.
- `data/eval_la/.gitkeep` — **created**. Preserves the directory in git so `--verify-only` can fail cleanly on a fresh clone with exit 3 and a fetch hint.
- `backend/tests/test_mapillary.py` — **created**. 26 tests in 4 classes: `TestValidateBbox` (6), `TestSearchImagesMocked` (4), `TestDownloadImageMocked` (4), `TestManifestVerification` (12).
- `backend/tests/test_fetch_eval_data.py` — **created**. 4 subprocess smoke tests for D-18 exit codes.
- `.env.example` — **modified**. Appended `# ----- Mapillary API (eval-set + Phase 3 ingestion) -----` block with the `MAPILLARY_ACCESS_TOKEN=` placeholder, CC-BY-SA attribution note, and a pointer to Phase 3's `ingest_mapillary.py` for cross-phase reuse. Preserved existing Plan 01 YOLO_MODEL_PATH + HUGGINGFACE_TOKEN sections exactly.
- `.gitignore` — **modified**. Appended Phase 2 eval-dataset block: excludes `data/eval_la/*` but explicitly un-ignores `manifest.json`, `data.yaml`, `.gitkeep`.

## Decisions Made

- **Default bbox zones chosen for CONTEXT.md geographic diversity** (CLAUDE discretion per D-04/D-15): DTLA `(-118.258, 34.043, -118.248, 34.053)`, West-LA residential `(-118.400, 34.050, -118.390, 34.060)`, Hollywood-adjacent freeway `(-118.340, 34.060, -118.330, 34.070)`. Each is a 0.01×0.01 deg² box (0.0001 deg² actual area), well inside the Pitfall-3 limit.
- **Split-by-sequence_id with seed=42** (Pitfall 7): every sequence `seq_id` lands entirely in one split, preventing contaminated test sets from adjacent-frame near-duplicates. Matches `scripts/seed_data.py` convention.
- **Empty-label stubs on --build**: the fetcher writes `labels/<split>/<image_id>.txt` as empty files so the operator can drop CVAT-exported YOLO labels into place later without re-running the fetcher. The manifest records these stubs too so `--verify-only` can detect tampering post-labeling.
- **`--verify-only` exits 3 via early `manifest_path.exists()` check instead of letting `verify_manifest` raise FileNotFoundError** — surfaces a human-readable `--build` hint before bubbling an exception, while still catching the exception path in `main()` as a fallback.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] IEEE-754 tolerance in `validate_bbox`**
- **Found during:** Task 3 (running `test_mapillary.py::TestValidateBbox::test_bbox_at_limit_ok`)
- **Issue:** The plan's own acceptance test asserts "area = 0.01 deg² exactly -> OK (<=)". But `(0.1 - 0.0) * (0.1 - 0.0)` in IEEE-754 float arithmetic yields `0.010000000000000002`, which tripped `area > MAX_BBOX_AREA_DEG2` and falsely rejected an at-limit bbox. Real-world lat/lon corners can produce similar artifacts.
- **Fix:** Added `_BBOX_AREA_TOLERANCE = 1e-9` constant and changed the comparison to `area > MAX_BBOX_AREA_DEG2 + _BBOX_AREA_TOLERANCE`. `MAX_BBOX_AREA_DEG2 = 0.01` stays exactly as specified in the plan (acceptance criterion still passes). A 1e-9 deg² tolerance corresponds to ~0.1mm at LA's latitude — negligibly above the documented API limit.
- **Files modified:** `data_pipeline/mapillary.py`
- **Verification:** `test_bbox_at_limit_ok` passes; `test_oversized_bbox_raises` still catches the 0.25 deg² case; `test_small_bbox_ok` still catches the 0.0001 deg² case; `test_search_oversized_bbox_fails_before_network` confirms the pre-flight still fires.
- **Committed in:** `407cfee` (part of Task 3 commit alongside the test suite that exposed the bug)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Small correctness fix; does not expand scope. Plan executed as specified otherwise.

## Issues Encountered

- **System Python is 3.9.6, repo conftest uses PEP-604 `dict | None`:** The worktree host `/usr/bin/python3` is 3.9, which chokes on `backend/tests/conftest.py` (transitively imports `backend/app/cache.py` with `dict | None` syntax). Resolution: reused `/tmp/rq-venv` (Python 3.12.13 venv created by Plan 02-01 executor) to run pytest. No project file changed. This is a recurring host-environment issue already documented in Plan 02-01's summary — future executors on this host should continue using `/tmp/rq-venv`.
- **Plan acceptance criterion "grep -c 'requests.get' returns 0" is overly literal:** The plan's prescribed test code itself contains the string `requests.get` inside `patch("data_pipeline.mapillary.requests.get", ...)` calls, so the criterion as literally written cannot hold. Interpreted by intent: "no unpatched `requests.get` at test body level." Every occurrence in `test_mapillary.py` is inside a `patch(...)` call, inside a `with patch(...)` block, or inside a docstring/comment. Semantic criterion satisfied — no real network I/O possible in any test.

## User Setup Required

The plan carries a `user_setup:` block for `MAPILLARY_ACCESS_TOKEN`, but its only consumer in this plan is the `--build` mode of `scripts/fetch_eval_data.py`. Building the real 300-image dataset is an operator task performed after Plan 03 merges (CONTEXT.md explicitly notes Plan 03 delivers *tooling*, not dataset content). For Plan 02 (eval harness), only `--verify-only` is required, and the committed manifest skeleton + empty files array make `--verify-only` succeed without any token.

**Operator action (out-of-plan, pre-Plan-02-finetune):**
1. Sign up at https://www.mapillary.com/signup.
2. Create a developer app at https://www.mapillary.com/dashboard/developers and copy the Client Token.
3. Add `MAPILLARY_ACCESS_TOKEN=<token>` to `.env`.
4. Run `python3 scripts/fetch_eval_data.py --build` and then hand-label the downloaded images with CVAT (or any YOLO-1.1-export tool).

## Known Stubs

- `data/eval_la/manifest.json` is a **deliberate skeleton** (files: []). Documented in the plan `<output>` and CONTEXT.md: Plan 03 ships tooling + skeleton; the operator populates it later via `--build` + hand-labeling. Not a wire-up gap — `--verify-only` against the skeleton exits 0 (tested in `test_verify_ok_on_empty_manifest`).
- `_build_fresh` writes empty `labels/<split>/<image_id>.txt` files; YOLO treats empty label files as "no pothole", so this is valid YOLO data and explicit in the user-facing print: "NEXT: hand-label images under …". No consumer of this plan depends on populated label content (Plan 02 uses its own `backend/tests/fixtures/` mini-eval set).

## Next Phase Readiness

- Plan 02-02 (eval harness) can call `verify_manifest` and `search_images` from `data_pipeline.mapillary` directly if it needs reference-set smoke tests; primary eval runs against `backend/tests/fixtures/` per VALIDATION.md.
- Plan 02-04 (fine-tune) will consume `data/eval_la/data.yaml` (generated by `--build`) and `images/train/` + `labels/train/`. No further client work required — the same `data_pipeline.mapillary` import surface is stable.
- Phase 3 `scripts/ingest_mapillary.py` will import the entire `data_pipeline.mapillary` module unchanged. Documented in module docstring as the cross-phase reuse point.

## Self-Check: PASSED

- [x] `data_pipeline/mapillary.py` FOUND (290 LOC)
- [x] `scripts/fetch_eval_data.py` FOUND (332 LOC)
- [x] `data/eval_la/manifest.json` FOUND (version 1.0, empty files)
- [x] `data/eval_la/.gitkeep` FOUND
- [x] `backend/tests/test_mapillary.py` FOUND (26 tests)
- [x] `backend/tests/test_fetch_eval_data.py` FOUND (4 tests)
- [x] `.env.example` MODIFIED — contains `MAPILLARY_ACCESS_TOKEN=` plus CC-BY-SA comment
- [x] `.gitignore` MODIFIED — contains `data/eval_la/*` exclusion and `!data/eval_la/manifest.json` un-ignore
- [x] Commit `98ed82e` FOUND (Task 1)
- [x] Commit `4b346f6` FOUND (Task 2)
- [x] Commit `407cfee` FOUND (Task 3)
- [x] All 30 tests pass in 0.28s
- [x] `python3 scripts/fetch_eval_data.py --manifest /nonexistent.json --root /tmp/nope` exits 3 with --build hint
- [x] `MAPILLARY_ACCESS_TOKEN= python3 -c "import data_pipeline.mapillary"` exits 0

---
*Phase: 02-real-data-detector-accuracy*
*Completed: 2026-04-23*
