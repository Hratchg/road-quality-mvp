# road-quality-mvp

## What This Is

A web app that routes drivers in Los Angeles along roads optimized for ride quality, not just speed. It combines OpenStreetMap topology, IRI (International Roughness Index) data, and pothole detections to score road segments, then uses pgRouting's k-shortest-paths to return a "fastest" and a "best" route side-by-side. **As of v0.3.0 (M1, shipped 2026-05-08):** the app runs as a public Fly.io tri-app deployment serving real LA Mapillary-ingested pothole data via the public-baseline `keremberke/yolov8s-pothole-segmentation` detector, with cross-LA routing under 5 seconds. Live at `https://road-quality-frontend.fly.dev/`.

## Core Value

Given any two points in LA, show the user a route that is demonstrably smoother than the fastest route — within a user-controlled time budget — using real, trustworthy road-quality data.

**Validated by v0.3.0:** Live demo serves the cross-LA fastest-vs-best comparison on real Mapillary detections in 2.5s. Core value confirmed correct; the next milestone can iterate on quality-of-data rather than re-litigating the proposition.

## Requirements

### Validated

<!-- Shipped in M0 v0.2.0 + M1 v0.3.0. Confirmed working per PRD, codebase, and v0.3.0-MILESTONE-AUDIT.md. -->

**v0.2.0 (M0 MVP):**

- ✓ `REQ-docker-compose-stack` — Docker Compose orchestrates db + backend + frontend — v0.2.0
- ✓ `REQ-db-schema` — Four-table schema (road_segments, segment_defects, segment_scores, route_requests) — v0.2.0
- ✓ `REQ-health-endpoint` — `GET /health` returns `{"status": "ok"}` (deepened to DB-reachability in v0.3.0) — v0.2.0
- ✓ `REQ-segments-endpoint` — `GET /segments?bbox=...` returns GeoJSON with IRI + pothole scores — v0.2.0
- ✓ `REQ-route-endpoint` — `POST /route` returns fastest + best route — v0.2.0 (algorithm replaced in Phase 8 v0.3.0)
- ✓ `REQ-scoring-logic` — Weight normalization + cost formula — v0.2.0
- ✓ `REQ-max-time-rule` — Reject candidates > fastest + max_extra_minutes; fall back with warning — v0.2.0
- ✓ `REQ-pydantic-models` — All API bodies validated by Pydantic v2 — v0.2.0
- ✓ `REQ-ml-detector-protocol` — `PotholeDetector` Protocol + `StubDetector` — v0.2.0
- ✓ `REQ-yolov8-detector` — `YOLOv8Detector` selectable via factory, graceful fallback — v0.2.0
- ✓ `REQ-seed-data` — OSMnx LA network + synthetic IRI + synthetic potholes (seed=42) — v0.2.0
- ✓ `REQ-iri-ingestion` — CSV/shapefile/synthetic IRI ingestion CLI — v0.2.0
- ✓ `REQ-frontend-skeleton` — Vite + React + TS + Tailwind + react-router — v0.2.0
- ✓ `REQ-map-view-page` — Full-screen Leaflet map with color-coded segments — v0.2.0
- ✓ `REQ-route-finder-page` — Origin/destination picker with fastest vs best comparison — v0.2.0
- ✓ `REQ-readme-docs` — README quick start + scoring + API overview — v0.2.0
- ✓ `REQ-demo-launch` — `docker compose up` → `seed_data.py` → http://localhost:3000 — v0.2.0
- ✓ `REQ-integration-tests` — 6+ live-DB integration tests — v0.2.0
- ✓ `REQ-caching-layer` — TTL caches for /segments + /route + admin endpoints — v0.2.0

**v0.3.0 (M1 Post-MVP + Public Demo):**

- ✓ `REQ-mvp-integrity-cleanup` — BIGINT migration, seed-radius, VITE_MAPBOX_TOKEN, psycopg2 pin reconciled — v0.3.0 Phase 1
- ✓ `REQ-real-data-accuracy` — YOLO env-var path config, eval harness with bootstrap CIs, Mapillary client, fine-tune CLI, DETECTOR_EVAL.md — v0.3.0 Phase 2 (tooling validated; live numbers per 02-HUMAN-UAT.md)
- ✓ `REQ-mapillary-pipeline` — `scripts/ingest_mapillary.py` + migration 002 + `compute_scores.py --source` filter + MAPILLARY_INGEST.md — v0.3.0 Phase 3
- ✓ `REQ-prod-deploy` — Fly.io tri-app + GH Actions deploy + ThreadedConnectionPool + env-driven CORS + /health DB-reachability — v0.3.0 Phase 5
- ✓ `REQ-public-demo` — `https://road-quality-frontend.fly.dev/` live with real LA data on the public-baseline detector — v0.3.0 Phase 6
- ✓ `REQ-routing-performance` (Phase 8 SCs, no formal REQ) — pre-filter + Dijkstra×K wired into 3-attempt fallback; cross-LA 2.47s, DTLA 0.385s — v0.3.0 Phase 8

