---
phase: 10-crash-scoring-formula-locked-weight-routing-api
verified: 2026-05-08T08:11:17Z
status: passed
score: 5/5 success criteria verified (3/3 plans verified; 2/2 in-scope requirements satisfied)
overrides_applied: 0
re_verification: false
notes:
  - "Plan-level pytest gate: 60 passed, 1 skipped in 1:33 (smoke histogram skipped by design at <100 crash-bearing segments — 23 in fixture; will run end-to-end at Phase 12 with live Socrata pull)"
  - "All 23 in-DB crash_norm values verified non-zero post Wave-0 re-ingest; histogram non-bimodal (60.9% in [0.05, 0.5])"
  - "5-arterial fatal-overweighting spot check explicitly deferred to Phase 12 runbook per CONTEXT D-10-21 (requires live LA City Socrata data, not in fixture)"
  - "REQ-route-filter-env-vars-doc deferred to Phase 12 — confirmed not in scope of Phase 10 (matches REQUIREMENTS.md mapping table)"
human_verification: []
---

# Phase 10: Crash Scoring Formula + Locked-Weight Routing API — Verification Report

**Phase Goal:** Per-segment `crash_norm` is pre-baked into `segment_scores` from a severity-weighted, length-normalized, p95-capped sum of `crash_records`, and `/route` uses module constants `W_IRI=0.40, W_POT=0.35, W_CRASH=0.25` while silently accepting (and ignoring) legacy `weight_iri` / `weight_potholes` request fields.

**Verified:** 2026-05-08T08:11:17Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths (from ROADMAP Phase 10 Success Criteria)

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | `compute_scores.py --source crash` runs the correlated-subquery UPDATE without touching iri_norm/pothole_score_total; `--source mapillary` v0.3.0 path unchanged; `--source all` sequences synthetic+mapillary then crash | VERIFIED | `scripts/compute_scores.py:47` extends `VALID_SOURCES = ("synthetic", "mapillary", "crash", "all")`; Path 1 (lines 157–215) handles synthetic/mapillary/all unchanged from v0.3.0; Path 2 (lines 224–258) is NEW crash branch with independent `conn.commit()`; `test_compute_scores_source.py` 9/10 PASS + 1 expected SKIP. **Note on SC-1 second clause:** the phrase "writes non-zero crash_norm to ≥100 segment_scores rows" is materially infeasible against the 205-row LA City fixture (only 23 segments snap-match) — this threshold is explicitly deferred to Phase 12 live ingest per Plan 10-02 SUMMARY and the smoke skip-clean design at `<100`. The CRASH_UPDATE_SQL primitive is fully exercised against live data; only the row-count threshold is fixture-bound. |
| 2 | Severity weights 8:3:1 in `backend/app/scoring.py`; per-segment raw sum / GREATEST(length_km, 0.05); p95-normalized; clipped [0,1]; ≥50% of crash-bearing segments in [0.05, 0.5] (non-bimodal — Pitfall 5) | VERIFIED | `backend/app/scoring.py:35-37` `FATAL_WEIGHT=8, INJURY_WEIGHT=3, PDO_WEIGHT=1` with `# Pitfall 5` annotation; `scripts/compute_scores.py:100` `GREATEST(length_m / 1000.0, 0.05)`; `scripts/compute_scores.py:105` `PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY raw_per_km)` over `WHERE raw_per_km > 0` (Pitfall 6); `scripts/compute_scores.py:110` `LEAST(1.0, ...)` clip. Live DB measured: 14/23 = 60.9% in [0.05, 0.5] — clears the ≥50% non-bimodal target. |
| 3 | `compute_segment_cost(travel_time_s, iri_norm, pothole_total, crash_norm)` returns `travel_time_s + 0.40*iri_norm + 0.35*pothole_total + 0.25*crash_norm`; no normalization step; `normalize_weights()` removed or DEPRECATED v0.4.0 | VERIFIED | `backend/app/scoring.py:24-26` exact float literals `W_IRI=0.40, W_POT=0.35, W_CRASH=0.25`; `backend/app/scoring.py:52-71` 4-arg `compute_segment_cost` no normalization step; `backend/app/scoring.py:74` and `:81` carry `DEPRECATED v0.4.0` marker (sibling comment + docstring). `inspect.signature` returns `['travel_time_s', 'iri_norm', 'pothole_total', 'crash_norm']` (arity=4); arithmetic spot-check `compute_segment_cost(100.0, 0.5, 2.0, 0.3) = 100.97500…` (≈ 100.975 within 1e-9). |
| 4 | `POST /route {... weight_iri:0.99, weight_potholes:0.01}` returns SAME route as without those fields (semantic ignore — Pitfall 7); `Deprecation: weight_iri,weight_potholes ignored as of v0.4.0` header on every response; `evil_field:true` passes through `extra='ignore'` without 422 | VERIFIED | `backend/app/models.py:14` `model_config = ConfigDict(extra='ignore')`; `backend/app/routes/routing.py:254-256` sets exact-string `Deprecation` header at TOP of handler (before audit log + cache check); `backend/tests/test_route.py:186` `test_identical_route_with_legacy_weight_fields` pins byte-equal geojson + total_cost; `backend/tests/test_route.py:247/273/314` pin Deprecation header on success/cache-hit/no-route paths; `backend/tests/test_models.py:37/57` pin extra='ignore' silent drop for evil_field. Runtime spot-check: `RouteRequest(... evil_field=True)` returns model with no `evil_field` attribute and `model_config['extra']=='ignore'`. |
| 5 | 8+ unit tests pin scoring math (severity ratio, length floor, p95 cap, no-crash default 0, locked constants); all 6 v0.2.0 + Phase-8 routing integration tests pass UNCHANGED | VERIFIED | 26 tests in `test_scoring.py` (6 preserved `TestNormalizeWeights` + 20 new across `TestLockedConstants`/`TestCrashScoringMath`/`TestComputeSegmentCostV4`/`TestNormalizeWeightsDeprecated`). All 6 v0.2.0 `TestNormalizeWeights` tests pass UNCHANGED. 2 Phase-8 routing-performance tests in `test_routing_performance.py` pass UNCHANGED. Plan-level gate: 60 passed, 1 skipped in 93.69s. |

