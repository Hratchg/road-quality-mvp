# Context Intel

Running notes extracted from DOC-class ingest documents (`docs/plans/2026-02-23-implementation-plan.md` and `docs/SETUP.md`). DOC is the lowest precedence tier; content here is informational and should not override SPEC or PRD decisions. Where DOCs disagree with higher-precedence sources, the higher source wins — see `decisions.md`, `constraints.md`, and `INGEST-CONFLICTS.md`.

---

## Topic: Implementation Plan Structure

- source: docs/plans/2026-02-23-implementation-plan.md
- Plan is task-by-task, TDD-driven where applicable. Tasks run sequentially:
  1. Docker Compose + DB init (docker-compose.yml, db/Dockerfile, db/migrations/001_initial.sql, db/init-pgrouting.sh)
  2. Backend skeleton + `/health` endpoint (FastAPI, CORS, psycopg2, tests)
  3. Scoring logic (pure functions: `normalize_weights`, `compute_segment_cost`) — TDD
  4. Pydantic models — request/response schemas
  (Subsequent tasks cover seed data, /segments, /route, frontend, integration tests, caching, YOLOv8 — not fully captured here to avoid duplicating requirements.)
- Each task concludes with a `git commit` instruction using conventional-commits-style messages (`feat:`, `fix:`, etc.).
- Plan assumes Python 3.12, Node 20+, Docker Desktop.

## Topic: Backend Dependency Pins (MVP)

- source: docs/plans/2026-02-23-implementation-plan.md (Task 2), docs/SETUP.md
- `fastapi==0.115.6`
- `uvicorn[standard]==0.34.0`
- `psycopg2-binary==2.9.10` (codebase STACK.md reports 2.9.11 — minor drift, INFO only)
- `pydantic==2.10.4`
- `pytest==8.3.4`
- `httpx==0.28.1`
- Additional deps implied by later tasks: `cachetools` (caching), `ultralytics` + `opencv-python-headless` (YOLOv8, optional).

## Topic: Database Credentials (Development Default)

- source: docs/SETUP.md, docs/plans/2026-02-23-implementation-plan.md
- `POSTGRES_DB=roadquality`
- `POSTGRES_USER=rq`
- `POSTGRES_PASSWORD=rqpass`
- `DATABASE_URL=postgresql://rq:rqpass@localhost:5432/roadquality`
- Development-only. Production credentials are not defined (prod deploy is Planned Post-MVP).

## Topic: Environment Variables

- source: docs/SETUP.md
- `DATABASE_URL` — PostgreSQL connection string. Default `postgresql://rq:rqpass@localhost:5432/roadquality`.
- `VITE_API_URL` — Frontend API URL. Default `/api` (proxied to backend by Vite).
- `VITE_MAPBOX_TOKEN` — Optional Mapbox token. Default empty.
- Note: SPEC uses `REACT_APP_MAPBOX_TOKEN` — stale Create-React-App naming. Current codebase + SETUP use the Vite-prefixed name. See INGEST-CONFLICTS.md INFO.

## Topic: Test Inventory

- source: docs/SETUP.md
- Total test count per SETUP: 19 tests across 8 files:
  - `test_health.py` — health endpoint
  - `test_models.py` — Pydantic model validation
  - `test_scoring.py` — weight normalization + cost formula
  - `test_cache.py` — cache operations + admin endpoints
  - `test_detector.py` — StubDetector
  - `test_yolo_detector.py` — YOLOv8 detector + factory
  - `test_integration.py` — live DB queries (auto-skip when DB down)
  - `test_iri_ingestion.py` — IRI data loading from CSV/shapefile
- PRD lists only "6 integration tests" for REQ-integration-tests — that is a subset (the `test_integration.py` file only). Not a conflict; different scope.

## Topic: Quick Start — Docker

- source: docs/SETUP.md
- `git clone https://github.com/Hratchg/road-quality-mvp.git`
- `cd road-quality-mvp`
- `docker compose up --build` (or `-d` for detached)
- `python scripts/seed_data.py` (first run only, ~2-5 minutes)
- Open http://localhost:3000

## Topic: Quick Start — Local Dev (hot reload)

- source: docs/SETUP.md
- `docker compose up db -d`
- Seed DB (see above).
- `cd backend && uvicorn app.main:app --reload --port 8000`
- `cd frontend && npm run dev`
- Backend: http://localhost:8000, Frontend: http://localhost:3000.

## Topic: IRI Ingestion CLI

- source: docs/SETUP.md
- CSV: `python scripts/ingest_iri.py --source csv --path data/my_iri_data.csv` (columns: `lat`, `lon`, `iri_value`).
- Shapefile: `python scripts/ingest_iri.py --source shapefile --path data/iri_measurements.shp`.
- Synthetic regen: `python scripts/ingest_iri.py --source synthetic --seed 42`.
- After ingest: `python scripts/compute_scores.py` to refresh `segment_scores`.

## Topic: Pothole Detector Factory

- source: docs/SETUP.md
- ```python
  from data_pipeline.detector_factory import get_detector
  detector = get_detector()  # default: StubDetector
  detector = get_detector(use_yolo=True, model_path="models/pothole_model.pt")  # YOLOv8
  ```
- Graceful fallback: if `ultralytics` is not installed, factory returns `StubDetector`.
- YOLOv8 supports two-class (moderate/severe) and single-class (confidence-based severity) models.

## Topic: Frontend UI Notes

- source: docs/SETUP.md
- Map View (`/`): color-coded segment overlay, control panel (IRI toggle, potholes toggle, weight sliders), legend.
- Route Finder (`/route`): address autocomplete + click-on-map for origin/destination, max-extra-minutes input, toggle/slider controls, side-by-side fastest (blue dashed) vs best (green solid) route visualization, summary card comparing per-route travel time / cost / avg IRI / pothole scores, warning banner, swap button.
- Geocoding: Nominatim API (from codebase ARCHITECTURE.md cross-check, not explicitly in PRD/SPEC/SETUP).

## Topic: Troubleshooting Snapshots

- source: docs/SETUP.md
- Windows: restart PC after Docker Desktop install; ensure WSL2 enabled.
- DB connection refused: wait 10-15s for healthcheck; check `DATABASE_URL`.
- OSMnx errors: ensure internet; re-run (OSMnx caches partial downloads).
- CORS: enabled for all origins in dev; check browser console.
- Skipped tests: integration tests auto-skip when DB down — start `docker compose up db -d`.

## Topic: Author Machine Path

- source: docs/plans/2026-02-23-pothole-tracker-design.md (Decisions table)
- SPEC lists project path as `C:\Users\King Hratch\road-quality-mvp` — author's Windows machine at time of authoring. Current repo lives at `/Users/hratchghanime/road-quality-mvp` (macOS). Treat the SPEC path as informational only; do not encode it anywhere downstream.
