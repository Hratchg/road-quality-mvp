# Requirements: road-quality-mvp

**Defined:** 2026-04-23
**Core Value:** Given any two points in LA, show the user a route that is demonstrably smoother than the fastest route, using real road-quality data.

## M0 Requirements (MVP — SHIPPED)

All requirements below are shipped and validated per `docs/PRD.md`. They are represented here as completed for traceability; the active roadmap targets M1 (below).

### Infrastructure & Dev Ergonomics

- [x] **REQ-docker-compose-stack**: Single-command local startup via Docker Compose orchestrating db, backend, frontend. `docker compose up --build` brings the full stack up; frontend reachable at `http://localhost:3000`.
- [x] **REQ-demo-launch**: From clean checkout, `docker compose up --build -d` → `python scripts/seed_data.py` → http://localhost:3000 renders segments + runs a route query.

### Database

- [x] **REQ-db-schema**: Four-table schema — `road_segments`, `segment_defects`, `segment_scores`, `route_requests` — with FK relations and the mandatory indexes (GIST on geom, BTREE on source/target, BTREE on segment_defects.segment_id). See `CON-db-schema`.

### Backend API

- [x] **REQ-health-endpoint**: `GET /health` returns HTTP 200 with body `{"status": "ok"}`.
- [x] **REQ-segments-endpoint**: `GET /segments?bbox=min_lon,min_lat,max_lon,max_lat` returns a GeoJSON FeatureCollection; each feature carries `id`, `iri_norm`, `moderate_score`, `severe_score`, `pothole_score_total`.
- [x] **REQ-route-endpoint**: `POST /route` accepts origin/destination + weight + budget params and returns `fastest_route`, `best_route`, `warning`, `per_segment_metrics`. See `CON-route-api`.
- [x] **REQ-pydantic-models**: All request/response bodies use Pydantic v2 models.
- [x] **REQ-caching-layer**: Two TTL caches (segments: 256 entries, 5 min; routes: 128 entries, 2 min). Admin endpoints `GET /cache/stats` and `POST /cache/clear` work.

### Backend Business Logic

- [x] **REQ-scoring-logic**: `cost_segment = travel_time_s + w_IRI * iri_norm + w_pothole * (moderate_score + severe_score)`; weight normalization per `CON-scoring-math` (one-enabled → 100%, both-enabled → normalized, neither-enabled → both 0).
- [x] **REQ-max-time-rule**: Routes where `total_time <= fastest_time + max_extra_minutes * 60` are kept. If all rejected, return fastest route with `warning` populated.

### Data Pipeline & ML

- [x] **REQ-ml-detector-protocol**: `PotholeDetector` Protocol with `detect(image_path) -> list[Detection]`; `StubDetector` returns deterministic results.
- [x] **REQ-yolov8-detector**: `YOLOv8Detector` implements `PotholeDetector`; factory `get_detector(use_yolo=True, model_path=...)` returns YOLOv8 when available, StubDetector otherwise. Supports two-class and single-class models.
- [x] **REQ-seed-data**: `python scripts/seed_data.py` downloads LA drive network via osmnx, inserts segments, runs `pgr_createTopology()`, generates deterministic (seed=42) synthetic IRI and defects.
- [x] **REQ-iri-ingestion**: `scripts/ingest_iri.py --source {csv|shapefile|synthetic} --path ...` loads IRI into `road_segments.iri_value` and normalizes to `iri_norm`.

### Frontend

- [x] **REQ-frontend-skeleton**: Vite + React 18 + TypeScript + Tailwind + react-router-dom on port 3000.
- [x] **REQ-map-view-page**: Page at `/` renders Leaflet map, fetches `/segments?bbox=...` on map move/zoom, color-codes polylines; control panel with toggles + sliders; legend.
- [x] **REQ-route-finder-page**: Page at `/route` accepts typed addresses (Nominatim autocomplete) or click-on-map; renders fastest (blue dashed) vs best (green solid) routes with summary card and warning banner. Swap button reverses origin/destination.