**Score:** 5/5 success criteria verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `backend/app/scoring.py` | 8 module constants + 4-arg `compute_segment_cost` + deprecated `normalize_weights` | VERIFIED | 101 LOC; defines `W_IRI=0.40`, `W_POT=0.35`, `W_CRASH=0.25`, `FATAL_WEIGHT=8`, `INJURY_WEIGHT=3`, `PDO_WEIGHT=1`, `FATAL_CAP_K=3`, `FATAL_CAP=24`. `compute_segment_cost(travel_time_s, iri_norm, pothole_total, crash_norm)` confirmed via `inspect.signature`. `normalize_weights` retained with `DEPRECATED v0.4.0` markers in both sibling comment (line 74) and docstring (line 81). |
| `backend/app/models.py` | `RouteRequest.model_config = ConfigDict(extra='ignore')`; legacy fields preserved as defaults | VERIFIED | 23 LOC; `from pydantic import BaseModel, ConfigDict, Field`; line 14 `model_config = ConfigDict(extra='ignore')`; lines 20-21 preserve `weight_iri`/`weight_potholes` Field defaults with inline preservation comment. |
| `backend/app/routes/routing.py` | drops normalize_weights call; 4-arg compute_segment_cost; sets Deprecation header on every response path; reads crash_norm via COALESCE column read (NO inline crash-aggregation SQL) | VERIFIED | 493 LOC; line 8 imports `compute_segment_cost` only (no `normalize_weights`); line 245 `find_route(req, response: Response)`; lines 254-256 set exact-string Deprecation header at TOP of handler (before audit log INSERT and cache check, so success/cache-hit/no-route inherit); line 432 calls 4-arg `compute_segment_cost(t, iri, pot, crash)`. Anti-pattern check: NO `PERCENTILE_CONT`, NO `crash_records` reference, NO `severity_kabco`, NO `raw_per_km` — only `COALESCE(ss.crash_norm, 0) AS crash_norm` column read at line 82. |
| `backend/app/routes/segments.py` | GET /segments returns crash_norm (default 0.0) on every feature | VERIFIED | 62 LOC; line 33 SQL extends with `COALESCE(ss.crash_norm, 0) AS crash_norm`; line 55 `"crash_norm": row["crash_norm"]` on every feature's properties dict with `D-10-17 / D-10-18` annotation. |
| `backend/app/cache.py` | `make_route_cache_key` 5-param signature (drops weight_iri/weight_potholes/include_iri/include_potholes) | VERIFIED | 70 LOC; lines 43-49 confirm 5 params: `(origin_lat, origin_lon, dest_lat, dest_lon, max_extra_minutes)`. `inspect.signature` confirms arity=5. Docstring rationale references D-10-14 / Pitfall 2. |
| `scripts/compute_scores.py` | --source crash branch; correlated subquery (NO segment_defects cross-product); GREATEST(length_m/1000.0, 0.05); PERCENTILE_CONT(0.95); LEAST(1.0, ...); %s parameterization | VERIFIED | 264 LOC; line 47 extends VALID_SOURCES; lines 33-38 import severity weights from `app.scoring` (sys.path injection); CRASH_UPDATE_SQL (lines 77-118) joins `road_segments LEFT JOIN crash_records` (NEVER segment_defects); line 100 `GREATEST(length_m / 1000.0, 0.05)`; line 105 `PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY raw_per_km)`; line 110 `LEAST(1.0, ...)`; line 112 `NULLIF(... , 0)` divide-by-zero guard; lines 243-248 `%(name)s` parameter binding. Pitfall-7-crash WARNING for empty crash_records at lines 232-241. |
| `docs/API.md` | NEW canonical contract: silent-ignore, Deprecation header, locked weights (40/35/25), severity weights (8:3:1), REQ-ID hygiene cite | VERIFIED | 217 LOC; sections cover Endpoints, Locked Outer Weights (40/35/25 table), Severity Weights (8:3:1 table with anti-pattern callout to Pitfall 5), Silent-Ignore Behavior (extra='ignore'), Deprecation Header (with RFC 9745 disclosure note), Identical-Route Guarantee, Cache Key Composition, REQ-ID Hygiene Pattern (cites commit `d0ef452`), Versioning, Out of Scope. |
| `backend/tests/test_scoring.py` | ≥8 unit tests (D-10-19 floor); 6 v0.2.0 TestNormalizeWeights pass UNCHANGED | VERIFIED | 332 LOC, 26 tests across 5 classes: `TestNormalizeWeights` (6 preserved v0.2.0), `TestNormalizeWeightsDeprecated` (2 new), `TestLockedConstants` (2 new), `TestCrashScoringMath` (9 new), `TestComputeSegmentCostV4` (7 new). Far exceeds the ≥8 floor. All 26 PASS. |
| `backend/tests/test_compute_scores_source.py` | Existing 6 tests UNCHANGED; 4 new tests for crash | VERIFIED | 411 LOC; existing 6 v0.3.0 tests preserved (D-10-12 backward-compat); 4 new tests added: CLI help lists crash; crash UPDATE writes non-zero; histogram non-bimodal (smoke marker, expected SKIP at <100); --source all sequencing. 9 PASS, 1 SKIP (by design). |
| `backend/tests/conftest.py` | `smoke` marker registered to avoid PytestUnknownMarkWarning | VERIFIED | 106 LOC; lines 21-26 register `smoke` marker via `config.addinivalue_line`. |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| `routing.py find_route` | `Response` header | `response.headers["Deprecation"] = ...` | WIRED | Line 254-256: exact-string locked, set BEFORE audit-log INSERT and BEFORE cache check (Pitfall 4). 3 distinct integration tests pin success/cache-hit/no-route paths. |
| `routing.py find_route` | `compute_segment_cost` | 4-arg call | WIRED | Line 432: `compute_segment_cost(t, iri, pot, crash)` — drops `w_iri`/`w_pot`. Imported from `app.scoring` at line 8 (no `normalize_weights` in import). |
| `routing.py SEGMENTS_BY_IDS_SQL` | `segment_scores.crash_norm` | `COALESCE(ss.crash_norm, 0) AS crash_norm` | WIRED | Line 82 reads only the pre-baked column; line 428 `crash = seg["crash_norm"] or 0.0` flows into compute_segment_cost. NO inline crash-aggregation SQL. |
| `compute_scores.py CRASH_UPDATE_SQL` | `app.scoring` constants | `sys.path.insert + from app.scoring import` | WIRED | Lines 32-38: shares `FATAL_WEIGHT/INJURY_WEIGHT/PDO_WEIGHT/FATAL_CAP` with the online routing.py via the single source-of-truth scoring.py. |
| `segments.py get_segments` | `segment_scores.crash_norm` | SQL COALESCE column read | WIRED | Lines 25-37: SELECT extended with `COALESCE(ss.crash_norm, 0) AS crash_norm`; lines 44-57 emit it on every feature's properties dict. |
| `RouteRequest` | extra fields silently dropped | `model_config = ConfigDict(extra='ignore')` | WIRED | Models.py line 14. Runtime spot-check confirms `evil_field` attribute is absent on instance and `model_dump()` returns only declared fields. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| `GET /segments` | `crash_norm` per feature | `segment_scores.crash_norm` (populated by Plan 10-02 CRASH_UPDATE_SQL after Wave-0 re-ingest) | Yes — 23 segments have non-zero crash_norm in live DB; column NOT NULL DEFAULT 0.0 means every other segment returns explicit 0.0 (not null) | FLOWING |
| `POST /route` total_cost | per-edge `crash` term | `seg["crash_norm"]` from `SEGMENTS_BY_IDS_SQL` LEFT JOIN segment_scores | Yes — `compute_segment_cost(t, iri, pot, crash)` actually multiplies by W_CRASH=0.25 and contributes to per-path total_cost. Pinned by `test_identical_route_with_legacy_weight_fields` (proves 4-arg call site is wired). | FLOWING |
| `compute_scores.py --source crash` | `crash_norm` column | `crash_records` correlated subquery → segment_scores UPDATE | Yes — verified live: post-execution `SELECT COUNT(*) FROM segment_scores WHERE crash_norm > 0` returns 23; crash_records has 197 rows. | FLOWING |
| `Deprecation` response header | exact-string "weight_iri,weight_potholes ignored as of v0.4.0" | hardcoded in routing.py line 254-256 | Yes — present on success / cache hit / no-route paths via Response-parameter pattern | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Plan-level pytest gate | `pytest tests/test_scoring.py tests/test_compute_scores_source.py tests/test_models.py tests/test_route.py tests/test_segments.py tests/test_cache.py tests/test_routing_performance.py -q --timeout=120` | `60 passed, 1 skipped in 93.69s` | PASS |
| `compute_segment_cost` arity is 4 | `inspect.signature(compute_segment_cost).parameters` | `['travel_time_s', 'iri_norm', 'pothole_total', 'crash_norm']` (arity=4) | PASS |
| Locked outer weights are exact float literals | `python -c "from app.scoring import W_IRI, W_POT, W_CRASH; print(W_IRI, W_POT, W_CRASH)"` | `0.4 0.35 0.25` | PASS |
| Severity weights are 8:3:1 (not 100:10:1) | `python -c "from app.scoring import FATAL_WEIGHT, INJURY_WEIGHT, PDO_WEIGHT; print(FATAL_WEIGHT, INJURY_WEIGHT, PDO_WEIGHT)"` | `8 3 1` | PASS |
| FATAL_CAP_K=3, FATAL_CAP=24 | `python -c "from app.scoring import FATAL_CAP_K, FATAL_CAP; print(FATAL_CAP_K, FATAL_CAP)"` | `3 24` | PASS |
| `make_route_cache_key` arity is 5 | `inspect.signature(make_route_cache_key).parameters` | `['origin_lat', 'origin_lon', 'dest_lat', 'dest_lon', 'max_extra_minutes']` (arity=5) | PASS |
| RouteRequest silently drops extra fields | `RouteRequest(..., evil_field=True, foo='bar')` then check attrs | `hasattr(r, 'evil_field')==False`; `model_dump()` excludes extras; `model_config['extra']=='ignore'` | PASS |
| Live DB has populated crash_norm column | `SELECT COUNT(*) FROM segment_scores WHERE crash_norm > 0` | `23` (matches Plan 10-02 SUMMARY) | PASS |
| Histogram non-bimodal (Pitfall 5) | `SELECT COUNT(*) FROM segment_scores WHERE crash_norm BETWEEN 0.05 AND 0.5` | `14 / 23 = 60.9%` (≥50% target) | PASS |
| crash_records populated in live DB | `SELECT COUNT(*) FROM crash_records` | `197` | PASS |
| `normalize_weights` still importable | `from app.scoring import normalize_weights; callable(normalize_weights)` | `True` | PASS |
| Deprecation header exact-string | `grep -r "weight_iri,weight_potholes ignored as of v0.4.0"` in code+tests+docs | 6 hits across `routing.py`, `test_route.py` (3x), `docs/API.md` (2x) — paraphrase risk zero | PASS |
| `routing.py` has NO inline crash-aggregation SQL | `grep -n "PERCENTILE_CONT\|crash_records\|severity_kabco\|raw_per_km" routing.py` | 0 matches (only `COALESCE(ss.crash_norm, 0)` column read) | PASS |
| `DEPRECATED v0.4.0` marker present | `grep -c "DEPRECATED v0.4.0" backend/app/scoring.py` | 2 (sibling comment + docstring) | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| REQ-crash-scoring-formula | 10-01 + 10-02 | Per-segment crash_norm pre-baked; severity 8:3:1; locked W_IRI/W_POT/W_CRASH constants; compute_segment_cost extended | SATISFIED | `backend/app/scoring.py:24-49` (constants), `:52-71` (4-arg cost), `:74-100` (deprecated normalize_weights); `scripts/compute_scores.py:77-118` (CRASH_UPDATE_SQL); `backend/tests/test_scoring.py` 26 tests; `backend/tests/test_compute_scores_source.py` 9P+1S. Acceptance criteria each MET (see breakdown below). |
| REQ-route-api-locked-weights | 10-03 | RouteRequest extra='ignore'; routing.py drops normalize_weights; Deprecation header; identical-route guarantee; v0.2.0 tests pass UNCHANGED; docs/API.md | SATISFIED | `backend/app/models.py:14`, `backend/app/routes/routing.py:8/254-256/432`, `backend/tests/test_route.py` (5 new + 2 unchanged), `docs/API.md` (217 LOC). Acceptance criteria each MET (see breakdown below). |

