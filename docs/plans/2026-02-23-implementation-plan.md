# Road Quality / Pothole Tracker MVP — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a local-first MVP that provides road-quality-aware route optimization and a map overlay for the LA area, using FastAPI + PostgreSQL/PostGIS/pgRouting + React/Leaflet.

**Architecture:** Fully DB-driven routing via pgRouting's `pgr_ksp()` for k=5 shortest paths. PostGIS handles spatial queries for map segments. FastAPI applies scoring math (weight normalization + cost formula) in Python. React frontend with Leaflet (default) or Mapbox (via env var) renders segments and routes.

**Tech Stack:** Python 3.12+, FastAPI, psycopg2, PostgreSQL 16 + PostGIS 3.4 + pgRouting 3.6, React 18, TypeScript, react-leaflet, Tailwind CSS, Docker Compose, osmnx, pytest.

---

## Task 1: Docker Compose + Database Init

**Files:**
- Create: `docker-compose.yml`
- Create: `db/Dockerfile`
- Create: `db/migrations/001_initial.sql`
- Create: `db/init-pgrouting.sh`

**Step 1: Create db/Dockerfile**

```dockerfile
FROM postgis/postgis:16-3.4

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-16-pgrouting \
    && rm -rf /var/lib/apt/lists/*
```

**Step 2: Create db/init-pgrouting.sh**

```bash
#!/bin/bash
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS postgis;
    CREATE EXTENSION IF NOT EXISTS pgrouting;
EOSQL
```

**Step 3: Create db/migrations/001_initial.sql**

```sql
-- Road segments (pgRouting edges)
CREATE TABLE IF NOT EXISTS road_segments (
    id            SERIAL PRIMARY KEY,
    osm_way_id    BIGINT,
    geom          GEOMETRY(LineString, 4326) NOT NULL,
    length_m      DOUBLE PRECISION NOT NULL,
    travel_time_s DOUBLE PRECISION NOT NULL,
    source        INTEGER,
    target        INTEGER,
    iri_value     DOUBLE PRECISION,
    iri_norm      DOUBLE PRECISION,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_segments_geom ON road_segments USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_segments_source ON road_segments(source);
CREATE INDEX IF NOT EXISTS idx_segments_target ON road_segments(target);

-- Pothole defect records
CREATE TABLE IF NOT EXISTS segment_defects (
    id              SERIAL PRIMARY KEY,
    segment_id      INTEGER REFERENCES road_segments(id) ON DELETE CASCADE,
    severity        VARCHAR(10) NOT NULL CHECK (severity IN ('moderate', 'severe')),
    count           INTEGER NOT NULL DEFAULT 1,
    confidence_sum  DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_defects_segment ON segment_defects(segment_id);

-- Pre-aggregated scores
CREATE TABLE IF NOT EXISTS segment_scores (
    segment_id          INTEGER PRIMARY KEY REFERENCES road_segments(id) ON DELETE CASCADE,
    moderate_score      DOUBLE PRECISION DEFAULT 0.0,
    severe_score        DOUBLE PRECISION DEFAULT 0.0,
    pothole_score_total DOUBLE PRECISION DEFAULT 0.0,
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Route request audit log
CREATE TABLE IF NOT EXISTS route_requests (
    id          SERIAL PRIMARY KEY,
    params_json JSONB NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
```

**Step 4: Create docker-compose.yml**

```yaml
services:
  db:
    build: ./db
    environment:
      POSTGRES_DB: roadquality
      POSTGRES_USER: rq
      POSTGRES_PASSWORD: rqpass
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./db/init-pgrouting.sh:/docker-entrypoint-initdb.d/01-pgrouting.sh
      - ./db/migrations/001_initial.sql:/docker-entrypoint-initdb.d/02-schema.sql
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U rq -d roadquality"]
      interval: 5s
      timeout: 5s
      retries: 5

  backend:
    build: ./backend
    depends_on:
      db:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql://rq:rqpass@db:5432/roadquality
    ports:
      - "8000:8000"
    volumes:
      - ./backend:/app

  frontend:
    build: ./frontend
    depends_on:
      - backend
    environment:
      VITE_API_URL: http://localhost:8000
      VITE_MAPBOX_TOKEN: ""
    ports:
      - "3000:3000"
    volumes:
      - ./frontend:/app
      - /app/node_modules

volumes:
  pgdata:
```

**Step 5: Test DB starts and has extensions**

Run: `docker compose up db -d && sleep 5 && docker compose exec db psql -U rq -d roadquality -c "SELECT postgis_version(); SELECT pgr_version();"`

Expected: Both return version strings without errors.

**Step 6: Verify schema exists**

Run: `docker compose exec db psql -U rq -d roadquality -c "\dt"`

Expected: Lists `road_segments`, `segment_defects`, `segment_scores`, `route_requests`.

**Step 7: Commit**

```bash
git add docker-compose.yml db/
git commit -m "feat: add Docker Compose with PostGIS + pgRouting and initial schema"
```

---

## Task 2: Backend Skeleton + Health Endpoint

**Files:**
- Create: `backend/Dockerfile`
- Create: `backend/requirements.txt`
- Create: `backend/app/__init__.py`
- Create: `backend/app/main.py`
- Create: `backend/app/db.py`
- Create: `backend/app/routes/__init__.py`
- Create: `backend/app/routes/health.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/test_health.py`

**Step 1: Create backend/requirements.txt**

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
psycopg2-binary==2.9.10
pydantic==2.10.4
pytest==8.3.4
httpx==0.28.1
```

**Step 2: Create backend/Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

**Step 3: Write the failing test — backend/tests/test_health.py**

```python
from fastapi.testclient import TestClient
from app.main import app


def test_health_returns_ok():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

**Step 4: Create backend/app/db.py**

```python
import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://rq:rqpass@localhost:5432/roadquality"
)


def get_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
```

**Step 5: Create backend/app/routes/health.py**

```python
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}
```

**Step 6: Create backend/app/main.py**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import health

