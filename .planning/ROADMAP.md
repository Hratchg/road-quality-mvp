# Roadmap: road-quality-mvp

## Overview

The MVP (M0) is shipped: a full local-dev Docker stack that routes drivers in LA based on synthetic IRI + synthetic pothole scores, with fastest-vs-best route comparison via pgRouting's `pgr_ksp`. M1 takes this from a synthetic local demo to a publicly demoable cloud deployment running on real LA pothole detections. The journey: (1) reconcile ingest-vs-code drift before building on top; (2) prove the detector works on real imagery; (3) wire an automated Mapillary-fed detection pipeline; (4) add authentication; (5) deploy to cloud with production-safe config; (6) put the demo on a public URL.

## Milestones

- ✅ **M0 MVP** — Phases 0.1-0.7 (shipped 2026-02-23, per PRD)
- 🚧 **M1 Post-MVP + Public Demo** — Phases 1-6 (active)

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

### M0 MVP (shipped) — summary

- [x] **Phase 0.1: Docker Stack + DB Init** — docker-compose.yml, PostGIS+pgRouting container, 001_initial.sql
- [x] **Phase 0.2: Backend Skeleton + /health** — FastAPI app, CORS, psycopg2, test_health
- [x] **Phase 0.3: Scoring + Pydantic Models** — normalize_weights, compute_segment_cost, RouteRequest/RouteResponse
- [x] **Phase 0.4: Seed + /segments + /route** — OSMnx LA network, synthetic IRI/potholes, /segments, /route with pgr_ksp
- [x] **Phase 0.5: Frontend** — Vite+React+Tailwind, MapView, RouteFinder, AddressInput (Nominatim), ControlPanel, Legend, RouteResults
- [x] **Phase 0.6: Caching + Admin** — cachetools TTL caches, /cache/stats, /cache/clear
- [x] **Phase 0.7: ML Pluggability** — PotholeDetector Protocol, StubDetector, YOLOv8Detector scaffold + factory, IRI ingestion CLI

### M1 Post-MVP + Public Demo (active)

- [ ] **Phase 1: MVP Integrity Cleanup** — Reconcile ingest-conflict INFO items with shipped code before building on top
- [ ] **Phase 2: Real-Data Detector Accuracy** — Run YOLOv8 on real LA imagery with a measurable eval set
- [ ] **Phase 3: Mapillary Ingestion Pipeline** — Automated pull-detect-write pipeline fed by real street imagery
- [ ] **Phase 4: Authentication** — Sign up / sign in / session enforcement on expensive endpoints
- [ ] **Phase 5: Cloud Deployment** — Deploy the stack to a cloud host with production-safe config
- [ ] **Phase 6: Public Demo Launch** — Publish the URL, verify real-data flow, link from README

## Phase Details

<details>
<summary>✅ M0 MVP (Phases 0.1-0.7) — SHIPPED 2026-02-23</summary>

### Phase 0.1: Docker Stack + DB Init
**Goal**: Reproducible local stack with spatial DB ready for routing
**Status**: Complete (M0, shipped 2026-02-23)
**Requirements**: REQ-docker-compose-stack, REQ-db-schema
**Success Criteria** (what WAS TRUE at close):
  1. `docker compose up --build` brings up db + backend + frontend
  2. PostgreSQL has PostGIS 3.4 + pgRouting 3.6 extensions installed
  3. Migration `001_initial.sql` creates all four tables with required indexes
**Plans**: Shipped

### Phase 0.2: Backend Skeleton + /health
**Goal**: Liveness-checkable FastAPI backend
**Status**: Complete (M0)
**Requirements**: REQ-health-endpoint
**Success Criteria**:
  1. `GET /health` returns `{"status": "ok"}` with HTTP 200
  2. CORS middleware active (dev: all origins)
  3. Smoke test (`test_health.py`) passes
**Plans**: Shipped

### Phase 0.3: Scoring + Pydantic Models
**Goal**: Pure functions and validated API shapes
**Status**: Complete (M0)
**Requirements**: REQ-scoring-logic, REQ-max-time-rule, REQ-pydantic-models
**Success Criteria**:
  1. `normalize_weights` handles one/both/neither-enabled cases
  2. `compute_segment_cost` matches the SPEC formula exactly
  3. RouteRequest/RouteResponse reject malformed input
