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

This downloads the LA road network (~20 km radius) via OSMnx and generates synthetic IRI + pothole data. Takes a few minutes on first run.

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

## Detector Accuracy

The YOLOv8 pothole detector is evaluated on a hand-labelled LA eval set
(~300 Mapillary images, 70/20/10 sequence-grouped split) with precision,
recall, mAP@0.5, and image-level bootstrap 95% CIs. Full methodology and
numbers: [`docs/DETECTOR_EVAL.md`](docs/DETECTOR_EVAL.md).

Reproduce from a clean checkout — see
[`docs/FINETUNE.md`](docs/FINETUNE.md) for laptop/Colab/EC2 fine-tuning
recipes, then:

```bash
# verify dataset integrity
python scripts/fetch_eval_data.py

# run eval on the held-out test split
python scripts/eval_detector.py --data data/eval_la/data.yaml --split test
```

Configuration: set `YOLO_MODEL_PATH` in `.env` to either a HuggingFace repo
id (e.g. `<user>/road-quality-la-yolov8@<revision>`) or a local `.pt`
file path. Default falls back to `keremberke/yolov8s-pothole-segmentation`.

## Real-Data Ingest

The `scripts/ingest_mapillary.py` CLI pulls Mapillary imagery for a target
list of road segments, runs the YOLOv8 detector, and writes detections back
into `segment_defects` with full provenance (`source = 'mapillary'`,
`source_mapillary_id = <image_id>`). Re-runs are idempotent.

Three target modes — explicit ids, ids-file, or `--where` SQL predicate.
After each ingest, the CLI auto-runs `scripts/compute_scores.py` so
`/segments` and `/route` reflect the new detections.

See [`docs/MAPILLARY_INGEST.md`](docs/MAPILLARY_INGEST.md) for the operator
runbook: prerequisites, all flags, the SC #4 ranking-comparison demo
workflow, the Phase 6 public-demo cutover sequence, and the trust model
for `--where`.

Quick start (after `MAPILLARY_ACCESS_TOKEN` is set):

```bash
python scripts/ingest_mapillary.py --segment-ids 1,2,3 --limit-per-segment 5
```

## Frontend Pages

- **Map View** (`/`): Full-screen map with color-coded road segments. Toggle IRI/potholes and adjust weights via sliders.
- **Route Finder** (`/route`): Click-to-select origin/destination, set max extra minutes, compare fastest vs. best route side-by-side.

## Tests

```bash
cd backend && python -m pytest -v
```

19 tests covering scoring logic, models, health endpoint, segments endpoint, route endpoint, and ML detector stub.

## Public Demo Account

The deployed app exposes a demo account for drive-by visitors:

- **Email:** `demo@road-quality-mvp.dev`
- **Password:** `demo1234`

On the `/route` page, click **Try as demo** in the sign-in modal to log in
with one click. (The modal opens automatically the first time you click
"Find Best Route" without being signed in — see `frontend/src/components/SignInModal.tsx`.)

Public endpoints (`GET /health`, `GET /segments`, the Map View at `/map`)
do NOT require authentication. Only `POST /route` and `/cache/*` are gated.

### Local setup

After `docker compose up --build` brings up the stack:

```bash
# 1. Generate an HS256 signing key (~43 chars URL-safe).
python -c "import secrets; print('AUTH_SIGNING_KEY=' + secrets.token_urlsafe(32))" >> .env

# 2. Restart the backend so it picks up AUTH_SIGNING_KEY from .env.
docker compose restart backend

# 3. Apply migration 003 (users table) — only needed if your DB existed before
#    Phase 4 landed; fresh `docker compose up -v` does this automatically via
#    /docker-entrypoint-initdb.d/04-users.sql.
docker compose exec -T db psql -U rq -d roadquality < db/migrations/003_users.sql

# 4. Seed the demo user. --password is required (no default lives in source;
#    rotate by passing a fresh value here and updating this README).
python scripts/seed_demo_user.py --password demo1234
# → "Demo user seeded: id=1, email=demo@road-quality-mvp.dev"
```

### Rotation

The demo password is documented and rotatable. To rotate locally:

```bash
python scripts/seed_demo_user.py --password $NEW_DEMO_PASSWORD
```

This UPSERTs the existing demo user with a fresh argon2id hash. Update this
README with the new password and redeploy. To also invalidate ALL active
sessions (emergency revocation), rotate `AUTH_SIGNING_KEY` in addition:

```bash
python -c "import secrets; print('AUTH_SIGNING_KEY=' + secrets.token_urlsafe(32))" > .env.new
# (manually merge .env.new into .env, replacing the old AUTH_SIGNING_KEY)
docker compose restart backend
```

Rotating `AUTH_SIGNING_KEY` invalidates every active session globally,
including any abuser's. This is the M1 revocation lever (no denylist by
design — see `.planning/phases/04-authentication/04-CONTEXT.md` D-01).

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
- [Detector Accuracy Report](docs/DETECTOR_EVAL.md) — evaluation methodology, numbers, reproduction
- [Mapillary Ingest Runbook](docs/MAPILLARY_INGEST.md) — operator workflow, SC #4 demo, Phase 6 cutover
- [Fine-Tuning Guide](docs/FINETUNE.md) — laptop / Colab / EC2 recipes
