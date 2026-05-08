# Roadmap: road-quality-mvp

## Overview

The MVP (M0, v0.2.0) shipped a full local-dev Docker stack routing drivers in LA on synthetic IRI + synthetic pothole scores. M1 (v0.3.0) took it to a publicly-demoable cloud deployment running on real LA Mapillary detections — including a documented-negative LA-trained detector experiment and a 2.5s cross-LA routing perf fix. M2 (v0.4.0, in progress) adds historical crash data as a third routing-cost factor with locked weights, scoped as an Option B end-to-end thin slice (LA City Socrata only, naive snap, no recency decay, no equity audit).

## Milestones

- ✅ **v0.2.0 M0 MVP** — Phases 0.1-0.7 (shipped 2026-02-23, per PRD)
- ✅ **v0.3.0 M1 Post-MVP + Public Demo** — Phases 1-8 (shipped 2026-05-08) — see `milestones/v0.3.0-ROADMAP.md`
- 📋 **v0.4.0 M2 Crash-Aware Routing** — Phases 9-12 (in progress, started 2026-05-08)

## Phases

<details>
<summary>✅ v0.2.0 M0 MVP (Phases 0.1-0.7) — SHIPPED 2026-02-23</summary>

- [x] Phase 0.1: Docker Stack + DB Init
- [x] Phase 0.2: Backend Skeleton + /health
- [x] Phase 0.3: Scoring + Pydantic Models
- [x] Phase 0.4: Seed + /segments + /route
- [x] Phase 0.5: Frontend
- [x] Phase 0.6: Caching + Admin
- [x] Phase 0.7: ML Pluggability + IRI Ingestion

Full details in PRD; not separately archived (pre-`.planning/`).

</details>

<details>
<summary>✅ v0.3.0 M1 Post-MVP + Public Demo (Phases 1-8) — SHIPPED 2026-05-08</summary>

- [x] Phase 1: MVP Integrity Cleanup (4/4 plans) — completed 2026-04-23
- [x] Phase 2: Real-Data Detector Accuracy (5/5 plans) — completed 2026-04-25
- [x] Phase 3: Mapillary Ingestion Pipeline (5/5 plans) — completed 2026-04-26
- [x] Phase 4: Authentication (5/5 plans) — completed 2026-04-27 (subsequently superseded by d0ef452 for public demo)
- [x] Phase 5: Cloud Deployment (5/5 plans) — completed 2026-04-28
- [x] Phase 6: Public Demo Launch (4/4 plans) — completed 2026-04-28
- [x] Phase 7: LA-Trained Detector (7/8 plans, 07-07 skipped per D-13 negative) — completed 2026-05-07 (DOCUMENTED NEGATIVE)
- [x] Phase 8: Routing Performance (5/5 plans) — completed 2026-05-07

Full details in `milestones/v0.3.0-ROADMAP.md`. Audit: `milestones/v0.3.0-MILESTONE-AUDIT.md` (passed).

</details>

### v0.4.0 M2 Crash-Aware Routing (Phases 9-12) — IN PROGRESS

- [ ] **Phase 9: Crash-Data Schema + LA City Ingest + Naive Snap-Match** — Migration 004, `scripts/ingest_crashes.py`, `data_pipeline/lacity_socrata.py`, `data_pipeline/lacity_mocodes.py`, `snap_match_crash()`; LA City rows land in `crash_records` with single-segment FK
- [ ] **Phase 10: Crash Scoring Formula + Locked-Weight Routing API** — `compute_scores.py --source crash`, `crash_norm` p95-capped, module constants `W_IRI/W_POT/W_CRASH = 0.40/0.35/0.25`, silent-ignore Pydantic `extra='ignore'`, deprecation header
- [ ] **Phase 11: Frontend Slider Removal + Liability Disclaimer + Data-Vintage Caption** — `ControlPanel.tsx` strips IRI/pothole sliders (max-extra-minutes preserved), `RouteFinder.tsx` drops the field from `/route` POST, disclaimer + caption rendered with locked copy
- [ ] **Phase 12: Cloud Deploy + First LA City Ingest + Verification + Doc Carryforward** — Migration 004 applied via `flyctl ssh console -C` (locked anti-pattern), first ingest + recompute against live DB, backend+frontend redeploy, manual route spot-checks, `.env.example` + README document `ROUTE_FILTER_BUFFER_DEG` / `ROUTE_FILTER_WIDEN_FACTOR` (carryforward)

