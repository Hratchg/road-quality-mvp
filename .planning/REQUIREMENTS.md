# Requirements: road-quality-mvp v0.4.0

**Defined:** 2026-05-08
**Milestone:** v0.4.0 Crash-Aware Routing
**Core Value (unchanged):** Given any two points in LA, show the user a route that is demonstrably smoother than the fastest route, using real road-quality data.

## Milestone Goal

Add historical crash data as a third routing-cost factor and replace user-tunable weight sliders with a single locked weighting (40 IRI / 35 pothole / 25 crash), so the public demo recommends routes that avoid both rough roads AND crash-prone segments.

**Scope chosen:** Option B end-to-end thin slice — LA City Socrata ingest only, naive single-nearest-segment snap, locked weights, frontend slider removal, Fly deploy. Multi-session expected (~6-8 hours operator + Claude time).

**Explicitly deferred** (clean v0.4.1 / v0.5.0 follow-ups, no re-architecting needed):
- SWITRS/TIMS source — requires manual operator download workflow; LA City alone is enough to prove the data flow
- Fractional intersection snap-match — naive nearest-segment is acceptable for v0.4.0; documented as known limitation
- Exponential recency decay — flat 5-year window is HSM-defensible; smooth decay is a v0.4.1 polish
- EQUITY_NOTE.md cross-neighborhood audit — process deliverable, not blocking
- Synthetic crash seed mode — operator decision; tests use real LA City data fixture

## Requirements

### Crash-Data Ingest

- [ ] **REQ-crash-ingest-lacity**: Automated pipeline pulls LA City open-data crash records (Socrata API, dataset `d5tf-ez2w`), maps the `mocodes` field to a three-tier severity (fatal / injury / pdo), snaps each point to the nearest road segment via `ST_DWithin + <-> KNN` (snap tolerance default 50m, env-tunable via `LACITY_SNAP_M`), and writes rows into a new `crash_records` table with `(source, source_record_id)` UNIQUE for idempotent re-ingest.
  - **Acceptance:**
    - `db/migrations/004_crash_records.sql` creates `crash_records` table + `segment_scores.crash_norm` column; idempotent (`CREATE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`); mounted into docker init flow
    - `data_pipeline/lacity_socrata.py` is a thin `requests`-based client mirroring `data_pipeline/mapillary.py` (env-var token via `LACITY_APP_TOKEN`, paged generator, no `sodapy` dependency)
    - `data_pipeline/lacity_mocodes.py` maps comma-separated `mocodes` to severity tier; raises `ValueError` on unknown codes
    - `scripts/ingest_crashes.py --source lacity` pulls all 5-year LA City records, snaps each, INSERTs with `ON CONFLICT DO NOTHING`
    - Re-running the script on the same data is a no-op (zero new rows on second run)
    - Run-summary JSON includes `dropped_outside_snap` counter
    - Docs: known limitation that LA City portal `d5tf-ez2w` is frozen since LAPD's March 2024 NIBRS migration (quarterly re-pulls past 2024-03 are no-ops on this source)

### Snap-Match

- [ ] **REQ-crash-snap-match**: Each crash record is attributed to its nearest road segment (single-segment), with a snap-distance audit column for spot-checking. **Intersection fractional attribution is explicitly deferred to v0.4.1** — known limitation documented in the disclaimer copy.
  - **Acceptance:**
    - `crash_records.snapped_segment_id` is set to the nearest segment within `LACITY_SNAP_M` (FK to `road_segments(id) ON DELETE SET NULL`)
    - `crash_records.snap_distance_m` records the distance for audit
    - Crashes more than `LACITY_SNAP_M` from any segment are dropped from the table and counted in the run-summary `dropped_outside_snap`
    - 5-test integration suite covers: idempotent re-ingest, snap-distance correctness, dropped-out-of-bounds counter, FK preservation on segment delete, run-summary structure
    - Limitation noted in the public-facing disclaimer: "Crashes at intersections may be attributed to a single incident segment rather than distributed across all approaches — to be addressed in a future release."

### Scoring & Routing