### Superseded

- ⚠ `REQ-user-auth` (v0.3.0 Phase 4 → SUPERSEDED by commit `d0ef452`) — Phase 4 originally shipped JWT (HS256, AUTH_SIGNING_KEY) + pwdlib argon2id + `/auth/{register,login,logout}` + sign-in modal + demo account, validated end-to-end via 8-scenario curl UAT against live Docker (2026-04-27). Commit `d0ef452` (2026-04-28, "feat: remove sign-in feature — demo is fully public") then unmounted the auth router and removed all auth gating per operator decision: the public-demo target is reachable without sign-up. Backend modules (`backend/app/auth/{tokens,passwords,dependencies}.py`) remain in tree as dormant code; re-enable by env-var toggle (`if os.environ.get("AUTH_ENABLED") == "true"`). Original acceptance criteria preserved as historical record.

### Documented Negative

- ✗ `REQ-trained-la-detector` (v0.3.0 Phase 7 → D-11 NEGATIVE) — Both training iterations failed the win-check on the held-out test split. Iter-1 (af7af59a): full collapse, 0 predictions. Iter-2 (84a874c2): val P=0.184 R=0.071 but 0 predictions on test split (likely operator labeling-style drift between CVAT splits). D-13 contingency executed: production retains keremberke baseline; both trained models preserved on HF for traceability. `docs/DETECTOR_EVAL.md` v0.3.0 documents both failure modes. Future-fine-tune options recorded in `.planning/phases/07-la-trained-detector/FUTURE-FINETUNE-OPTIONS.md`.

### Active

<!-- v0.4.0 Crash-Aware Routing — populated by REQUIREMENTS.md when it lands. -->

- [ ] Crash-data ingest pipeline (SWITRS/TIMS + LA City open-data) with historical aggregate + three-tier severity (fatal/injury/PDO)
- [ ] Snap-match crashes to road segments → per-segment `crash_norm`
- [ ] Scoring formula update: locked weights `0.40·iri_norm + 0.35·pothole_norm + 0.25·crash_norm` (replaces user-tunable sliders)
- [ ] Frontend: remove IRI/pothole sliders from Control Panel (keep max-extra-minutes); segment colors continue to encode the locked cost
- [ ] Backend: `/route` API silently ignores `w_IRI` / `w_pothole` if present (backwards-compatible)
- [ ] Operator runbook for quarterly crash-data refresh
- [ ] Document Phase 8 env vars (`ROUTE_FILTER_BUFFER_DEG`, `ROUTE_FILTER_WIDEN_FACTOR`) in README/.env.example (carryforward from v0.3.0)

## Current Milestone: v0.4.0 Crash-Aware Routing

**Goal:** Add historical crash data as a third routing-cost factor and replace user-tunable weight sliders with a single locked weighting (40 IRI / 35 pothole / 25 crash), so the public demo recommends routes that avoid both rough roads AND crash-prone segments.

**Target features:**
- Crash-data ingest pipeline (SWITRS/TIMS + LA City open-data) — historical aggregate, three-tier severity
- Snap-match crashes to road segments → `crash_norm` per segment
- Locked scoring weights: `cost = travel_time + 0.40·iri_norm + 0.35·pothole_norm + 0.25·crash_norm`
- Slimmer Control Panel — sliders removed, max-extra-minutes retained
- Backwards-compatible `/route` API (silently ignores `w_IRI` / `w_pothole`)
- Quarterly crash-data refresh runbook
- Document Phase 8 routing-buffer env vars

**Out of scope this milestone:** Phase 7 v2 detector retry; deferred operator UAT walkthroughs (02/03/05); auth re-enablement; crash heatmap/markers map layer; multi-city expansion.

### Out of Scope

<!-- Carryforward from v0.3.0 — re-audit at next milestone scoping. -->

- Real-time chat / user-to-user messaging — not relevant to routing value
- Mobile apps (iOS/Android native) — web-first; responsive web is sufficient
- Multi-city support — hard-coded LA viewbox; generalization deferred until demo signal validates
- Redis / distributed cache — in-memory `cachetools` adequate for single-instance Fly deploy
- Alembic migrations — raw SQL in `db/migrations/` is fine; adopt only if 5+ migrations land without ADR
- SQLAlchemy / ORM migration — raw psycopg2 works
- Structured logging / Prometheus / full observability stack — defer until prod reveals real need
- Native YOLOv8 training from scratch — fine-tune only; Phase 7 demonstrated the constraint
- Pagination on `/segments` — known limitation; defer unless demo reveals large-bbox problems

