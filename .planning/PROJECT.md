# road-quality-mvp

## What This Is

A web app that routes drivers in Los Angeles along roads optimized for ride quality, not just speed. It combines OpenStreetMap topology, IRI (International Roughness Index) data, and pothole detections to score road segments, then uses pgRouting's k-shortest-paths to return a "fastest" and a "best" route side-by-side. The MVP (M0) ships a full local-dev Docker stack with a FastAPI backend, a React/Leaflet frontend, and a synthetic-data seed of the LA road network. The next milestone (M1) takes it to a publicly demoable cloud deployment with authenticated access and real (non-synthetic) pothole data from Mapillary imagery.

## Core Value

Given any two points in LA, show the user a route that is demonstrably smoother than the fastest route — within a user-controlled time budget — using real, trustworthy road-quality data.

## Requirements

### Validated

<!-- Shipped in M0 MVP. Confirmed working per PRD and codebase map. -->

- `REQ-docker-compose-stack` — Docker Compose orchestrates db + backend + frontend — M0
- `REQ-db-schema` — Four-table schema (road_segments, segment_defects, segment_scores, route_requests) — M0
- `REQ-health-endpoint` — `GET /health` returns `{"status": "ok"}` — M0
- `REQ-segments-endpoint` — `GET /segments?bbox=...` returns GeoJSON with IRI + pothole scores — M0
- `REQ-route-endpoint` — `POST /route` returns fastest + best route using pgr_ksp — M0
- `REQ-scoring-logic` — Weight normalization + `cost_segment = travel_time + w_IRI*iri_norm + w_pothole*(mod+sev)` — M0
- `REQ-max-time-rule` — Reject candidates > fastest + max_extra_minutes; fall back with warning — M0
- `REQ-pydantic-models` — All API bodies validated by Pydantic v2 — M0
- `REQ-ml-detector-protocol` — `PotholeDetector` Protocol + `StubDetector` — M0
- `REQ-yolov8-detector` — `YOLOv8Detector` selectable via factory, graceful fallback — M0
- `REQ-seed-data` — OSMnx LA network + synthetic IRI + synthetic potholes (seed=42) — M0
- `REQ-iri-ingestion` — CSV/shapefile/synthetic IRI ingestion CLI — M0
- `REQ-frontend-skeleton` — Vite + React + TS + Tailwind + react-router — M0
- `REQ-map-view-page` — Full-screen Leaflet map with color-coded segments + control panel — M0
- `REQ-route-finder-page` — Origin/destination picker with fastest vs best comparison — M0
- `REQ-readme-docs` — README with quick start + scoring + API overview — M0
- `REQ-demo-launch` — End-to-end `docker compose up` → `seed_data.py` → http://localhost:3000 — M0
- `REQ-integration-tests` — 6 live-DB integration tests, auto-skip when DB down — M0
- `REQ-caching-layer` — TTL caches for /segments (5m, 256) and /route (2m, 128) + admin endpoints — M0

### Active

<!-- M1 scope. These drive the current roadmap. -->

- [ ] `REQ-mvp-integrity-cleanup` — Reconcile ingest-conflict INFO items with shipped code (BIGINT migration types, VITE_MAPBOX_TOKEN env var, seed radius literal, psycopg2 pin) before building on top
- [ ] `REQ-real-data-accuracy` — YOLOv8 pothole detector runs on real LA street imagery with measurable precision/recall on a labelled eval set (no longer just synthetic)
- [ ] `REQ-mapillary-pipeline` — Automated pipeline pulls Mapillary imagery, runs the real detector, and writes detections into `segment_defects` without manual steps
- [ ] `REQ-user-auth` — Backend enforces authenticated access to `/route` and `/cache/*`; users can sign up, sign in, and sign out
- [ ] `REQ-prod-deploy` — The stack deploys to a cloud host from `main` via a reproducible process, with production-safe config (CORS, secrets, CORS origins, pooling)
- [ ] `REQ-public-demo` — A public URL serves the live frontend against real LA pothole data, usable without any local setup

### Out of Scope

<!-- Explicit exclusions for M1. Revisit post-M1 if demo validates the concept. -->

- Real-time chat / user-to-user messaging — not relevant to routing value
- Mobile apps (iOS/Android native) — web-first; responsive web is sufficient for demo
- Multi-city support (New York, SF, etc.) — hard-coded LA viewbox is acceptable for M1; generalization deferred until after demo signal
- Redis / distributed cache — in-memory `cachetools` is adequate for single-instance cloud deploy; revisit on scale pressure
- Alembic migrations — raw SQL in `db/migrations/` is fine for M1; adopt Alembic if a second migration ships without an ADR
- SQLAlchemy / ORM migration — raw psycopg2 works; no churn for M1
- Structured logging / Prometheus / full observability stack — note in CONCERNS.md, defer until prod deploy reveals real need
- Native YOLOv8 training from scratch — use a pretrained model and fine-tune or evaluate only; custom dataset curation beyond Mapillary imagery is M2 territory
- Pagination on `/segments` — known limitation (CONCERNS.md), defer unless demo reveals large-bbox problems

## Context

**Current state (from codebase map, 2026-04-23):**

- Repo lives at `/Users/hratchghanime/road-quality-mvp` (macOS dev). SPEC's Windows path is author-specific, ignore.
- Stack: Python 3.12 + FastAPI 0.115.6 + psycopg2-binary 2.9.11, React 18 + Vite 6 + Leaflet 1.9, PostgreSQL 16 + PostGIS 3.4 + pgRouting 3.6.
- Entry points: `backend/app/main.py`, `frontend/src/main.tsx`, `docker-compose.yml`.
- Tests: 10 backend test files (per codebase STRUCTURE.md); SETUP.md cites 19 total tests across 8 files; PRD cites 6 integration tests. All three are consistent at different scopes.
- YOLOv8 detector class exists (`data_pipeline/yolo_detector.py`) with graceful stub fallback, but no real model is integrated and no real imagery has flowed through it.