**Plans**: Shipped

### Phase 0.4: Seed + /segments + /route
**Goal**: Real LA topology with synthetic data, usable via API
**Status**: Complete (M0)
**Requirements**: REQ-seed-data, REQ-iri-ingestion, REQ-segments-endpoint, REQ-route-endpoint, REQ-integration-tests
**Success Criteria**:
  1. `scripts/seed_data.py` produces 10k+ segments in `road_segments`
  2. `/segments?bbox=...` returns GeoJSON with IRI + pothole properties
  3. `/route` returns fastest + best with correct warning fallback behavior
  4. 6 integration tests run against a live DB, auto-skip when DB down
**Plans**: Shipped

### Phase 0.5: Frontend
**Goal**: Interactive map + route finder for end users
**Status**: Complete (M0)
**Requirements**: REQ-frontend-skeleton, REQ-map-view-page, REQ-route-finder-page
**Success Criteria**:
  1. Map View (`/`) renders color-coded segments based on control-panel weights
  2. Route Finder (`/route`) shows fastest (blue dashed) vs best (green solid) routes
  3. Address autocomplete + click-on-map both work for origin/destination
**Plans**: Shipped
**UI hint**: yes (historical reference only; not re-planned)

### Phase 0.6: Caching + Admin
**Goal**: Performance + operability for hot endpoints
**Status**: Complete (M0)
**Requirements**: REQ-caching-layer
**Success Criteria**:
  1. /segments cache hits return instantly within TTL
  2. /route cache hits return instantly within TTL
  3. `GET /cache/stats` and `POST /cache/clear` work
**Plans**: Shipped

### Phase 0.7: ML Pluggability + IRI Ingestion
**Goal**: Detector interface + synthetic baseline + CSV/shapefile IRI input
**Status**: Complete (M0)
**Requirements**: REQ-ml-detector-protocol, REQ-yolov8-detector, REQ-iri-ingestion, REQ-readme-docs, REQ-demo-launch
**Success Criteria**:
  1. `get_detector()` returns StubDetector when ultralytics missing, YOLOv8Detector when available
  2. `scripts/ingest_iri.py` accepts csv/shapefile/synthetic
  3. README gets someone from clone to http://localhost:3000 successfully
**Plans**: Shipped

</details>

### 🚧 M1 Post-MVP + Public Demo (active)

**Milestone Goal:** Ship the three post-MVP requirements + real-data accuracy + a public demo URL.

### Phase 1: MVP Integrity Cleanup
**Goal**: Reconcile the four ingest-conflict INFO items with the shipped code so M1 phases build on a verified foundation, not on document drift.
**Depends on**: Nothing (first M1 phase)
**Requirements**: REQ-mvp-integrity-cleanup
**Success Criteria** (what must be TRUE):
  1. `db/migrations/001_initial.sql` declares `road_segments.source`/`target` as `BIGINT`, matching the SPEC (verified by inspection or follow-up migration committed)
  2. `scripts/seed_data.py` and `docs/SETUP.md` agree on the seed radius literal (SPEC says 10 km; whichever the seed script actually uses is codified in both places)
  3. No reference to `REACT_APP_MAPBOX_TOKEN` remains anywhere in code or docs; `VITE_MAPBOX_TOKEN` is the only documented name
  4. `backend/requirements.txt` pins `psycopg2-binary` consistently with what is actually installed (2.9.11 per codebase map)
  5. A `.env.example` lives at repo root listing every env var the stack reads (DATABASE_URL, VITE_API_URL, VITE_MAPBOX_TOKEN, and any new ones added in later phases)