## Context

**Current state (post-v0.3.0, 2026-05-08):**

- Live deploy: `https://road-quality-frontend.fly.dev/` (Fly.io tri-app: db internal-only, backend public, frontend public with VITE_API_URL build-arg)
- Repo lives at `/Users/hratchghanime/road-quality-mvp` (macOS dev)
- Stack (backend): Python 3.12 + FastAPI 0.115.6 + psycopg2-binary 2.9.11 + ThreadedConnectionPool wrapper + uvicorn
- Stack (frontend): React 18 + Vite 6 + Leaflet 1.9 + TypeScript + Tailwind
- Stack (database): PostgreSQL 16 + PostGIS 3.4 + pgRouting 3.6 (Fly: PostGIS+pgRouting 3.8 custom image)
- Codebase: 11,583 LOC (Py+TS+SQL) across backend/frontend/db/scripts/data_pipeline
- Production data: ~205,000 segments + ~74,000 vertices + ~125,632 defects across 12 LA zones (real Mapillary detections via keremberke baseline)
- Cross-LA routing: 2.47s uncached (was 20-90s pre-Phase-8)
- Detector in production: `keremberke/yolov8s-pothole-segmentation` (public baseline, per Phase 6 D-09 + Phase 7 D-13 negative path)
- Auth: backend modules retained but unmounted; demo is public per d0ef452

**Known concerns carried forward:**

- 5 Mapillary integration tests hang on `subprocess.run` selectors.poll (pre-existing, surfaced in Phase 8 UAT)
- README:312 stale prose (seed-on-demand description references in-container workflow but actual is host-venv + flyctl proxy)
- `ROUTE_FILTER_BUFFER_DEG` + `ROUTE_FILTER_WIDEN_FACTOR` env vars not documented in README/.env.example (Phase 8 tech debt)
- Untracked: `data/eval_la/labels/test.cache` + `.planning/phases/03-mapillary-ingestion-pipeline/.Rhistory` (should be gitignored)
- 4 deferred operator-runbook walkthroughs (02-HUMAN-UAT, 02/03/05-VERIFICATION) — see STATE.md

**Lessons learned for v0.3.0:**

- Long DDL on Fly DB must run via `flyctl ssh console -C "psql ..."`, NOT `flyctl proxy` — wireguard timeouts trigger postgres recovery crash loops (Phase 5 LESSONS-LEARNED)
- Fully-seeded LA dataset needs ≥ 2 GB DB memory + ≥ 3 GB volume; empty-schema sizing OOM-crashes during `pgr_createTopology`
- pgr_ksp evaluates inner SQL via SPI which doesn't use GiST index on `road_segments.geom` — bbox WHERE inside the SQL string is full seq scan (Phase 8 root cause)
- Operator labeling-style drift across CVAT splits can quietly break fine-tuning — likely root cause of Phase 7 iter-2 train/test mismatch

## Constraints

