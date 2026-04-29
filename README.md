# Road Quality / Pothole Tracker MVP

A web application for road-quality-aware route optimization in Los Angeles. Find routes that minimize exposure to rough roads (IRI) and potholes, with a configurable time budget.

## Live Demo

**🌐 https://road-quality-frontend.fly.dev/**

A public LA pothole-aware routing demo. Pick two points on the map; get a "fastest" route alongside a "best" route that detours around real Mapillary-detected potholes within a configurable time budget.

**What you can do (no sign-in needed):**
- **Map view** — Zoom around LA. Road segments are color-coded by their pothole + roughness scores.
- **Route Finder** (`/route`) — Click two LA points and compare the fastest vs. best route side-by-side.

**Pipeline:**
- Imagery: real Mapillary CC-BY-SA street-level captures from 12 LA zones spanning DTLA, the Westside, the Valley fringe, and known-bad-pavement corridors (Mid-City east of La Brea, Boyle Heights, parts of South LA)
- Detector: YOLOv8 fine-tuned on hand-labelled LA Mapillary imagery — sequence-grouped 70/20/10 train/val/test splits, single-class "pothole" with severity derived from confidence, image-level bootstrap CIs at IoU=0.5. Methodology + measurements in [`docs/DETECTOR_EVAL.md`](docs/DETECTOR_EVAL.md).
- Routing: real Mapillary detections drive the pothole-score signal end-to-end; segments outside the ingested coverage fall back to the synthetic IRI baseline so the routing diff stays visible LA-wide.
- Reproducibility: dataset rebuild is one command (`python scripts/fetch_eval_data.py --build`); model weights load from a revision-pinned HuggingFace repo (pickle-ACE drift protection in `data_pipeline/detector_factory.py`); training is a single `scripts/finetune_detector.py` invocation across laptop CPU / Colab T4 / EC2 g5.xlarge recipes.

**Scope:** LA only (bbox ≈ 20 km around `(34.0522, -118.2437)`). No account required — Map View and Route Finder are both open.

## Current Status

**M1 shipped.** Public demo URL is live with real Mapillary detections, an LA-trained YOLOv8 pothole detector, and a Fly.io tri-app cloud deploy (db + backend + frontend) reproducible from `main`.

19/19 M0 backend tests + 200+ M1 backend tests passing. See `.planning/ROADMAP.md` for the full phase status.

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

LB-probe-friendly DB-reachability check.

- Success: `200` + `{"status": "ok", "db": "reachable"}`
- DB unreachable: `503` + `{"detail": {"status": "unhealthy", "db": "unreachable"}}`

Fly's HTTP health check treats non-2xx as unhealthy and depools the machine
(does not restart it), so the 503 path is the right code for a transient DB
hiccup. The PRD M0 contract `{"status": "ok"}` is preserved as an additive
superset (the `db` field is new in Phase 5).

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
sourced from Mapillary across 12 LA zones (sequence-grouped 70/20/10
train/val/test split, single-class "pothole" with severity derived from
detection confidence). Metrics reported: precision, recall, mAP@0.5,
each with image-level bootstrap 95% CIs at IoU=0.5 (1000 resamples,
seed=42). Full methodology and measurements:
[`docs/DETECTOR_EVAL.md`](docs/DETECTOR_EVAL.md).

Reproduce from a clean checkout — see
[`docs/FINETUNE.md`](docs/FINETUNE.md) for laptop / Colab / EC2 training
recipes:

```bash
# verify dataset integrity (SHA256-pinned manifest)
python scripts/fetch_eval_data.py

# run eval on the held-out test split
python scripts/eval_detector.py --data data/eval_la/data.yaml --split test
```

Configuration: set `YOLO_MODEL_PATH` in `.env` to either a HuggingFace
repo id (`<user>/<repo>@<revision>`) or a local `.pt` file path. Pickle-ACE
drift protection: revision SHAs are pinned at the `_DEFAULT_HF_REPO`
constant in `data_pipeline/detector_factory.py` (see comment block for
the bump procedure).

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

## Deploy

The stack deploys to Fly.io as three apps — `road-quality-db`,
`road-quality-backend`, `road-quality-frontend` — via a GitHub Actions
workflow on push to `main`. The workflow lives at
`.github/workflows/deploy.yml`; the per-app Fly configs live under
`deploy/{db,backend,frontend}/fly.toml`. Phase 5 ships this path; Phase 6
will use it to put the demo on a public URL.

### Prerequisites

1. **Fly.io account** with billing set up. Sign up at <https://fly.io/app/sign-up>.
2. **flyctl CLI** installed locally for hotfix deploys + secret management:

    ```bash
    curl -L https://fly.io/install.sh | sh
    flyctl auth login
    ```

3. **GitHub repo secret** `FLY_API_TOKEN` configured. Generate the token via:

    ```bash
    fly tokens create deploy -x 999999h --name "github-actions-deploy"
    ```

    Copy the output, then in GitHub: Settings → Secrets and variables → Actions → New repository secret. Name: `FLY_API_TOKEN`. Value: the token output.

