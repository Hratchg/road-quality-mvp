# Testing Patterns

**Analysis Date:** 2026-04-23

## Test Framework

**Backend:**

**Runner:**
- pytest 8.3.4
- Config: No `pytest.ini` or `setup.cfg` found; using defaults
- Markers: Custom `integration` marker defined in `conftest.py` via `pytest_configure`

**Assertion Library:**
- pytest built-in assertions (using `assert` statements)
- Pydantic `ValidationError` for validation testing

**Run Commands:**
```bash
pytest                           # Run all tests
pytest -v                        # Verbose output
pytest -k "test_scoring"         # Run specific test
pytest -m integration            # Run only integration tests (need live DB)
pytest --tb=short                # Short traceback format
pytest tests/test_health.py       # Run specific file
```

**Frontend:**
- No test framework detected
- No test files found (no `.test.ts`, `.spec.ts`, or test directory)

## Test File Organization

**Backend Location:**
- Path: `backend/tests/`
- Pattern: `test_*.py` (e.g., `test_scoring.py`, `test_cache.py`, `test_models.py`)
- Structure:
  ```
  backend/tests/
  ├── __init__.py
  ├── conftest.py              # Fixtures and configuration
  ├── test_cache.py            # Cache module tests
  ├── test_detector.py         # StubDetector tests
  ├── test_health.py           # Health endpoint
  ├── test_integration.py      # Live DB tests (marked with @pytest.mark.integration)
  ├── test_iri_ingestion.py    # IRI data ingestion
  ├── test_models.py           # Pydantic model validation
  ├── test_route.py            # Route endpoint with mocks
  ├── test_scoring.py          # Scoring functions
  ├── test_segments.py         # Segments endpoint with mocks
  └── test_yolo_detector.py    # YOLOv8Detector with mocked ultralytics
  ```

**Frontend:**
- No tests present
- No test directory structure

## Test Structure

**Suite Organization:**

Test files use pytest with optional class-based grouping for related tests:

```python
# Simple function-level tests
def test_health_returns_ok():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

# Class-based suites for logical grouping
class TestNormalizeWeights:
    def test_both_enabled_normalizes_to_sum_1(self):
        w_iri, w_pot = normalize_weights(...)
        assert abs(w_iri - 0.6) < 1e-9
    
    def test_only_iri_enabled(self):
        w_iri, w_pot = normalize_weights(...)
        assert w_iri == 1.0
```

**Test Naming:**
- Function tests: `test_<description>()` (e.g., `test_cache_set_and_get()`)
- Class tests: `class Test<Component>:` with methods `test_<scenario>()`
- Assertion clarity: Clear expectation in test name (e.g., `test_segments_rejects_missing_bbox`)

**Patterns:**

**Setup/Teardown:**
```python
def setup_function():
    """Clear caches before each test to avoid cross-test contamination."""
    clear_all_caches()

# Session-scoped fixtures in conftest.py
@pytest.fixture(scope="session")
def client(db_available):
    return TestClient(app)
```

**Fixtures (from `backend/tests/conftest.py`):**
```python
def pytest_configure(config):
    config.addinivalue_line("markers", "integration: marks tests that need a live database")

@pytest.fixture(scope="session")
def db_available():
    """Check if the database is reachable; skip all integration tests if not."""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.close()
        return True
    except psycopg2.OperationalError:
        pytest.skip("Database not available — skipping integration tests")

@pytest.fixture(scope="session")
def client(db_available):
    return TestClient(app)

@pytest.fixture(scope="session")
def db_conn(db_available):
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    yield conn
    conn.close()
```

## Mocking

**Framework:** unittest.mock (from standard library)

**Patterns:**

**Mocking Database Connections:**
```python
from unittest.mock import patch, MagicMock

@patch("app.routes.segments.get_connection")
def test_segments_returns_geojson(mock_conn):
    # Create mock cursor
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        {
            "id": 1,
            "geojson": '{"type":"LineString","coordinates":[...]}',
            "iri_norm": 0.4,
            "moderate_score": 1.5,
            "severe_score": 0.5,
            "pothole_score_total": 2.0,
        }
    ]
    
    # Setup context manager mocks (with statements)
    mock_conn.return_value.__enter__ = lambda s: s
    mock_conn.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn.return_value.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.return_value.cursor.return_value.__exit__ = MagicMock(return_value=False)
    
    # Test assertion
    client = TestClient(app)
    response = client.get("/segments?bbox=-118.26,34.04,-118.23,34.07")
    assert response.status_code == 200
```