**Known concerns the roadmap must address (from `.planning/codebase/CONCERNS.md`):**

- Hardcoded DB credentials in `docker-compose.yml` and scripts — blocker for prod deploy.
- CORS allows `*` — blocker for prod deploy.
- Single DB connection per request (no pooling) — will exhaust pool under load.
- Frontend API URL assumes localhost — breaks any non-local deployment.
- Health endpoint is trivial — needs DB-reachability check for production LB probes.
- YOLO model path hardcoded relative to CWD — breaks across run contexts.
- `route_requests` audit log has no retention policy — will grow unbounded.

**Ingest-conflict INFO items carried forward (from `.planning/INGEST-CONFLICTS.md`):**

- SPEC says `road_segments.source`/`target` are BIGINT; implementation plan says INTEGER. Verify `db/migrations/001_initial.sql` matches SPEC.
- SPEC says seed radius is 10 km; SETUP.md says ~20 km. Verify `scripts/seed_data.py` literal and reconcile the two docs.
- SPEC uses `REACT_APP_MAPBOX_TOKEN`; codebase + SETUP use `VITE_MAPBOX_TOKEN`. Lock to Vite name.
- psycopg2-binary pin drift (2.9.10 in plan vs 2.9.11 in codebase) — re-pin consistently.

**Next-milestone success metric (user-supplied):**

Post-MVP features shipped + detector accuracy demonstrated on real LA imagery + a public demo URL live.

## Constraints

- **Stack (backend)**: Python 3.12+, FastAPI, psycopg2 with RealDictCursor, uvicorn, Pydantic v2, pytest — per `CON-stack-backend`. No migration to SQLAlchemy in M1.
- **Stack (frontend)**: TypeScript, React 18, Vite, react-leaflet (default), react-map-gl (Mapbox upgrade), Tailwind — per `CON-stack-frontend`. No state library beyond hooks.
- **Stack (database)**: PostgreSQL 16 + PostGIS 3.4 + pgRouting 3.6, geometry SRID 4326. Container base `postgis/postgis:16-3.4` with pgRouting apt-installed.
- **Schema**: The four-table schema in `CON-db-schema` is load-bearing. `road_segments.source`/`target` must be BIGINT (SPEC wins over DOC). Changes require a new migration file.
- **API contracts**: `/health`, `/segments`, `/route`, `/cache/stats`, `/cache/clear` shapes are locked — see `CON-route-api`, `CON-segments-api`, `CON-health-api`, `CON-cache-admin-api`. M1 may add auth headers but must not break existing response shapes.
- **Scoring math**: `cost_segment = travel_time_s + w_IRI*iri_norm + w_pothole*(moderate_score + severe_score)` is locked. Weight normalization rules locked — see `CON-scoring-math`.
- **Route-selection algorithm**: pgr_ksp with K=5, time-budget filter, fastest-fallback-with-warning — locked per `CON-route-selection-algorithm`.
- **Detector protocol**: `PotholeDetector` Protocol with `detect(image_path) -> list[Detection]`. New detectors (Mapillary-fed) must implement it.
- **Ports**: Frontend 3000, backend 8000, Postgres 5432.
- **Seed data**: Center (34.0522, -118.2437), radius 10 km, IRI 1.0-12.0 m/km, defects on ~30% of segments, seed=42. SPEC wins over SETUP.md's "~20 km" claim; ground truth is `scripts/seed_data.py`.
- **Migrations**: Single SQL files under `db/migrations/`, no Alembic for M1.
- **CORS**: Dev uses `*`; production CORS must be restricted to the deployed frontend origin(s) before `REQ-prod-deploy` ships.
- **Secrets**: Production deploy must not use the dev defaults (`rq`/`rqpass`/`roadquality`). All secrets via environment, never committed.

## Key Decisions

<!-- No ADR-locked decisions yet. SPEC-level design decisions are documented here as current-state context, not locked. If M1 promotes any of these to ADR, move rows accordingly. -->

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Routing via pgRouting (`pgr_ksp`) in DB, not in-process | Production-grade routing in SQL; avoids in-process graph libs | ✓ Good (shipped in M0) |
| k = 5 for pgr_ksp | Variety without perf blowup | ✓ Good (shipped in M0) |
| Seed=42 for deterministic synthetic IRI/pothole data | Reproducible demos and tests | ✓ Good (shipped in M0) |
| Leaflet + OSM default, Mapbox via `VITE_MAPBOX_TOKEN` | Free default, optional upgrade; Vite-native env var | ✓ Good (shipped in M0) |
| PRD is a living document (updated at each checkpoint) | Per user request | — Pending (re-verify at M1 close) |
| Seed radius = 20 km around (34.05, -118.24) | Code is authoritative per ROADMAP Phase 1 SC #2; `scripts/seed_data.py` `DIST = 20000` confirmed; SETUP.md already agreed; README.md and docs/PRD.md updated in Phase 1 Plan 02 | ✓ Resolved (Phase 1, 2026-04-23) |
| `road_segments.source`/`target` as BIGINT | SPEC over implementation plan's INTEGER; verify migration literal | ⚠️ Revisit (INFO item from ingest) |

---
*Last updated: 2026-04-23 after Phase 1 Plan 02 (seed radius drift resolved)*