### Docs & Tests

- [x] **REQ-readme-docs**: `README.md` documents prerequisites, docker-compose quick start, scoring formula, endpoint summary.
- [x] **REQ-integration-tests**: 6 integration tests in `backend/tests/test_integration.py` run real DB queries and auto-skip when DB unreachable.

## M1 Requirements (ACTIVE — Next Milestone)

Scope for the next milestone: post-MVP features + real-data accuracy + public demo.

### Integrity

- [ ] **REQ-mvp-integrity-cleanup**: Reconcile ingest-conflict INFO items with shipped code before building on top. Specifically:
  - Verify `db/migrations/001_initial.sql` declares `road_segments.source`/`target` as `BIGINT` (SPEC-authoritative). If `INTEGER`, author a follow-up migration and re-seed.
  - Verify `scripts/seed_data.py` uses 10 km radius (SPEC-authoritative); update `docs/SETUP.md` to match the literal, whichever it is.
  - Confirm frontend Mapbox env-var name is `VITE_MAPBOX_TOKEN` in code and docs; retire any `REACT_APP_MAPBOX_TOKEN` references.
  - Re-pin `psycopg2-binary` consistently (codebase has 2.9.11, plan had 2.9.10) in `backend/requirements.txt`.

### Real-Data Accuracy

- [ ] **REQ-real-data-accuracy**: `YOLOv8Detector` runs end-to-end on a curated set of real LA street-level images with reported precision/recall on a labelled eval set. Acceptance:
  - A reproducible eval script (e.g., `scripts/eval_detector.py`) runs the detector against a committed (or downloadable) labelled eval set and prints precision, recall, and per-severity counts.
  - At least one non-synthetic model (pretrained or fine-tuned) is wired up via `get_detector(use_yolo=True, model_path=...)` and works outside of tests.
  - Eval metrics are documented in `docs/` (method + numbers) so the demo can cite them honestly.

### Mapillary Pipeline

- [ ] **REQ-mapillary-pipeline**: Automated pipeline pulls Mapillary imagery for LA segments, runs `YOLOv8Detector`, writes rows into `segment_defects`, then triggers `compute_scores.py` to refresh `segment_scores`. Acceptance:
  - A documented CLI (e.g., `scripts/ingest_mapillary.py --bbox ... --limit N`) authenticates to Mapillary, downloads images, runs detection, and commits detections with correct `segment_id`, `severity`, `count`, `confidence_sum`.
  - Mapillary access token is taken from an environment variable, not hard-coded.
  - Idempotency: re-running on the same bbox does not double-count detections (either dedupe on image id or upsert by detection key).
  - After running, `/segments` and `/route` reflect the real detections (not synthetic) end-to-end.

### Authentication

- [ ] **REQ-user-auth**: Backend authentication gates state-mutating and expensive endpoints. Acceptance:
  - User can sign up and sign in via a minimal flow (API endpoints at minimum; UI optional for M1 demo).
  - `POST /route` and `/cache/*` require a valid session/token; `GET /health` and `GET /segments` may remain public for the demo.
  - Invalid/missing credentials return `401`; all responses stay within existing shapes elsewhere.
  - Passwords (or equivalent secrets) are hashed; no plaintext credentials in the DB.

### Production Deployment

- [ ] **REQ-prod-deploy**: The stack is deployable to a cloud host from `main` in a reproducible way, with production-safe config. Acceptance:
  - A documented deploy path (cloud provider + commands or pipeline) brings up db + backend + frontend in a non-local environment.
  - CORS is restricted to the deployed frontend origin(s), not `*`.
  - Database credentials and all secrets come from the cloud host's secret mechanism, not committed defaults.
  - Frontend `VITE_API_URL` points at the deployed backend (no `localhost` hard-coding).
  - Health endpoint returns DB reachability, not just `{"status": "ok"}` (enables LB probes).
  - DB connection pooling is in place (psycopg2 pool or equivalent) so concurrent requests do not exhaust the connection pool.