- [ ] **REQ-crash-scoring-formula**: Per-segment `crash_norm` is pre-baked at ingest-time into `segment_scores`, computed from a severity-weighted sum normalized to `[0, 1]`. `cost_segment` formula extends to include the third term using locked weight constants. **Replaces v0.3.0's user-tunable weight normalization with module constants.**
  - **Acceptance:**
    - `scripts/compute_scores.py` extends `VALID_SOURCES` to include `'crash'`; adds `--source crash` and `--source all` paths; correlated subquery against `crash_records` (no cross-product blowup with `segment_defects`)
    - Severity weight constants live in one file (`backend/app/scoring.py`) starting at literature-converged ratio `fatal:injury:pdo = 8:3:1` (NOT academic `100:10:1` which saturates `crash_norm`); a single fatal's per-segment contribution is capped to keep one freak crash from dominating
    - Per-segment raw score divided by segment length in km (per-mile/km is the honest substitute for unavailable AADT exposure data); normalized against the 95th percentile across all segments; clipped to `[0, 1]`
    - Module constants `W_IRI=0.40, W_POT=0.35, W_CRASH=0.25` exported from `backend/app/scoring.py`
    - `compute_segment_cost(travel_time_s, iri_norm, pothole_total, crash_norm)` returns `travel_time_s + W_IRI*iri_norm + W_POT*pothole_total + W_CRASH*crash_norm`; no normalization step
    - `normalize_weights()` removed (or kept-but-unused with deprecation comment)
    - 8+ unit tests pin: severity-weighting math, length-normalization, p95 cap, locked constants, no-crash-segments default to 0
    - Note: PDO severity is supported in the schema but LA City `mocodes`-to-PDO mapping is lossy; documented in the runbook

- [ ] **REQ-route-api-locked-weights**: `POST /route` continues to accept request bodies that include `weight_iri` / `weight_potholes` (per locked CON-route-api contract) but silently ignores the values; the server uses 40/35/25 regardless. A `Deprecation` response header signals the change.
  - **Acceptance:**
    - `RouteRequest` Pydantic model gains `model_config = ConfigDict(extra='ignore')`
    - `routing.py` no longer calls `normalize_weights(req.weight_iri, req.weight_potholes)`; uses `W_IRI / W_POT / W_CRASH` constants
    - `Deprecation` response header on `/route` carries `weight_iri,weight_potholes ignored as of v0.4.0`
    - Integration tests assert: same route comes back with `{... "weight_iri": 0.99}` as without the field
    - All 6 existing v0.2.0 integration tests pass unchanged
    - `docs/API.md` (or README API section) documents the silent-ignore behavior + cites the `d0ef452`-style REQ-ID hygiene pattern

### Frontend / Public-Facing

- [ ] **REQ-frontend-slider-removal**: Control Panel sheds the IRI weight slider + pothole weight slider; max-extra-minutes slider stays. Map View carries a one-line data-vintage legend. Route Finder shows a one-sentence liability disclaimer at the route-selection moment using "lower historical crash density," NOT "safer route."
  - **Acceptance:**
    - `frontend/src/components/ControlPanel.tsx` no longer renders IRI / pothole sliders; `max_extra_minutes` slider preserved
    - `frontend/src/components/RouteFinder.tsx` POST body to `/route` no longer includes `weight_iri` / `weight_potholes`
    - Disclaimer text adjacent to the "find route" button (not in a hamburger menu): exact copy `"Routes incorporate historical crash data from LA City open-data (through March 2024). This is informational, not a safety guarantee — always drive defensively."`
    - Map View has a small static caption (NOT a new map layer): `"Crash data: LA City open-data through March 2024. Single-segment attribution; intersection distribution to be added in a future release."`
    - `/segments` returns a `crash_norm` property on each feature (additive, non-breaking)
    - Frontend smoke test: open Map View, see ≥1 segment with non-zero `crash_norm` after ingest; open Route Finder, see disclaimer rendered
    - No new map layer / no heatmap / no per-segment crash markers (locked anti-features)

### Cloud Deployment

