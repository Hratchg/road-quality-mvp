# Requirements Intel

Extracted from `docs/PRD.md` (PRD class, high confidence). The PRD distinguishes "Implemented" vs "Planned (Post-MVP)." Both are surfaced here; implementation status is metadata for the roadmapper, not a filter on requirement extraction.

Codebase-map cross-check (STACK.md, ARCHITECTURE.md): all "Implemented" items in the PRD appear to have corresponding code in the repo. Any divergence is called out per-requirement.

---

## Functional Requirements — MVP (Implemented per PRD)

### REQ-docker-compose-stack
- source: docs/PRD.md
- description: Single-command local startup via Docker Compose orchestrating db, backend, and frontend services.
- acceptance: `docker compose up --build` starts PostgreSQL+PostGIS+pgRouting db, FastAPI backend, and React frontend; frontend reachable at http://localhost:3000.
- scope: infra / dev ergonomics
- status (per PRD): Implemented

### REQ-db-schema
- source: docs/PRD.md
- description: Persist road network, pothole detections, aggregate scores, and route audit log.
- acceptance: Schema includes four tables — `road_segments`, `segment_defects`, `segment_scores`, `route_requests` — with FK relations and indexes per design doc. See constraints.md CON-db-schema for exact column list.
- scope: database
- status (per PRD): Implemented

### REQ-health-endpoint
- source: docs/PRD.md
- description: FastAPI backend exposes a health probe for liveness checks.
- acceptance: `GET /health` returns HTTP 200 with body `{"status": "ok"}`.
- scope: backend API
- status (per PRD): Implemented

### REQ-segments-endpoint
- source: docs/PRD.md
- description: Backend returns GeoJSON road-segment data for a map bounding box for frontend overlay rendering.
- acceptance: `GET /segments?bbox=min_lon,min_lat,max_lon,max_lat` returns GeoJSON FeatureCollection; each feature carries properties `id`, `iri_norm`, `moderate_score`, `severe_score`, `pothole_score_total`.
- scope: backend API
- status (per PRD): Implemented

### REQ-route-endpoint
- source: docs/PRD.md
- description: Backend computes k-shortest paths via pgRouting, applies weighted quality scoring, and returns fastest + best route with metrics and optional warning.
- acceptance: `POST /route` accepts origin/destination, include_iri, include_potholes, weight_iri, weight_potholes, max_extra_minutes; returns `fastest_route`, `best_route`, `warning`, `per_segment_metrics`. See constraints.md CON-route-api for full contract.
- scope: backend API
- status (per PRD): Implemented

### REQ-scoring-logic
- source: docs/PRD.md
- description: Weight normalization and segment cost formula implemented as pure functions.
- acceptance: `cost_segment = travel_time_s + w_IRI * iri_norm + w_pothole * (moderate_score + severe_score)`; weight normalization rule: one-enabled → 100% to that weight; both-enabled → sliders normalized to sum to 1.0; neither-enabled → both 0.
- scope: backend business logic
- status (per PRD): Implemented

### REQ-max-time-rule
- source: docs/PRD.md
- description: Reject candidate routes that exceed the user's time budget relative to the fastest route; fall back to fastest with warning if all rejected.
- acceptance: Keep routes where `total_time <= fastest_time + max_extra_minutes * 60`. If all rejected, return fastest route with `warning` populated.
- scope: backend business logic
- status (per PRD): Implemented

### REQ-pydantic-models
- source: docs/PRD.md
- description: All request/response bodies use Pydantic v2 models for validation.
- acceptance: Pydantic v2.10.4 models cover `/route` request + response and `/segments` response.
- scope: backend API contracts
- status (per PRD): Implemented

### REQ-ml-detector-protocol
- source: docs/PRD.md
- description: Pluggable pothole detector interface with a deterministic stub fallback.
- acceptance: `PotholeDetector` protocol with `detect(image_path) -> list[Detection]`; `StubDetector` returns deterministic results for MVP dev/test.
- scope: data pipeline / ML
- status (per PRD): Implemented

### REQ-yolov8-detector
- source: docs/PRD.md
- description: Real ML detector using Ultralytics YOLOv8 selectable via factory, with graceful fallback to stub when `ultralytics` package or model file missing.
- acceptance: `YOLOv8Detector` implements `PotholeDetector` protocol; factory `get_detector(use_yolo=True, model_path=...)` returns YOLOv8 when available, StubDetector otherwise. Supports two-class (moderate/severe) and single-class (confidence-based severity) models.
- scope: data pipeline / ML
- status (per PRD): Implemented