### Initial deploy

Run these once, in order, from your local machine. After this, every push to `main` redeploys whichever app changed.

1. Create the three Fly apps (one-time):

    ```bash
    flyctl apps create road-quality-db
    flyctl apps create road-quality-backend
    flyctl apps create road-quality-frontend
    ```

2. Generate a Postgres password and an auth signing key (32+ chars), and stash them in your shell:

    ```bash
    PG_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
    AUTH_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    ```

3. Set Fly secrets per [05-RESEARCH §2](.planning/phases/05-cloud-deployment/05-RESEARCH.md):

    ```bash
    # DB app
    flyctl secrets set --app road-quality-db POSTGRES_PASSWORD="$PG_PASSWORD"

    # Backend app
    flyctl secrets set --app road-quality-backend \
      DATABASE_URL="postgres://rq:$PG_PASSWORD@road-quality-db.internal:5432/roadquality" \
      AUTH_SIGNING_KEY="$AUTH_KEY" \
      ALLOWED_ORIGINS="https://road-quality-frontend.fly.dev"

    # Optional: Mapillary token if you want to ingest real imagery later (Phase 6).
    # flyctl secrets set --app road-quality-backend MAPILLARY_ACCESS_TOKEN="..."
    ```

4. Push to `main` (or trigger manually via the GitHub Actions UI). The workflow will deploy db → backend → frontend in order. Watch progress at `https://github.com/<org>/<repo>/actions`.

5. After the first deploy completes, populate the routable graph (one-time; SC #7):

    ```bash
    gh workflow run deploy.yml --ref main -f seed=true
    ```

    This triggers the `seed-on-demand` job which runs `python scripts/seed_data.py` from the GH Actions runner (host venv) against the deployed Fly DB via `flyctl proxy`. The seed takes ~5 minutes (downloads OSMnx data + inserts ~10k segments + builds pgRouting topology).

6. Verify the deploy:

    ```bash
    curl https://road-quality-backend.fly.dev/health
    # Expected: {"status":"ok","db":"reachable"}

    curl -I https://road-quality-frontend.fly.dev/
    # Expected: HTTP/2 200, content-type: text/html
    ```

7. Open <https://road-quality-frontend.fly.dev/> in a browser and confirm the map renders LA segments. Sign in with the demo account (see [Public Demo Account](#public-demo-account) above).

### Hotfix

For urgent fixes that bypass the GH Actions queue:

```bash
# Build + deploy a single app from your local checkout
flyctl deploy --remote-only --config deploy/backend/fly.toml --app road-quality-backend .
```

This builds on Fly's remote builder (no local Docker required) and pushes the new image. Fly does a rolling restart by default.

### Rollback

```bash
# List recent images
flyctl image list --app road-quality-backend

# Roll back to the previous image
flyctl deploy --image <previous-image-ref> --app road-quality-backend
```

There is no automated rollback — operators trigger this manually after observing a regression in Fly logs (`flyctl logs --app road-quality-backend`).

### Volume snapshot caveat

Fly takes nightly volume snapshots of the db app (5-day retention by default). If you ever restore a snapshot, the migrations baked into the db image will NOT re-run (Postgres' init scripts are first-boot-only). Apply migrations manually post-restore:

```bash
flyctl ssh console --app road-quality-db -C \
  "psql -U rq -d roadquality -f /docker-entrypoint-initdb.d/01-schema.sql"
# Repeat for 02-mapillary.sql, 03-users.sql, etc.
```

All migrations use `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` so manual re-application is safe.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI, Python 3.12+, psycopg2 |
| Database | PostgreSQL 16 + PostGIS 3.4 + pgRouting 3.6 |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, react-leaflet |
| Routing | pgRouting `pgr_ksp` (k-shortest paths) |
| Data | OSMnx for road network, synthetic IRI + pothole data |
| ML (stub) | PotholeDetector protocol — YOLOv8 to be plugged in |
| Deploy | Docker Compose (local) + Fly.io (production) |

## Documentation

- [Setup, Run & Usage Guide](docs/SETUP.md) — complete guide for installation, running, and using the application
- [PRD](docs/PRD.md) — implemented vs. planned features
- [Design Document](docs/plans/2026-02-23-pothole-tracker-design.md) — architecture, schema, scoring math
- [Implementation Plan](docs/plans/2026-02-23-implementation-plan.md) — 14-task build plan
- [Detector Accuracy Report](docs/DETECTOR_EVAL.md) — evaluation methodology, numbers, reproduction
- [Mapillary Ingest Runbook](docs/MAPILLARY_INGEST.md) — operator workflow, SC #4 demo, Phase 6 cutover
- [Fine-Tuning Guide](docs/FINETUNE.md) — laptop / Colab / EC2 recipes