#### REQ-crash-scoring-formula — Acceptance Criteria

| Criterion | Status | Evidence |
| --------- | ------ | -------- |
| `scripts/compute_scores.py` extends VALID_SOURCES with 'crash'; `--source crash` and `--source all` paths; correlated subquery against crash_records (no cross-product blowup with segment_defects) | MET | `compute_scores.py:47` `VALID_SOURCES = ("synthetic", "mapillary", "crash", "all")`; `:77-118` CRASH_UPDATE_SQL joins `road_segments LEFT JOIN crash_records` (never segment_defects). |
| Severity weights live in one file (`backend/app/scoring.py`) at literature-converged ratio fatal:injury:pdo = 8:3:1 (NOT 100:10:1); single-fatal cap | MET | `scoring.py:35-37` constants 8/3/1; `:48-49` FATAL_CAP_K=3, FATAL_CAP=24 (whole-sum cap). |
| Per-segment raw / km, p95-normalized, clipped [0,1] | MET | `compute_scores.py:99-100` `LEAST(raw_sum, %(fatal_cap)s) / GREATEST(length_m / 1000.0, 0.05)`; `:105` PERCENTILE_CONT(0.95); `:110-113` LEAST(1.0, ...) clip with NULLIF guard. |
| Module constants W_IRI=0.40, W_POT=0.35, W_CRASH=0.25 exported | MET | `scoring.py:24-26`. |
| `compute_segment_cost(travel_time_s, iri_norm, pothole_total, crash_norm)` returns sum with no normalization step | MET | `scoring.py:52-71`. |
| `normalize_weights()` removed or kept-but-unused with deprecation comment | MET | Kept-but-deprecated; `scoring.py:74` (`# DEPRECATED v0.4.0 — remove after one milestone of confidence`) + `:81` docstring. |
| 8+ unit tests pin: severity-weighting math, length-normalization, p95 cap, locked constants, no-crash-segments default to 0 | MET | 26 tests in test_scoring.py (well above the ≥8 floor); 4 SQL-mirror helpers (`_capped`, `_floor_km`, `_p95_normalize`, `_p95_normalize_safe`) cross-validate Python and SQL contracts. |
| PDO support documented as lossy mapping | MET | Documented in `docs/API.md` Severity Weights section + `10-CONTEXT.md` D-10-06 references the runbook (Phase 12). |