## Phase Details

### Phase 9: Crash-Data Schema + LA City Ingest + Naive Snap-Match
**Goal**: LA City crash records (Socrata `d5tf-ez2w`, 5-year window) are ingested into a new `crash_records` table, three-tier severity is mapped from `mocodes`, each crash is snapped to its single nearest road segment within `LACITY_SNAP_M`, and re-running the script is a no-op.
**Depends on**: Phase 8 (production schema baseline 001/002/003; routing.py temp-table pattern)
**Requirements**: REQ-crash-ingest-lacity, REQ-crash-snap-match
**Success Criteria** (what must be TRUE):
  1. `db/migrations/004_crash_records.sql` applies cleanly to a fresh local Postgres after 001 → 002 → 003, AND a second apply on the same DB is a no-op (idempotent `CREATE IF NOT EXISTS` + `ADD COLUMN IF NOT EXISTS` per the v0.3.0 migration-002 precedent)
  2. `python scripts/ingest_crashes.py --source lacity` against the local stack inserts ≥1 row into `crash_records` for every distinct LA City `incident_id` within the LA viewbox, populates `severity` + `snapped_segment_id` + `snap_distance_m`, and a re-run inserts zero new rows
  3. `data_pipeline/lacity_mocodes.py` maps every `mocodes` value present in a 200-row LA City fixture to one of `fatal | injury | pdo`, AND raises `ValueError` on a synthetic unknown code (Wave-0 RED test per v0.3.0 KEY LESSON 2 — code-set drift surfaces loudly, never silently defaults to PDO)
  4. Run-summary JSON includes `dropped_outside_snap` counter; crashes farther than `LACITY_SNAP_M` from any segment are NOT inserted (audited by counting `crash_records` rows whose `snap_distance_m > LACITY_SNAP_M` — must be zero)
  5. 5-test integration suite passes: idempotent re-ingest, snap-distance correctness on a synthetic mid-block crash, dropped-out-of-bounds counter, FK preservation when a `road_segments` row is deleted (`ON DELETE SET NULL`), run-summary JSON shape
**Plans** (4 plans, 3 waves):
- [ ] 09-01-PLAN.md — Migration 004 (crash_records table + segment_scores.crash_norm column) + Wave-0 RED idempotency test [Wave 1]
- [ ] 09-02-PLAN.md — KABCO mocode→severity mapper (`data_pipeline/lacity_mocodes.py`) + shared snap primitive (`data_pipeline/snap.py`) + their unit tests [Wave 2, parallel with 09-03]
- [ ] 09-03-PLAN.md — Socrata SoQL client (`data_pipeline/lacity_socrata.py`) + committed CSV fixture (`data/crashes_la/lacity_fixture.csv`) + mock-based client tests [Wave 2, parallel with 09-02]
- [ ] 09-04-PLAN.md — Driver CLI (`scripts/ingest_crashes.py`) + 5-test integration suite + `.env.example` updates [Wave 3]

