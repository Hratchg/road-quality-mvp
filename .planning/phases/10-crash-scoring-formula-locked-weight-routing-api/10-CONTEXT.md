# Phase 10: Crash Scoring Formula + Locked-Weight Routing API - Context

**Gathered:** 2026-05-08
**Status:** Ready for planning
**Mode:** Auto-generated via /gsd-discuss-phase 10 --auto (decisions sourced from v0.4.0 locked scoping in PROJECT.md / REQUIREMENTS.md / ROADMAP.md / 09-VERIFICATION.md hand-offs)

<domain>
## Phase Boundary

Per-segment `crash_norm` is pre-baked into `segment_scores` via a severity-weighted, length-normalized, p95-capped sum over `crash_records`. The `/route` API drops user-tunable weight sliders in favor of module constants `W_IRI=0.40, W_POT=0.35, W_CRASH=0.25` while remaining backwards-compatible (silently ignores legacy `weight_iri` / `weight_potholes` request fields, returns a `Deprecation` response header). `GET /segments` is extended to expose `crash_norm` per feature so Phase 11 frontend can render the data-vintage caption without a backend redeploy.

This phase does NOT touch:
- `routing.py` cost computation beyond the locked-weight swap (no inline crash-aggregation SQL — pinned anti-pattern from PROJECT.md "Phase 10 must NOT inline crash-aggregation SQL into routing.py")
- Frontend (`ControlPanel.tsx` / `RouteFinder.tsx` / `MapView.tsx`) — Phase 11
- Fly.io deploy or Migration 004 cloud apply — Phase 12
- The `crash_records` ingest pipeline — locked in Phase 9
- SWITRS / fractional snap-match / TAU-3y decay / equity audit — deferred to v0.4.1

</domain>

<decisions>
## Implementation Decisions

### Locked Weight Constants (REQ-route-api-locked-weights)
- **D-10-01:** Module constants live in `backend/app/scoring.py`: `W_IRI = 0.40`, `W_POT = 0.35`, `W_CRASH = 0.25`. Exact float literals; no env var overrides.
- **D-10-02:** `compute_segment_cost(travel_time_s, iri_norm, pothole_total, crash_norm)` signature drops the `w_iri` / `w_pot` parameters. Returns `travel_time_s + W_IRI*iri_norm + W_POT*pothole_total + W_CRASH*crash_norm`. No normalization step (the constants already sum to 1.0).
- **D-10-03:** `normalize_weights()` is kept-but-unused with `# DEPRECATED v0.4.0 — remove after one milestone of confidence` comment (per pending-todos in STATE.md "mark `# DEPRECATED v0.4.0` rather than delete (test compatibility)"). Existing v0.2.0 unit tests for `normalize_weights` continue to pass unchanged. Removal is deferred.

### Severity Weighting (REQ-crash-scoring-formula)
- **D-10-04:** Severity weights `FATAL_WEIGHT = 8`, `INJURY_WEIGHT = 3`, `PDO_WEIGHT = 1` as named constants in `backend/app/scoring.py`. Literature-converged routing-cost ratio per PROJECT.md key decisions; explicitly NOT the academic 100:10:1 (which saturates `crash_norm` at the 0/1 bimodal extremes — Pitfall 5).
- **D-10-05:** Single-fatal cap: cap the per-segment **raw** severity sum so one freak crash cannot dominate a long arterial. Exact cap mechanism is Claude's discretion — researcher recommends a value (e.g., `min(raw_sum, K * FATAL_WEIGHT)` for some small K, or per-segment percentile cap). Pin in unit tests once chosen.
- **D-10-06:** PDO support: schema accepts the `pdo` tier (Phase 9 added severity 0–4 — pdo is severity 0). LA City `mocodes` → PDO mapping is lossy by design (most LA City rows lack PDO codes); this is documented in the Phase 12 runbook, not blocking for Phase 10.