**Plans**: 4 plans
- [x] 01-01-PLAN.md — Verify BIGINT source/target in migration + psycopg2-binary pin consistency (SC #1 + SC #4)
- [x] 01-02-PLAN.md — Reconcile seed radius drift across README.md, docs/PRD.md, .planning/PROJECT.md (SC #2)
- [x] 01-03-PLAN.md — Retire REACT_APP_MAPBOX_TOKEN from historical design doc (SC #3)
- [x] 01-04-PLAN.md — Create repo-root .env.example with DATABASE_URL, VITE_API_URL, VITE_MAPBOX_TOKEN (SC #5)

### Phase 2: Real-Data Detector Accuracy
**Goal**: Prove the YOLOv8 detector is usable against real LA street-level imagery, with honest precision/recall numbers — so the demo has something defensible to claim.
**Depends on**: Phase 1
**Requirements**: REQ-real-data-accuracy
**Success Criteria** (what must be TRUE):
  1. A reproducible eval script (e.g., `scripts/eval_detector.py`) runs the detector on a labelled eval set and prints precision, recall, and per-severity counts
  2. `get_detector(use_yolo=True, model_path=...)` loads a real (pretrained or fine-tuned) model from a configurable path, not a hardcoded one
  3. The model path resolves from an environment variable (not CWD-relative), fixing the concerns from `.planning/codebase/CONCERNS.md`
  4. A short writeup in `docs/` records the eval methodology and current numbers, honest enough to cite in the public demo
**Plans**: 5 plans
- [x] 02-01-PLAN.md — Config Surface & Factory Wiring: YOLO_MODEL_PATH env + HF-vs-local resolution in detector_factory.py (SC #2, SC #3)
- [x] 02-02-PLAN.md — Eval Harness & Metrics: scripts/eval_detector.py + data_pipeline/eval.py (bootstrap CI, per-severity) + fixture tests (SC #1)
- [x] 02-03-PLAN.md — Mapillary Client & Dataset Fetcher: data_pipeline/mapillary.py + scripts/fetch_eval_data.py with SHA256 constant-time verify (enables SC #1)
- [x] 02-04-PLAN.md — Fine-tuning Script + Multi-Env Guide: scripts/finetune_detector.py + requirements-train.txt + docs/FINETUNE.md (D-03, D-11..D-13, D-16)
- [x] 02-05-PLAN.md — Eval Writeup + data.yaml Seed + README link: docs/DETECTOR_EVAL.md + README "Detector Accuracy" section (SC #4)

### Phase 3: Mapillary Ingestion Pipeline
**Goal**: Replace the synthetic pothole seed with a real, rerunnable pipeline that pulls Mapillary imagery, runs the detector, and writes detections into the database.
**Depends on**: Phase 2
**Requirements**: REQ-mapillary-pipeline
**Success Criteria** (what must be TRUE):
  1. A documented CLI (e.g., `scripts/ingest_mapillary.py`) takes a bbox and a limit, authenticates to Mapillary via an env-var token, downloads images, runs detection, and writes rows into `segment_defects`
  2. Rerunning the CLI on the same bbox is idempotent — no double-counted detections (dedupe by image id or equivalent)
  3. After ingestion, `scripts/compute_scores.py` refreshes `segment_scores` and `/segments` reflects real (non-synthetic) pothole data
  4. `/route` returns different rankings for real vs synthetic data on the same bbox, verifying the pipeline end-to-end
  5. Mapillary access token is env-only; no credentials in code, docker-compose, or docs
**Plans**: 5 plans
- [x] 03-01-PLAN.md — Schema migration + docker-compose mount + .gitignore + migration test (foundation for SC #2 idempotency)
- [ ] 03-02-PLAN.md — `compute_scores.py --source {synthetic|mapillary|all}` filter + tests (SC #4 demonstrability)
- [ ] 03-03-PLAN.md — `scripts/ingest_mapillary.py` core: target resolution + snap-match + ingestion loop + manifest + tests (SC #1, SC #5)
- [ ] 03-04-PLAN.md — `--wipe-synthetic` + auto-recompute + run-summary JSON + integration tests (SC #1-#4 end-to-end)
- [ ] 03-05-PLAN.md — `docs/MAPILLARY_INGEST.md` operator runbook + README link + Phase 6 cutover forward-flag

### Phase 4: Authentication
**Goal**: Users can sign up, sign in, and sign out; state-mutating and expensive endpoints require auth so the public demo can't be drained by anonymous traffic.
**Depends on**: Phase 1 (integrity)
**Requirements**: REQ-user-auth
**Success Criteria** (what must be TRUE):
  1. User can sign up with email + password via an API endpoint (UI optional for M1)
  2. User can sign in, receive a session token (or cookie), and use it on subsequent requests
  3. `POST /route` and `/cache/*` return 401 without valid credentials; `GET /health` and `GET /segments` remain public
  4. Passwords are hashed (bcrypt/argon2-equivalent), never stored as plaintext
  5. A new migration in `db/migrations/` adds the users table; the migration applies cleanly to a fresh DB via the existing init flow
**Plans**: TBD
**UI hint**: yes

### Phase 5: Cloud Deployment
**Goal**: The stack runs on a cloud host from `main` with production-safe configuration — the prerequisite for a public demo.
**Depends on**: Phase 3, Phase 4
**Requirements**: REQ-prod-deploy
**Success Criteria** (what must be TRUE):
  1. A documented deploy path (cloud provider + commands or pipeline) brings up db + backend + frontend in a non-local environment
  2. CORS is restricted to the deployed frontend origin(s); no `allow_origins=["*"]` in production config
  3. All secrets (DB creds, Mapillary token, auth signing key) come from the cloud host's secret mechanism; no committed defaults are used in prod
  4. Frontend's `VITE_API_URL` points at the deployed backend; no `localhost` in the production bundle
  5. `GET /health` reports DB reachability (not just `{"status": "ok"}`) so load-balancer probes are meaningful
  6. Database connections are pooled (psycopg2 `SimpleConnectionPool` or equivalent); under burst load the pool does not exhaust PostgreSQL's connection limit
**Plans**: TBD

### Phase 6: Public Demo Launch
**Goal**: Anyone with the URL can open the app and see real LA pothole data informing routes — the user-visible payoff of the milestone.
**Depends on**: Phase 5
**Requirements**: REQ-public-demo
**Success Criteria** (what must be TRUE):
  1. A public URL serves the live frontend; opening it requires no local setup
  2. Map View at the demo URL shows colored segments reflecting real Mapillary-ingested detections
  3. Route Finder at the demo URL (after sign-in, if auth gates `/route`) returns a fastest-vs-best comparison
  4. README links to the public URL and briefly explains what the viewer is looking at (data source + detector eval numbers)
**Plans**: TBD
**UI hint**: yes

## Progress

**Execution Order:**
Phases execute in numeric order within M1: 1 → 2 → 3 → 4 → 5 → 6. Phase 4 (auth) can start in parallel with Phase 2 or 3 once Phase 1 is complete, but Phase 5 depends on both 3 and 4.

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 0.1 Docker Stack + DB Init | M0 | — | Complete | 2026-02-23 |
| 0.2 Backend Skeleton + /health | M0 | — | Complete | 2026-02-23 |
| 0.3 Scoring + Pydantic Models | M0 | — | Complete | 2026-02-23 |
| 0.4 Seed + /segments + /route | M0 | — | Complete | 2026-02-23 |
| 0.5 Frontend | M0 | — | Complete | 2026-02-23 |
| 0.6 Caching + Admin | M0 | — | Complete | 2026-02-23 |
| 0.7 ML Pluggability + IRI Ingestion | M0 | — | Complete | 2026-02-23 |
| 1. MVP Integrity Cleanup | M1 | 4/4 | Complete | 2026-04-23 |
| 2. Real-Data Detector Accuracy | M1 | 0/5 | Planned | - |
| 3. Mapillary Ingestion Pipeline | M1 | 0/5 | Planned | - |
| 4. Authentication | M1 | 0/TBD | Not started | - |
| 5. Cloud Deployment | M1 | 0/TBD | Not started | - |
| 6. Public Demo Launch | M1 | 0/TBD | Not started | - |

---
*Roadmap initialized: 2026-04-23 after ingest synthesis + codebase map*
*Phase 2 planned: 2026-04-23*
*Phase 3 planned: 2026-04-25*
