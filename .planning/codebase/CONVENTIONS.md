# Coding Conventions

**Analysis Date:** 2026-04-23

## Naming Patterns

**Files (Backend - Python):**
- Modules: `snake_case` (e.g., `detector.py`, `yolo_detector.py`, `compute_scores.py`)
- Route files: `descriptive_noun.py` (e.g., `segments.py`, `routing.py`, `health.py`, `cache_routes.py`)
- Classes: `PascalCase` (e.g., `StubDetector`, `YOLOv8Detector`, `RouteRequest`, `SegmentMetric`)
- Test files: `test_*.py` or `*_test.py` (e.g., `test_scoring.py`, `test_models.py`, `test_cache.py`)

**Files (Frontend - TypeScript/React):**
- Page components: `PascalCase.tsx` (e.g., `MapView.tsx`, `RouteFinder.tsx`)
- UI components: `PascalCase.tsx` (e.g., `AddressInput.tsx`, `ControlPanel.tsx`, `RouteResults.tsx`)
- Hooks: `use*.ts` (e.g., `useNominatim.ts`)
- Utilities: `camelCase.ts` (e.g., `api.ts`)
- Config files: lowercase with dots (e.g., `vite.config.ts`, `tsconfig.json`)

**Functions:**
- Backend: `snake_case` (e.g., `normalize_weights`, `compute_segment_cost`, `get_detector`, `get_segments_cached`)
- Frontend: `camelCase` for regular functions, `PascalCase` for React components (e.g., `handleSwap`, `geoJsonToLatLngs`, `fetchRoute`)
- Mocking helpers: `_snake_case` prefix for private test helpers (e.g., `_mock_ksp_results`, `_mock_segments`, `_setup_mock_conn`)

**Variables:**
- Backend: `snake_case` consistently (e.g., `DATABASE_URL`, `api_key`, `total_cost`)
- Frontend: `camelCase` (e.g., `originText`, `maxExtra`, `loading`, `wrapperRef`)
- Constants: `UPPER_SNAKE_CASE` when truly constant at module level (e.g., `LA_CENTER`, `NOMINATIM_URL`, `DEBOUNCE_MS`, `MIN_CHARS`, `K = 5`)
- React state: `camelCase` with descriptive names (e.g., `includeIri`, `includePotholes`, `weightIri`)

**Types & Interfaces:**
- Backend Pydantic models: `PascalCase` (e.g., `LatLon`, `RouteRequest`, `RouteResponse`, `SegmentMetric`)
- Frontend interfaces: `PascalCase` (e.g., `AddressInputProps`, `ControlState`, `NominatimResult`, `RouteRequestBody`)
- Union types: Use Python's `|` syntax in Backend (e.g., `str | None`, `float | None`, `list[Detection]`)
- Optional/nullable: Use TypeScript `?` or `| null` in Frontend

## Code Style

**Formatting:**
- No automatic formatter detected (.prettierrc, .eslintrc not configured)
- Python: PEP 8 style implicitly followed (evident from code samples)
- TypeScript: Modern ES2020+, strict mode enabled (see `tsconfig.json`)
- Line length: Appears to be flexible, longest observed ~120 chars

**Indentation & Spacing:**
- Python: 4 spaces
- TypeScript: 2 spaces (observed in vite.config.ts, tsx components)
- No explicit line-length limit enforced

**Linting:**
- No `.eslintrc` or linter config found for frontend
- No `pylintrc` or similar for backend
- Type checking enforced via TypeScript strict mode: `"strict": true` in `tsconfig.json`
- Python type hints used sparingly (e.g., function signatures in `scoring.py`, `detector.py`)

**Imports:**
- Python: Standard library → third-party → local imports (PEP 8 order observed)
  - Example: `from __future__ import annotations` at top, then `import` statements, then `from` statements
  - Local absolute imports: `from app.db import get_connection` (not relative)
  - Data pipeline imports: `from data_pipeline.detector import Detection`
- TypeScript: Similar grouping observed
  - React/third-party: `import { useState } from "react"`
  - Internal modules: `import { fetchRoute } from "../api"`
  - Local types/interfaces: imported before component definition

## Import Organization

**Order:**
1. Python `__future__` imports
2. Standard library (`import os`, `import json`)
3. Third-party packages (`import psycopg2`, `from fastapi import`)
4. Local app imports (`from app.db import`, `from app.models import`)

**Path Aliases:**
- No path aliases configured in `tsconfig.json` (moduleResolution: "bundler")
- Relative imports used in frontend (e.g., `../api`, `../hooks/useNominatim`)

## Error Handling

**Backend (FastAPI/Python):**
- HTTPException for API errors: `raise HTTPException(status_code=400, detail="message")`
- Example: `raise HTTPException(status_code=400, detail="bbox must be min_lon,min_lat,max_lon,max_lat")`
- Validation errors: Rely on Pydantic for request body validation (auto 422 response)
- Database operations: Use context managers (`with get_connection() as conn`, `with conn.cursor() as cur`)
- YOLO detector: Returns empty list on missing image/model rather than raising exception (graceful degradation)
- Fallback pattern: `get_detector()` falls back to StubDetector if ultralytics not installed

**Frontend (React/TypeScript):**
- Fetch errors: Caught and set to state: `catch (err: any) => setError(err.message || "Route request failed")`
- Use try/catch in async handlers (e.g., `handleSearch` in `RouteFinder.tsx`)
- Display errors in UI: Render error message conditionally: `{error && <p className="text-red-600 text-sm">{error}</p>}`
- Network request validation: Check response status: `if (!res.ok) throw new Error(...)`
- Hook errors: useNominatim catches AbortError and distinguishes from real errors

## Logging

**Framework:** Python built-in `logging` module (not console.log in Python scripts)