**Mocking Routes with Multiple Cursors:**
```python
def _setup_mock_conn(mock_conn):
    """Wire up mock connection with cursor context managers."""
    mock_cursor = MagicMock()
    mock_conn.return_value.__enter__ = lambda s: s
    mock_conn.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn.return_value.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.return_value.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn.return_value.commit = MagicMock()
    return mock_cursor

@patch("app.routes.routing.get_connection")
def test_route_returns_best_and_fastest(mock_conn):
    mock_cursor = _setup_mock_conn(mock_conn)
    
    # Multiple fetchone results (for snapping origin and destination)
    mock_cursor.fetchone.side_effect = [
        {"id": 100},  # origin node
        {"id": 200},  # destination node
    ]
    
    # Multiple fetchall results (KSP results, then segment data)
    mock_cursor.fetchall.side_effect = [
        _mock_ksp_results(),
        _mock_segment_data(),
    ]
    
    # Test assertion
    client = TestClient(app)
    response = client.post("/route", json={...})
    assert response.status_code == 200
```

**Mocking External Modules (YOLO detector):**
```python
from unittest.mock import patch, MagicMock
import types
import sys

def _make_mock_ultralytics():
    """Create a mock ultralytics module with a YOLO class."""
    mock_mod = types.ModuleType("ultralytics")
    mock_mod.YOLO = MagicMock
    return mock_mod

with patch.dict(sys.modules, {"ultralytics": _make_mock_ultralytics()}):
    from data_pipeline.yolo_detector import YOLOv8Detector
    detector = YOLOv8Detector(model_path="fake.pt")
```

**What to Mock:**
- Database connections: Always mock `get_connection()` for unit tests
- External APIs: Mock HTTP calls (could be done but not yet in codebase)
- File system: Mock path checks in detector (seen in YOLOv8Detector tests)
- Expensive operations: pgr_ksp routing in unit tests

**What NOT to Mock:**
- Pydantic model validation: Test actual validation behavior
- Pure functions: `normalize_weights()`, `compute_segment_cost()` tested without mocks
- Cache operations: Test actual TTLCache behavior
- StubDetector: Use real StubDetector (deterministic, no external deps)

## Fixtures and Factories

**Test Data:**

**Database-free test fixtures:**
```python
def _mock_ksp_results():
    """Simulate pgr_ksp returning 2 paths on a tiny graph."""
    return [
        {"path_id": 1, "seq": 1, "edge": 1, "cost": 60.0},
        {"path_id": 1, "seq": 2, "edge": 2, "cost": 60.0},
        {"path_id": 2, "seq": 1, "edge": 3, "cost": 70.0},
        {"path_id": 2, "seq": 2, "edge": 4, "cost": 70.0},
    ]

def _mock_segment_data():
    """Segment data for edges referenced by ksp."""
    return [
        {
            "id": 1, "travel_time_s": 60.0, "iri_norm": 0.8,
            "pothole_score_total": 3.0, "moderate_score": 1.5, "severe_score": 1.5,
            "geojson": '{"type":"LineString","coordinates":[[-118.24,34.05],[-118.245,34.055]]}',
        },
        # ... more segments
    ]
```

**Location:**
- Private test helpers: Defined within test files with `_` prefix (e.g., `_mock_segments()`)
- Shared fixtures: In `conftest.py` using `@pytest.fixture` decorator
- No separate factory or fixture files

## Coverage

**Requirements:** Not explicitly enforced

**View Coverage:**
```bash
pytest --cov=app --cov-report=html     # Generate HTML report (if pytest-cov installed)
pytest --cov=app --cov-report=term     # Terminal coverage report
```

**Observed Coverage:**
- Core modules well-tested: `scoring.py`, `models.py`, `cache.py`
- Route handlers tested with mocks: `segments.py`, `routing.py`
- Integration tests: Point-to-point routing, segments bbox queries
- **Frontend: No tests** — TypeScript compiled but no test coverage
- **Scripts: No tests** — Data pipeline scripts (`compute_scores.py`, `ingest_iri.py`) not tested

## Test Types

