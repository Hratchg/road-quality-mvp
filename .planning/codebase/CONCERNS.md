# Codebase Concerns

**Analysis Date:** 2026-04-23

## Security Issues

**Hardcoded Database Credentials:**
- Issue: Database passwords (`rqpass`) embedded in code and docker-compose.yml
- Files: 
  - `backend/app/db.py` (default connection string)
  - `scripts/compute_scores.py` (line 7)
  - `scripts/ingest_iri.py` (line 42)
  - `scripts/seed_data.py` (line 16)
  - `docker-compose.yml` (lines 5-7)
- Impact: Any git history exposure reveals production credentials. Default credentials visible to anyone with code access.
- Fix approach: Move all credentials to environment variables. Never commit docker-compose with plaintext passwords. Use secure secret management for production.

**CORS Misconfiguration:**
- Issue: CORS allows all origins (`allow_origins=["*"]`)
- Files: `backend/app/main.py` (lines 8-12)
- Impact: API is open to any website making requests. Enables CSRF attacks and unintended cross-origin requests.
- Fix approach: Restrict to specific frontend origin(s) once deployed. Use environment-based CORS configuration.

**No Input Validation on fetchone() Calls:**
- Issue: Direct subscript access `cur.fetchone()["id"]` without null check
- Files: `backend/app/routes/routing.py` (lines 73, 75)
- Impact: If snap-to-node query returns null (invalid coordinates), code crashes with unhelpful error. No graceful degradation.
- Fix approach: Add explicit null checks before accessing dictionary keys. Return meaningful error responses.

**Unhandled Database Query Exceptions:**
- Issue: Database operations lack try-catch blocks
- Files: `backend/app/routes/routing.py` (entire function), `backend/app/routes/segments.py` (lines 38-41)
- Impact: SQL errors, connection timeouts, or pgRouting failures crash the endpoint without logging. Clients get generic 500 errors.
- Fix approach: Wrap all database operations in try-except. Log detailed errors. Return appropriate HTTP status codes (504 for timeout, 400 for bad queries).

## Tech Debt

**Single Database Connection Per Request:**
- Issue: Each request creates a new connection via `get_connection()` and discards it
- Files: `backend/app/db.py`, `backend/app/routes/routing.py`, `backend/app/routes/segments.py`, `backend/app/routes/cache_routes.py`
- Impact: High connection overhead. With concurrent requests, will exhaust PostgreSQL connection pool (default 100). No connection reuse, no pooling.
- Fix approach: Implement psycopg2 connection pooling (e.g., `psycopg2.pool.SimpleConnectionPool`) or migrate to SQLAlchemy with built-in pooling.

**In-Memory Caching Has No Persistence:**
- Issue: Cache uses `cachetools.TTLCache` in process memory
- Files: `backend/app/cache.py` (lines 13-14)
- Impact: 
  - Cache lost on process restart
  - Route cache key space collisions unlikely but unmonitored
  - No cache coherency across multiple backend instances
  - Expensive pgr_ksp queries re-executed for every restart
- Fix approach: Use Redis for distributed, persistent caching. Implement cache invalidation strategy.

**Hardcoded Route Constants:**
- Issue: K=5 for K-shortest paths, cache TTLs (300s, 120s), confidence thresholds are hardcoded
- Files: 
  - `backend/app/routes/routing.py` (line 37: `K = 5`)
  - `backend/app/cache.py` (lines 13-14)
  - `data_pipeline/yolo_detector.py` (lines 43, 149-152)
- Impact: Changing algorithm parameters requires code modification and redeployment. No way to tune performance/accuracy without restart.
- Fix approach: Move to environment variables or a configuration module. Allow runtime updates where appropriate.

**Frontend Relies on Hardcoded LA Coordinates:**
- Issue: Routes and bounding boxes hardcoded for Los Angeles
- Files: `frontend/src/pages/RouteFinder.tsx` (line 10), `frontend/src/pages/MapView.tsx` (line 8), `frontend/src/hooks/useNominatim.ts` (line 15)
- Impact: Not portable to other cities. Nominatim viewbox fixes results to LA area. Would need code changes for different region.
- Fix approach: Make location configurable. Add a location selector or environment-based region setup.

**No Request Logging or Request ID Correlation:**
- Issue: Route requests logged to database but no unique request ID or correlation tracking
- Files: `backend/app/routes/routing.py` (lines 58-62)
- Impact: Hard to trace a specific user's request through logs. No request tracing across backend services.
- Fix approach: Implement request ID middleware. Add correlation IDs to all logs.

## Database Design Issues

**Inconsistent Null Handling in Queries:**
- Issue: LEFT JOIN with COALESCE for segment_scores but optional JSON fields not always present
- Files: `backend/app/routes/routing.py` (line 25-35), `backend/app/routes/segments.py` (line 25-36)
- Impact: Missing segment_scores fields return 0, which is ambiguous (0 actual vs 0 missing data). Frontend can't distinguish.
- Fix approach: Return explicit null vs 0. Add metadata field indicating data availability.