app = FastAPI(title="Road Quality Tracker", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
```

**Step 7: Create empty __init__.py files**

- `backend/app/__init__.py`
- `backend/app/routes/__init__.py`
- `backend/tests/__init__.py`

**Step 8: Run test to verify it passes**

Run: `cd backend && pip install -r requirements.txt && pytest tests/test_health.py -v`

Expected: PASS — `test_health_returns_ok PASSED`

**Step 9: Commit**

```bash
git add backend/
git commit -m "feat: add FastAPI backend skeleton with /health endpoint and test"
```

---

## Task 3: Scoring Logic (TDD — Pure Functions)

**Files:**
- Create: `backend/app/scoring.py`
- Create: `backend/tests/test_scoring.py`

**Step 1: Write the failing tests — backend/tests/test_scoring.py**

```python
import pytest
from app.scoring import normalize_weights, compute_segment_cost


class TestNormalizeWeights:
    def test_both_enabled_normalizes_to_sum_1(self):
        w_iri, w_pot = normalize_weights(
            include_iri=True, include_potholes=True,
            weight_iri=60, weight_potholes=40,
        )
        assert abs(w_iri - 0.6) < 1e-9
        assert abs(w_pot - 0.4) < 1e-9

    def test_both_enabled_equal_weights(self):
        w_iri, w_pot = normalize_weights(
            include_iri=True, include_potholes=True,
            weight_iri=50, weight_potholes=50,
        )
        assert abs(w_iri - 0.5) < 1e-9
        assert abs(w_pot - 0.5) < 1e-9

    def test_only_iri_enabled(self):
        w_iri, w_pot = normalize_weights(
            include_iri=True, include_potholes=False,
            weight_iri=30, weight_potholes=70,
        )
        assert w_iri == 1.0
        assert w_pot == 0.0

    def test_only_potholes_enabled(self):
        w_iri, w_pot = normalize_weights(
            include_iri=False, include_potholes=True,
            weight_iri=80, weight_potholes=20,
        )
        assert w_iri == 0.0
        assert w_pot == 1.0

    def test_neither_enabled_returns_zeros(self):
        w_iri, w_pot = normalize_weights(
            include_iri=False, include_potholes=False,
            weight_iri=50, weight_potholes=50,
        )
        assert w_iri == 0.0
        assert w_pot == 0.0

    def test_zero_weights_both_enabled(self):
        w_iri, w_pot = normalize_weights(
            include_iri=True, include_potholes=True,
            weight_iri=0, weight_potholes=0,
        )
        assert abs(w_iri - 0.5) < 1e-9
        assert abs(w_pot - 0.5) < 1e-9


class TestComputeSegmentCost:
    def test_basic_cost(self):
        cost = compute_segment_cost(
            travel_time_s=100.0,
            iri_norm=0.5,
            pothole_score_total=2.0,
            w_iri=0.6,
            w_pot=0.4,
        )
        # 100 + 0.6*0.5 + 0.4*2.0 = 100 + 0.3 + 0.8 = 101.1
        assert abs(cost - 101.1) < 1e-9

    def test_zero_weights_equals_travel_time(self):
        cost = compute_segment_cost(
            travel_time_s=200.0,
            iri_norm=0.9,
            pothole_score_total=5.0,
            w_iri=0.0,
            w_pot=0.0,
        )
        assert abs(cost - 200.0) < 1e-9

    def test_only_iri(self):
        cost = compute_segment_cost(
            travel_time_s=50.0,
            iri_norm=0.8,
            pothole_score_total=3.0,
            w_iri=1.0,
            w_pot=0.0,
        )
        # 50 + 1.0*0.8 + 0.0*3.0 = 50.8
        assert abs(cost - 50.8) < 1e-9
```

**Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_scoring.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'app.scoring'`

**Step 3: Implement — backend/app/scoring.py**

```python
def normalize_weights(
    include_iri: bool,
    include_potholes: bool,
    weight_iri: float,
    weight_potholes: float,
) -> tuple[float, float]:
    """Normalize weights based on which parameters are enabled.

    Returns (w_iri, w_pot) that sum to 1.0 (or both 0.0 if neither enabled).
    """
    if not include_iri and not include_potholes:
        return 0.0, 0.0
    if include_iri and not include_potholes:
        return 1.0, 0.0
    if not include_iri and include_potholes:
        return 0.0, 1.0

    total = weight_iri + weight_potholes
    if total == 0:
        return 0.5, 0.5
    return weight_iri / total, weight_potholes / total


def compute_segment_cost(
    travel_time_s: float,
    iri_norm: float,
    pothole_score_total: float,
    w_iri: float,
    w_pot: float,
) -> float:
    """Compute cost for a single segment.

    cost = travel_time_s + w_iri * iri_norm + w_pot * pothole_score_total
    """
    return travel_time_s + w_iri * iri_norm + w_pot * pothole_score_total
```

**Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_scoring.py -v`

Expected: All 9 tests PASS.

**Step 5: Commit**

```bash
git add backend/app/scoring.py backend/tests/test_scoring.py
git commit -m "feat: add scoring logic with weight normalization and segment cost (TDD)"
```

---

## Task 4: Pydantic Models

**Files:**
- Create: `backend/app/models.py`
- Create: `backend/tests/test_models.py`

**Step 1: Write the failing test — backend/tests/test_models.py**

```python
import pytest
from pydantic import ValidationError
from app.models import LatLon, RouteRequest


def test_route_request_valid():
    req = RouteRequest(
        origin=LatLon(lat=34.05, lon=-118.24),
        destination=LatLon(lat=34.06, lon=-118.25),
        include_iri=True,
        include_potholes=True,
        weight_iri=60,
        weight_potholes=40,
        max_extra_minutes=5,
    )
    assert req.origin.lat == 34.05
    assert req.max_extra_minutes == 5


def test_route_request_defaults():
    req = RouteRequest(
        origin=LatLon(lat=34.05, lon=-118.24),
        destination=LatLon(lat=34.06, lon=-118.25),
    )
    assert req.include_iri is True
    assert req.include_potholes is True
    assert req.weight_iri == 50
    assert req.weight_potholes == 50
    assert req.max_extra_minutes == 5


def test_route_request_rejects_invalid_lat():
    with pytest.raises(ValidationError):
        LatLon(lat=100.0, lon=-118.24)
```

**Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_models.py -v`

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement — backend/app/models.py**

```python
from pydantic import BaseModel, Field


class LatLon(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class RouteRequest(BaseModel):
    origin: LatLon
    destination: LatLon
    include_iri: bool = True
    include_potholes: bool = True
    weight_iri: float = Field(default=50, ge=0, le=100)
    weight_potholes: float = Field(default=50, ge=0, le=100)
    max_extra_minutes: float = Field(default=5, ge=0)


class SegmentMetric(BaseModel):
    id: int
    iri_norm: float | None
    pothole_score: float | None


class RouteInfo(BaseModel):
    geojson: dict
    total_time_s: float
    total_cost: float
    avg_iri_norm: float | None = None
    total_moderate_score: float | None = None
    total_severe_score: float | None = None


class RouteResponse(BaseModel):
    fastest_route: RouteInfo
    best_route: RouteInfo
    warning: str | None = None
    per_segment_metrics: list[SegmentMetric]
```

**Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_models.py -v`

Expected: All 3 tests PASS.

**Step 5: Commit**

```bash
git add backend/app/models.py backend/tests/test_models.py
git commit -m "feat: add Pydantic request/response models with validation (TDD)"
```

---

## Task 5: Segments Endpoint

**Files:**
- Create: `backend/app/routes/segments.py`
- Create: `backend/tests/test_segments.py`
- Modify: `backend/app/main.py` (add router)

**Step 1: Write the failing test — backend/tests/test_segments.py**

```python
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app


def _mock_segments():
    """Return fake segment rows as if from DB."""
    return [
        {
            "id": 1,
            "geojson": '{"type":"LineString","coordinates":[[-118.24,34.05],[-118.25,34.06]]}',
            "iri_norm": 0.4,
            "moderate_score": 1.5,
            "severe_score": 0.5,
            "pothole_score_total": 2.0,
        }
    ]


@patch("app.routes.segments.get_connection")
def test_segments_returns_geojson(mock_conn):
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = _mock_segments()
    mock_conn.return_value.__enter__ = lambda s: s
    mock_conn.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn.return_value.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.return_value.cursor.return_value.__exit__ = MagicMock(return_value=False)

    client = TestClient(app)
    response = client.get("/segments?bbox=-118.26,34.04,-118.23,34.07")
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 1
    assert data["features"][0]["properties"]["iri_norm"] == 0.4


def test_segments_rejects_missing_bbox():
    client = TestClient(app)
    response = client.get("/segments")
    assert response.status_code == 422
```

**Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_segments.py -v`

Expected: FAIL

**Step 3: Implement — backend/app/routes/segments.py**

```python
import json
from fastapi import APIRouter, Query, HTTPException
from app.db import get_connection

router = APIRouter()


@router.get("/segments")
def get_segments(bbox: str = Query(..., description="min_lon,min_lat,max_lon,max_lat")):
    parts = bbox.split(",")
    if len(parts) != 4:
        raise HTTPException(status_code=400, detail="bbox must be min_lon,min_lat,max_lon,max_lat")

    try:
        min_lon, min_lat, max_lon, max_lat = (float(p) for p in parts)
    except ValueError:
        raise HTTPException(status_code=400, detail="bbox values must be numbers")

    sql = """
        SELECT
            rs.id,
            ST_AsGeoJSON(rs.geom) AS geojson,
            rs.iri_norm,
            COALESCE(ss.moderate_score, 0) AS moderate_score,
            COALESCE(ss.severe_score, 0) AS severe_score,
            COALESCE(ss.pothole_score_total, 0) AS pothole_score_total
        FROM road_segments rs
        LEFT JOIN segment_scores ss ON rs.id = ss.segment_id
        WHERE rs.geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (min_lon, min_lat, max_lon, max_lat))
            rows = cur.fetchall()

    features = []
    for row in rows:
        features.append({
            "type": "Feature",
            "geometry": json.loads(row["geojson"]),
            "properties": {
                "id": row["id"],
                "iri_norm": row["iri_norm"],
                "moderate_score": row["moderate_score"],
                "severe_score": row["severe_score"],
                "pothole_score_total": row["pothole_score_total"],
            },
        })

    return {"type": "FeatureCollection", "features": features}
```

**Step 4: Register router in main.py**

Add to `backend/app/main.py`:
```python
from app.routes import health, segments

app.include_router(segments.router)
```

**Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_segments.py -v`

Expected: Both tests PASS.

**Step 6: Commit**

```bash
git add backend/app/routes/segments.py backend/tests/test_segments.py backend/app/main.py
git commit -m "feat: add GET /segments endpoint returning GeoJSON with bbox filter (TDD)"
```

---

## Task 6: Route Endpoint

**Files:**
- Create: `backend/app/routes/routing.py`
- Create: `backend/tests/test_route.py`
- Modify: `backend/app/main.py` (add router)

**Step 1: Write the failing test — backend/tests/test_route.py**

```python
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app


def _mock_ksp_results():
    """Simulate pgr_ksp returning 2 paths on a tiny graph."""
    return [
        # Path 1 (fastest): edges 1, 2
        {"path_id": 1, "seq": 1, "edge": 1, "cost": 60.0},
        {"path_id": 1, "seq": 2, "edge": 2, "cost": 60.0},
        # Path 2 (longer but smoother): edges 3, 4
        {"path_id": 2, "seq": 1, "edge": 3, "cost": 70.0},
        {"path_id": 2, "seq": 2, "edge": 4, "cost": 70.0},
    ]


def _mock_segment_data():
    """Segment data for edges referenced by ksp."""
    return {
        1: {
            "id": 1, "travel_time_s": 60.0, "iri_norm": 0.8,
            "pothole_score_total": 3.0, "moderate_score": 1.5, "severe_score": 1.5,
            "geojson": '{"type":"LineString","coordinates":[[-118.24,34.05],[-118.245,34.055]]}',
        },
        2: {
            "id": 2, "travel_time_s": 60.0, "iri_norm": 0.7,
            "pothole_score_total": 2.0, "moderate_score": 1.0, "severe_score": 1.0,
            "geojson": '{"type":"LineString","coordinates":[[-118.245,34.055],[-118.25,34.06]]}',
        },
        3: {
            "id": 3, "travel_time_s": 70.0, "iri_norm": 0.2,
            "pothole_score_total": 0.5, "moderate_score": 0.3, "severe_score": 0.2,
            "geojson": '{"type":"LineString","coordinates":[[-118.24,34.05],[-118.242,34.058]]}',
        },
        4: {
            "id": 4, "travel_time_s": 70.0, "iri_norm": 0.1,
            "pothole_score_total": 0.0, "moderate_score": 0.0, "severe_score": 0.0,
            "geojson": '{"type":"LineString","coordinates":[[-118.242,34.058],[-118.25,34.06]]}',
        },
    }


@patch("app.routes.routing.get_connection")
def test_route_returns_best_and_fastest(mock_conn):
    mock_cursor = MagicMock()

    # First call: snap origin node
    # Second call: snap destination node
    # Third call: pgr_ksp
    # Fourth+ calls: segment data lookups
    mock_cursor.fetchone.side_effect = [
        {"id": 100},  # origin node
        {"id": 200},  # destination node
    ]
    mock_cursor.fetchall.side_effect = [
        _mock_ksp_results(),
        list(_mock_segment_data().values()),  # all segments for path 1+2
    ]

    mock_conn.return_value.__enter__ = lambda s: s
    mock_conn.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn.return_value.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.return_value.cursor.return_value.__exit__ = MagicMock(return_value=False)

    client = TestClient(app)
    response = client.post("/route", json={
        "origin": {"lat": 34.05, "lon": -118.24},
        "destination": {"lat": 34.06, "lon": -118.25},
        "include_iri": True,
        "include_potholes": True,
        "weight_iri": 50,
        "weight_potholes": 50,
        "max_extra_minutes": 5,
    })

    assert response.status_code == 200
    data = response.json()
    assert "fastest_route" in data
    assert "best_route" in data
    assert data["fastest_route"]["total_time_s"] <= data["best_route"]["total_time_s"]
    assert data["best_route"]["total_cost"] <= data["fastest_route"]["total_cost"]


@patch("app.routes.routing.get_connection")
def test_route_warning_when_all_exceed_time_budget(mock_conn):
    mock_cursor = MagicMock()
    mock_cursor.fetchone.side_effect = [
        {"id": 100},
        {"id": 200},
    ]
    mock_cursor.fetchall.side_effect = [
        _mock_ksp_results(),
        list(_mock_segment_data().values()),
    ]

    mock_conn.return_value.__enter__ = lambda s: s
    mock_conn.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn.return_value.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.return_value.cursor.return_value.__exit__ = MagicMock(return_value=False)

    client = TestClient(app)
    response = client.post("/route", json={
        "origin": {"lat": 34.05, "lon": -118.24},
        "destination": {"lat": 34.06, "lon": -118.25},
        "include_iri": True,
        "include_potholes": True,
        "weight_iri": 50,
        "weight_potholes": 50,
        "max_extra_minutes": 0,  # zero budget = only fastest allowed
    })

    assert response.status_code == 200
    data = response.json()
    # With 0 extra minutes, best should equal fastest + warning if alternatives exceed
    assert data["warning"] is None or "fastest" in data["warning"].lower()
```

**Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_route.py -v`

Expected: FAIL

**Step 3: Implement — backend/app/routes/routing.py**

```python
import json
from fastapi import APIRouter
from app.db import get_connection
from app.models import RouteRequest, RouteResponse, RouteInfo, SegmentMetric
from app.scoring import normalize_weights, compute_segment_cost

router = APIRouter()

SNAP_NODE_SQL = """
    SELECT id FROM road_segments_vertices_pgr
    ORDER BY the_geom <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326)
    LIMIT 1
"""

KSP_SQL = """
    SELECT path_id, seq, edge, cost
    FROM pgr_ksp(
        'SELECT id, source, target, travel_time_s AS cost FROM road_segments',
        %s, %s, %s, directed := false
    )
    WHERE edge != -1
"""

SEGMENTS_BY_IDS_SQL = """
    SELECT
        rs.id, rs.travel_time_s, rs.iri_norm,
        ST_AsGeoJSON(rs.geom) AS geojson,
        COALESCE(ss.moderate_score, 0) AS moderate_score,
        COALESCE(ss.severe_score, 0) AS severe_score,
        COALESCE(ss.pothole_score_total, 0) AS pothole_score_total
    FROM road_segments rs
    LEFT JOIN segment_scores ss ON rs.id = ss.segment_id
    WHERE rs.id = ANY(%s)
"""

K = 5


@router.post("/route", response_model=RouteResponse)
def find_route(req: RouteRequest):
    w_iri, w_pot = normalize_weights(
        req.include_iri, req.include_potholes,
        req.weight_iri, req.weight_potholes,
    )

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Log request
            cur.execute(
                "INSERT INTO route_requests (params_json) VALUES (%s)",
                (json.dumps(req.model_dump()),),
            )
            conn.commit()

            # Snap to nearest nodes
            cur.execute(SNAP_NODE_SQL, (req.origin.lon, req.origin.lat))
            origin_node = cur.fetchone()["id"]

            cur.execute(SNAP_NODE_SQL, (req.destination.lon, req.destination.lat))
            dest_node = cur.fetchone()["id"]

            # K-shortest paths
            cur.execute(KSP_SQL, (origin_node, dest_node, K))
            ksp_rows = cur.fetchall()

            # Group by path_id
            paths: dict[int, list[int]] = {}
            for row in ksp_rows:
                paths.setdefault(row["path_id"], []).append(row["edge"])

            if not paths:
                # Fallback: no paths found
                return RouteResponse(
                    fastest_route=RouteInfo(geojson={"type": "LineString", "coordinates": []}, total_time_s=0, total_cost=0),
                    best_route=RouteInfo(geojson={"type": "LineString", "coordinates": []}, total_time_s=0, total_cost=0),
                    warning="No route found between these points",
                    per_segment_metrics=[],
                )

            # Fetch all segment data
            all_edge_ids = list({eid for edges in paths.values() for eid in edges})
            cur.execute(SEGMENTS_BY_IDS_SQL, (all_edge_ids,))
            seg_rows = cur.fetchall()
            seg_data = {row["id"]: row for row in seg_rows}

    # Score each path
    scored_paths = []
    for path_id, edge_ids in paths.items():
        total_time = 0.0
        total_cost = 0.0
        total_iri = 0.0
        total_mod = 0.0
        total_sev = 0.0
        coordinates = []
        metrics = []
        count = 0

        for eid in edge_ids:
            seg = seg_data.get(eid)
            if not seg:
                continue
            count += 1
            t = seg["travel_time_s"]
            iri = seg["iri_norm"] or 0.0
            pot = seg["pothole_score_total"] or 0.0

            total_time += t
            total_cost += compute_segment_cost(t, iri, pot, w_iri, w_pot)
            total_iri += iri
            total_mod += seg["moderate_score"]
            total_sev += seg["severe_score"]

            geom = json.loads(seg["geojson"])
            coordinates.extend(geom.get("coordinates", []))
            metrics.append(SegmentMetric(id=eid, iri_norm=iri, pothole_score=pot))

        scored_paths.append({
            "path_id": path_id,
            "total_time_s": total_time,
            "total_cost": total_cost,
            "avg_iri_norm": total_iri / count if count else 0,
            "total_moderate_score": total_mod,
            "total_severe_score": total_sev,
            "geojson": {"type": "LineString", "coordinates": coordinates},
            "metrics": metrics,
        })

    # Find fastest (min travel time)
    fastest = min(scored_paths, key=lambda p: p["total_time_s"])
    fastest_time = fastest["total_time_s"]
    max_time = fastest_time + req.max_extra_minutes * 60

    # Filter by time budget
    within_budget = [p for p in scored_paths if p["total_time_s"] <= max_time]

    warning = None
    if not within_budget or (len(within_budget) == 1 and within_budget[0]["path_id"] == fastest["path_id"]):
        best = fastest
        if len(scored_paths) > 1:
            warning = "No route within time budget found; returning fastest route"
    else:
        best = min(within_budget, key=lambda p: p["total_cost"])

    def to_route_info(p, include_details=False):
        info = RouteInfo(
            geojson=p["geojson"],
            total_time_s=p["total_time_s"],
            total_cost=p["total_cost"],
        )
        if include_details:
            info.avg_iri_norm = p["avg_iri_norm"]
            info.total_moderate_score = p["total_moderate_score"]
            info.total_severe_score = p["total_severe_score"]
        return info

    return RouteResponse(
        fastest_route=to_route_info(fastest),
        best_route=to_route_info(best, include_details=True),
        warning=warning,
        per_segment_metrics=best["metrics"],
    )
```

**Step 4: Register router in main.py**

Add to `backend/app/main.py`:
```python
from app.routes import health, segments, routing

app.include_router(routing.router)
```

**Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_route.py -v`

Expected: Both tests PASS (with mocked DB).

**Step 6: Commit**

```bash
git add backend/app/routes/routing.py backend/tests/test_route.py backend/app/main.py
git commit -m "feat: add POST /route endpoint with pgRouting k-shortest paths and scoring (TDD)"
```

---

## Task 7: ML Interface Stub

**Files:**
- Create: `data_pipeline/__init__.py`
- Create: `data_pipeline/detector.py`
- Create: `backend/tests/test_detector.py`

**Step 1: Write the failing test — backend/tests/test_detector.py**

```python
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from data_pipeline.detector import StubDetector, Detection


def test_stub_detector_returns_detections():
    detector = StubDetector(seed=42)
    results = detector.detect("test_image.jpg")
    assert isinstance(results, list)
    for d in results:
        assert isinstance(d, Detection)
        assert d.severity in ("moderate", "severe")
        assert 0.0 <= d.confidence <= 1.0


def test_stub_detector_is_deterministic():
    d1 = StubDetector(seed=42).detect("test_image.jpg")
    d2 = StubDetector(seed=42).detect("test_image.jpg")
    assert len(d1) == len(d2)
    for a, b in zip(d1, d2):
        assert a.severity == b.severity
        assert a.confidence == b.confidence
```

**Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_detector.py -v`

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement — data_pipeline/detector.py**

```python
from __future__ import annotations
import hashlib
import random
from dataclasses import dataclass
from typing import Protocol


@dataclass
class Detection:
    severity: str  # "moderate" or "severe"
    confidence: float  # 0.0-1.0


class PotholeDetector(Protocol):
    def detect(self, image_path: str) -> list[Detection]: ...


class StubDetector:
    """Deterministic fake detector for MVP testing."""

    def __init__(self, seed: int = 42):
        self.seed = seed

    def detect(self, image_path: str) -> list[Detection]:
        # Deterministic seed from image path + base seed
        path_hash = int(hashlib.md5(image_path.encode()).hexdigest()[:8], 16)
        rng = random.Random(self.seed + path_hash)

        num_detections = rng.randint(0, 4)
        detections = []
        for _ in range(num_detections):
            score_severe = rng.random()
            score_moderate = rng.random()

            # Severity assignment per spec
            if score_severe >= 0.5:
                severity = "severe"
            elif score_moderate >= 0.5:
                severity = "moderate"
            else:
                continue  # Not reported

            confidence = max(score_severe, score_moderate)
            detections.append(Detection(severity=severity, confidence=round(confidence, 3)))

        return detections
```

**Step 4: Create data_pipeline/__init__.py**

Empty file.

**Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_detector.py -v`

Expected: Both tests PASS.

**Step 6: Commit**

```bash
git add data_pipeline/ backend/tests/test_detector.py
git commit -m "feat: add ML interface with Protocol + StubDetector for deterministic fake detections"
```

---

## Task 8: Seed Data Script

**Files:**
- Create: `scripts/seed_data.py`
- Create: `scripts/compute_scores.py`
- Create: `scripts/requirements.txt`

**Step 1: Create scripts/requirements.txt**

```
osmnx==2.0.1
psycopg2-binary==2.9.10
numpy==2.2.1
```

**Step 2: Implement scripts/seed_data.py**

```python
"""Seed the database with LA road segments + synthetic IRI/pothole data.

Usage: python scripts/seed_data.py
Requires: PostgreSQL running with schema from 001_initial.sql
"""

import json
import os
import random
import numpy as np
import osmnx as ox
import psycopg2
from psycopg2.extras import execute_values

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://rq:rqpass@localhost:5432/roadquality"
)