### Per-Segment crash_norm Formula (REQ-crash-scoring-formula)
- **D-10-07:** Per-segment formula: `raw_sum / GREATEST(length_km, 0.05)`, where `raw_sum = SUM(severity_weight)` over crashes snapped to that segment within the 5-year window. The `0.05` km floor (50m minimum) prevents short-segment divide-by-near-zero. Length is read from `road_segments.length_km` (already populated by Phase 8 baseline).
- **D-10-08:** Normalize against the **95th percentile** of all per-segment per-km severity sums across the whole dataset (`PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY raw_per_km)`). Clip the result to `[0, 1]`. This produces a long-tailed distribution, NOT the bimodal 0/1 split that academic 100:10:1 weights would produce (Pitfall 5).
- **D-10-09:** Segments with zero crashes get `crash_norm = 0` (already guaranteed by the migration 004 `DEFAULT 0.0 NOT NULL` column). The COALESCE(0) safety net works because Phase 9 made the column NOT NULL.

### `compute_scores.py` Extension (REQ-crash-scoring-formula)
- **D-10-10:** Extend `VALID_SOURCES = ("synthetic", "mapillary", "all")` to `("synthetic", "mapillary", "crash", "all")`. New `--source crash` path runs the crash correlated subquery only (does NOT touch `iri_norm` / `pothole_score_total`). `--source all` runs every source's UPDATE in sequence.
- **D-10-11:** Crash UPDATE is a **correlated subquery** against `crash_records`, NOT a JOIN-then-aggregate cross-product with `segment_defects`. Pattern (pseudocode):
  ```sql
  UPDATE segment_scores SET crash_norm = LEAST(1.0, raw_per_km / p95)
  FROM (
    SELECT rs.id,
           SUM(CASE c.severity_kabco WHEN 4 THEN FATAL_WEIGHT WHEN 3 THEN INJURY_WEIGHT ELSE PDO_WEIGHT END) / GREATEST(rs.length_km, 0.05) AS raw_per_km
    FROM road_segments rs
    LEFT JOIN crash_records c ON c.snapped_segment_id = rs.id
    GROUP BY rs.id, rs.length_km
  ) sub, (SELECT PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY raw_per_km) AS p95 FROM ...) p95v
  WHERE segment_scores.segment_id = sub.id
  ```
  Researcher refines the exact SQL; the constraint is no cross-product blowup with `segment_defects`.
- **D-10-12:** Existing `--source mapillary` and `--source synthetic` paths are unchanged (the v0.3.0 Pitfall 7 warning for `--source mapillary` against zero-Mapillary DB is preserved).

