# Road Quality / Pothole Tracker MVP

A web application for road-quality-aware route optimization in Los Angeles. Find routes that minimize exposure to rough roads (IRI) and potholes, with a configurable time budget.

## Current Status (2026-02-23)

**MVP code is complete.** 19/19 backend tests passing, frontend builds clean. Docker Desktop has been installed but **PC restart is required** before the demo can run.

### Resume After Restart

1. Restart PC and **launch Docker Desktop** from Start menu
2. Wait for Docker whale icon to turn solid in system tray (~30-60 seconds)
3. Open a terminal in this project directory and follow Quick Start below

## Quick Start

### Prerequisites

- Docker & Docker Compose (Docker Desktop installed, needs restart to activate)
- Python 3.12+ (for seed script)
- Node.js 20+ (for frontend dev)

### 1. Start the database

```bash
docker compose up db -d
```

Wait for healthcheck to pass (~10 seconds).

### 2. Seed data

```bash
pip install -r scripts/requirements.txt
python scripts/seed_data.py
```

This downloads the LA road network (~10km radius) via OSMnx and generates synthetic IRI + pothole data. Takes a few minutes on first run.

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

### Docker Compose (all services)

```bash
docker compose up --build
```

## How It Works

### Scoring

Each road segment has:
- **IRI** (International Roughness Index): normalized 0-1, where 1 = roughest
- **Pothole scores**: moderate (0.5 weight) and severe (1.0 weight), computed from detection count and confidence

Route cost per segment:
```
cost = travel_time + w_IRI * IRI_norm + w_pothole * pothole_score_total
```

### Weight Normalization

- One metric enabled: that metric gets 100% weight
- Both enabled: user slider values normalized to sum to 100%
- Neither enabled: cost = travel time only

### Route Selection

1. Find k=5 shortest paths via pgRouting (`pgr_ksp`)
2. Score each path using the weighted cost formula
3. Filter by max extra time budget over the fastest route
4. Return the lowest-cost path as "best route"
5. If no path fits the time budget, return the fastest route with a warning

## API Endpoints

### GET /health
Returns `{"status": "ok"}`

### POST /route
Find the best quality-aware route.

**Request body:**
```json
{
  "origin": {"lat": 34.05, "lon": -118.24},
  "destination": {"lat": 34.06, "lon": -118.25},
  "include_iri": true,
  "include_potholes": true,
  "weight_iri": 60,
  "weight_potholes": 40,
  "max_extra_minutes": 5
}
```

**Response:** `fastest_route`, `best_route` (with GeoJSON + metrics), optional `warning`, `per_segment_metrics`

### GET /segments?bbox=min_lon,min_lat,max_lon,max_lat
Returns GeoJSON FeatureCollection of road segments within the bounding box, with properties: `id`, `iri_norm`, `moderate_score`, `severe_score`, `pothole_score_total`.

## Frontend Pages

- **Map View** (`/`): Full-screen map with color-coded road segments. Toggle IRI/potholes and adjust weights via sliders.
- **Route Finder** (`/route`): Click-to-select origin/destination, set max extra minutes, compare fastest vs. best route side-by-side.

## Tests

```bash
cd backend && python -m pytest -v
```

19 tests covering scoring logic, models, health endpoint, segments endpoint, route endpoint, and ML detector stub.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI, Python 3.12+, psycopg2 |
| Database | PostgreSQL 16 + PostGIS 3.4 + pgRouting 3.6 |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, react-leaflet |
| Routing | pgRouting `pgr_ksp` (k-shortest paths) |
| Data | OSMnx for road network, synthetic IRI + pothole data |
| ML (stub) | PotholeDetector protocol — YOLOv8 to be plugged in |
| Deploy | Docker Compose (local) |

## Documentation

- [Setup, Run & Usage Guide](docs/SETUP.md) — complete guide for installation, running, and using the application
- [PRD](docs/PRD.md) — implemented vs. planned features
- [Design Document](docs/plans/2026-02-23-pothole-tracker-design.md) — architecture, schema, scoring math
- [Implementation Plan](docs/plans/2026-02-23-implementation-plan.md) — 14-task build plan