# LA center, 10km radius
CENTER = (34.0522, -118.2437)
DIST = 10000
SEED = 42


def main():
    rng = random.Random(SEED)
    np_rng = np.random.default_rng(SEED)

    print("Downloading LA road network (this may take a few minutes)...")
    G = ox.graph_from_point(CENTER, dist=DIST, network_type="drive")
    G = ox.add_edge_speeds(G)
    G = ox.add_edge_travel_times(G)

    edges = ox.graph_to_gdfs(G, nodes=False)
    print(f"Downloaded {len(edges)} edges")

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Clear existing data
    cur.execute("TRUNCATE road_segments, segment_defects, segment_scores CASCADE")

    # Insert road segments
    print("Inserting road segments...")
    seg_values = []
    for idx, (u, v, key) in enumerate(edges.index):
        row = edges.loc[(u, v, key)]
        geom_json = json.loads(row.geometry.to_json()) if hasattr(row.geometry, 'to_json') else json.dumps(row.geometry.__geo_interface__)
        geom_wkt = row.geometry.wkt
        length_m = row.get("length", 0)
        travel_time_s = row.get("travel_time", length_m / 13.4)  # fallback ~30mph

        # Synthetic IRI: 1-12 m/km, biased by road type
        highway_type = row.get("highway", "residential")
        if isinstance(highway_type, list):
            highway_type = highway_type[0]
        if highway_type in ("motorway", "trunk", "primary"):
            iri = np_rng.uniform(1.0, 4.0)
        elif highway_type in ("secondary", "tertiary"):
            iri = np_rng.uniform(2.0, 7.0)
        else:
            iri = np_rng.uniform(3.0, 12.0)

        seg_values.append((
            row.get("osmid", 0) if not isinstance(row.get("osmid"), list) else row["osmid"][0],
            geom_wkt,
            length_m,
            travel_time_s,
            u,  # source node (osmnx node ID)
            v,  # target node (osmnx node ID)
            round(iri, 2),
        ))

    insert_sql = """
        INSERT INTO road_segments (osm_way_id, geom, length_m, travel_time_s, source, target, iri_value)
        VALUES %s
    """
    template = "(%s, ST_GeomFromText(%s, 4326), %s, %s, %s, %s, %s)"
    execute_values(cur, insert_sql, seg_values, template=template, page_size=1000)
    conn.commit()

    # Normalize IRI
    cur.execute("SELECT MIN(iri_value), MAX(iri_value) FROM road_segments")
    iri_min, iri_max = cur.fetchone()
    iri_range = iri_max - iri_min if iri_max != iri_min else 1.0
    cur.execute(
        "UPDATE road_segments SET iri_norm = (iri_value - %s) / %s",
        (iri_min, iri_range),
    )
    conn.commit()
    print("IRI normalized")

    # Insert synthetic pothole defects (~30% of segments)
    print("Generating synthetic pothole data...")
    cur.execute("SELECT id FROM road_segments")
    segment_ids = [row[0] for row in cur.fetchall()]

    defect_values = []
    for sid in segment_ids:
        if rng.random() > 0.3:
            continue
        num_defects = rng.randint(1, 3)
        for _ in range(num_defects):
            severity = rng.choice(["moderate", "severe"])
            count = rng.randint(1, 5)
            confidence_sum = round(rng.uniform(0.3, 1.0) * count, 3)
            defect_values.append((sid, severity, count, confidence_sum))

    if defect_values:
        execute_values(
            cur,
            "INSERT INTO segment_defects (segment_id, severity, count, confidence_sum) VALUES %s",
            defect_values,
            page_size=1000,
        )
        conn.commit()
    print(f"Inserted {len(defect_values)} defect records")

    # Compute segment_scores
    print("Computing segment scores...")
    cur.execute("""
        INSERT INTO segment_scores (segment_id, moderate_score, severe_score, pothole_score_total)
        SELECT
            rs.id,
            COALESCE(SUM(CASE WHEN sd.severity = 'moderate' THEN 0.5 * sd.count * sd.confidence_sum ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN sd.severity = 'severe' THEN 1.0 * sd.count * sd.confidence_sum ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN sd.severity = 'moderate' THEN 0.5 * sd.count * sd.confidence_sum ELSE 0 END), 0)
            + COALESCE(SUM(CASE WHEN sd.severity = 'severe' THEN 1.0 * sd.count * sd.confidence_sum ELSE 0 END), 0)
        FROM road_segments rs
        LEFT JOIN segment_defects sd ON rs.id = sd.segment_id
        GROUP BY rs.id
        ON CONFLICT (segment_id) DO UPDATE SET
            moderate_score = EXCLUDED.moderate_score,
            severe_score = EXCLUDED.severe_score,
            pothole_score_total = EXCLUDED.pothole_score_total,
            updated_at = NOW()
    """)
    conn.commit()

    # Build pgRouting topology
    print("Building pgRouting topology...")
    cur.execute("SELECT pgr_createTopology('road_segments', 0.0001, 'geom', 'id')")
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM road_segments")
    count = cur.fetchone()[0]
    print(f"Done! {count} segments seeded with IRI + pothole data.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
```

**Step 3: Implement scripts/compute_scores.py**

```python
"""Recompute segment_scores from segment_defects. Run after new detections are added."""

import os
import psycopg2

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://rq:rqpass@localhost:5432/roadquality"
)


