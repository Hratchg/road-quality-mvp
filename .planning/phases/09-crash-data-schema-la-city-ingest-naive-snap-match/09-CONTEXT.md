# Phase 9: Crash-Data Schema + LA City Ingest + Naive Snap-Match - Context

**Gathered:** 2026-05-08
**Status:** Ready for planning

<domain>
## Phase Boundary

By end of phase, `python scripts/ingest_crashes.py --source lacity` against the local stack:
1. Pulls LA City open-data crash records from Socrata API (`d5tf-ez2w`) for the locked time window
2. Maps `mocodes` → three-tier severity (`fatal | injury | pdo`)
3. Snaps each crash point to the single nearest road segment within `LACITY_SNAP_M`
4. Writes rows to a new `crash_records` table with `(source, source_record_id)` UNIQUE for idempotent re-ingest
5. Outputs a structured run-summary JSON

`db/migrations/004_crash_records.sql` is mounted into the docker init flow and applies idempotently. No frontend changes; no scoring changes; no routing changes (those land in Phase 10).

**In scope:** Migration 004, `data_pipeline/lacity_socrata.py`, `data_pipeline/lacity_mocodes.py`, `scripts/ingest_crashes.py`, naive single-segment snap-match, run-summary JSON, integration tests against committed CSV fixture.

**Out of scope (deferred to v0.4.1 / explicit decision):**
- SWITRS/TIMS source — operator workflow + manual download; v0.4.1
- Fractional intersection snap-match — naive single-nearest is shipped with documented limitation; v0.4.1
- Exponential recency decay — flat 5-year window; v0.4.1
- `record_status` provisional/final tracking — only relevant once SWITRS lands; v0.4.1
- `crash_norm` computation + `compute_scores.py` extension — Phase 10
- Cost formula update + locked routing weights — Phase 10
- Frontend changes — Phase 11

</domain>

<decisions>
## Implementation Decisions

### Time Window
- **D-09-01:** LA City fetch is anchored to **2019-03-01 → 2024-03-01** (5 full pre-freeze years, ending at LAPD's NIBRS migration freeze). Implemented as `--start-date 2019-03-01 --end-date 2024-03-01` argparse defaults; both env-overridable. Rationale: portal frozen since 2024-03 means rolling-from-today gets only ~3y of usable data with gaps; anchored gives 5 full representative years and quarterly refresh is a genuine no-op (data won't change).
- **D-09-02:** Document the freeze + window choice in `docs/CRASH_INGEST.md` and the run-summary so operators understand why row counts don't change quarter-over-quarter.

### Snap Tolerance
- **D-09-03:** `LACITY_SNAP_M` default = **50 m**, env-tunable. Tighter than SWITRS's 75 m because LA City `mocodes`-derived geocoding has decent precision. Drops above ~5% of input rows trigger a runbook check (widen the env var or investigate data quality).
- **D-09-04:** `crash_records.snap_distance_m` is recorded for audit; `dropped_outside_snap` counter exposed in run-summary for tuning visibility.

### Test Strategy
- **D-09-05:** Integration tests use a **committed CSV fixture of ~200 real LA City rows** at `data/crashes_la/lacity_fixture.csv`. Stable, no network dependency in CI, no `LACITY_APP_TOKEN` secret leak risk. Fixture refreshed manually at quarterly cadence (or when SWITRS lands in v0.4.1).
- **D-09-06:** No live LA City API hit in CI. Manual smoke test against the live API is part of operator runbook (`docs/CRASH_INGEST.md`), not the test suite. Per the v0.3.0 KEY LESSON 4 ("auth-or-no-auth is a product decision, not a phase decision"), we lock the test-data source decision now and don't drift back.
- **D-09-07:** Fixture rows hand-picked to cover: (a) all three severity tiers, (b) at least 1 mid-block crash, (c) at least 1 intersection crash, (d) at least 1 row that should drop because it's outside any segment's snap radius, (e) at least 1 row with a comma-separated multi-`mocodes` value. ~200 rows is enough for distribution coverage without bloating the repo.

### Run-Summary Verbosity
- **D-09-08:** Run-summary JSON shape (mid-verbosity per user choice):
  ```json
  {
    "source": "lacity",
    "fetched": <int>,
    "inserted": <int>,
    "skipped_duplicate": <int>,
    "dropped_outside_snap": <int>,
    "errors": <int>,
    "snap_distance_m": {"p50": <float>, "p95": <float>, "max": <float>},
    "by_severity": {"fatal": <int>, "injury": <int>, "pdo": <int>},
    "started_at": "<ISO8601>",
    "duration_s": <float>
  }
  ```