- **Stack (backend)**: Python 3.12+, FastAPI, psycopg2 with RealDictCursor + ThreadedConnectionPool wrapper, uvicorn, Pydantic v2, pytest. No SQLAlchemy migration in foreseeable scope.
- **Stack (frontend)**: TypeScript, React 18, Vite, react-leaflet (default), react-map-gl (Mapbox upgrade), Tailwind. No state library beyond hooks.
- **Stack (database)**: PostgreSQL 16 + PostGIS 3.4 + pgRouting 3.6 (Fly uses 3.8 custom image), geometry SRID 4326.
- **Schema**: Four-table schema in `CON-db-schema` is load-bearing. `road_segments.source`/`target` BIGINT (verified Phase 1). Migrations under `db/migrations/`.
- **API contracts**: `/health`, `/segments`, `/route`, `/cache/stats`, `/cache/clear` shapes locked. /health now returns 503 on DB unreachability per Phase 5.
- **Scoring math (v0.3.0, SUPERSEDED in v0.4.0):** `cost_segment = travel_time_s + w_IRI*iri_norm + w_pothole*(moderate_score + severe_score)` with user-tunable weights. **Replaced in v0.4.0 by locked constants:** `cost_segment = travel_time_s + 0.40*iri_norm + 0.35*pothole_norm + 0.25*crash_norm`. Weight normalization rules removed (no longer needed with fixed constants). Migration path: existing `/route` API still accepts `w_IRI` / `w_pothole` per locked CON-route-api but backend ignores them.
- **Route-selection algorithm**: K=5 candidate paths preserved. Implementation: pgr_dijkstra × K with edge-weight perturbation (Yen's-style, replaces pgr_ksp K=5 per Phase 8 D-08-03; OSRM/Valhalla pattern).
- **Routing 3-attempt fallback**: filter (3.3 km buffer) → wide-filter (×2) → full-graph. Catches BOTH `psycopg2.errors.QueryCanceled` AND empty-result conditions per Phase 8.
- **Detector protocol**: `PotholeDetector` Protocol with `detect(image_path) -> list[Detection]`. Production model: `keremberke/yolov8s-pothole-segmentation` via `_DEFAULT_HF_REPO` per Phase 6 D-09 / Phase 7 D-13.
- **Ports**: Frontend 3000, backend 8000, Postgres 5432.
- **Seed data**: Center (34.0522, -118.2437), radius 20 km (DIST=20000 in seed_data.py is authoritative; SPEC's 10 km claim was overridden Phase 1).
- **Migrations**: Single SQL files under `db/migrations/`, no Alembic.
- **CORS**: Production CORS env-driven, restricted to deployed frontend origin(s); never `allow_origins=["*"]` in prod.
- **Secrets**: All secrets via Fly secrets / environment, never committed defaults in prod.
- **Cloud infra sizing**: Fully-seeded LA needs ≥ 2 GB DB memory + ≥ 3 GB volume. Phase 5 currently runs `shared-cpu-1x:2048MB` + 5 GB volume.
- **Long DDL on Fly DB**: Run via `flyctl ssh console -C "psql ..."`, NOT `flyctl proxy` (wireguard timeout → postgres recovery crash loop).
- **Auth toggle (latent)**: Backend auth modules in tree but unmounted. Re-enable by env-var (`AUTH_ENABLED=true`) — see Phase 4 modules + d0ef452 commit.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Routing via pgRouting in DB, not in-process | Production-grade; avoids in-process graph libs | ✓ Good (v0.2.0; algorithm refined v0.3.0 Phase 8) |
| K = 5 for k-shortest-paths | Variety without perf blowup | ✓ Good (v0.2.0) |
| Seed=42 for deterministic synthetic data | Reproducible demos and tests | ✓ Good (v0.2.0) |
| Leaflet + OSM default, Mapbox via `VITE_MAPBOX_TOKEN` | Free default, optional upgrade | ✓ Good (v0.2.0) |
| Seed radius = 20 km (code authoritative) | `scripts/seed_data.py` `DIST = 20000` confirmed; docs reconciled | ✓ Resolved (v0.3.0 Phase 1) |
| `road_segments.source`/`target` as BIGINT | SPEC over plan's INTEGER; verified in migration 001 | ✓ Resolved (v0.3.0 Phase 1) |
| YOLO_MODEL_PATH env var + HF resolution via `huggingface_hub.hf_hub_download` | Removes CWD-relative hardcoded path | ✓ Good (v0.3.0 Phase 2) |
| Mapillary ingest dedupe via `ON CONFLICT DO NOTHING` on `(source_mapillary_id, source)` UNIQUE | Idempotent rerun without manual dedup pass | ✓ Good (v0.3.0 Phase 3) |
| Fly.io as cloud target (tri-app) | Single-platform deploy, internal networking, secret management | ✓ Good (v0.3.0 Phase 5) |
| ThreadedConnectionPool wrapper for psycopg2 | Avoids exhausting Postgres connection limit under burst | ✓ Good (v0.3.0 Phase 5) |
| Long DDL via `flyctl ssh console -C` not `flyctl proxy` | Wireguard timeout triggers Postgres crash loop | ✓ Locked anti-pattern (v0.3.0 Phase 5 LESSONS-LEARNED) |
| Public-baseline detector for v0.3.0 demo (D-09) | Hand-labeling pass yielded only 17 positive bboxes — too sparse for stable fine-tune | ✓ Good (v0.3.0 Phase 6) |
| Authentication removed for fully-public demo (commit d0ef452) | Operator decision: lower friction for public demo target | ✓ Good (v0.3.0 post-Phase-4) |
| Phase 7 D-13 contingency: skip prod cutover on negative win-check | Trained model (val P=0.184, 0 test predictions) would actively degrade the live demo | ✓ Good (v0.3.0 Phase 7) |
| pgr_dijkstra × K with edge-weight perturbation replacing pgr_ksp K=5 | pgr_ksp super-linear timed out at 12s on dense urban subgraphs; OSRM/Valhalla pattern is linear in K | ✓ Good (v0.3.0 Phase 8) |
| 3-attempt fallback chain (filter → wide → full) catching `QueryCanceled` AND empty results | Reverted Plan 08-03 only caught empty results — timeouts bubbled to HTTP 500 | ✓ Good (v0.3.0 Phase 8) |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-08 — v0.4.0 milestone started (Crash-Aware Routing)*