def main():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO segment_scores (segment_id, moderate_score, severe_score, pothole_score_total)
        SELECT
            rs.id,
            COALESCE(SUM(CASE WHEN sd.severity = 'moderate' THEN 0.5 * sd.count * sd.confidence_sum ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN sd.severity = 'severe' THEN 1.0 * sd.count * sd.confidence_sum ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN sd.severity = 'moderate' THEN 0.5 * sd.count * sd.confidence_sum ELSE 0 END), 0)
            + COALESCE(SUM(CASE WHEN sd.severity = 'severe' THEN 1.0 * sd.count * sd.confidence_sum ELSE 0 END), 0)
        FROM road_segments rs
        LEFT JOIN segment_defects sd ON rs.id = sd.segment_id
        GROUP BY rs.id
        ON CONFLICT (segment_id) DO UPDATE SET
            moderate_score = EXCLUDED.moderate_score,
            severe_score = EXCLUDED.severe_score,
            pothole_score_total = EXCLUDED.pothole_score_total,
            updated_at = NOW()
    """)
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM segment_scores WHERE pothole_score_total > 0")
    count = cur.fetchone()[0]
    print(f"Scores recomputed. {count} segments have pothole data.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
```

**Step 4: Test seed script runs (requires Docker DB running)**

Run: `docker compose up db -d && sleep 5 && pip install osmnx psycopg2-binary numpy && python scripts/seed_data.py`

Expected: Prints progress messages, ends with "Done! N segments seeded..."

**Step 5: Verify data in DB**

Run: `docker compose exec db psql -U rq -d roadquality -c "SELECT COUNT(*) FROM road_segments; SELECT COUNT(*) FROM segment_defects; SELECT COUNT(*) FROM segment_scores WHERE pothole_score_total > 0;"`

Expected: ~10,000+ segments, ~3,000+ defects, ~3,000 scored segments.

**Step 6: Commit**

```bash
git add scripts/
git commit -m "feat: add seed data script (osmnx LA 10km) with synthetic IRI + pothole data"
```

---

## Task 9: Frontend Skeleton

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/api.ts`
- Create: `frontend/tailwind.config.js`
- Create: `frontend/postcss.config.js`
- Create: `frontend/src/index.css`
- Create: `frontend/Dockerfile`

**Step 1: Initialize React + Vite + TypeScript project**

Run: `cd "C:/Users/King Hratch/road-quality-mvp" && npm create vite@latest frontend -- --template react-ts`

Or create files manually:

**frontend/package.json:**
```json
{
  "name": "road-quality-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite --port 3000",
    "build": "tsc -b && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "leaflet": "^1.9.4",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-leaflet": "^4.2.1",
    "react-router-dom": "^7.1.1"
  },
  "devDependencies": {
    "@types/leaflet": "^1.9.14",
    "@types/react": "^18.3.18",
    "@types/react-dom": "^18.3.5",
    "@vitejs/plugin-react": "^4.3.4",
    "autoprefixer": "^10.4.20",
    "postcss": "^8.4.49",
    "tailwindcss": "^3.4.17",
    "typescript": "^5.7.3",
    "vite": "^6.0.7"
  }
}
```

**frontend/vite.config.ts:**
```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
```

**frontend/index.html:**
```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Road Quality Tracker</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

**frontend/src/index.css:**
```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

**frontend/src/main.tsx:**
```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
```

**frontend/src/App.tsx:**
```tsx
import { Routes, Route, Link } from "react-router-dom";
import MapView from "./pages/MapView";
import RouteFinder from "./pages/RouteFinder";

export default function App() {
  return (
    <div className="min-h-screen bg-gray-100">
      <nav className="bg-white shadow px-6 py-3 flex gap-6">
        <Link to="/" className="font-semibold text-blue-600 hover:underline">
          Map View
        </Link>
        <Link to="/route" className="font-semibold text-blue-600 hover:underline">
          Route Finder
        </Link>
      </nav>
      <Routes>
        <Route path="/" element={<MapView />} />
        <Route path="/route" element={<RouteFinder />} />
      </Routes>
    </div>
  );
}
```

**frontend/src/api.ts:**
```typescript
const API_BASE = import.meta.env.VITE_API_URL || "";

export async function fetchSegments(bbox: string) {
  const res = await fetch(`${API_BASE}/segments?bbox=${bbox}`);
  if (!res.ok) throw new Error(`Segments fetch failed: ${res.status}`);
  return res.json();
}

export interface RouteRequestBody {
  origin: { lat: number; lon: number };
  destination: { lat: number; lon: number };
  include_iri: boolean;
  include_potholes: boolean;
  weight_iri: number;
  weight_potholes: number;
  max_extra_minutes: number;
}

export async function fetchRoute(body: RouteRequestBody) {
  const res = await fetch(`${API_BASE}/route`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Route fetch failed: ${res.status}`);
  return res.json();
}
```

**frontend/src/pages/MapView.tsx (placeholder):**
```tsx
export default function MapView() {
  return <div className="p-4">Map View — coming in Task 10</div>;
}
```

**frontend/src/pages/RouteFinder.tsx (placeholder):**
```tsx
export default function RouteFinder() {
  return <div className="p-4">Route Finder — coming in Task 11</div>;
}
```

**frontend/tailwind.config.js:**
```javascript
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: { extend: {} },
  plugins: [],
};
```

**frontend/postcss.config.js:**
```javascript
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

**frontend/Dockerfile:**
```dockerfile
FROM node:20-slim

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

CMD ["npm", "run", "dev", "--", "--host"]
```

**Step 2: Install and verify build**

Run: `cd frontend && npm install && npm run build`

Expected: Build succeeds with no errors.

**Step 3: Commit**

```bash
git add frontend/
git commit -m "feat: add React + Vite + TypeScript frontend skeleton with routing and API helpers"
```

---

## Task 10: Map View Page

**Files:**
- Create: `frontend/src/pages/MapView.tsx`
- Create: `frontend/src/components/ControlPanel.tsx`
- Create: `frontend/src/components/Legend.tsx`

**Step 1: Implement ControlPanel — frontend/src/components/ControlPanel.tsx**

```tsx
import { useState } from "react";

export interface ControlState {
  includeIri: boolean;
  includePotholes: boolean;
  weightIri: number;
  weightPotholes: number;
}

interface Props {
  state: ControlState;
  onChange: (state: ControlState) => void;
}

export default function ControlPanel({ state, onChange }: Props) {
  const update = (patch: Partial<ControlState>) =>
    onChange({ ...state, ...patch });

  return (
    <div className="bg-white rounded-lg shadow p-4 space-y-3 w-64">
      <h3 className="font-bold text-sm uppercase text-gray-500">Layers</h3>

      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={state.includeIri}
          onChange={(e) => update({ includeIri: e.target.checked })}
        />
        <span>Show IRI</span>
      </label>
      {state.includeIri && (
        <label className="flex items-center gap-2 pl-6">
          <span className="text-sm text-gray-600 w-16">Weight</span>
          <input
            type="range"
            min={0}
            max={100}
            value={state.weightIri}
            onChange={(e) => update({ weightIri: Number(e.target.value) })}
            className="flex-1"
          />
          <span className="text-sm w-8">{state.weightIri}</span>
        </label>
      )}

      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={state.includePotholes}
          onChange={(e) => update({ includePotholes: e.target.checked })}
        />
        <span>Show Potholes</span>
      </label>
      {state.includePotholes && (
        <label className="flex items-center gap-2 pl-6">
          <span className="text-sm text-gray-600 w-16">Weight</span>
          <input
            type="range"
            min={0}
            max={100}
            value={state.weightPotholes}
            onChange={(e) => update({ weightPotholes: Number(e.target.value) })}
            className="flex-1"
          />
          <span className="text-sm w-8">{state.weightPotholes}</span>
        </label>
      )}
    </div>
  );
}
```

**Step 2: Implement Legend — frontend/src/components/Legend.tsx**

```tsx
export default function Legend() {
  return (
    <div className="bg-white rounded-lg shadow p-3 w-48">
      <h4 className="font-bold text-xs uppercase text-gray-500 mb-2">Road Quality</h4>
      <div className="flex items-center gap-2 text-sm">
        <div className="w-4 h-3 rounded" style={{ background: "#22c55e" }} />
        <span>Good</span>
      </div>
      <div className="flex items-center gap-2 text-sm">
        <div className="w-4 h-3 rounded" style={{ background: "#eab308" }} />
        <span>Fair</span>
      </div>
      <div className="flex items-center gap-2 text-sm">
        <div className="w-4 h-3 rounded" style={{ background: "#ef4444" }} />
        <span>Poor</span>
      </div>
    </div>
  );
}
```

**Step 3: Implement MapView — frontend/src/pages/MapView.tsx**

```tsx
import { useEffect, useState, useCallback } from "react";
import { MapContainer, TileLayer, GeoJSON, useMapEvents } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import ControlPanel, { ControlState } from "../components/ControlPanel";
import Legend from "../components/Legend";
import { fetchSegments } from "../api";

const LA_CENTER: [number, number] = [34.0522, -118.2437];

function scoreForFeature(
  props: any,
  controls: ControlState
): number {
  const { includeIri, includePotholes, weightIri, weightPotholes } = controls;
  if (!includeIri && !includePotholes) return 0;

  let wIri = 0, wPot = 0;
  if (includeIri && includePotholes) {
    const total = weightIri + weightPotholes || 1;
    wIri = weightIri / total;
    wPot = weightPotholes / total;
  } else if (includeIri) {
    wIri = 1;
  } else {
    wPot = 1;
  }

  return wIri * (props.iri_norm || 0) + wPot * (props.pothole_score_total || 0);
}

function scoreToColor(score: number): string {
  // 0 = green, 0.5 = yellow, 1+ = red
  const clamped = Math.min(score, 1);
  if (clamped < 0.5) {
    const t = clamped / 0.5;
    const r = Math.round(34 + t * (234 - 34));
    const g = Math.round(197 + t * (179 - 197));
    const b = Math.round(94 + t * (8 - 94));
    return `rgb(${r},${g},${b})`;
  }
  const t = (clamped - 0.5) / 0.5;
  const r = Math.round(234 + t * (239 - 234));
  const g = Math.round(179 - t * 179);
  const b = Math.round(8 + t * (68 - 8));
  return `rgb(${r},${g},${b})`;
}

function MapEvents({ onBoundsChange }: { onBoundsChange: (bbox: string) => void }) {
  useMapEvents({
    moveend(e) {
      const b = e.target.getBounds();
      onBoundsChange(`${b.getWest()},${b.getSouth()},${b.getEast()},${b.getNorth()}`);
    },
  });
  return null;
}

export default function MapView() {
  const [controls, setControls] = useState<ControlState>({
    includeIri: true,
    includePotholes: true,
    weightIri: 50,
    weightPotholes: 50,
  });
  const [geojson, setGeojson] = useState<any>(null);
  const [bbox, setBbox] = useState("");

  const loadSegments = useCallback(async (b: string) => {
    if (!b) return;
    try {
      const data = await fetchSegments(b);
      setGeojson(data);
    } catch (err) {
      console.error("Failed to fetch segments", err);
    }
  }, []);

  useEffect(() => {
    if (bbox) loadSegments(bbox);
  }, [bbox, loadSegments]);

  return (
    <div className="relative h-[calc(100vh-52px)]">
      <MapContainer center={LA_CENTER} zoom={13} className="h-full w-full">
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <MapEvents onBoundsChange={setBbox} />
        {geojson && (
          <GeoJSON
            key={JSON.stringify(controls)}
            data={geojson}
            style={(feature) => {
              const score = scoreForFeature(feature?.properties, controls);
              return {
                color: scoreToColor(score),
                weight: 3,
                opacity: 0.8,
              };
            }}
          />
        )}
      </MapContainer>
      <div className="absolute top-4 right-4 z-[1000] space-y-2">
        <ControlPanel state={controls} onChange={setControls} />
        <Legend />
      </div>
    </div>
  );
}
```

**Step 4: Verify build**

Run: `cd frontend && npm run build`

Expected: Build succeeds.

**Step 5: Commit**

```bash
git add frontend/src/
git commit -m "feat: add Map View page with segment overlay, controls, and legend"
```

---

## Task 11: Route Finder Page

**Files:**
- Create: `frontend/src/pages/RouteFinder.tsx`
- Create: `frontend/src/components/RouteResults.tsx`

**Step 1: Implement RouteResults — frontend/src/components/RouteResults.tsx**

```tsx
interface RouteInfo {
  total_time_s: number;
  total_cost: number;
  avg_iri_norm?: number;
  total_moderate_score?: number;
  total_severe_score?: number;
}

interface Props {
  fastest: RouteInfo;
  best: RouteInfo;
  warning?: string | null;
}

export default function RouteResults({ fastest, best, warning }: Props) {
  const fmt = (s: number) => `${Math.round(s / 60)} min`;

  return (
    <div className="bg-white rounded-lg shadow p-4 space-y-3">
      {warning && (
        <div className="bg-yellow-100 border-l-4 border-yellow-500 text-yellow-700 p-2 text-sm">
          {warning}
        </div>
      )}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <h4 className="font-bold text-blue-600 text-sm">Fastest Route</h4>
          <p className="text-sm">Time: {fmt(fastest.total_time_s)}</p>
          <p className="text-sm">Cost: {fastest.total_cost.toFixed(1)}</p>
        </div>
        <div>
          <h4 className="font-bold text-green-600 text-sm">Best Route</h4>
          <p className="text-sm">Time: {fmt(best.total_time_s)}</p>
          <p className="text-sm">Cost: {best.total_cost.toFixed(1)}</p>
          {best.avg_iri_norm != null && (
            <p className="text-sm">Avg IRI: {best.avg_iri_norm.toFixed(2)}</p>
          )}
          {best.total_moderate_score != null && (
            <p className="text-sm">Moderate: {best.total_moderate_score.toFixed(1)}</p>
          )}
          {best.total_severe_score != null && (
            <p className="text-sm">Severe: {best.total_severe_score.toFixed(1)}</p>
          )}
        </div>
      </div>
    </div>
  );
}
```

**Step 2: Implement RouteFinder — frontend/src/pages/RouteFinder.tsx**

```tsx
import { useState } from "react";
import { MapContainer, TileLayer, Polyline, useMapEvents, Marker } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import ControlPanel, { ControlState } from "../components/ControlPanel";
import RouteResults from "../components/RouteResults";
import { fetchRoute, RouteRequestBody } from "../api";

const LA_CENTER: [number, number] = [34.0522, -118.2437];

// Fix default marker icons in react-leaflet
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
});

function ClickHandler({ onSelect }: { onSelect: (lat: number, lon: number) => void }) {
  useMapEvents({
    click(e) {
      onSelect(e.latlng.lat, e.latlng.lng);
    },
  });
  return null;
}

function geoJsonToLatLngs(geojson: any): [number, number][] {
  if (!geojson?.coordinates) return [];
  return geojson.coordinates.map(([lon, lat]: [number, number]) => [lat, lon]);
}

export default function RouteFinder() {
  const [controls, setControls] = useState<ControlState>({
    includeIri: true,
    includePotholes: true,
    weightIri: 50,
    weightPotholes: 50,
  });
  const [origin, setOrigin] = useState<{ lat: number; lon: number } | null>(null);
  const [destination, setDestination] = useState<{ lat: number; lon: number } | null>(null);
  const [selectingOrigin, setSelectingOrigin] = useState(true);
  const [maxExtra, setMaxExtra] = useState(5);
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleMapClick = (lat: number, lon: number) => {
    if (selectingOrigin) {
      setOrigin({ lat, lon });
      setSelectingOrigin(false);
    } else {
      setDestination({ lat, lon });
      setSelectingOrigin(true);
    }
  };

  const handleSearch = async () => {
    if (!origin || !destination) return;
    setLoading(true);
    setError(null);
    try {
      const body: RouteRequestBody = {
        origin,
        destination,
        include_iri: controls.includeIri,
        include_potholes: controls.includePotholes,
        weight_iri: controls.weightIri,
        weight_potholes: controls.weightPotholes,
        max_extra_minutes: maxExtra,
      };
      const data = await fetchRoute(body);
      setResult(data);
    } catch (err: any) {
      setError(err.message || "Route request failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-[calc(100vh-52px)]">
      <div className="w-80 p-4 space-y-4 overflow-y-auto bg-gray-50 border-r">
        <h2 className="font-bold text-lg">Route Finder</h2>

        <p className="text-sm text-gray-500">
          {selectingOrigin
            ? "Click the map to set ORIGIN"
            : "Click the map to set DESTINATION"}
        </p>

        {origin && (
          <p className="text-xs">
            Origin: {origin.lat.toFixed(4)}, {origin.lon.toFixed(4)}
          </p>
        )}
        {destination && (
          <p className="text-xs">
            Dest: {destination.lat.toFixed(4)}, {destination.lon.toFixed(4)}
          </p>
        )}

        <label className="block text-sm">
          Max extra minutes:
          <input
            type="number"
            min={0}
            value={maxExtra}
            onChange={(e) => setMaxExtra(Number(e.target.value))}
            className="ml-2 w-16 border rounded px-1"
          />
        </label>

        <ControlPanel state={controls} onChange={setControls} />

        <button
          onClick={handleSearch}
          disabled={!origin || !destination || loading}
          className="w-full bg-blue-600 text-white rounded py-2 hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? "Searching..." : "Find Best Route"}
        </button>

        {error && <p className="text-red-600 text-sm">{error}</p>}

        {result && (
          <RouteResults
            fastest={result.fastest_route}
            best={result.best_route}
            warning={result.warning}
          />
        )}
      </div>

      <MapContainer center={LA_CENTER} zoom={13} className="flex-1">
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <ClickHandler onSelect={handleMapClick} />
        {origin && <Marker position={[origin.lat, origin.lon]} />}
        {destination && <Marker position={[destination.lat, destination.lon]} />}
        {result?.fastest_route?.geojson && (
          <Polyline
            positions={geoJsonToLatLngs(result.fastest_route.geojson)}
            pathOptions={{ color: "#3b82f6", weight: 4, dashArray: "10 6" }}
          />
        )}
        {result?.best_route?.geojson && (
          <Polyline
            positions={geoJsonToLatLngs(result.best_route.geojson)}
            pathOptions={{ color: "#22c55e", weight: 5 }}
          />
        )}
      </MapContainer>
    </div>
  );
}
```

**Step 3: Verify build**

Run: `cd frontend && npm run build`

Expected: Build succeeds.

**Step 4: Commit**

```bash
git add frontend/src/
git commit -m "feat: add Route Finder page with click-to-select, route display, and results panel"
```

---

## Task 12: PRD (Living Document)

**Files:**
- Create: `docs/PRD.md`

**Step 1: Create docs/PRD.md**

```markdown
# Road Quality / Pothole Tracker — PRD

**Version:** 0.1.0 (MVP)
**Last Updated:** 2026-02-23

---

## Implemented

- [x] PostgreSQL + PostGIS + pgRouting database with schema
- [x] Docker Compose (db, backend, frontend)
- [x] FastAPI backend with `/health`, `/segments`, `/route` endpoints
- [x] Scoring logic: weight normalization + segment cost formula
- [x] Pydantic request/response models with validation
- [x] ML interface: PotholeDetector protocol + StubDetector
- [x] Seed script: osmnx LA 10km, synthetic IRI + pothole data
- [x] React frontend: Map View with segment overlay + controls
- [x] React frontend: Route Finder with click-to-select + route comparison
- [x] Unit tests: scoring, models, health
- [x] Mock-based tests: segments, route endpoints

## Next / Planned

- [ ] Integration tests against real DB
- [ ] YOLOv8 detector implementation (replace StubDetector)
- [ ] Real IRI data ingestion (FHWA/state DOT sources)
- [ ] Mapillary image pipeline
- [ ] Caching layer for heavy queries
- [ ] User authentication
- [ ] Production deployment (Docker → cloud)

## Scoring Formula

`cost_segment = travel_time_s + w_IRI * iri_norm + w_pothole * (moderate_score + severe_score)`

See design doc: `docs/plans/2026-02-23-pothole-tracker-design.md`
```

**Step 2: Commit**

```bash
git add docs/PRD.md
git commit -m "docs: add living PRD tracking implemented and planned features"
```

---

## Task 13: README

**Files:**
- Create: `README.md`

**Step 1: Create README.md**

```markdown
# Road Quality / Pothole Tracker MVP

A web application for road-quality-aware route optimization in Los Angeles. Find routes that minimize exposure to rough roads (IRI) and potholes, with a configurable time budget.

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.12+ (for seed script)
- Node.js 20+ (for frontend dev)

### 1. Start the database

```bash
docker compose up db -d
```

### 2. Seed data

```bash
pip install -r scripts/requirements.txt
python scripts/seed_data.py
```

### 3. Start backend

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 4. Start frontend

```bash
cd frontend
npm install
npm run dev
```

Visit http://localhost:3000

## How It Works

### Scoring

Each road segment has:
- **IRI** (International Roughness Index): normalized 0-1
- **Pothole scores**: moderate (0.5 weight) and severe (1.0 weight)

Route cost = travel_time + w_IRI * IRI_norm + w_pothole * pothole_score

### Weight Normalization

- One metric enabled → 100% weight
- Both enabled → user sliders normalized to sum to 100%

### Route Selection

1. Find k=5 shortest paths (pgRouting)
2. Score each path
3. Filter by max extra time budget
4. Return lowest-cost path as "best route"

## API

- `GET /health` — Health check
- `POST /route` — Find best route (see design doc for schema)
- `GET /segments?bbox=...` — Get road segments as GeoJSON

## Tests

```bash
cd backend && pytest -v
```

## Docs

- [PRD](docs/PRD.md)
- [Design Document](docs/plans/2026-02-23-pothole-tracker-design.md)
```

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with quick start, scoring explanation, and API overview"
```

---

## Task 14: Final Polish + Update PRD

**Step 1: Run all backend tests**

Run: `cd backend && pytest -v`

Expected: All tests pass.

**Step 2: Run frontend build**

Run: `cd frontend && npm run build`

Expected: Build succeeds with no errors.

**Step 3: Full docker compose up**

Run: `docker compose up --build -d`

Expected: All 3 services start. `curl http://localhost:8000/health` returns `{"status":"ok"}`.

**Step 4: Update PRD with final status**

Update `docs/PRD.md` to reflect any changes discovered during testing.

**Step 5: Final commit**

```bash
git add -A
git commit -m "chore: final polish — all tests passing, builds clean, PRD updated"
```

---

## Execution Summary

| Task | Description | Key Files |
|------|-------------|-----------|
| 1 | Docker + DB | docker-compose.yml, db/ |
| 2 | Backend skeleton + /health | backend/app/, Dockerfile |
| 3 | Scoring logic (TDD) | scoring.py, test_scoring.py |
| 4 | Pydantic models (TDD) | models.py, test_models.py |
| 5 | /segments endpoint (TDD) | routes/segments.py |
| 6 | /route endpoint (TDD) | routes/routing.py |
| 7 | ML interface stub (TDD) | data_pipeline/detector.py |
| 8 | Seed data script | scripts/seed_data.py |
| 9 | Frontend skeleton | frontend/src/ |
| 10 | Map View page | MapView.tsx, ControlPanel.tsx |
| 11 | Route Finder page | RouteFinder.tsx, RouteResults.tsx |
| 12 | PRD | docs/PRD.md |
| 13 | README | README.md |
| 14 | Polish + verify | All |