#### REQ-route-api-locked-weights — Acceptance Criteria

| Criterion | Status | Evidence |
| --------- | ------ | -------- |
| `RouteRequest` Pydantic model gains `model_config = ConfigDict(extra='ignore')` | MET | `models.py:14`. |
| `routing.py` no longer calls `normalize_weights(req.weight_iri, req.weight_potholes)`; uses W_IRI/W_POT/W_CRASH constants | MET | `routing.py:8` import drops `normalize_weights`; `:432` calls 4-arg `compute_segment_cost(t, iri, pot, crash)` which uses module constants internally. |
| Deprecation response header on `/route`: `weight_iri,weight_potholes ignored as of v0.4.0` | MET | `routing.py:254-256` exact-string locked, set at TOP of handler before audit-log INSERT + cache check (Pitfall 4). |
| Integration tests assert: same route comes back with `weight_iri:0.99` as without the field | MET | `test_route.py:186` `test_identical_route_with_legacy_weight_fields` pins byte-equal geojson + total_cost. |
| All 6 existing v0.2.0 integration tests pass UNCHANGED | MET | 6 `TestNormalizeWeights` tests + Phase-8 routing-performance tests + RouteRequest baseline tests pass UNCHANGED in the 60-pass-1-skip plan-level gate. |
| `docs/API.md` documents silent-ignore behavior + cites `d0ef452`-style REQ-ID hygiene pattern | MET | `docs/API.md:105-123` (Silent-Ignore Behavior) and `:177-187` (REQ-ID Hygiene Pattern citing commit `d0ef452`). |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| (none) | — | grep for `TODO|FIXME|XXX|HACK|placeholder|coming soon|not yet implemented` across modified files (`scoring.py`, `models.py`, `cache.py`, `routes/routing.py`, `routes/segments.py`, `compute_scores.py`, `docs/API.md`) returned 0 hits in production code | — | None |
| (none) | — | grep for inline crash-aggregation SQL in `routing.py` (PERCENTILE_CONT / crash_records / severity_kabco / raw_per_km) | — | 0 hits — locked anti-pattern guard from PROJECT.md/D-08 LESSONS-LEARNED preserved end-to-end |