### REQ-seed-data
- source: docs/PRD.md
- description: One-shot seed script downloads the LA road network and inserts segments with synthetic IRI and pothole defect data.
- acceptance: `python scripts/seed_data.py` downloads LA drive network via osmnx, inserts road_segments, runs `pgr_createTopology()`, generates deterministic (seed=42) synthetic IRI (1.0-12.0 m/km, biased higher on arterials), and generates defects on ~30% of segments with 1-3 records each. Variant note: PRD + SPEC say "LA 10km"; SETUP.md says "~20 km radius." See INGEST-CONFLICTS.md INFO.
- scope: data pipeline / seeding
- status (per PRD): Implemented

### REQ-iri-ingestion
- source: docs/PRD.md
- description: Ingest real IRI measurements from CSV or shapefile, with an improved-synthetic fallback using spatial smoothing.
- acceptance: `scripts/ingest_iri.py --source {csv|shapefile|synthetic} --path ...` loads IRI values into `road_segments.iri_value`, normalizes to 0-1 in `iri_norm`. CSV columns: `lat`, `lon`, `iri_value`. Re-run `scripts/compute_scores.py` after ingest.
- scope: data pipeline / ingestion
- status (per PRD): Implemented

### REQ-frontend-skeleton
- source: docs/PRD.md
- description: Vite + React + TypeScript + Tailwind frontend skeleton with client-side routing.
- acceptance: React 18 app served by Vite on port 3000, TypeScript strict enough to build, Tailwind configured, react-router-dom wires two pages.
- scope: frontend
- status (per PRD): Implemented

### REQ-map-view-page
- source: docs/PRD.md
- description: Full-screen interactive map with color-coded segment overlay and control panel.
- acceptance: Page at `/` renders Leaflet map, fetches `/segments?bbox=...` on map move/zoom, color-codes polylines green/yellow/red; control panel top-right with IRI toggle, Potholes toggle, and weight sliders; legend bottom-right. Mapbox used when token is set via env var.
- scope: frontend
- status (per PRD): Implemented

### REQ-route-finder-page
- source: docs/PRD.md
- description: Second page for origin/destination selection and side-by-side fastest vs best route visualization.
- acceptance: Page at `/route` accepts typed addresses (with autocomplete) or click-on-map for origin + destination; same control panel as Map View plus a `max_extra_minutes` input (default 5); on submit renders fastest route as blue dashed line and best route as green solid line; summary card shows per-route total time, cost, avg IRI, and pothole scores; warning banner when backend returns warning. Swap button reverses origin/destination.
- scope: frontend
- status (per PRD): Implemented

### REQ-readme-docs
- source: docs/PRD.md
- description: Top-level README covering quick start, scoring docs, and API overview.
- acceptance: `README.md` documents prerequisites, docker-compose quick start, scoring formula, and endpoint summary.
- scope: docs
- status (per PRD): Implemented

### REQ-demo-launch
- source: docs/PRD.md
- description: Repeatable end-to-end demo launch path (Docker Desktop + seed + backend + frontend).
- acceptance: From a clean checkout: `docker compose up --build -d` → `python scripts/seed_data.py` → visit http://localhost:3000 and successfully render segments + run a route query.
- scope: infra / demo
- status (per PRD): Implemented

### REQ-integration-tests
- source: docs/PRD.md
- description: Integration tests against a real database, with auto-skip when DB is down.
- acceptance: 6 integration tests in `backend/tests/test_integration.py` run real DB queries and automatically skip when the DB is unreachable. Note: SETUP.md's test inventory lists "19 tests total" across 8 files — see INGEST-CONFLICTS.md INFO (different scope: 6 integration tests vs 19 total).
- scope: backend testing
- status (per PRD): Implemented

### REQ-caching-layer
- source: docs/PRD.md
- description: In-memory TTL caching for the `/segments` and `/route` endpoints, plus admin endpoints for inspection and invalidation.
- acceptance: Two TTLCaches (segments: 256 entries, 5 min; routes: 128 entries, 2 min). Admin endpoints: `GET /cache/stats` returns current sizes; `POST /cache/clear` clears both caches.
- scope: backend infra
- status (per PRD): Implemented

---

## Planned (Post-MVP) Requirements

### REQ-mapillary-pipeline
- source: docs/PRD.md
- description: Image pipeline that pulls street-level imagery from Mapillary for pothole detection.
- acceptance: Not yet specified. Out of MVP scope.
- scope: data pipeline / image sourcing
- status (per PRD): Planned

### REQ-user-auth
- source: docs/PRD.md
- description: User authentication layer on the backend.
- acceptance: Not yet specified. Out of MVP scope.
- scope: backend / security
- status (per PRD): Planned

### REQ-prod-deploy
- source: docs/PRD.md
- description: Production deployment of the Docker stack to a cloud host.
- acceptance: Not yet specified. Out of MVP scope.
- scope: infra / deployment
- status (per PRD): Planned
