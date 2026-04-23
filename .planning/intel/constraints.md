# Constraints Intel

Extracted from `docs/plans/2026-02-23-pothole-tracker-design.md` (SPEC class, medium confidence, Status: Approved, 2026-02-23). Per the active precedence `SPEC > PRD > DOC`, these are the authoritative technical constraints for downstream planning.

Each constraint carries `type`: `api-contract | schema | nfr | protocol | stack`.

---

## Stack Constraints

### CON-stack-backend
- source: docs/plans/2026-02-23-pothole-tracker-design.md
- type: stack
- content:
  - Language: Python 3.12+
  - Framework: FastAPI with CORS middleware
  - DB adapter: psycopg2 with RealDictCursor
  - ASGI server: uvicorn
  - Validation: Pydantic v2
  - Test runner: pytest

### CON-stack-frontend
- source: docs/plans/2026-02-23-pothole-tracker-design.md
- type: stack
- content:
  - Language: TypeScript
  - Framework: React 18
  - Build: Vite
  - Map: react-leaflet (default) / react-map-gl (Mapbox)
  - Styling: Tailwind CSS
  - State: useState/useEffect (no global store for MVP)

### CON-stack-database
- source: docs/plans/2026-02-23-pothole-tracker-design.md
- type: stack
- content:
  - Engine: PostgreSQL 16
  - Extensions required: PostGIS 3.4, pgRouting 3.6
  - Container base: `postgis/postgis:16-3.4` with `postgresql-16-pgrouting` apt-installed on top
  - Geometry SRID: 4326 (WGS84)

### CON-stack-data-pipeline
- source: docs/plans/2026-02-23-pothole-tracker-design.md
- type: stack
- content:
  - OSM ingest: osmnx (LA drive network, 10km radius from center 34.0522, -118.2437)
  - ML: `PotholeDetector` Protocol with `StubDetector` (MVP) and `YOLOv8Detector` (future)

---

## Schema Constraints

### CON-db-schema
- source: docs/plans/2026-02-23-pothole-tracker-design.md (section 4)
- type: schema
- content: Four tables define the MVP data model. All columns and types are load-bearing — downstream migrations must not rename or drop without ADR.

  **road_segments** (pgRouting edges)
  - `id` SERIAL PRIMARY KEY
  - `osm_way_id` BIGINT
  - `geom` GEOMETRY(LineString, 4326) NOT NULL
  - `length_m` DOUBLE PRECISION NOT NULL
  - `travel_time_s` DOUBLE PRECISION NOT NULL (derived from OSM speed limits)
  - `source` BIGINT (pgRouting node id)
  - `target` BIGINT (pgRouting node id)
  - `iri_value` DOUBLE PRECISION (raw m/km)
  - `iri_norm` DOUBLE PRECISION (0-1 normalized)
  - `created_at` TIMESTAMPTZ DEFAULT NOW()

  **segment_defects** (detection events)
  - `id` SERIAL PRIMARY KEY
  - `segment_id` INTEGER FK → road_segments(id) ON DELETE CASCADE
  - `severity` VARCHAR(10) CHECK IN ('moderate', 'severe')
  - `count` INTEGER NOT NULL DEFAULT 1
  - `confidence_sum` DOUBLE PRECISION NOT NULL DEFAULT 0.0
  - `created_at` TIMESTAMPTZ DEFAULT NOW()

  **segment_scores** (pre-aggregated per segment)
  - `segment_id` INTEGER PRIMARY KEY FK → road_segments(id) ON DELETE CASCADE
  - `moderate_score` DOUBLE PRECISION DEFAULT 0.0 — `0.5 * sum(count * confidence)`
  - `severe_score` DOUBLE PRECISION DEFAULT 0.0 — `1.0 * sum(count * confidence)`
  - `pothole_score_total` DOUBLE PRECISION DEFAULT 0.0 — `moderate + severe`
  - `updated_at` TIMESTAMPTZ DEFAULT NOW()

  **route_requests** (audit log)
  - `id` SERIAL PRIMARY KEY
  - `params_json` JSONB NOT NULL
  - `created_at` TIMESTAMPTZ DEFAULT NOW()

  **Indexes (mandatory):**
  - GIST on `road_segments(geom)`
  - BTREE on `road_segments(source)` and `road_segments(target)` (pgRouting perf)
  - BTREE on `segment_defects(segment_id)`

- notes: SPEC declares `source` and `target` as `BIGINT`; implementation plan (DOC) declares them as `INTEGER`. SPEC > DOC wins. Codebase migrations should be verified — flagged INFO.

---

## API Contract Constraints

### CON-route-api
- source: docs/plans/2026-02-23-pothole-tracker-design.md (section 6)
- type: api-contract
- endpoint: `POST /route`
- content:
  - Request body fields:
    - `origin: {lat: number, lon: number}` — required, WGS84
    - `destination: {lat: number, lon: number}` — required, WGS84
    - `include_iri: boolean` — default true
    - `include_potholes: boolean` — default true
    - `weight_iri: number` (0-100) — default 50 (per SETUP); SPEC example uses 60
    - `weight_potholes: number` (0-100) — default 50 (per SETUP); SPEC example uses 40
    - `max_extra_minutes: number` (>=0) — default 5
  - Response body fields:
    - `fastest_route: {geojson, total_time_s, total_cost, ...}`
    - `best_route: {geojson, total_time_s, total_cost, avg_iri_norm, total_moderate_score, total_severe_score}`
    - `warning: string | null`
    - `per_segment_metrics: [{id, iri_norm, pothole_score}, ...]` — per SPEC; SETUP restates as per-segment IRI + pothole score on the best route

