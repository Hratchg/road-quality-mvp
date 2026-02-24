# Road Quality / Pothole Tracker MVP — Design Document

**Date:** 2026-02-23
**Status:** Approved

---

## 1. Product Overview

A web application that provides **road quality-aware route optimization** and a **map visualization** of road conditions in the Los Angeles area. Users can find routes that minimize exposure to rough roads (high IRI) and potholes, subject to a maximum time budget.

### Core Features

1. **Route Optimization** (`POST /route`): Given origin/destination, returns the best route subject to a max-extra-time constraint. Scoring combines travel time + weighted penalties for IRI roughness and pothole severity.

2. **Map View** (`GET /segments`): Visualizes road segments color-coded by IRI and/or pothole severity. Toggles and sliders control which metrics are shown and their weights.

---

## 2. Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Project path | `C:\Users\King Hratch\road-quality-mvp` | Clean sibling to SkillShock |
| Architecture | Fully DB-driven (pgRouting) | Production-grade routing in SQL |
| Seed area | LA ~10km radius (~34.05, -118.24) | Realistic demo, 10k+ segments |
| Map provider | Leaflet+OSM default, Mapbox via env var | Free default, upgrade path |
| K-shortest paths | k=5 | Good variety without perf issues |
| Seed data | Deterministic (seed=42) | Reproducible demos and tests |
| PRD | Living document, updated at each checkpoint | Per user request |

---

## 3. Architecture

```
React (Leaflet/Mapbox)  →  FastAPI Backend  →  PostgreSQL + PostGIS + pgRouting
```

### Data Flow

1. **Seed time**: osmnx downloads LA OSM graph → Python script inserts road_segments with PostGIS geometries → pgr_createTopology() builds routing graph → synthetic IRI + pothole data inserted
2. **POST /route**: pgr_ksp() finds k=5 shortest paths → SQL joins segment_scores → Python applies weight normalization + cost formula → filters by max_extra_minutes → returns best + fastest
3. **GET /segments?bbox=...**: PostGIS spatial query returns GeoJSON with scores
4. **Frontend**: renders color-coded segments + route comparison

---

## 4. Database Schema

### Tables

**road_segments** — edges in the pgRouting graph
- `id` SERIAL PK
- `osm_way_id` BIGINT
- `geom` GEOMETRY(LineString, 4326)
- `length_m` DOUBLE PRECISION
- `travel_time_s` DOUBLE PRECISION (from OSM speed limits)
- `source` INTEGER (pgRouting node)
- `target` INTEGER (pgRouting node)
- `iri_value` DOUBLE PRECISION (raw m/km)
- `iri_norm` DOUBLE PRECISION (0-1 normalized)
- `created_at` TIMESTAMPTZ

**segment_defects** — individual detection events
- `id` SERIAL PK
- `segment_id` FK → road_segments
- `severity` VARCHAR(10) CHECK IN ('moderate', 'severe')
- `count` INTEGER
- `confidence_sum` DOUBLE PRECISION
- `created_at` TIMESTAMPTZ

**segment_scores** — pre-aggregated (materialized view pattern)
- `segment_id` PK FK → road_segments
- `moderate_score` DOUBLE PRECISION — `0.5 * sum(count * confidence)`
- `severe_score` DOUBLE PRECISION — `1.0 * sum(count * confidence)`
- `pothole_score_total` DOUBLE PRECISION — `moderate + severe`
- `updated_at` TIMESTAMPTZ

**route_requests** — audit log
- `id` SERIAL PK
- `params_json` JSONB
- `created_at` TIMESTAMPTZ

---

## 5. Scoring Math

### Pothole Scoring Per Segment
```
moderate_score = 0.5 * sum(count * confidence)
severe_score   = 1.0 * sum(count * confidence)
```

### Severity Assignment Per Image
```
if score_Severe >= 0.5 → Severe
else if score_Moderate >= 0.5 → Moderate
else → Not reported
Tie → Severe
```