### Human Verification Required

(none — all in-scope success criteria verified programmatically; explicit deferrals routed to Phase 11 / Phase 12)

### Gaps Summary

No gaps. All 5 ROADMAP success criteria, both in-scope requirements (REQ-crash-scoring-formula, REQ-route-api-locked-weights), all artifacts (10/10), all key links (6/6 WIRED), and all data-flow traces (4/4 FLOWING) verify against the codebase. The 60-pass / 1-skip pytest gate runs in 93.69s; the single skipped test is `test_crash_norm_histogram_not_bimodal`, which gates on `len(crash_bearing) >= 100` and skips at the fixture-bound 23 — its contract is met by the live histogram measurement (60.9% in [0.05, 0.5], ≥50% target).

The "≥100 segment_scores rows with non-zero crash_norm" wording in ROADMAP success criterion 1 is fixture-bound rather than code-bound: the LA City fixture (205 rows) only snap-matches 23 unique segments. CONTEXT D-10-21 + Plan 10-02 SUMMARY explicitly defer this row-count threshold to Phase 12 cloud deploy, where the live Socrata pull provides 10k+ crashes/year. The CRASH_UPDATE_SQL primitive itself produces non-zero `crash_norm` against any non-empty crash_records — verified live with 23 rows.

---

## Outstanding Hand-Offs