### `/route` Backwards-Compat (REQ-route-api-locked-weights)
- **D-10-13:** `RouteRequest` Pydantic model gains `model_config = ConfigDict(extra='ignore')`. `weight_iri` / `weight_potholes` Field defaults are preserved (so existing v0.2.0 integration tests still see them in the model — they're just unused by the cost computation). This is safer than removing the fields outright, which would 422-reject `extra='ignore'` payloads against `extra='forbid'`.
- **D-10-14:** `routing.py` no longer calls `normalize_weights(req.weight_iri, req.weight_potholes)`. Uses `compute_segment_cost(travel_time_s, iri_norm, pothole_total, crash_norm)` directly with `crash_norm` read from the (Phase 9 + Phase 10) populated `segment_scores.crash_norm` column via the existing temp-table pattern.
- **D-10-15:** `Deprecation` response header on every `/route` response: literal value `weight_iri,weight_potholes ignored as of v0.4.0`. Set in the FastAPI route handler via `response.headers["Deprecation"] = ...`.
- **D-10-16:** Identical-route guarantee: `POST /route {... "weight_iri": 0.99, "weight_potholes": 0.01}` returns the SAME `geojson` and `total_cost` as `POST /route` without those fields. Pinned by integration test (Pitfall 7 fix — semantic ignore, not just accepted).

### `GET /segments` crash_norm Exposure (cross-cutting for Phase 11)
- **D-10-17:** `GET /segments?bbox=...` returns `crash_norm` (numeric, 0.0 default) on every feature's `properties` dict. Additive change — non-breaking. Phase 11 frontend will consume this for the data-vintage caption; backend exposes the field NOW so Phase 11 needs no backend redeploy.
- **D-10-18:** Default to `0.0` (not `null`) for segments with no crashes so the frontend can do simple numeric comparisons.

### Validation
- **D-10-19:** ≥8 unit tests in `backend/tests/test_scoring.py` (or new `test_crash_scoring.py`) pin: severity-weight ratio (`assert FATAL_WEIGHT == 8 * PDO_WEIGHT`), length-floor math, p95 cap, single-fatal cap, no-crash-segments default to 0, locked outer constants (`assert W_IRI == 0.40`), `compute_segment_cost` signature, deprecated-but-importable `normalize_weights`.
- **D-10-20:** Histogram smoke test (manual via runbook or pytest mark): `python scripts/compute_scores.py --source crash` after Phase 9 ingest + assert ≥50% of crash-bearing segments land in `crash_norm ∈ [0.05, 0.5]` (NOT bimodal at 0/1 — Pitfall 5 verification).
- **D-10-21:** Existing 6 v0.2.0 integration tests + Phase 8 routing integration tests pass unchanged. The fatal-overweighting smoke test (5 known-safe arterials should NOT get `crash_norm > 0.5`) lives in the runbook for Phase 12.
- **D-10-22:** Test command remains `cd backend && DATABASE_URL=... PYTHONPATH=. /tmp/rq-venv/bin/python -m pytest tests/...` (host venv per project runtime memory; backend container does not mount `scripts/`).

### Documentation
- **D-10-23:** Update `README.md` (or new `docs/API.md`) section documenting:
  - Silent-ignore behavior of `weight_iri` / `weight_potholes`
  - Locked outer weights (40/35/25) and severity weights (8:3:1)
  - The `Deprecation` header
  - REQ-ID hygiene cite to commit `d0ef452` (REQUIREMENTS.md + PROJECT.md updated in same diff)

### Claude's Discretion
- Exact mechanism for the single-fatal cap (researcher recommends; pin in unit test).
- Whether to introduce a new `test_crash_scoring.py` file or extend `test_scoring.py` (default: extend existing for cohesion).
- Exact SQL of the correlated subquery (researcher refines; the constraint is no `segment_defects` cross-product).
- File location of the API documentation update (README section vs new `docs/API.md`).
- Whether `compute_scores.py --source all` runs sources sequentially or in a single multi-CTE UPDATE (default: sequential — easier to debug, matches existing pattern).

### Folded Todos (from STATE.md)
- "`normalize_weights()` becomes dead code; mark `# DEPRECATED v0.4.0` rather than delete (test compatibility)" — folded into D-10-03.
- "fatal-overweighting smoke test against 5 known-safe arterials before declaring scoring done" — partially folded as D-10-20 (histogram smoke) + deferred-to-runbook for Phase 12 (5-arterial spot check, since live data isn't available until cloud deploy).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### v0.4.0 Locked Decisions (Project-Level)
- `.planning/PROJECT.md` — v0.4.0 key decisions table; locked outer weights, severity weights, anti-features
- `.planning/REQUIREMENTS.md` §REQ-crash-scoring-formula — locked acceptance criteria
- `.planning/REQUIREMENTS.md` §REQ-route-api-locked-weights — locked acceptance criteria
- `.planning/ROADMAP.md` §Phase 10 — 5 success criteria

### Phase 9 Hand-Off (consumed by Phase 10)
- `.planning/phases/09-crash-data-schema-la-city-ingest-naive-snap-match/09-VERIFICATION.md` — explicit hand-off pointers for compute_scores.py extension
- `.planning/phases/09-crash-data-schema-la-city-ingest-naive-snap-match/09-CONTEXT.md` D-09-11 — `crash_norm DEFAULT 0.0 NOT NULL` rationale (LEFT JOIN COALESCE(0) safety net)
- `db/migrations/004_crash_records.sql` — schema target for the correlated subquery (severity_kabco column, snapped_segment_id FK)

### Existing Code (touched by Phase 10)
- `backend/app/scoring.py` — adds W_IRI/W_POT/W_CRASH constants, severity weight constants, new `compute_segment_cost` signature, deprecates `normalize_weights`
- `backend/app/models.py:9` — `RouteRequest` adds `model_config = ConfigDict(extra='ignore')`
- `backend/app/routes/routing.py` — drops `normalize_weights()` call, sets `Deprecation` header
- `scripts/compute_scores.py` — extends `VALID_SOURCES`, adds `--source crash` path
- Existing `GET /segments` route handler — extends response to include `crash_norm`

### Anti-Patterns (load-bearing — do NOT violate)
- `.planning/PROJECT.md` "Phase 10 must NOT inline crash-aggregation SQL into routing.py — pre-bake in compute_scores.py only" — locked anti-pattern from v0.3.0 Phase 8 LESSONS-LEARNED
- `.planning/PROJECT.md` Pitfall 5 — academic 100:10:1 saturates `crash_norm`; use 8:3:1
- `.planning/PROJECT.md` Pitfall 7 — semantic ignore (not just `extra='ignore'`); pin with identical-route integration test
- v0.2.0 6 integration tests + Phase 8 routing tests — must pass unchanged

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `scripts/compute_scores.py:25` — `VALID_SOURCES` tuple already exists; `--source synthetic|mapillary|all` argparse machinery extends naturally
- `backend/app/scoring.py` — single-file home for all weight constants; both routing.py and compute_scores.py import from it
- Phase 8 routing.py temp-table pattern — already reads `iri_norm` and `pothole_total` from `segment_scores`; extending to read `crash_norm` from the same row is a one-line change
- Phase 9 `crash_records.snapped_segment_id` (FK INTEGER, ON DELETE SET NULL) — correlated-subquery target

### Established Patterns
- Migration 004 added `segment_scores.crash_norm DOUBLE PRECISION NOT NULL DEFAULT 0.0` — Phase 10's UPDATE is a write-only operation against an already-existing column
- All compute-side SQL uses psycopg2 `%s` placeholders — extend the same pattern for the correlated subquery
- `pytestmark = pytest.mark.integration` (module-level) for live-DB tests — Phase 9 09-04-SUMMARY codified

### Integration Points
- `compute_scores.py` consumed by Phase 12 cloud deploy — must run cleanly via `flyctl ssh console -C "python scripts/compute_scores.py --source all"`
- `GET /segments` consumed by Phase 11 frontend — `crash_norm` field MUST be additive (non-breaking) so Phase 11 can deploy without backend coordination
- `RouteRequest` consumed by Phase 11 frontend — silent-ignore guarantee means Phase 11 frontend can drop weight_iri/weight_potholes from the POST body without breaking the contract

</code_context>

<specifics>
## Specific Ideas

- Histogram smoke test target: ≥50% of crash-bearing segments in `crash_norm ∈ [0.05, 0.5]` (not bimodal at 0/1) — Pitfall 5 verification.
- The `Deprecation` header value is exact-string locked: `weight_iri,weight_potholes ignored as of v0.4.0`. Do NOT paraphrase.
- The 0.05 km segment-length floor (50m) is the divide-by-near-zero guard — researcher should empirically confirm it doesn't affect any LA road segments shorter than 50m (which would then artificially inflate their crash_norm).

</specifics>

<deferred>
## Deferred Ideas

- **Fatal-overweighting smoke test against 5 known-safe arterials** — deferred to Phase 12 runbook (requires live LA City data which is only available post-cloud-deploy). Phase 10 ships the histogram smoke + unit tests; the 5-arterial spot check waits for Phase 12.
- **Removing `normalize_weights()` outright** — kept-but-deprecated for now. Remove "after one milestone of confidence" (i.e., post-v0.4.0 if no regressions surface).
- **Single-fatal cap calibration** — exact K constant in the cap formula is researcher-recommended; if calibration shifts post-deploy (Phase 12), it's a one-line constant change and re-run of `compute_scores.py --source crash`.
- **GET /segments pagination** — already deferred to post-v0.4.0 (PROJECT.md). Phase 10 only adds the field; if response sizes grow, pagination is its own future phase.

</deferred>

---

*Phase: 10-Crash Scoring Formula + Locked-Weight Routing API*
*Context gathered: 2026-05-08*