### Route Cost
```
cost_segment = travel_time_s + w_IRI * iri_norm + w_pothole * (moderate_score + severe_score)
total_route_cost = sum(cost_segment)
```

### Weight Normalization
- One parameter checked → that weight = 100%
- Both checked → `w_iri = weight_iri / (weight_iri + weight_potholes)`, same for potholes

### Max Time Rule
- Reject candidates where `total_time > fastest_time + max_extra_minutes * 60`
- If all rejected → return fastest route + warning

---

## 6. API Endpoints

### GET /health
Returns `{"status": "ok"}`

### POST /route
**Body:**
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
**Response:**
```json
{
  "fastest_route": {"geojson": {...}, "total_time_s": 420, "total_cost": 425.3},
  "best_route": {"geojson": {...}, "total_time_s": 450, "total_cost": 410.1,
                  "avg_iri_norm": 0.32, "total_moderate_score": 2.1, "total_severe_score": 0.5},
  "warning": null,
  "per_segment_metrics": [{"id": 1, "iri_norm": 0.4, "pothole_score": 1.2}, ...]
}
```

### GET /segments?bbox=min_lon,min_lat,max_lon,max_lat
Returns GeoJSON FeatureCollection with segment properties: `id`, `iri_norm`, `moderate_score`, `severe_score`, `pothole_score_total`.

---

## 7. Frontend

### Page 1: Map View
- Full-screen Leaflet map (Mapbox if token set via `REACT_APP_MAPBOX_TOKEN`)
- Segment overlay: colored polylines from `/segments?bbox=...`, fetched on map move
- Color scale: green → yellow → red
- Control panel: IRI toggle, Potholes toggle, weight sliders
- Legend

### Page 2: Route Finder
- Origin/destination inputs (text or click-on-map)
- Max extra minutes input (default 5)
- Same toggle/slider controls
- Two routes on map: fastest (blue dashed) vs best (green solid)
- Summary card with metrics per route
- Warning banner if applicable

### Shared: ControlPanel component (toggles + sliders)

### Tech: React 18, react-leaflet / react-map-gl, Tailwind CSS, useState/useEffect

---

## 8. Data Pipeline & ML Interface

### Seed Script (`scripts/seed_data.py`)
- osmnx downloads LA drive network (10km radius, center 34.0522, -118.2437)
- Converts to road_segments with PostGIS geometries
- pgr_createTopology() builds routing nodes
- Deterministic (seed=42) synthetic data:
  - IRI: 1.0-12.0 m/km, biased higher on arterials
  - ~30% segments get 1-3 defect records
- Computes segment_scores from defects

### ML Interface
```python
class PotholeDetector(Protocol):
    def detect(self, image_path: str) -> list[Detection]: ...

class StubDetector:  # MVP
class YOLOv8Detector:  # Future
```

---

## 9. Docker Compose

- **db**: postgis/postgis:16-3.4 + pgRouting (via init script)
- **backend**: FastAPI, port 8000
- **frontend**: React dev server, port 3000
- Volume: pgdata for persistence

---

## 10. Testing

- `test_scoring.py`: weight normalization (both-on, one-on, neither, edge cases)
- `test_cost.py`: route cost formula with known inputs
- `test_route.py`: integration test with tiny 4-node graph in test DB
- DB migration: `db/migrations/001_initial.sql` (single file, no Alembic for MVP)

---

## 11. Repo Structure

```
road-quality-mvp/
├── backend/
│   ├── app/ (main.py, routes/, models.py, scoring.py, db.py)
│   ├── tests/
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/ (App.tsx, pages/, components/, api.ts)
│   ├── package.json
│   └── Dockerfile
├── data_pipeline/
│   └── detector.py
├── db/
│   └── migrations/001_initial.sql
├── scripts/ (seed_data.py, compute_scores.py)
├── docs/ (PRD.md, plans/)
├── docker-compose.yml
└── README.md
```