### Public Demo

- [ ] **REQ-public-demo**: A public URL serves the live frontend against real LA pothole data, usable without any local setup. Acceptance:
  - Anyone with the URL can open the Map View, pan/zoom LA, and see colored segments reflecting real (Mapillary-ingested) pothole scores.
  - Anyone with the URL (after sign-in, if auth is enforced on `/route`) can run a route query and see fastest vs best comparison.
  - The demo URL is linked from `README.md`.
  - A "what you're looking at" paragraph on the landing page clarifies that scores come from real imagery + reported eval accuracy.

## Out of Scope

Explicit exclusions for M1. Revisit post-M1 if demo validates the concept.

| Feature | Reason |
|---------|--------|
| Real-time chat / messaging | Not relevant to routing value |
| Native mobile apps | Web-first; responsive web covers the demo |
| Multi-city support (beyond LA) | Hard-coded LA viewbox is acceptable for M1; generalize later |
| Redis / distributed cache | In-memory `cachetools` is fine for single-instance cloud deploy |
| Alembic migrations | Raw SQL under `db/migrations/` is sufficient for M1 |
| SQLAlchemy / ORM migration | Raw psycopg2 works; no churn for M1 |
| Prometheus / structured logging / full observability | Defer; noted in CONCERNS.md. Revisit after prod reveals real need |
| YOLOv8 training from scratch on custom dataset | Use pretrained or fine-tune only; full training pipeline is M2+ |
| Pagination on `/segments` | Known limitation; defer unless demo hits large-bbox problems |
| OAuth / SSO login | Email/password sufficient for M1 demo |
| Admin UI / moderation tooling | No user-generated content in M1 |

## Traceability

### M0 (shipped)

| Requirement | Phase | Status |
|-------------|-------|--------|
| REQ-docker-compose-stack | M0 (shipped) | Complete |
| REQ-db-schema | M0 (shipped) | Complete |
| REQ-health-endpoint | M0 (shipped) | Complete |
| REQ-segments-endpoint | M0 (shipped) | Complete |
| REQ-route-endpoint | M0 (shipped) | Complete |
| REQ-scoring-logic | M0 (shipped) | Complete |
| REQ-max-time-rule | M0 (shipped) | Complete |
| REQ-pydantic-models | M0 (shipped) | Complete |
| REQ-ml-detector-protocol | M0 (shipped) | Complete |
| REQ-yolov8-detector | M0 (shipped) | Complete |
| REQ-seed-data | M0 (shipped) | Complete |
| REQ-iri-ingestion | M0 (shipped) | Complete |
| REQ-frontend-skeleton | M0 (shipped) | Complete |
| REQ-map-view-page | M0 (shipped) | Complete |
| REQ-route-finder-page | M0 (shipped) | Complete |
| REQ-readme-docs | M0 (shipped) | Complete |
| REQ-demo-launch | M0 (shipped) | Complete |
| REQ-integration-tests | M0 (shipped) | Complete |
| REQ-caching-layer | M0 (shipped) | Complete |

### M1 (active)

| Requirement | Phase | Status |
|-------------|-------|--------|
| REQ-mvp-integrity-cleanup | Phase 1 | Pending |
| REQ-real-data-accuracy | Phase 2 | Pending |
| REQ-mapillary-pipeline | Phase 3 | Pending |
| REQ-user-auth | Phase 4 | Pending |
| REQ-prod-deploy | Phase 5 | Pending |
| REQ-public-demo | Phase 6 | Pending |

**Coverage:**

- M0 requirements: 19 total, 19/19 shipped
- M1 requirements: 6 total, 6/6 mapped to phases, 0 unmapped ✓

---
*Requirements defined: 2026-04-23*
*Last updated: 2026-04-23 after ingest + roadmap initialization*