**Unit Tests:**
- Scope: Individual functions and classes
- Approach: Test in isolation with mocks
- Examples:
  - `TestNormalizeWeights` — pure function variants
  - `TestComputeSegmentCost` — cost calculation logic
  - `test_cache_set_and_get()` — cache operations
  - `test_route_request_valid()` — Pydantic model validation
- No external dependencies required (DB mocked or local)

**Integration Tests:**
- Scope: Full request → database → response flow
- Approach: Use real TestClient against FastAPI app with live PostgreSQL
- Marker: `@pytest.mark.integration` (auto-skipped if DB unavailable)
- Examples:
  - `test_segments_returns_geojson(client)` — Live segments query
  - `test_route_real_points(client)` — Live routing with pgr_ksp
  - `test_segments_empty_bbox()` — Edge cases with real DB
- Auto-skip: `db_available` fixture detects unreachable DB, skips gracefully
- Timeout: `@pytest.mark.timeout(30)` on slow route tests

**E2E Tests:**
- Not used
- Frontend has no tests at all
- No browser/Selenium tests

## Common Patterns

**Async Testing:**
- Not used in backend (FastAPI routes are sync, not async)
- Frontend hooks use async but untested

**Error Testing:**

**Validation Errors:**
```python
def test_route_request_rejects_invalid_lat():
    with pytest.raises(ValidationError):
        LatLon(lat=100.0, lon=-118.24)  # lat > 90, rejected by Field(ge=-90, le=90)
```

**API Error Responses:**
```python
def test_segments_rejects_missing_bbox():
    client = TestClient(app)
    response = client.get("/segments")  # Missing required bbox query param
    assert response.status_code == 422  # FastAPI auto-validates, returns 422
```

**HTTPException:**
```python
def test_segments_returns_400_on_invalid_bbox(mock_conn):
    client = TestClient(app)
    response = client.get("/segments?bbox=invalid,values")  # ValueError on float parse
    assert response.status_code == 400  # Route raises HTTPException(status_code=400)
    assert response.json()["detail"] == "bbox values must be numbers"
```

**Database-Less Tests:**

Most unit tests mock `get_connection()` and use `@patch` decorator:
```python
@patch("app.routes.segments.get_connection")
def test_segments_returns_geojson(mock_conn):
    # No DB required
    ...
```

Allows tests to run in CI/CD without Docker/Postgres.

**TestClient Usage:**
```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
response = client.get("/health")
assert response.status_code == 200
```

## Test Execution Patterns

**Setup/Teardown:**

**Function-level:**
```python
def setup_function():
    """Called before each test function in the file."""
    clear_all_caches()

def teardown_function():
    """Called after each test function (not used in observed tests)."""
    pass
```

**Fixture-based:**
```python
@pytest.fixture(scope="session")
def client(db_available):
    """Single client instance shared across all tests in session."""
    return TestClient(app)
    # Auto-closed after session ends

@pytest.fixture
def fresh_cache():
    """Function-scoped, called for each test."""
    clear_all_caches()
    yield
    clear_all_caches()  # Cleanup
```

## Data Pipeline & Scripts

**No tests found** for:
- `data_pipeline/` — `detector.py`, `yolo_detector.py`, `detector_factory.py` (only tested via backend)
- `scripts/` — `compute_scores.py`, `ingest_iri.py`, `seed_data.py` (no tests)

**Testing strategy:**
- Detector tested through `test_detector.py`, `test_yolo_detector.py` in backend
- Scripts assumed to be run manually or in CI as part of data setup
- YOLOv8Detector mocking approach allows testing without ultralytics installed

## Frontend Testing Status

**Current:** No tests implemented

**Implications:**
- Components untested: `MapView`, `RouteFinder`, `AddressInput`, `ControlPanel`, `RouteResults`, `Legend`
- Hooks untested: `useNominatim`
- API client untested: `api.ts` functions
- Risk: UI logic changes may break without detection

**Potential Approach (if testing added):**
- Framework: Vitest (lightweight, Vite-native) or Jest
- UI testing: React Testing Library (component behavior, not implementation)
- Examples:
  ```typescript
  describe('RouteFinder', () => {
    it('should display route results when route is found', async () => {
      render(<RouteFinder />);
      // Simulate user interactions
      // Assert UI updates
    });
  });
  ```

---

*Testing analysis: 2026-04-23*
