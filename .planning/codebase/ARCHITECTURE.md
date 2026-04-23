# Architecture

**Analysis Date:** 2026-04-23

## Pattern Overview

**Overall:** Three-tier REST API with in-memory caching, spatial database routing, and stateless frontend.

**Key Characteristics:**
- Layered architecture with separation between API routes, business logic, and database access
- Event-driven data pipeline feeding quality metrics into the database
- pgRouting-based k-shortest-path algorithm for route optimization
- In-memory caching layer for expensive queries (segments and routes)
- Frontend state management via React hooks with proxy-based API access

## Layers

**API Layer (FastAPI):**
- Purpose: Expose REST endpoints for frontend consumption and audit logging
- Location: `backend/app/main.py` (entry point), `backend/app/routes/` (route handlers)
- Contains: Route handlers, request/response models (Pydantic), middleware (CORS)
- Depends on: Scoring, database, caching modules
- Used by: Frontend via `/api/` proxy, external clients

**Business Logic Layer:**
- Purpose: Core scoring algorithms and weight normalization
- Location: `backend/app/scoring.py`
- Contains: `normalize_weights()` (balances IRI/pothole weights), `compute_segment_cost()` (calculates cost per segment)
- Depends on: None (pure functions)
- Used by: Routing layer when scoring paths

**Database Layer:**
- Purpose: Abstraction for PostgreSQL connections and connection pooling
- Location: `backend/app/db.py`
- Contains: `get_connection()` context manager using psycopg2 with RealDictCursor
- Depends on: psycopg2, environment variables
- Used by: All route handlers

**Caching Layer:**
- Purpose: TTL-based in-memory cache to avoid expensive database queries
- Location: `backend/app/cache.py`
- Contains: Two TTLCache instances (segments: 5min, routes: 2min), helper functions for cache keys
- Depends on: cachetools
- Used by: Routing and segments handlers

**Data Pipeline:**
- Purpose: Populate database with road network and quality metrics
- Location: `data_pipeline/`, `scripts/`
- Contains: OSMnx-based road network importer, pothole detector protocol, scoring computation
- Depends on: PostgreSQL, external data sources (OSM)
- Used by: Seeding phase, potentially continuous ingestion

**Frontend Layer:**
- Purpose: Interactive map and route-finding UI
- Location: `frontend/src/`
- Contains: Pages (MapView, RouteFinder), components (ControlPanel, Legend, AddressInput, RouteResults), API client
- Depends on: React Router, react-leaflet, Nominatim geocoding API
- Used by: End users via browser

## Data Flow

**Seeding Phase:**

1. `scripts/seed_data.py` downloads LA road network via OSMnx
2. Calculates synthetic IRI (roughness) biased by road type
3. Inserts segments into `road_segments` table with geometry
4. Normalizes IRI values (0-1 range) across all segments
5. `scripts/compute_scores.py` generates synthetic pothole defects in `segment_defects`
6. Aggregates defect counts into `segment_scores` table (moderate/severe/total scores)

**Request-Response Flow (Route Finding):**

1. Frontend: User selects origin/destination, configures weights via ControlPanel
2. Frontend calls `fetchRoute(RouteRequestBody)` → POST `/route` to backend
3. Backend: `routing.py` handler receives RouteRequest, logs to `route_requests` table
4. Backend: Checks `route_cache` for prior computation (cache key = hash of all parameters)
5. Cache miss: Queries PostgreSQL for k=5 shortest paths using `pgr_ksp()`
6. Backend: Snaps origin/destination to nearest graph vertices using spatial index
7. Backend: Computes cost for each path using `normalize_weights()` and `compute_segment_cost()`
8. Backend: Selects fastest route (min travel time) and best route (min weighted cost within time budget)
9. Backend: Caches RouteResponse, returns both routes + per-segment metrics to frontend
10. Frontend: Renders fastest vs. best routes on map, displays metrics

**Segments Query Flow:**

1. Frontend: MapView loads segments for current bbox as user pans/zooms
2. Frontend calls `fetchSegments(bbox)` → GET `/segments?bbox=min_lon,min_lat,max_lon,max_lat`
3. Backend: Checks `segments_cache` for bbox key
4. Cache miss: Queries spatial index on `road_segments.geom` using `ST_MakeEnvelope()`
5. Backend: LEFT JOINs with `segment_scores` to include pothole data
6. Backend: Returns GeoJSON FeatureCollection with segment properties (iri_norm, pothole scores)
7. Backend: Caches result, returns to frontend
8. Frontend: Renders segments as colored lines using `scoreToColor()` based on weights

**State Management:**

- **Frontend state:** React hooks store control panel state (weights, toggles), selected origin/destination, route results
- **Backend state:** None (stateless API); caches are ephemeral (cleared on restart)
- **Database state:** Road network (immutable), segment quality metrics (updated via `compute_scores.py`), audit log (`route_requests`)