**No Indexes on route_requests Audit Log:**
- Issue: `route_requests` table appended to on every route request without cleanup or indexing strategy
- Files: `backend/app/routes/routing.py` (lines 58-62)
- Impact: Table grows unbounded. Queries slow down over time. No retention policy.
- Fix approach: Add VACUUM/ANALYZE schedule. Implement data retention policy (e.g., delete > 30 days). Add index on timestamp.

## Performance Concerns

**pgr_ksp Can Be Slow with Wide Point Spacing:**
- Issue: Routing comment notes "spacing causes exponential blowup" but no runtime safeguards
- Files: `backend/app/routes/routing.py` (line 37: `K = 5`)
- Impact: Users far apart (>500m) may hit timeout. No max-distance check. Tests use narrow spacing (~200m) which doesn't catch this.
- Fix approach: Add distance check before pgr_ksp. Warn or reject if > threshold. Increase K or decrease timeout gracefully.

**Expensive Recomputation on Cache Miss:**
- Issue: Every unique route query re-runs full pgr_ksp even for slightly different coords
- Files: `backend/app/routes/routing.py` (lines 78-149)
- Impact: Nearby points with minor weight/budget changes force full recomputation. No approximate/nearby cache hits.
- Fix approach: Consider spatial quantization for cache keys (round coords to nearest 0.01 degree) for approximate hits.

**No Query Timeout on Database Operations:**
- Issue: `cur.execute()` calls have no timeout parameter
- Files: `backend/app/routes/routing.py`, `backend/app/routes/segments.py`
- Impact: Slow queries can hang indefinitely, blocking connections. Frontend will wait until server timeout.
- Fix approach: Set `statement_timeout` on connection or use `timeout` in execute calls.

## Fragile Areas

**Route Response Snapping Logic:**
- Files: `frontend/src/pages/RouteFinder.tsx` (lines 74-81)
- Why fragile: After getting route, code re-snaps origin/destination to route endpoints. If route geometry is empty, snapping fails silently.
- Safe modification: Check for empty geometry before snapping. Store snapped coords separately from user-entered text.
- Test coverage: No test for empty route case in frontend.

**Detection Severity Mapping in YOLO Detector:**
- Files: `data_pipeline/yolo_detector.py` (lines 128-157)
- Why fragile: Severity mapped based on class name string matching (case-insensitive). If model changes class names, all detections become unknown.
- Safe modification: Make class name mapping configurable. Add validation that model's classes match expected set.
- Test coverage: `backend/tests/test_yolo_detector.py` tests the logic but uses mock model.

**Address Input Nominatim Integration:**
- Files: `frontend/src/hooks/useNominatim.ts`, `frontend/src/components/AddressInput.tsx` (line 58)
- Why fragile: `parseFloat(result.lat)` and `parseFloat(result.lon)` assume Nominatim always returns valid numbers. No validation.
- Safe modification: Add try-catch around parseFloat. Validate lat/lon ranges before passing to API.
- Test coverage: No unit tests for useNominatim hook.

**No Error Handling for Coordinate Parsing:**
- Files: `frontend/src/pages/MapView.tsx` (line 51: bbox parsing)
- Why fragile: Trusts Leaflet map bounds are always valid. If bounds calculation fails, bbox becomes malformed string.
- Safe modification: Validate bbox format before API call. Handle Leaflet coordinate errors.

## Test Coverage Gaps

**Routing Edge Cases Not Fully Covered:**
- What's not tested: 
  - Coordinates that snap to same node (origin == destination)
  - Out-of-network coordinates (no valid snap)
  - Partial segment coverage (empty segment_data dict)
- Files: `backend/tests/test_route.py`, `backend/tests/test_integration.py`
- Risk: Silent failures returning empty routes instead of errors. No validation of edge cases.
- Priority: High - routing is core feature

**Frontend Route Display Has No Error States:**
- What's not tested: 
  - Handling of undefined geojson coordinates
  - Empty fastest_route vs best_route
  - Network latency / slow responses
- Files: `frontend/src/pages/RouteFinder.tsx` (lines 169-179)
- Risk: Rendering null/undefined in Polyline crashes React. No user feedback on loading state nuances.
- Priority: Medium - mostly dev error but impacts UX

**Data Pipeline Detector Tests Are Mocked:**
- What's not tested: 
  - Real YOLO model loading and inference
  - Model file missing scenario (code handles it but untested)
  - Different model architectures (single-class vs two-class)
- Files: `backend/tests/test_yolo_detector.py`
- Risk: Model load errors only caught at runtime in production. No guarantee model path is correct.
- Priority: Medium - failure graceful but unprepared