- **D-09-09:** Run-summary written to stdout AND optionally to a file via `--summary-out path/to/summary.json`. Mirrors the v0.3.0 Phase 3 Plan 03-04 structured run-summary pattern.

### Schema (Migration 004)
- **D-09-10:** New `crash_records` table with these columns (final):
  ```sql
  id BIGSERIAL PRIMARY KEY,
  source TEXT NOT NULL CHECK (source IN ('lacity')),  -- expanded to 'switrs' in v0.4.1
  source_record_id TEXT NOT NULL,                       -- LA City: dr_no
  severity TEXT NOT NULL CHECK (severity IN ('fatal','injury','pdo')),
  occurred_at DATE NOT NULL,
  snapped_segment_id BIGINT REFERENCES road_segments(id) ON DELETE SET NULL,
  snap_distance_m DOUBLE PRECISION,
  geom GEOMETRY(POINT, 4326) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  ```
  Plus `UNIQUE INDEX idx_crash_records_source_id ON crash_records(source, source_record_id)` for ON-CONFLICT idempotency. Plus GIST index on `geom`. **`record_status` deferred to v0.4.1** (only relevant once SWITRS lands).
- **D-09-11:** `segment_scores.crash_norm DOUBLE PRECISION NOT NULL DEFAULT 0.0` added by migration 004 even though it is populated in Phase 10 — keeps the schema migration atomic and the LEFT JOIN COALESCE(0) safety net intact for the Phase 9 → 10 gap.
- **D-09-12:** Migration 004 mirrors `002_mapillary_provenance.sql` exactly: `CREATE TABLE IF NOT EXISTS`, separate `CREATE UNIQUE INDEX IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, `DROP CONSTRAINT IF EXISTS` then `ADD CONSTRAINT` for the CHECK. Applies cleanly in both fresh-init AND re-apply-on-existing-DB scenarios.

### Mocode → Severity Mapping
- **D-09-13:** `data_pipeline/lacity_mocodes.py` exposes `map_mocodes_to_severity(mocodes_str: str) -> str` that:
  - Splits comma-separated `mocodes` field
  - Looks up each code in an explicit `MOCODE_SEVERITY_MAP` dict
  - Returns the highest-severity tier present (`fatal` > `injury` > `pdo`)
  - **Raises `ValueError` on any unknown code** — no silent default, no fallback to `pdo` (per Pitfall 2 + KEY LESSON 2 from v0.3.0 Phase 7 operator-style drift)
- **D-09-14:** Wave-0 RED test loads `lacity_fixture.csv`, asserts every row's mocodes successfully maps; loads a synthetic row with `mocodes="ZZZ99"` and asserts `ValueError`. Test name: `test_unknown_mocode_raises_value_error`.

### Idempotency
- **D-09-15:** ON CONFLICT DO NOTHING on `(source, source_record_id)` UNIQUE. Mirrors v0.3.0 Phase 3 D-08. Re-running the script on the same data produces zero new rows; re-fetch from Socrata is allowed (cheap, idempotent at DB layer). LA City's `dr_no` (district report number) is the `source_record_id`.
- **D-09-16:** No deletion logic in this phase. Future quarterly refreshes of LA City data will be no-ops (portal frozen). When SWITRS lands in v0.4.1, the operator runbook will document any `--wipe-source switrs` flag that may be needed.

### Snap-Match (naive)
- **D-09-17:** Reuses `ST_DWithin geography + ORDER BY geom <-> point + LIMIT 1` SQL primitive from `snap_match_image()` in `scripts/ingest_mapillary.py`. Lifted into a shared helper `data_pipeline/snap.py::snap_point_to_segment(conn, lon, lat, snap_meters)` so both Mapillary and crash ingest pipelines share the same primitive. **Single-nearest-segment only — no fractional intersection attribution** (deferred to v0.4.1; documented in disclaimer copy).
- **D-09-18:** Crashes outside `snap_meters` are dropped (NOT inserted). Counted in `dropped_outside_snap`. No "best-effort attribution to nearest-anyway" fallback — if it's outside the radius, it's not in the data.

### Operator Environment
- **D-09-19:** `scripts/ingest_crashes.py` runs from the host `/tmp/rq-venv` (Python 3.12), NOT inside the backend container. Locked memory-pinned pattern from v0.3.0: backend container doesn't mount `scripts/`, ingest scripts run host-side and connect to DB via `DATABASE_URL`. README + `docs/CRASH_INGEST.md` document this.
- **D-09-20:** `LACITY_APP_TOKEN` env var loaded via the project's Python `.env` parser (per memory-pinned pattern: don't `source .env`, parse via Python and emit quoted KEY='VALUE'). Token is NOT required for read-only Socrata access (works without auth at lower rate limit) — token is recommended for production runs and required for CI smoke. Document both paths.

### Claude's Discretion
The following implementation details are NOT user gray areas — Claude/planner decides during planning:
- Exact pagination size for Socrata fetch (default `$limit=1000` mirrors mapillary.py)
- Internal class structure for `lacity_socrata.py` (one module-level function vs class — match Mapillary client style)
- Test fixture exact 200 rows — Claude picks during plan execution to satisfy D-09-07 coverage criteria
- Run-summary `started_at` / `duration_s` precision — sensible defaults
- argparse subcommand structure — match `ingest_mapillary.py` patterns

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & milestone scope
- `.planning/REQUIREMENTS.md` — REQ-crash-ingest-lacity, REQ-crash-snap-match (acceptance criteria authoritative for Phase 9 close)
- `.planning/PROJECT.md` § Current Milestone (v0.4.0 goal + locked anti-features) + § Constraints (load-bearing routing/scoring contracts)
- `.planning/ROADMAP.md` § Phase 9 (success criteria + dependencies)

### Research grounding
- `.planning/research/SUMMARY.md` — cross-doc consensus + build-order chain + data-source surprises
- `.planning/research/STACK.md` — geopandas>=1.0 bump rationale; sodapy rejection; LA City Socrata dataset URL + endpoint shape
- `.planning/research/ARCHITECTURE.md` — schema decisions (a–g); snap-match approach (75m vs 25m tolerance rationale, naive vs intersection-buffer); migration ordering
- `.planning/research/PITFALLS.md` § Pitfall 2 (severity-code drift), § Pitfall 4 (intersection ambiguity — DEFERRED in v0.4.0; documented), § Pitfall 13 (synthetic-test-data integrity)

### Phase 3 ancestor patterns (reuse, don't reinvent)
- `.planning/milestones/v0.3.0-phases/03-mapillary-ingestion-pipeline/03-01-PLAN.md` — migration 002 idempotent pattern (the model for migration 004)
- `.planning/milestones/v0.3.0-phases/03-mapillary-ingestion-pipeline/03-03-PLAN.md` — Mapillary ingest core (the model for ingest_crashes.py: target resolution, snap-match SQL, ON CONFLICT upsert)
- `.planning/milestones/v0.3.0-phases/03-mapillary-ingestion-pipeline/03-04-PLAN.md` — `--wipe-synthetic` pattern + run-summary JSON shape (the model for D-09-08)
- `.planning/milestones/v0.3.0-phases/03-mapillary-ingestion-pipeline/03-RESEARCH.md` — Mapillary pipeline research (snap tolerance rationale, idempotency strategy)

### Live codebase (read for current shape)
- `db/migrations/001_initial.sql` — base schema (`road_segments` table, GIST index name `idx_segments_geom`)
- `db/migrations/002_mapillary_provenance.sql` — exact pattern for migration 004
- `db/migrations/003_users.sql` — most recent migration; 004 follows numerically
- `data_pipeline/mapillary.py` — Socrata-client model (env-var token, paged generator, `requests`-only)
- `scripts/ingest_mapillary.py` — driver structure model (argparse subcommands, snap-match call site, ON CONFLICT upsert via `execute_values`)
- `scripts/ingest_mapillary.py::snap_match_image()` — SQL primitive to lift into shared `data_pipeline/snap.py`

### Codebase maps (existing intel)
- `.planning/codebase/STACK.md`
- `.planning/codebase/STRUCTURE.md`
- `.planning/codebase/CONCERNS.md`
- `.planning/codebase/CONVENTIONS.md`
- `.planning/codebase/TESTING.md`

### v0.3.0 lessons-learned (anti-pattern pins)
- `.planning/RETROSPECTIVE.md` § Key Lessons (lessons 1, 2, 3, 4 all relevant to Phase 9 risk profile)
- `.planning/milestones/v0.3.0-phases/05-cloud-deployment/05-LESSONS-LEARNED.md` § flyctl ssh console -C anti-pattern (relevant to Phase 12 deploy, not Phase 9, but planner should be aware for build-order)

### External
- LA City open-data dataset: `https://data.lacity.org/Public-Safety/Traffic-Collision-Data-from-2010-to-Present/d5tf-ez2w/data`
- Socrata SoQL docs: `https://dev.socrata.com/foundry/data.lacity.org/d5tf-ez2w` (endpoint shape, `mocodes` field semantics, paging)
- LAPD NIBRS migration freeze: documented in `.planning/research/STACK.md` and `.planning/research/SUMMARY.md` (relevant to D-09-01)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`scripts/ingest_mapillary.py::snap_match_image()`** — exact SQL primitive needed for crash snap-match. Lift into `data_pipeline/snap.py::snap_point_to_segment(conn, lon, lat, snap_meters)` so both pipelines share it.
- **`data_pipeline/mapillary.py` module shape** — env-var token pattern, paged generator, `requests`-only HTTP, no `sodapy`. Mirror it as `data_pipeline/lacity_socrata.py`.
- **`scripts/ingest_mapillary.py` argparse + driver structure** — model for `scripts/ingest_crashes.py`. Reuse `--summary-out` flag pattern, `--limit` for testing, `--source` for routing-filter selectivity.
- **psycopg2 `execute_values` + ON CONFLICT DO NOTHING** — bulk upsert idiom proven at 125k Mapillary rows; same shape for crashes.
- **`db/migrations/002_mapillary_provenance.sql`** — line-by-line template for migration 004 (idempotent `IF NOT EXISTS` everywhere).