## Key Abstractions

**RouteRequest/RouteResponse:**
- Purpose: Validates and constrains user input; structures route result output
- Examples: `backend/app/models.py` (Pydantic BaseModel definitions)
- Pattern: Request validation via Pydantic, response serialization via `.model_dump()`

**PotholeDetector Protocol:**
- Purpose: Abstract interface for plugging in ML detection backends
- Examples: `data_pipeline/detector.py` (Protocol definition), `data_pipeline/yolo_detector.py` (YOLOv8 stub)
- Pattern: Python Protocol/ABC allowing StubDetector (current) or YOLOv8Detector (future)

**Segment Data Structure:**
- Purpose: Represents a single road segment with geometry and quality metrics
- Composed of: `road_segments` (geometry, IRI), `segment_scores` (pothole counts/confidence)
- Pattern: Denormalized query result (LEFT JOIN) for single-pass rendering

**Route Info:**
- Purpose: Encapsulates a computed route with metrics
- Examples: `RouteInfo` model in `backend/app/models.py`
- Pattern: Contains GeoJSON geometry, total cost, travel time, quality metrics; returned in RouteResponse

## Entry Points

**Backend API:**
- Location: `backend/app/main.py` (FastAPI app instance)
- Triggers: `uvicorn app.main:app` command or Docker container
- Responsibilities: Initializes FastAPI app, registers routers, sets up CORS middleware

**Routes:**
- GET `/health`: `backend/app/routes/health.py` — Returns {"status": "ok"} for liveness checks
- GET `/segments`: `backend/app/routes/segments.py` — Fetches GeoJSON segments for bbox with caching
- POST `/route`: `backend/app/routes/routing.py` — Computes k-shortest paths, scores, returns best route with caching
- GET `/cache/stats`: `backend/app/routes/cache_routes.py` — Returns cache occupancy
- POST `/cache/clear`: `backend/app/routes/cache_routes.py` — Evicts all cache entries

**Frontend:**
- Location: `frontend/src/main.tsx` (React DOM root), `frontend/src/App.tsx` (Router)
- Triggers: `npm run dev` (Vite dev server) or `npm run build` → production bundle
- Responsibilities: Mounts React root, defines route structure, renders pages

**Pages:**
- MapView: `frontend/src/pages/MapView.tsx` — Full-screen map with segment visualization and control panel
- RouteFinder: `frontend/src/pages/RouteFinder.tsx` — Click-to-select origin/destination, compare routes

**Database Initialization:**
- Location: `db/migrations/001_initial.sql`, `db/init-pgrouting.sh`
- Triggers: Docker Compose db service startup
- Responsibilities: Creates tables, PostGIS/pgRouting extensions, spatial indexes

**Data Pipeline:**
- Seeding: `scripts/seed_data.py` — Imports LA road network, generates synthetic IRI/potholes
- Scoring: `scripts/compute_scores.py` — Aggregates segment defects into scores
- Detection: `data_pipeline/` — Protocol for ML-based pothole detection (stub or YOLOv8)

## Error Handling

**Strategy:** HTTP status codes for API errors, JavaScript `try/catch` in frontend, database transactions for consistency.

**Patterns:**
- **400 Bad Request:** Invalid bbox format in `/segments`, invalid coordinates
- **404 Not Found:** Invalid endpoints (FastAPI default)
- **500 Internal Server:** Database connection errors, unhandled exceptions
- **Frontend:** Fetch errors caught, displayed as `error` state in pages; graceful fallback for missing route
- **Database:** Transactions used in seed_data.py to ensure atomicity; TRUNCATE CASCADE for data reset
- **Route failure:** Returns empty LineStrings + warning message if no path found between points within time budget

## Cross-Cutting Concerns

**Logging:**
- Approach: Audit trail via `route_requests` table (logs all route queries as JSON)
- Implementation: Every route request inserted to database before cache check, enabling usage analytics

**Validation:**
- Approach: Pydantic models enforce type and range constraints (lat: -90 to 90, lon: -180 to 180, weights: 0-100)
- Implementation: RouteRequest, LatLon, SegmentMetric defined in `backend/app/models.py`

**Authentication:**
- Approach: None (MVP); CORS allows all origins via `allow_origins=["*"]`
- Future: Would require Bearer token or API key middleware

**Caching:**
- Approach: Two separate TTL caches (segments: 5min, routes: 2min) for independent invalidation
- Key generation: SHA256 hash of request parameters ensures deterministic lookups
- Invalidation: Time-based TTL via cachetools, manual clear via POST `/cache/clear`

**Database Connections:**
- Approach: Context manager pattern (`with get_connection() as conn`) ensures cleanup
- Connection string: Loaded from `DATABASE_URL` env var with fallback to localhost

---

*Architecture analysis: 2026-04-23*
