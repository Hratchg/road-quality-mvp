# External Integrations

**Analysis Date:** 2026-04-23

## APIs & External Services

**Geospatial Services:**
- OpenStreetMap (via OSMnx) - Road network data download
  - SDK/Client: `osmnx` 2.0.1
  - Auth: None required
  - Used in: `scripts/seed_data.py` (line 30) - `ox.graph_from_point(CENTER, dist=DIST, network_type="drive")`
  - Purpose: Download LA road network within 20km radius, add edge speeds and travel times

**Geocoding/Address Search:**
- Nominatim (OpenStreetMap Nominatim service) - Address-to-coordinates conversion
  - URL: `https://nominatim.openstreetmap.org/search`
  - Auth: None required (public API)
  - Used in: `frontend/src/hooks/useNominatim.ts` (line 10)
  - Purpose: Search addresses in LA area and convert to lat/lon for route origin/destination
  - Rate Limit: Debounce 400ms, follows Nominatim usage policy (no API key needed for low volume)

**Map Tiles:**
- OpenStreetMap (Tile Layer) - Raster map background
  - URL: `https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png`
  - Auth: None required (public tiles)
  - Used in: `frontend/src/pages/MapView.tsx` (line 84-87)
  - Purpose: Render map background tiles via Leaflet

**Potential/Unused:**
- Mapbox - Token placeholder configured but currently unused
  - Env var: `VITE_MAPBOX_TOKEN` (empty in docker-compose.yml)
  - Not integrated in any component
  - Future expansion point for premium map features

## Data Storage

**Databases:**
- PostgreSQL 16
  - Connection: `DATABASE_URL` env var (default: `postgresql://rq:rqpass@localhost:5432/roadquality`)
  - Client: `psycopg2-binary` 2.9.11
  - Used in: `backend/app/db.py`, all route/segment endpoints, seed scripts
  - Accessed via: `psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)`

**Database Extensions:**
- PostGIS 3.4 - Spatial data types and operations
  - Initialized in: `db/init-pgrouting.sh` (line 4)
  - Used for: Geometry storage (LineString), spatial indexing, distance calculations
  
- pgRouting 3.6 - Graph routing algorithms
  - Initialized in: `db/init-pgrouting.sh` (line 5)
  - Used in: `backend/app/routes/routing.py` (line 18-21) - `pgr_ksp()` for k-shortest paths
  - SQL: Finds 5 shortest paths between snapped nodes

**File Storage:**
- Local filesystem only - No external file storage configured
- Seed data generated locally and stored in PostgreSQL
- GeoJSON returned in-memory during route computation

**Caching:**
- In-memory TTL caches (cachetools library)
  - segments_cache: 256 max entries, 300s TTL
  - route_cache: 128 max entries, 120s TTL
  - Used in: `backend/app/cache.py`, routing and segments endpoints
  - No external cache service (Redis/Memcached) - all in-process

## Authentication & Identity

**Auth Provider:**
- None currently implemented
- CORS middleware: `CORSMiddleware` in `backend/app/main.py` (lines 8-13)
  - allow_origins: `["*"]` (open to all)
  - allow_methods: `["*"]`
  - allow_headers: `["*"]`
- No API key validation, authentication tokens, or user sessions
- All endpoints public

## Monitoring & Observability

**Error Tracking:**
- None configured - No Sentry, DataDog, or similar

**Logs:**
- Console/stdout only
  - Uvicorn logs during startup
  - FastAPI request logs
  - Python print() statements in seed_data.py (e.g., line 29: "Downloading LA road network...")
- No structured logging framework
- No log aggregation service

**Database Audit:**
- route_requests table in PostgreSQL logs all route requests
  - Schema: `id`, `params_json` (JSONB), `created_at` (TIMESTAMPTZ)
  - Used in: `backend/app/routes/routing.py` (line 59-62)
  - Purpose: Audit trail of all route calculations

## CI/CD & Deployment

**Hosting:**
- Docker Compose (local/single-server deployment)
  - Orchestrates: db (PostgreSQL), backend (FastAPI), frontend (React/Vite)
  - Services defined in: `docker-compose.yml`

**CI Pipeline:**
- None configured - No GitHub Actions, GitLab CI, Jenkins, etc.
- Manual docker compose up for development and deployment

**Build Process:**
- Backend: `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`
- Frontend: `npm run dev -- --host` (Vite dev server)
- Database: PostgreSQL 16 with PostGIS/pgRouting extensions

## Environment Configuration

**Required env vars:**
- `DATABASE_URL` (default: `postgresql://rq:rqpass@localhost:5432/roadquality`)
  - Used by: Backend (`backend/app/db.py`), seed scripts (`scripts/seed_data.py`)
  - Must include username, password, host, port, database name

- `VITE_API_URL` (default: `http://localhost:8000` in dev)
  - Used by: Frontend (`frontend/src/api.ts` line 1)
  - Configures the backend API base URL for fetch requests

**Optional env vars:**
- `VITE_MAPBOX_TOKEN` (currently unused)
  - Placeholder for future Mapbox integration

**Development env vars (docker-compose.yml):**
- `POSTGRES_DB: roadquality`
- `POSTGRES_USER: rq`
- `POSTGRES_PASSWORD: rqpass`

**Secrets location:**
- `.env` files: Not committed (none found in repo)
- docker-compose.yml: Contains default development credentials (rq/rqpass)
- Production: Env vars should be injected at runtime, not committed to git

## Webhooks & Callbacks

**Incoming:**
- None configured - All endpoints are request-response, no webhook receivers

**Outgoing:**
- None configured - No external notifications, alerts, or event callbacks

## Data Pipeline & Ingestion

**Initial Data Load:**
- `scripts/seed_data.py` - One-time seed script
  - Downloads road network from OpenStreetMap via OSMnx
  - Generates synthetic IRI (International Roughness Index) data
  - Generates synthetic pothole defect data
  - Loads all data into PostgreSQL
  - Must be run manually after database initialization

**IRI Ingestion (Future):**
- `scripts/ingest_iri.py` - Not currently called from main flow
- `scripts/iri_sources.py` - Placeholder for real IRI data sources
- Purpose: For future integration of real IRI datasets

**ML Model (Stub/Future):**
- `data_pipeline/requirements.txt` includes: ultralytics 8.1+, opencv-python-headless 4.8+
- YOLOv8 model framework is available but not integrated
- Purpose: Future pothole detection from images
- Current implementation: Synthetic pothole detection in seed_data.py

## API Endpoints (Backend)

**Health:**
- GET `/health` - Simple health check, returns `{"status": "ok"}`
  - Used by: Docker health checks, frontend startup verification

**Route Calculation:**
- POST `/route` - Find best quality-aware route
  - Request: `RouteRequest` with origin, destination, scoring weights, time budget
  - Response: `RouteResponse` with fastest_route, best_route, warnings, per-segment metrics
  - Uses: pgr_ksp for k-shortest paths, cachetools for result caching
  - Logs: Audit entry to route_requests table

**Segments Query:**
- GET `/segments?bbox=min_lon,min_lat,max_lon,max_lat` - Get road segments in bounding box
  - Response: GeoJSON FeatureCollection with segment properties (IRI, pothole scores)
  - Uses: Spatial indexing on road_segments, cachetools for result caching

**Cache Management (Internal):**
- Internal cache routes via `backend/app/routes/cache_routes.py`
- No public cache invalidation endpoint

---

*Integration audit: 2026-04-23*
