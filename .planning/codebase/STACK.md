# Technology Stack

**Analysis Date:** 2026-04-23

## Languages

**Primary:**
- Python 3.12 - Backend API, data pipeline, seed scripts
- TypeScript 5.7.3 - Frontend application
- JavaScript - Build config, PostCSS, Tailwind

**Secondary:**
- SQL - PostgreSQL schemas and routing queries
- Bash - Database initialization scripts

## Runtime

**Environment:**
- Python 3.12+ (backend, data pipeline)
- Node.js 20+ (frontend)

**Package Manager:**
- pip (Python) - `backend/requirements.txt`, `scripts/requirements.txt`, `data_pipeline/requirements.txt`
- npm (Node) - `frontend/package.json` with npm 10+ (from Node 20 image)
- Lockfiles: `frontend/package-lock.json` present

## Frameworks

**Core:**
- FastAPI 0.115.6 - REST API framework for routing, segments, health endpoints
- React 18.3.1 - Frontend UI library
- Vite 6.0.7 - Frontend build tool and dev server (port 3000)

**Data & Geospatial:**
- OSMnx 2.0.1 - Road network data download from OpenStreetMap
- GeoPandas 0.14+ - Geographic data structures and operations
- PostgreSQL 16 - Primary database with PostGIS and pgRouting extensions
- PostGIS 3.4 - Spatial data types and operations
- pgRouting 3.6 - Graph routing algorithms (pgr_ksp for k-shortest paths)

**Routing & HTTP:**
- Uvicorn 0.34.0 - ASGI server for FastAPI
- httpx 0.28.1 - HTTP client (async support)
- psycopg2-binary 2.9.11 - PostgreSQL adapter

**Frontend Mapping:**
- Leaflet 1.9.4 - Interactive map library
- react-leaflet 4.2.1 - React wrapper for Leaflet
- react-router-dom 7.1.1 - Client-side routing

**Styling & UI:**
- Tailwind CSS 3.4.17 - Utility-first CSS framework
- PostCSS 8.4.49 - CSS transformation tool
- autoprefixer 10.4.20 - CSS vendor prefix plugin

**Testing:**
- pytest 8.3.4 - Python test runner
- httpx test client (from httpx) - HTTP testing

**ML (Stub/Future):**
- ultralytics 8.1+ - YOLOv8 model framework (data_pipeline only, not yet integrated)
- opencv-python-headless 4.8+ - Computer vision library (data_pipeline only)

**Utilities:**
- Pydantic 2.10.4 - Data validation and serialization
- cachetools 5.3+ - TTL cache implementation for segments and routes
- numpy 2.2+ - Numerical computing (data_pipeline)

## Configuration

**Environment:**
- `DATABASE_URL` env var: PostgreSQL connection string (default: `postgresql://rq:rqpass@localhost:5432/roadquality`)
- `VITE_API_URL` env var: Frontend API base URL (default: `http://localhost:8000` in dev, inferred at runtime)
- `VITE_MAPBOX_TOKEN` env var: Mapbox token (currently empty, not in use)

**Build:**
- `backend/Dockerfile` - Python 3.12-slim image, runs uvicorn with reload
- `frontend/Dockerfile` - Node 20-slim image, runs npm dev
- `db/Dockerfile` - postgis/postgis:16-3.4 image with pgrouting extension
- `docker-compose.yml` - Orchestrates db, backend, frontend services

**Frontend Config Files:**
- `frontend/vite.config.ts` - Vite dev server config with API proxy to `/api` → http://localhost:8000
- `frontend/tsconfig.json` - TypeScript compilation config
- `frontend/tailwind.config.js` - Tailwind CSS customization
- `frontend/postcss.config.js` - PostCSS plugin config

**Backend Config Files:**
- `backend/app/main.py` - FastAPI app entry point with CORS middleware
- `backend/app/db.py` - PostgreSQL connection factory

## Platform Requirements

**Development:**
- Docker Desktop with Docker Compose (required for postgres, postgis, pgrouting)
- Python 3.12+ (for seed_data.py and backend dev)
- Node.js 20+ (for frontend dev)
- PostgreSQL 16+ (via Docker, or local)

**Production:**
- Docker Compose (current deployment method)
- PostgreSQL 16+ with PostGIS 3.4 and pgRouting 3.6 extensions
- ~10km-20km road network data for LA area (loaded via OSMnx during seed)

## Data & Services

**Database Schema:** `backend/db/migrations/001_initial.sql`
- `road_segments` - Graph edges with IRI scores and travel times
- `segment_defects` - Pothole detections with severity and confidence
- `segment_scores` - Aggregated moderate/severe pothole scores
- `route_requests` - Audit log of all route requests (JSONB params)

**Network Data:**
- OpenStreetMap (via OSMnx) - Road geometry and topology
- Synthetic IRI data - Generated during seed_data.py
- Synthetic pothole data - Generated during seed_data.py

---

*Stack analysis: 2026-04-23*