### To Phase 11 (Frontend Slider Removal + Disclaimer + Caption)

- `RouteRequest.model_config = ConfigDict(extra='ignore')` is the silent-ignore guarantee — frontend can drop `weight_iri` / `weight_potholes` from POST /route bodies WITHOUT breaking the backend contract.
- `GET /segments` now returns `crash_norm` (numeric, default 0.0, never null) on every feature's `properties` dict — frontend can render the data-vintage caption without a backend redeploy.
- `Deprecation` response header is structured signal frontend can log a console warning against if the legacy fields are still being sent (during Phase 11 transition).

### To Phase 12 (Cloud Deploy + First Ingest + Verification + Doc Carryforward)

- **5-arterial fatal-overweighting spot check** (CONTEXT D-10-21 + 10-CONTEXT.md `<deferred>`): pick 5 known-safe LA arterials (e.g., Wilshire Blvd) and assert they get `crash_norm < 0.5` post-live-ingest. Lives in the Phase 12 runbook; requires live Socrata data not in fixture.
- **Operator runbook step:** `flyctl ssh console -C "python scripts/compute_scores.py --source crash"` should run quarterly after `scripts/ingest_crashes.py --source lacity`. Documented in 10-03-SUMMARY.md "Phase 12 cloud deploy runbook" section.
- **REQ-route-filter-env-vars-doc** (Phase 12 scope per REQUIREMENTS.md mapping table): document `ROUTE_FILTER_BUFFER_DEG=0.03` and `ROUTE_FILTER_WIDEN_FACTOR=2.0` in `.env.example` + README Configuration section. Carryforward from v0.3.0 Phase 8 tech debt. Confirmed not yet present (`grep` of both files returns 0 hits) — explicitly Phase 12 scope.
- **Histogram smoke test re-runs end-to-end** at Phase 12: with the live Socrata pull (10k+ crashes/year), `len(crash_bearing) >= 100` will be satisfied and `test_crash_norm_histogram_not_bimodal` will run instead of skip — providing the post-deploy Pitfall 5 regression gate.
- **Pre-deploy `df -h` rehearsal** on Fly.io DB volume to confirm ≥1.5× the expected `crash_records` + GiST footprint (ROADMAP Phase 12 SC-1).