### Phase 10: Crash Scoring Formula + Locked-Weight Routing API
**Goal**: Per-segment `crash_norm` is pre-baked into `segment_scores` from a severity-weighted, length-normalized, p95-capped sum of `crash_records`, and `/route` uses module constants `W_IRI=0.40, W_POT=0.35, W_CRASH=0.25` while silently accepting (and ignoring) legacy `weight_iri` / `weight_potholes` request fields.
**Depends on**: Phase 9 (`crash_records` populated; `segment_scores.crash_norm` column exists)
**Requirements**: REQ-crash-scoring-formula, REQ-route-api-locked-weights
**Success Criteria** (what must be TRUE):
  1. `python scripts/compute_scores.py --source all` after a Phase-9 ingest writes non-zero `crash_norm` to ≥100 `segment_scores` rows; `--source crash` runs the same correlated subquery without touching `iri_norm` / `pothole_score_total`; `--source mapillary` (existing v0.3.0 path) is unchanged
  2. Severity weights `fatal:injury:pdo = 8:3:1` live as named constants in `backend/app/scoring.py`, the per-segment raw sum is divided by `GREATEST(length_km, 0.05)`, normalized against the 95th percentile across all segments, and clipped to `[0, 1]` — verified by the score-histogram smoke test (≥50% of segments with crashes land in the 0.05–0.5 range, NOT bimodal at 0/1 per Pitfall 5)
  3. `compute_segment_cost(travel_time_s, iri_norm, pothole_total, crash_norm)` returns `travel_time_s + 0.40*iri_norm + 0.35*pothole_total + 0.25*crash_norm` with no normalization step; `normalize_weights()` is removed or marked `# DEPRECATED v0.4.0` and unused
  4. `POST /route {... "weight_iri": 0.99, "weight_potholes": 0.01}` returns the SAME route geometry as `POST /route` without those fields (semantic ignore, not just accepted; Pitfall 7 fix), AND the response carries header `Deprecation: weight_iri,weight_potholes ignored as of v0.4.0`; truly-unexpected fields like `evil_field: true` still pass through `extra='ignore'` without 422 (silent compat is the locked CON-route-api contract)
  5. 8+ unit tests pin the scoring math (severity ratio, length floor, p95 cap, no-crash-segments default to 0, locked constants); all 6 v0.2.0 + Phase-8 routing integration tests pass unchanged
**Plans**: TBD

### Phase 11: Frontend Slider Removal + Liability Disclaimer + Data-Vintage Caption
**Goal**: The Control Panel renders only the `max_extra_minutes` slider (IRI + pothole sliders gone), the Route Finder shows the locked liability disclaimer copy at the route-selection moment, the Map View carries a one-line crash-data-vintage caption, and `/segments` exposes `crash_norm` so future debugging is possible without backend redeploy.
**Depends on**: Phase 10 (backend silently ignores slider fields; sending them is safe)
**Requirements**: REQ-frontend-slider-removal
**Success Criteria** (what must be TRUE):
  1. `frontend/src/components/ControlPanel.tsx` renders the `max_extra_minutes` slider but no IRI or pothole slider; `frontend/src/components/RouteFinder.tsx` POSTs to `/route` with no `weight_iri` or `weight_potholes` keys (verified by reading the network request body in a manual smoke OR a Playwright/RTL assertion if one exists)
  2. The disclaimer text adjacent to the "find route" button is the EXACT locked copy `"Routes incorporate historical crash data from LA City open-data (through March 2024). This is informational, not a safety guarantee — always drive defensively."` — string match, not paraphrase (Pitfall 9 — disclaimer is at the moment-of-decision, not in a hamburger menu)
  3. The Map View static caption is the EXACT locked copy `"Crash data: LA City open-data through March 2024. Single-segment attribution; intersection distribution to be added in a future release."` (NOT a new map layer, NOT a heatmap, NOT per-segment markers — locked anti-features per PROJECT.md)
  4. `GET /segments?bbox=...` against the local stack returns features whose `properties` dict contains a `crash_norm` numeric field on EVERY feature (default 0 for segments with no crashes; non-zero for ≥1 segment after Phase 9 + Phase 10 have run)
  5. Manual smoke: open Map View on `localhost:3000` after a fresh ingest+recompute, see ≥1 segment with non-zero `crash_norm` in the GeoJSON; open Route Finder, see disclaimer rendered next to the action button; verify NO new map layer toggle has appeared
**Plans**: TBD
**UI hint**: yes