### Established Patterns
- **Idempotency via `(source, source_record_id)` UNIQUE** — Phase 3 proved this works at scale; rerunning ingest is safe.
- **Run-summary JSON written to stdout AND optional `--summary-out` file** — Phase 3 Plan 03-04 pattern.
- **Wave-0 RED tests pin contracts before implementation** — v0.3.0 Phase 7 / Phase 8 RED test pattern. Apply to D-09-14 (`test_unknown_mocode_raises_value_error`) and D-09-17 fixtures.
- **Backend container does NOT mount `scripts/`** — host venv `/tmp/rq-venv` for ingest. Memory-locked pattern.
- **Python `.env` parser, NOT `source .env`** — for `LACITY_APP_TOKEN` plus `MAPILLARY_TOKEN` etc. Memory-locked pattern (tokens contain pipes).

### Integration Points
- **Migration 004 mounts into `db/migrations/`** — ordering enforced by filename prefix (003 → 004).
- **Docker init flow** — `docker-compose.yml` already mounts `db/migrations` as the init volume; new SQL file picked up automatically on next `docker compose up --build`.
- **`scripts/ingest_crashes.py` connects via `DATABASE_URL`** — same pattern as `seed_data.py`, `ingest_iri.py`, `ingest_mapillary.py`. No new DB-connection plumbing.
- **`crash_records.snapped_segment_id` FK to `road_segments(id)`** — `ON DELETE SET NULL` matches `segment_defects` semantics (deleting a road shouldn't delete the historical record).
- **Phase 10 reads `crash_records` via correlated subquery in `compute_scores.py`** — Phase 9 doesn't touch `compute_scores.py` (build-order separation).

</code_context>

<specifics>
## Specific Ideas

- **D-09-07 fixture coverage criteria** — explicit list of edge cases (multi-mocodes, intersection vs mid-block, dropped-outside-snap, all severity tiers). Planner picks the actual rows to satisfy these criteria.
- **D-09-13 mocode mapping is fail-loud** — references v0.3.0 Phase 7 negative result (operator labeling drift surfaced too late). Planner should write the RED test FIRST, then the mapping.
- **D-09-12 migration mirrors 002 exactly** — every `IF NOT EXISTS`, every `DROP IF EXISTS` then `ADD`. No clever simplifications. Planner reads `002_mapillary_provenance.sql` line-by-line as the template.

</specifics>

<deferred>
## Deferred Ideas

(All scope creep candidates were caught in milestone-scoping; nothing surfaced in Phase 9 discussion that needs new entries.)

### Already deferred to v0.4.1 (per REQUIREMENTS.md and locked here)
- SWITRS/TIMS source — `crash_records.source CHECK` will be widened from `('lacity')` to `('lacity','switrs')` in v0.4.1 migration; existing Phase 9 schema accommodates without rewrite
- Fractional intersection snap-match — `data_pipeline/snap.py::snap_point_to_segment()` is a single-nearest function; v0.4.1 adds `snap_point_to_intersection()` as an alternate path with fractional weights
- Exponential recency decay — `crash_norm` formula in Phase 10 starts as flat-window-weighted; v0.4.1 adds `weight = exp(-age_years / TAU)` factor
- `record_status` provisional/final — column not added in migration 004; v0.4.1 migration adds it (additive, non-breaking)

### Out-of-scope-for-v0.4.0 entirely
- Per-hour / time-of-day weighting — locked anti-feature
- Naming intersections in UI — locked anti-feature (litigation risk)
- Crash heatmap overlay — locked anti-feature (segment color encodes via cost)

</deferred>

---

*Phase: 09-Crash-Data Schema + LA City Ingest + Naive Snap-Match*
*Context gathered: 2026-05-08*
