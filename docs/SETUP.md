# Setup, Run & Usage Guide

Complete guide for setting up, running, and using the Road Quality / Pothole Tracker MVP.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation](#installation)
3. [Running the Application](#running-the-application)
   - [Option A: Docker Compose (Recommended)](#option-a-docker-compose-recommended)
   - [Option B: Local Development](#option-b-local-development)
4. [Seeding the Database](#seeding-the-database)
5. [Using the Application](#using-the-application)
   - [Map View](#map-view)
   - [Route Finder](#route-finder)
6. [API Reference](#api-reference)
7. [Running Tests](#running-tests)
8. [Configuration](#configuration)
9. [Data Pipeline](#data-pipeline)
10. [Architecture Overview](#architecture-overview)
11. [Troubleshooting](#troubleshooting)

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | Latest | Database (PostgreSQL + PostGIS + pgRouting) |
| [Python](https://www.python.org/downloads/) | 3.12+ | Backend server & data seeding scripts |
| [Node.js](https://nodejs.org/) | 20+ | Frontend dev server |
| [Git](https://git-scm.com/) | Latest | Version control |

> **Windows users:** After installing Docker Desktop for the first time, you must restart your PC before Docker will work.

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/Hratchg/road-quality-mvp.git
cd road-quality-mvp
```

### 2. Install backend dependencies

```bash
cd backend
pip install -r requirements.txt
cd ..
```

### 3. Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

### 4. Install script dependencies (for data seeding)

```bash
pip install -r scripts/requirements.txt
```

---

## Running the Application

### Option A: Docker Compose (Recommended)

Starts all three services (database, backend, frontend) with a single command:

```bash
docker compose up --build
```

Then visit **http://localhost:3000** in your browser.

To run in the background:

```bash
docker compose up --build -d
```

To stop:

```bash
docker compose down
```

> **Note:** The database starts with an empty schema. You still need to [seed the data](#seeding-the-database) on first run.

### Option B: Local Development

This approach gives you hot-reload on both backend and frontend.

#### Step 1: Start the database

```bash
docker compose up db -d
```

Wait ~10 seconds for the healthcheck to pass. Verify with:

```bash
docker compose ps
```

The `db` service should show `healthy`.

#### Step 2: Seed the database

See [Seeding the Database](#seeding-the-database) below.

#### Step 3: Start the backend

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

The API will be available at **http://localhost:8000**.

#### Step 4: Start the frontend

Open a new terminal:

```bash
cd frontend
npm run dev
```

The frontend will be available at **http://localhost:3000**.

---

## Seeding the Database

The seed script downloads the Los Angeles road network via OSMnx and populates the database with road segments, synthetic IRI (roughness) values, and synthetic pothole data.

```bash
python scripts/seed_data.py
```

**What it does:**

1. Downloads the LA road network (~20 km radius from downtown) via OSMnx
2. Inserts road segments into the `road_segments` table
3. Generates synthetic IRI values based on FHWA distributions per road class
4. Normalizes IRI to a 0-1 scale
5. Generates synthetic pothole defects (~30% of segments)
6. Computes aggregate `segment_scores`
7. Builds the pgRouting network topology

**First run** takes 2-5 minutes (network download + processing). Subsequent runs are faster if the OSMnx cache is present.

### Ingesting Real IRI Data

If you have real IRI measurements, you can ingest them from CSV or shapefile:

```bash
# From CSV (columns: lat, lon, iri_value)
python scripts/ingest_iri.py --source csv --path data/my_iri_data.csv

# From shapefile
python scripts/ingest_iri.py --source shapefile --path data/iri_measurements.shp

# Regenerate improved synthetic IRI (with spatial smoothing)
python scripts/ingest_iri.py --source synthetic --seed 42
```

After ingesting new IRI or defect data, recompute scores:

```bash
python scripts/compute_scores.py
```

---

## Using the Application

The application has two pages, accessible via the navigation bar at the top.

### Map View

**URL:** http://localhost:3000/

An interactive full-screen map of Los Angeles showing color-coded road segments based on quality.

**Features:**

- **Segment overlay:** Road segments are colored by quality score:
  - Green = Good condition
  - Yellow = Fair condition
  - Red = Poor condition
- **Control panel (top-right):**
  - Toggle IRI (roughness) on/off
  - Toggle pothole scores on/off
  - Adjust weight sliders (0-100) for IRI vs. potholes
- **Legend (bottom-right):** Shows the color scale
- **Pan & zoom:** Segment data loads automatically as you navigate the map

### Route Finder

**URL:** http://localhost:3000/route

Find the best road-quality-aware route between two points.

**How to use:**

1. **Set origin:** Type an LA address in the "From" field and select from autocomplete suggestions, or click on the map
2. **Set destination:** Type an LA address in the "To" field and select from autocomplete, or click on the map
3. **Configure preferences:**
   - Toggle IRI and/or pothole scoring
   - Adjust weight sliders to prioritize roughness vs. potholes
   - Set **Max extra minutes** (how much longer than the fastest route you're willing to travel for better road quality)
4. **Click "Find Best Route"**

**Results:**

- **Blue dashed line:** Fastest route (shortest travel time)
- **Green solid line:** Best route (lowest cost within your time budget)
- **Results panel:** Compares the two routes side-by-side showing:
  - Travel time
  - Route cost score
  - Average IRI
  - Pothole scores (moderate / severe)
- **Warning banner:** Appears if no route fits within your time budget (falls back to fastest)

**Swap button:** Click the swap icon between the From/To fields to reverse your route.

---

## API Reference

The backend API runs on port 8000. All endpoints accept and return JSON.

### GET /health

Health check endpoint.

```bash
curl http://localhost:8000/health
```

**Response:**
```json
{"status": "ok"}
```

### POST /route

Find the best quality-aware route between two points.

```bash
curl -X POST http://localhost:8000/route \
  -H "Content-Type: application/json" \
  -d '{
    "origin": {"lat": 34.0522, "lon": -118.2437},
    "destination": {"lat": 34.0622, "lon": -118.2537},
    "include_iri": true,
    "include_potholes": true,
    "weight_iri": 60,
    "weight_potholes": 40,
    "max_extra_minutes": 5
  }'
```

**Request body parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `origin` | `{lat, lon}` | *required* | Starting point (WGS84 coordinates) |
| `destination` | `{lat, lon}` | *required* | End point (WGS84 coordinates) |
| `include_iri` | boolean | `true` | Include roughness in route scoring |
| `include_potholes` | boolean | `true` | Include pothole scores in route scoring |
| `weight_iri` | number (0-100) | `50` | Relative weight for IRI metric |
| `weight_potholes` | number (0-100) | `50` | Relative weight for pothole metric |
| `max_extra_minutes` | number (>=0) | `5` | Max additional travel time over fastest route |

**Response fields:**

| Field | Description |
|-------|-------------|
| `fastest_route` | Route with minimum travel time |
| `best_route` | Route with lowest quality-weighted cost within time budget |
| `warning` | Present if no route fits within the time budget |
| `per_segment_metrics` | IRI and pothole score for each segment in the best route |

Each route object contains:
- `geojson` — GeoJSON geometry for map rendering
- `total_time_s` — Total travel time in seconds
- `total_cost` — Weighted cost score
- `avg_iri_norm` — Average normalized IRI (0-1)
- `total_moderate_score` — Aggregate moderate pothole score
- `total_severe_score` — Aggregate severe pothole score

### GET /segments

Get road segment quality data for a map bounding box.

```bash
curl "http://localhost:8000/segments?bbox=-118.26,34.04,-118.23,34.06"
```

**Query parameter:**

| Parameter | Format | Description |
|-----------|--------|-------------|
| `bbox` | `min_lon,min_lat,max_lon,max_lat` | Bounding box in WGS84 coordinates |

**Response:** GeoJSON FeatureCollection. Each feature has properties:
- `id` — Segment ID
- `iri_norm` — Normalized IRI (0-1, higher = rougher)
- `moderate_score` — Moderate pothole score
- `severe_score` — Severe pothole score
- `pothole_score_total` — Combined pothole score

### GET /cache/stats

Returns current in-memory cache sizes.

```bash
curl http://localhost:8000/cache/stats
```

**Response:**
```json
{
  "segments_cache_size": 12,
  "route_cache_size": 3,
  "segments_cache_maxsize": 256,
  "route_cache_maxsize": 128
}
```

### POST /cache/clear

Clear all caches (segments and routes).

```bash
curl -X POST http://localhost:8000/cache/clear
```

**Response:**
```json
{"cleared": true}
```

---

## Running Tests

### Backend tests (unit + integration)

```bash
cd backend
python -m pytest -v
```

**19 tests** covering:

| Test file | What it tests |
|-----------|---------------|
| `test_health.py` | Health endpoint |
| `test_models.py` | Pydantic model validation |
| `test_scoring.py` | Weight normalization and cost formula |
| `test_cache.py` | Cache operations and cache endpoints |
| `test_detector.py` | StubDetector (ML detector protocol) |
| `test_yolo_detector.py` | YOLOv8 detector and factory |
| `test_integration.py` | Live database queries (auto-skipped if DB is down) |
| `test_iri_ingestion.py` | IRI data loading from CSV/shapefile |

> **Note:** Integration tests require a running database. They are automatically skipped if the database is not available.

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://rq:rqpass@localhost:5432/roadquality` | PostgreSQL connection string |
| `VITE_API_URL` | `/api` (proxied to backend) | Backend API URL for the frontend |
| `VITE_MAPBOX_TOKEN` | *(empty)* | Optional Mapbox token for premium map tiles |

### Database Credentials (Docker)

| Variable | Value |
|----------|-------|
| `POSTGRES_DB` | `roadquality` |
| `POSTGRES_USER` | `rq` |
| `POSTGRES_PASSWORD` | `rqpass` |

### Caching

| Cache | Max Size | TTL | Purpose |
|-------|----------|-----|---------|
| Segments | 256 entries | 5 minutes | Bounding box segment queries |
| Routes | 128 entries | 2 minutes | Route computation results |

---

## Data Pipeline

### Pothole Detection (ML)

The project includes a pluggable pothole detection pipeline:

- **StubDetector** (default): Deterministic fake detector for development and testing. Uses seeded randomness to produce repeatable results.
- **YOLOv8Detector** (optional): Real ML detector using Ultralytics YOLOv8. Supports both two-class (moderate/severe) and single-class (confidence-based severity) models.

The detector is selected via the factory:

```python
from data_pipeline.detector_factory import get_detector

# Use stub (default)
detector = get_detector()

# Use YOLOv8 (requires ultralytics package + model file)
detector = get_detector(use_yolo=True, model_path="models/pothole_model.pt")
```

If `ultralytics` is not installed, the factory gracefully falls back to the StubDetector.

### IRI Data Sources

The project supports three IRI data sources:

1. **Synthetic** (default in seed script): FHWA-derived distributions per road class with spatial smoothing
2. **CSV**: Load from any CSV with `lat`, `lon`, `iri_value` columns
3. **Shapefile**: Load from GIS shapefiles with geometry and IRI attributes

---

## Architecture Overview

```
┌──────────────┐     ┌──────────────┐     ┌──────────────────────────┐
│   Frontend   │────▸│   Backend    │────▸│       Database            │
│  React 18    │     │   FastAPI    │     │  PostgreSQL 16            │
│  TypeScript  │     │   Python     │     │  + PostGIS 3.4            │
│  Leaflet     │     │   psycopg2   │     │  + pgRouting 3.6          │
│  Vite        │     │              │     │                           │
│  Port 3000   │     │  Port 8000   │     │  Port 5432                │
└──────────────┘     └──────────────┘     └──────────────────────────┘
```

### Database Schema

- **road_segments** — Road network edges with geometry, IRI, and pgRouting source/target nodes
- **segment_defects** — Pothole detections per segment (moderate/severe with confidence)
- **segment_scores** — Precomputed aggregate pothole scores per segment
- **route_requests** — Audit log of all route queries (JSONB)

### Scoring Formula

```
segment_cost = travel_time_s + w_iri * iri_norm + w_pothole * pothole_score_total
```

Where:
- `iri_norm` is the normalized IRI (0 = smooth, 1 = roughest)
- `pothole_score_total = moderate_score + severe_score`
- `moderate_score = 0.5 * count * confidence_sum`
- `severe_score = 1.0 * count * confidence_sum`
- Weights (`w_iri`, `w_pothole`) are normalized to sum to 1.0

### Route Selection Algorithm

1. Snap origin/destination to nearest pgRouting nodes (KNN spatial query)
2. Run `pgr_ksp()` with K=5 to find 5 candidate shortest paths
3. Score each path: sum of segment costs
4. Find the fastest path (minimum total travel time)
5. Apply time budget filter: keep paths where `total_time <= fastest_time + max_extra_minutes * 60`
6. Return the lowest-cost path within budget as "best route"
7. If no path fits the budget, return the fastest route with a warning

---

## Troubleshooting

### Docker Desktop won't start

- **Windows:** Restart your PC after installing Docker Desktop. Ensure WSL 2 is enabled.
- Verify Docker is running: `docker info`

### Database connection refused

- Ensure the database container is running and healthy: `docker compose ps`
- Wait 10-15 seconds after starting for the healthcheck to pass
- Check the connection string: `postgresql://rq:rqpass@localhost:5432/roadquality`

### Seed script fails with OSMnx errors

- Ensure you have internet connectivity (OSMnx downloads from OpenStreetMap)
- If the download times out, re-run the script — OSMnx caches partial downloads
- Ensure `scripts/requirements.txt` dependencies are installed

### Frontend can't reach the backend

- In local development, the Vite dev server proxies `/api/*` to `http://localhost:8000`
- Ensure the backend is running on port 8000
- Check browser console for CORS errors (CORS is enabled for all origins in development)

### Tests are skipped

- Integration tests require a running database and are auto-skipped if unavailable
- Start the database with `docker compose up db -d` before running tests