### Phase 12: Cloud Deploy + First LA City Ingest + Verification + Doc Carryforward
**Goal**: Migration 004 lands on the Fly.io database via the locked `flyctl ssh console -C` anti-pattern, the first LA City ingest + score recompute completes against the live DB, backend + frontend redeploy via GH Actions, the live demo at `https://road-quality-frontend.fly.dev/` returns crash-aware routes within the Phase-8 5s perf budget, and the v0.3.0 carry-forward env-var documentation lands in the same milestone-close diff.
**Depends on**: Phase 11 (full feature stack ready to ship)
**Requirements**: REQ-crash-cloud-deploy, REQ-route-filter-env-vars-doc
**Success Criteria** (what must be TRUE):
  1. Pre-deploy `df -h` rehearsal on the Fly DB volume confirms ≥1.5× the expected `crash_records` + GiST footprint is free; migration 004 is applied via `flyctl ssh console -C "psql ..."` (NEVER `flyctl proxy` — locked v0.3.0 Phase 5 anti-pattern; wireguard timeout → Postgres recovery crash loop). `\d+ crash_records` and `\d+ segment_scores` against the live DB show the new schema
  2. First quarterly LA City ingest run completes end-to-end against the live DB; `compute_scores.py --source all` runs successfully post-ingest; `SELECT COUNT(*) FROM segment_scores WHERE crash_norm > 0` returns ≥100 on prod
  3. Backend redeployed with locked-weights code; frontend redeployed with slider-removal + disclaimer; GH Actions deploy.yml passes for the v0.4.0 commit; cold cross-LA route via the live demo returns 200 with a route geometry in <5s (Phase 8 perf budget intact); 3-route manual spot-check (DTLA-local + cross-LA + a known-safe arterial like Wilshire) produces routes that "make sense to a local" (Pitfall 5 sanity gate against fatal-overweighting)
  4. `.env.example` lists `ROUTE_FILTER_BUFFER_DEG=0.03` and `ROUTE_FILTER_WIDEN_FACTOR=2.0` with one-line descriptions; `README.md` Configuration section documents both env vars and cross-links `08-PERF-NUMBERS.md` for the tuning rationale (carryforward from v0.3.0 Phase 8 tech debt)
  5. First-deploy delta report records: count of `crash_records` rows by source, count of segments with non-zero `crash_norm`, and the 3 spot-checked route URLs/screenshots — committed under `.planning/phases/12-*/` so the milestone-close audit can find it
**Plans**: TBD

## Progress

| Phase | Milestone | Plans Complete | Status   | Completed  |
| ----- | --------- | -------------- | -------- | ---------- |
| 0.1-0.7 | v0.2.0 | — | Complete | 2026-02-23 |
| 1. MVP Integrity Cleanup | v0.3.0 | 4/4 | Complete | 2026-04-23 |
| 2. Real-Data Detector Accuracy | v0.3.0 | 5/5 | Complete | 2026-04-25 |
| 3. Mapillary Ingestion Pipeline | v0.3.0 | 5/5 | Complete | 2026-04-26 |
| 4. Authentication | v0.3.0 | 5/5 | Complete (superseded) | 2026-04-27 |
| 5. Cloud Deployment | v0.3.0 | 5/5 | Complete | 2026-04-28 |
| 6. Public Demo Launch | v0.3.0 | 4/4 | Complete | 2026-04-28 |
| 7. LA-Trained Detector | v0.3.0 | 7/8 | Complete (negative) | 2026-05-07 |
| 8. Routing Performance | v0.3.0 | 5/5 | Complete | 2026-05-07 |
| 9. Crash-Data Schema + LA City Ingest + Snap-Match | v0.4.0 | 0/4 | Plans defined | — |
| 10. Crash Scoring Formula + Locked-Weight Routing API | v0.4.0 | 0/? | Not started | — |
| 11. Frontend Slider Removal + Disclaimer + Caption | v0.4.0 | 0/? | Not started | — |
| 12. Cloud Deploy + First Ingest + Verification + Doc Carryforward | v0.4.0 | 0/? | Not started | — |

---
*Roadmap initialized: 2026-04-23 after ingest synthesis + codebase map*
*v0.3.0 archived: 2026-05-08 — 8 phases / 41 plans / 73 tasks shipped*
*v0.4.0 phases 9-12 added: 2026-05-08 — 7 reqs / 4 phases (Option B end-to-end thin slice)*