**No Tests for IRI Ingestion Spatial Matching:**
- What's not tested: 
  - Spatial join correctness for various road network topologies
  - Batch update consistency
  - Edge cases like duplicate locations or far-from-network points
- Files: `scripts/ingest_iri.py`, `backend/tests/test_iri_ingestion.py`
- Risk: Silent data corruption (wrong segment gets wrong IRI). Batch commits hide partial failures.
- Priority: High - affects data integrity

**Cache TTL and Eviction Not Tested:**
- What's not tested: 
  - TTL expiration behavior
  - Maxsize LRU eviction
  - Thread-safety under concurrent access
- Files: `backend/app/cache.py`, `backend/tests/test_cache.py`
- Risk: Cache behavior under load unknown. May evict wrong entries or leak memory.
- Priority: Medium - will show up with scale

## Outdated / Deprecated Patterns

**Hardcoded Model Path with Relative Resolution:**
- Issue: Model path defaults to `"models/pothole_yolov8.pt"` resolved relative to CWD
- Files: `data_pipeline/yolo_detector.py` (line 42)
- Impact: Working directory affects where model is loaded from. Breaks in different run contexts.
- Fix approach: Use `Path(__file__).parent` or absolute paths. Make configurable.

**String-Based SQL Instead of ORM:**
- Issue: Raw SQL queries embedded in route logic
- Files: `backend/app/routes/routing.py` (lines 10-35)
- Impact: Hard to test, reuse, or modify queries. Vulnerable if inputs not properly parameterized (though currently done correctly).
- Fix approach: Consider migration to SQLAlchemy for type safety and composable queries.

## Missing Observability

**No Structured Logging:**
- Issue: Uses Python `logging` module but no structured format (JSON, key-value pairs)
- Files: Throughout backend
- Impact: Logs hard to parse/aggregate. CloudWatch/ELK integration would be difficult.
- Fix approach: Add structured logging library (e.g., `python-json-logger`).

**No Metrics or Monitoring:**
- Issue: No Prometheus metrics, request latency tracking, or cache hit rates
- Files: All services
- Impact: Can't monitor performance in production. No alerts on slow queries or cache misses.
- Fix approach: Add Prometheus client. Instrument endpoints for latency, cache hits, DB query times.

**No Health Check Details:**
- Issue: Health endpoint just returns `{"status": "ok"}`
- Files: `backend/app/routes/health.py`
- Impact: Can't verify DB connectivity or data pipeline readiness from health check.
- Fix approach: Add component checks (DB reachability, model file presence) to health endpoint.

## Scaling Limitations

**Frontend API URL Hardcoded for localhost:**
- Issue: Vite proxy config targets `http://localhost:8000` and frontend defaults to `/api`
- Files: `frontend/vite.config.ts` (line 10), `frontend/src/api.ts` (line 1)
- Impact: Docker Compose sets frontend API to `http://localhost:8000` which breaks if services on different hosts. Production needs explicit config.
- Fix approach: Make API URL configurable via environment. Default to relative path `/api`.

**No Pagination for Segments Endpoint:**
- Issue: `/segments?bbox=...` returns ALL features in bbox with no limit
- Files: `backend/app/routes/segments.py` (line 40)
- Impact: Large bboxes (many segments) cause huge responses and browser rendering lag. Network will time out.
- Fix approach: Add optional `limit` and `offset` query params. Implement proper pagination.

**Cache Maxsize Hardcoded:**
- Issue: Route cache maxsize=128, segments cache maxsize=256
- Files: `backend/app/cache.py` (lines 13-14)
- Impact: With many concurrent users, cache will evict frequently. Memory usage unbounded if cache not cleared.
- Fix approach: Make configurable. Implement cache statistics endpoint to monitor hit rates.

**No Database Backups Strategy:**
- Issue: No backup mechanism in place
- Files: `docker-compose.yml` (volume: `pgdata`)
- Impact: Data loss on container deletion. Seed data takes ~5 min, but segment_scores computed data is irreplaceable.
- Fix approach: Add automated daily backups. Document restore procedure.

## Configuration Smells

**Environment Variable Missing for YOLO Model:**
- Issue: Model path hardcoded, no env var override
- Files: `data_pipeline/yolo_detector.py` (line 42)
- Impact: Can't swap model variants without code change.
- Fix approach: Add `MODEL_PATH` env var with fallback.

**Frontend Missing API Base URL Config:**
- Issue: API base determined by Vite proxy or hardcoded `/api`
- Files: `frontend/src/api.ts` (line 1)
- Impact: Breaks if backend on different host/port. Hard to swap between local/staging/prod.
- Fix approach: Add `VITE_API_URL` env var (already in docker-compose but unused in dev).

**No .env.example File:**
- Issue: Required env vars not documented
- Files: Project root
- Impact: New developers don't know which vars to set.
- Fix approach: Create `.env.example` with all required vars and descriptions.

---

*Concerns audit: 2026-04-23*