**Backend Patterns:**
- Module-level logger: `logger = logging.getLogger(__name__)`
- Log levels used:
  - `logger.info()`: Detector selection, model loading ("Using StubDetector", "Loaded YOLOv8 model")
  - `logger.warning()`: Fallback paths, missing files, dependency not installed
  - `logger.exception()`: Failures with stack trace
  - `logger.debug()`: Low-level details (unknown YOLO classes)
- Example: `logger.info("Loaded YOLOv8 model from %s", self.model_path)`

**Frontend Patterns:**
- No logging framework imported; console output not observed in code
- Error messages surfaced through UI state (`setError`)
- Status indicators via UI states (loading, error, success)

## Comments

**When to Comment:**
- Python: Docstrings for public functions and classes (seen in `yolo_detector.py`, `detector_factory.py`)
- Block comments explaining complex logic (e.g., "Snap to nearest nodes", "K-shortest paths" in `routing.py`)
- Inline comments for non-obvious SQL or algorithmic choices
- Skip comments for self-documenting code with clear variable names

**JSDoc/TSDoc:**
- Not used in frontend code
- Python docstrings (triple quotes) used for public APIs
- Function docstrings include args, returns, and description:
  ```python
  def normalize_weights(...) -> tuple[float, float]:
      """Normalize weights based on which parameters are enabled.
      
      Returns (w_iri, w_pot) that sum to 1.0 (or both 0.0 if neither enabled).
      """
  ```

## Function Design

**Size:** Relatively compact functions (10-50 lines common)
- Example: `normalize_weights()` - 10 lines
- Example: `compute_segment_cost()` - 2 lines
- Longer functions handle routing logic (50-100+ lines) with clear sections marked by comments

**Parameters:**
- Functions accept explicit parameters rather than large config objects (except for Pydantic models)
- Query parameters in routes: Use FastAPI's `Query` for validation
- Keyword-only when appropriate: Not heavily used, positional args more common

**Return Values:**
- Type hints used: `-> tuple[float, float]`, `-> list[Detection]`, `-> RouteResponse`
- Union types: `-> dict | None`, `-> str | None`
- React hooks return tuples: `{ results, loading, search, clear }`

**Dataclasses & Named Returns:**
- Pydantic models for API contracts (e.g., `RouteRequest`, `RouteResponse`)
- @dataclass for simple data structures (e.g., `Detection` in detector.py)
- Plain dicts for intermediate data (e.g., mock data in tests)

## Module Design

**Exports:**
- Backend: Use explicit imports from modules (e.g., `from app.models import RouteRequest`)
- Router registration: Import routers into `main.py` and register via `app.include_router()`
- Frontend: Explicit default exports for components, named exports for utilities

**Barrel Files:** Not used
- Each file exports what it defines; no `__init__.py` re-exports in backend/app/
- Frontend `__init__.py` files are empty

**Dependency Injection:**
- Database: Passed through `get_connection()` function calls in route handlers
- Detector: Factory pattern via `get_detector()` returns appropriate implementation
- No DI framework; direct imports and instantiation

## Code Examples

**Backend - Route Handler Pattern:**
```python
@router.post("/route", response_model=RouteResponse)
def find_route(req: RouteRequest):
    # Normalize input
    w_iri, w_pot = normalize_weights(...)
    
    # Check cache
    cached = get_route_cached(cache_key)
    if cached is not None:
        return RouteResponse(**cached)
    
    # Perform computation
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Query logic
            ...
    
    # Return typed response
    return RouteResponse(fastest_route=..., best_route=...)
```

**Backend - Test Helper Pattern:**
```python
def _mock_segments():
    """Return fake segment rows as if from DB."""
    return [
        {
            "id": 1,
            "geojson": '{"type":"LineString","coordinates":[...]}',
            "iri_norm": 0.4,
            ...
        }
    ]

@patch("app.routes.segments.get_connection")
def test_segments_returns_geojson(mock_conn):
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = _mock_segments()
    # Setup context manager mocks...
```

**Frontend - Component Pattern:**
```typescript
interface AddressInputProps {
  label: string;
  placeholder: string;
  markerColor: string;
  value: string;
  onSelect: (lat: number, lon: number, displayName: string) => void;
}

export default function AddressInput({
  label,
  placeholder,
  markerColor,
  value,
  onSelect,
}: AddressInputProps) {
  const [text, setText] = useState(value);
  const { results, loading, search, clear } = useNominatim();
  
  useEffect(() => {
    // Side effects
  }, []);
  
  return (
    <div>
      {/* JSX */}
    </div>
  );
}
```

**Frontend - Hook Pattern:**
```typescript
export function useNominatim() {
  const [results, setResults] = useState<NominatimResult[]>([]);
  const [loading, setLoading] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  
  const search = useCallback((query: string) => {
    // Debounced search with abort signal
    if (timerRef.current) clearTimeout(timerRef.current);
    if (abortRef.current) abortRef.current.abort();
    // ...
  }, []);
  
  return { results, loading, search, clear };
}
```

**Data Pipeline - Protocol Pattern:**
```python
class PotholeDetector(Protocol):
    def detect(self, image_path: str) -> list[Detection]: ...

class StubDetector:
    def detect(self, image_path: str) -> list[Detection]:
        # Implementation satisfies protocol
        ...

class YOLOv8Detector:
    def detect(self, image_path: str) -> list[Detection]:
        # Implementation satisfies protocol
        ...

def get_detector(use_yolo: bool = False) -> PotholeDetector:
    if not use_yolo:
        return StubDetector()
    try:
        return YOLOv8Detector()
    except ImportError:
        return StubDetector()  # Fallback
```

---

*Convention analysis: 2026-04-23*