- [ ] **REQ-crash-cloud-deploy**: Migration 004 applies cleanly to the Fly.io database via `flyctl ssh console -C` (NOT `flyctl proxy` — locked v0.3.0 anti-pattern); first LA City ingest run completes against the live DB; backend redeploy picks up the locked weights; frontend redeploy reflects the slider removal + disclaimer; live demo at `https://road-quality-frontend.fly.dev/` returns crash-aware routes.
  - **Acceptance:**
    - Pre-deploy `df -h` rehearsal confirms volume sizing (current 5 GB volume vs. expected ~10-20 MB crash data + spatial index)
    - Migration 004 applied via `flyctl ssh console -C "psql ..."` (locked anti-pattern compliance)
    - First quarterly LA City ingest run completes end-to-end against the live DB
    - `compute_scores.py --source all` runs successfully post-ingest; `segment_scores.crash_norm` non-zero on ≥100 segments
    - Backend redeployed with locked-weights code; frontend redeployed with slider-removal + disclaimer
    - Live `POST /route` returns 200 with the new disclaimer-bearing response; cold cross-LA route stays under 5s (Phase 8 perf budget intact)
    - Live `GET /segments?bbox=...` returns features with `crash_norm` field
    - GH Actions deploy.yml passes for the v0.4.0 commit
    - First-deploy delta report: count of `crash_records` rows by source; count of segments with non-zero `crash_norm`; manual spot-check of 3 routes (DTLA-local + cross-LA + known-safe-arterial)

### Documentation Carryforward

- [ ] **REQ-route-filter-env-vars-doc**: Document the v0.3.0 Phase 8 routing-buffer env vars (`ROUTE_FILTER_BUFFER_DEG`, `ROUTE_FILTER_WIDEN_FACTOR`) in `README.md` and `.env.example` so operators know they're tunable. Carryforward from the v0.3.0 audit.
  - **Acceptance:**
    - `.env.example` lists both env vars with their defaults (0.03, 2.0) and one-line descriptions
    - `README.md` "Configuration" section (or equivalent) documents the env vars + cites `08-PERF-NUMBERS.md` for tuning rationale
    - Cross-link to `routing.py:272-298` inline header anti-pattern pin

## Out of Scope (for v0.4.0)

Explicit exclusions for v0.4.0. Re-audit at next milestone scoping.

| Feature | Reason | Likely milestone |
|---------|--------|------------------|
| SWITRS/TIMS source | Manual operator download workflow eats most of a session; LA City alone proves the data flow end-to-end | v0.4.1 |
| Fractional intersection snap-match | Highest-risk single piece; naive nearest-segment is acceptable for v0.4.0 with documented limitation | v0.4.1 |
| Exponential recency decay (TAU=3y) | Flat 5-year window is HSM-defensible; smooth decay is polish | v0.4.1 |
| `record_status` provisional/final tracking | Only relevant once SWITRS is wired up | v0.4.1 |
| EQUITY_NOTE.md cross-neighborhood audit | Process deliverable, not blocking; disclaimer alone is the legal minimum | v0.4.1 |
| Synthetic crash seed mode | Operator declined; tests use real LA City fixture | — |
| Crash heatmap / markers / separate map layer | Locked anti-feature — segment color encodes crash_norm via cost | — |
| Per-hour, time-of-day, weather weighting | Locked anti-feature | — |
| Naming intersections in UI | Litigation risk; locked anti-feature | — |
| Detector retry / Phase 7 v2 | Out of scope this milestone | v0.5.0+ |
| Auth re-enablement | Public demo target unchanged; auth modules dormant | v0.5.0+ |
| AADT integration / SPF-based EB shrinkage | Requires AADT data we don't have | v0.5.0+ |
| CCRS public CSV dataset | STACK confidence MEDIUM; defer to research | v0.5.0+ |
| Multi-city expansion | Hard-coded LA viewbox; defer until demo signal | v0.5.0+ |

## Traceability

Mapped to phases by the roadmapper.

| Requirement | Phase | Status |
|-------------|-------|--------|
| REQ-crash-ingest-lacity | Phase 9 | Pending |
| REQ-crash-snap-match | Phase 9 | Pending |
| REQ-crash-scoring-formula | Phase 10 | Pending |
| REQ-route-api-locked-weights | Phase 10 | Pending |
| REQ-frontend-slider-removal | Phase 11 | Pending |
| REQ-crash-cloud-deploy | Phase 12 | Pending |
| REQ-route-filter-env-vars-doc | Phase 12 | Pending |

**Coverage:**

- v0.4.0 requirements: 7 total, 7/7 to be mapped to phases by roadmapper

---
*Requirements defined: 2026-05-08*
*Research grounding: `.planning/research/SUMMARY.md` + STACK / FEATURES / ARCHITECTURE / PITFALLS*