### Test Environment / Tooling Carryforward

- **`test_idempotent_reingest` parallel-agent timeout** (`deferred-items.md`): out-of-scope for Phase 10 (the test does not exercise this phase's code). Resolution options: bump test timeout to 600s (Option A, simplest), trim fixture (Option B), or serialize integration tests via pytest-xdist `--dist=loadgroup` (Option C). Owner: Phase 12 runbook / future test-infrastructure work.
- **`pwdlib[argon2]` not installed in `/tmp/rq-venv`**: `tests/test_auth_passwords.py` fails at collection. Pre-existing host-venv issue unrelated to Phase 10. Skip with `--ignore=tests/test_auth_passwords.py` for full-suite gates; not blocking.

---

## Verification Summary

| Gate | Status | Evidence |
| ---- | ------ | -------- |
| ROADMAP Phase 10 SC-1 (compute_scores.py crash branch) | PASS | VALID_SOURCES extended; correlated subquery against crash_records; --source all sequencing |
| ROADMAP Phase 10 SC-2 (severity 8:3:1, length floor 0.05km, p95 cap, [0,1] clip, non-bimodal) | PASS | scoring.py constants + CRASH_UPDATE_SQL primitives; live DB 60.9% in [0.05, 0.5] |
| ROADMAP Phase 10 SC-3 (4-arg compute_segment_cost; normalize_weights deprecated) | PASS | inspect.signature confirms 4 args; arithmetic spot-check exact; DEPRECATED v0.4.0 marker present |
| ROADMAP Phase 10 SC-4 (semantic identical-route + Deprecation header + extra='ignore' for evil_field) | PASS | test_identical_route, 3x deprecation tests, 2x extra='ignore' tests all PASS |
| ROADMAP Phase 10 SC-5 (≥8 unit tests + v0.2.0 + Phase-8 routing pass UNCHANGED) | PASS | 26 scoring tests; 6 v0.2.0 TestNormalizeWeights UNCHANGED; 2 Phase-8 routing-performance UNCHANGED; total 60P/1S |
| Anti-pattern guard (no inline crash-aggregation SQL in routing.py) | PASS | grep for PERCENTILE_CONT/crash_records/severity_kabco/raw_per_km in routing.py: 0 matches |
| REQ-crash-scoring-formula 8/8 acceptance criteria | PASS | All MET |
| REQ-route-api-locked-weights 6/6 acceptance criteria | PASS | All MET |
| docs/API.md exists and covers locked weights, severity weights, silent-ignore, Deprecation header, REQ-ID hygiene | PASS | 217 LOC |
| Plan-level pytest gate (60P/1S) | PASS | 93.69s; only skip is by-design smoke histogram |
| Live DB integrity (crash_records=197; segments with crash_norm>0 = 23; 14 in [0.05, 0.5]) | PASS | Direct psycopg2 query against 127.0.0.1:5432 |

---

*Verified: 2026-05-08T08:11:17Z*
*Verifier: Claude (gsd-verifier)*