### CON-segments-api
- source: docs/plans/2026-02-23-pothole-tracker-design.md (section 6)
- type: api-contract
- endpoint: `GET /segments?bbox={min_lon,min_lat,max_lon,max_lat}`
- content:
  - Response: GeoJSON FeatureCollection
  - Feature `properties`: `id`, `iri_norm`, `moderate_score`, `severe_score`, `pothole_score_total`
  - Geometry: LineString in EPSG:4326

### CON-health-api
- source: docs/plans/2026-02-23-pothole-tracker-design.md (section 6)
- type: api-contract
- endpoint: `GET /health`
- content: Returns `{"status": "ok"}` HTTP 200. No request body or query params.

### CON-cache-admin-api
- source: docs/SETUP.md (DOC class; SPEC did not originally document these — the SPEC is older and this was added during caching feature work)
- type: api-contract
- endpoint: `GET /cache/stats`, `POST /cache/clear`
- content:
  - `GET /cache/stats` → `{segments_cache_size, route_cache_size, segments_cache_maxsize, route_cache_maxsize}`
  - `POST /cache/clear` → `{cleared: true}`
- notes: Lower-precedence DOC adds an endpoint the SPEC does not mention. This is an additive (non-conflicting) extension. Flagged INFO (auto-resolved as additive).

---

## Protocol Constraints

### CON-pothole-detector-protocol
- source: docs/plans/2026-02-23-pothole-tracker-design.md (section 8)
- type: protocol
- content:
  ```python
  class PotholeDetector(Protocol):
      def detect(self, image_path: str) -> list[Detection]: ...
  ```
  Implementations in the MVP:
  - `StubDetector` — deterministic mock for dev/test
  - `YOLOv8Detector` — Ultralytics YOLOv8-backed real detector, selectable via factory
  - Factory `get_detector(use_yolo=False, model_path=None)` returns stub when `ultralytics` unavailable.

### CON-scoring-math
- source: docs/plans/2026-02-23-pothole-tracker-design.md (section 5)
- type: protocol
- content:
  - Pothole scoring per segment: `moderate_score = 0.5 * sum(count * confidence)`, `severe_score = 1.0 * sum(count * confidence)`.
  - Per-image severity assignment: `if score_Severe >= 0.5 → Severe; elif score_Moderate >= 0.5 → Moderate; else → Not reported; ties → Severe`.
  - Route cost: `cost_segment = travel_time_s + w_IRI * iri_norm + w_pothole * (moderate_score + severe_score)`. `total_route_cost = sum(cost_segment)`.
  - Weight normalization: one-enabled → that weight = 1.0; both-enabled → `w_x = weight_x / (weight_iri + weight_potholes)`; neither-enabled → both 0.0; both-enabled with zero weights → 0.5 / 0.5 (implementation plan tiebreaker, consistent with SPEC intent).
  - Max-time rule: reject candidates where `total_time > fastest_time + max_extra_minutes * 60`; if all rejected, return fastest + warning.

### CON-route-selection-algorithm
- source: docs/plans/2026-02-23-pothole-tracker-design.md (section 3) + docs/SETUP.md (architecture overview)
- type: protocol
- content:
  1. Snap origin/destination to nearest pgRouting nodes (KNN spatial query).
  2. Run `pgr_ksp()` with K=5 to find 5 candidate shortest paths.
  3. Score each path: sum of segment costs using `CON-scoring-math`.
  4. Identify fastest path by minimum total travel time.
  5. Apply time-budget filter.
  6. Return the lowest-cost path within budget as `best_route`.
  7. If no candidate fits the budget, return fastest as both + populate `warning`.

---

## Non-Functional Constraints

### CON-caching-nfr
- source: docs/SETUP.md (DOC; SPEC predates caching feature)
- type: nfr
- content:
  - Segments cache: TTL 5 minutes, max 256 entries (keyed by bbox).
  - Routes cache: TTL 2 minutes, max 128 entries (keyed by route request params).
  - In-memory only; no external cache (Redis/memcached) for MVP.

### CON-ports-nfr
- source: docs/plans/2026-02-23-pothole-tracker-design.md + docs/SETUP.md
- type: nfr
- content:
  - Frontend dev server: 3000
  - Backend API: 8000
  - PostgreSQL: 5432
  - Ports exposed via `docker-compose.yml`.

### CON-seed-data-nfr
- source: docs/plans/2026-02-23-pothole-tracker-design.md
- type: nfr
- content:
  - OSMnx center: (34.0522, -118.2437), LA downtown.
  - Radius: 10 km (SPEC). SETUP.md states ~20 km — see INGEST-CONFLICTS.md INFO; SPEC > DOC.
  - Synthetic IRI range: 1.0-12.0 m/km, biased higher on arterials.
  - Pothole defects: ~30% of segments get 1-3 records each.
  - Seed: 42 (deterministic).

### CON-cors-nfr
- source: docs/plans/2026-02-23-pothole-tracker-design.md (section 11 / implementation plan Task 2)
- type: nfr
- content: Backend FastAPI has CORS enabled for all origins in development. Production CORS policy is TBD (out of MVP scope).

### CON-migrations-nfr
- source: docs/plans/2026-02-23-pothole-tracker-design.md (section 10)
- type: nfr
- content: Single SQL migration file `db/migrations/001_initial.sql`. No Alembic for MVP. Subsequent schema changes require a new migration file or an explicit decision to adopt Alembic.
