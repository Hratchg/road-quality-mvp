---
phase: 05-cloud-deployment
created: 2026-04-27
status: ready_to_research
requirements: [REQ-prod-deploy]
dependencies: [Phase 3, Phase 4]
---

# Phase 05 — Cloud Deployment: Decision Context

This document captures the locked decisions from the discuss-phase conversation. Downstream agents (`gsd-phase-researcher`, `gsd-planner`) consume it to know WHAT to investigate and WHAT NOT to re-ask.

## Phase goal (from ROADMAP.md)

> The stack runs on a cloud host from `main` with production-safe configuration — the prerequisite for a public demo.

## Success Criteria (from ROADMAP — locked, do not negotiate; 9 SCs total: 6 original + 3 folded in from Phase 4)

1. A documented deploy path (cloud provider + commands or pipeline) brings up db + backend + frontend in a non-local environment
2. CORS is restricted to the deployed frontend origin(s); no `allow_origins=["*"]` in production config
3. All secrets (DB creds, Mapillary token, auth signing key) come from the cloud host's secret mechanism; no committed defaults are used in prod
4. Frontend's `VITE_API_URL` points at the deployed backend; no `localhost` in the production bundle
5. `GET /health` reports DB reachability (not just `{"status": "ok"}`) so load-balancer probes are meaningful
6. Database connections are pooled (psycopg2 `SimpleConnectionPool` or equivalent); under burst load the pool does not exhaust PostgreSQL's connection limit
7. **(folded from Phase 4)** Fresh deploy initializes a routable graph: `seed_data.py` (or its deploy-time equivalent) populates `road_segments_vertices_pgr` via `pgr_createTopology` so the first `POST /route` after deploy succeeds without a manual SQL step
8. **(folded from Phase 4)** The repo's migration test suite collects and runs cleanly inside the deployed `backend` container — `test_migration_002.py` and `test_migration_003.py` resolve their migration-file paths via the project root, not absolute `/db/...`
9. **(folded from Phase 4)** `backend/app/routes/routing.py` releases its psycopg2 connection on the exception path (wrap in `contextlib.closing` like Phase 3 plan 03's WR-04 fix and Phase 4 plan 03's WR-03 fix) — required so the SimpleConnectionPool in SC #6 doesn't leak slots under the route load it's meant to handle

## What downstream agents need to know

### D-01 — Cloud provider: Fly.io

**Decision:** Fly.io as the deployment platform. Three Fly apps:
- `<project>-db` — Postgres+PostGIS+pgRouting on a Fly volume
- `<project>-backend` — FastAPI (existing `backend/Dockerfile`)
- `<project>-frontend` — nginx serving the built Vite bundle

**Why:** The PostGIS 3.4 + pgRouting 3.6 requirement (locked in `STACK.md`) eliminates most managed-Postgres options (Render, Supabase, GCP Cloud SQL all lack pgRouting as of 2026). Fly lets us roll our own Postgres image while still giving us git-push-style deploy ergonomics, secret management via `fly secrets set`, and auto-TLS at `*.fly.dev`. Multi-container apps map cleanly onto our existing `docker-compose.yml` mental model. Estimated cost ~$5–10/mo at demo scale.

**Implementation hint:** Each app gets a `fly.toml` at the repo root or in a per-service subdirectory. The researcher should confirm Fly's current best-practice for monorepo-with-multiple-apps (one fly.toml at root with `[[deploy.processes]]` vs. one fly.toml per app subdirectory — both work, latter is cleaner for our tri-service shape).

**What's NOT in scope for M1 (deferred, additive if needed):**
- Multi-region deployment
- Autoscaling beyond Fly's defaults
- Fly Machines (we use the higher-level Apps platform)
- Migration to a managed Postgres provider

### D-02 — Database hosting: custom Dockerfile from `postgis/postgis:16-3.4`

**Decision:** A small Dockerfile that inherits `postgis/postgis:16-3.4` and `apt install`s `postgresql-16-pgrouting`. Mounted onto a Fly volume for persistence.

```dockerfile
FROM postgis/postgis:16-3.4
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-16-pgrouting \
 && rm -rf /var/lib/apt/lists/*
```

**Why:** Smallest moving parts. Exact version pinning matches `STACK.md` (PostGIS 3.4, pgRouting 3.6 — researcher to confirm Debian apt ships pgRouting 3.6.x for PG16; if it ships 3.7 or later that's fine, the project doesn't pin a minor version). We already use this image locally so the migration init flow (mounted `db/migrations/`) is byte-identical to dev.

**Locked file layout:**
- `deploy/db/Dockerfile` — the 3-line image
- `deploy/db/fly.toml` — Fly app config: 1 GB volume, `mount_path = "/var/lib/postgresql/data"`, single primary process, internal-only ports

**Backup posture (deferred):** Fly volume snapshots are configurable post-deploy. For MVP demo we accept "rebuild from migration + seed if lost" since data is reproducible (synthetic baseline + Mapillary re-ingest). Phase 6+ can layer on a snapshot schedule or `pg_dump` cron.

### D-03 — Frontend hosting: separate Fly app, cross-origin

**Decision:** A second Fly app for the frontend. nginx (in `deploy/frontend/Dockerfile`) serves the Vite-built `frontend/dist/` static bundle. Cross-origin to the backend at `<backend>.fly.dev`.

**Why:** Properly exercises SC #2 (CORS restricted to deployed origin) — option of bundling frontend into the backend container would let us punt on CORS, but we WANT to prove CORS works because Phase 6's public demo + future custom domains will need that pattern. Independent deploys for frontend bug fixes. Both services get free auto-TLS at `*.fly.dev`.

**Implementation hint:**
- `deploy/frontend/Dockerfile`: multi-stage — `node:20` build → `nginx:alpine` runtime
- `deploy/frontend/nginx.conf`: serves `/`, falls back to `index.html` for SPA routing, sets `Cache-Control` headers for static assets
- `VITE_API_URL` baked at build time → set via `fly deploy --build-arg VITE_API_URL=https://<backend>.fly.dev` OR via `[build] args` in `fly.toml`
- Backend's CORS allowlist reads from a new env var `ALLOWED_ORIGINS` (comma-separated) rather than being hardcoded

**Researcher to confirm:** Vite's `import.meta.env.VITE_API_URL` reads its value at BUILD time, not runtime. The Dockerfile must set the build arg correctly; runtime env changes won't propagate to the bundle.

### D-04 — Deploy automation: GitHub Actions on push to `main`

**Decision:** `.github/workflows/deploy.yml` runs `fly deploy` for each of the 3 apps on green CI on push to `main`. `FLY_API_TOKEN` as a GitHub repo secret.

**Why:** Matches the codebase's existing test discipline (Phase 2/3 already imply CI). The workflow file IS the documented deploy path SC #1 demands — no separate runbook required. Branch protection on `main` becomes trivially valuable. Operators retain the ability to run `fly deploy` manually for hotfixes if they have a working `flyctl`.

**Locked file layout:**
- `.github/workflows/deploy.yml` — separate jobs for `db`, `backend`, `frontend` with explicit `needs:` dependencies (db before backend before frontend)
- README "Deploy" section documents the manual-hotfix path and how to set up `flyctl` locally

**Implementation hint:**
- Each job uses `superfly/flyctl-actions/setup-flyctl@master` (or pin to a version)
- `flyctl deploy --app <name>` per service
- Skip frontend deploy if no `frontend/` files changed (path filter on `on.push.paths`); same for backend; db only redeploys when `deploy/db/**` changes
- Pre-deploy: run the existing pytest suite as a CI gate (the Phase 4 in-container suite that needs the `data_pipeline` mount fix per SC #8 — the researcher must surface this dependency)

**What's NOT in scope:**
- Staging environment + promotion gate (deferred — a single prod env is sufficient for demo)
- Manual approval gate before deploy (rejected — main is the source of truth)
- Rollback automation beyond `fly deploy --image-label <prev>` (manual)

### D-05 — Default secret-management mechanism (NOT discussed; default applied)

**Decision (default):** Use `fly secrets set` for all runtime secrets. Production secret roster:
- `DATABASE_URL` — composed from db app's internal hostname + Fly-generated password
- `AUTH_SIGNING_KEY` — 32-byte token_urlsafe (Phase 4 pattern)
- `MAPILLARY_ACCESS_TOKEN` — operator-provided when ingest runs
- `ALLOWED_ORIGINS` — comma-separated frontend origins
- `YOLO_MODEL_PATH` — defaults to HF repo, override possible

**Why:** Matches Fly's idiomatic pattern. SC #3 satisfied with zero extra plumbing. Secrets are encrypted at rest and exposed to the app as env vars at runtime. No `.env` file ever lives on prod — only `.env.example` (already in repo) documents the names.

**Researcher to confirm:** Best practice for `DATABASE_URL` between Fly apps is to use Fly's internal `*.flycast` or `.internal` hostnames (not public IPs) so DB traffic never leaves the Fly network. The exact format and how to expose Fly's auto-generated PG password into the backend's env is a researcher item.

### D-06 — Default CORS scope (NOT discussed; default applied)

**Decision (default):** Single allowlist entry for the deployed frontend origin (e.g., `https://<frontend>.fly.dev`), read from the `ALLOWED_ORIGINS` env var (comma-separated to allow future expansion to a custom domain). Backend's `CORSMiddleware` configuration stops being `allow_origins=["*"]` and becomes `allow_origins=ALLOWED_ORIGINS.split(",")`.

**Implementation hint:** This is the surgical fix to `backend/app/main.py` lines 8-12 (CONCERNS.md called out the `allow_origins=["*"]`). The change must be additive — `allow_credentials`, `allow_methods`, `allow_headers` stay the same; only `allow_origins` becomes env-driven.

### D-07 — Default connection-pool sizing (NOT discussed; default applied)

**Decision (default):** `psycopg2.pool.SimpleConnectionPool(minconn=2, maxconn=10)` per backend instance. Pool created in `backend/app/db.py` at module import; `get_connection()` becomes `pool.getconn()` and a context-manager wrapper that calls `pool.putconn()` on exit (mirrors Phase 4's `contextlib.closing` fix discipline).

**Why:** At MVP demo scale, ~10 concurrent requests is the realistic upper bound. PG default `max_connections` is 100; reserving 10 leaves comfortable headroom for psql sessions, the demo seed script, etc. SimpleConnectionPool is single-process (matches our single-Fly-machine backend); ThreadedConnectionPool would only be needed if we ever spawn worker threads in-process, which we don't.

**Researcher to confirm:** Whether FastAPI's threadpool default (40 threads via `anyio`) means we should bump `maxconn` higher — researcher's call based on observed peak concurrency.

### D-08 — Default `/health` reachability check shape (NOT discussed; default applied)

**Decision (default):** `GET /health` becomes:

```python
@router.get("/health")
def health():
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return {"status": "ok", "db": "reachable"}
    except Exception:
        raise HTTPException(status_code=503, detail={"status": "unhealthy", "db": "unreachable"})
```

**Why:** Minimal change — the existing endpoint shape (200 + `{status: ok}`) is preserved on the happy path; failure produces 503 + `{db: unreachable}` for LB probes. This satisfies SC #5 ("not just `{status: ok}`") without breaking any existing client.

**Researcher to confirm:** Whether we should use a separate `/healthz` (k8s convention) for the LB-probe endpoint and keep `/health` semantically richer. At Fly scale, `/health` works for both.

### D-09 — Default observability minimum (NOT discussed; default applied)

**Decision (default):** No new observability infra in Phase 5. We rely on:
- Fly's built-in log streaming (`fly logs --app <name>`)
- Fly's per-app metrics dashboard (CPU, memory, request count, latency)
- The existing FastAPI default request logging

**Why:** PROJECT.md "Out of Scope" already says "Structured logging / Prometheus / full observability stack ... defer until prod deploy reveals real need." Phase 5 IS that prod deploy; if it reveals real need, Phase 6 or beyond can add Sentry / structured logs. For now, Fly's defaults are enough.

## Out of scope for Phase 5 (explicit)

- Multi-region deployment, autoscaling, blue/green, canary
- Staging environment + promotion gate
- Custom domain + Let's Encrypt (Fly auto-TLS at `*.fly.dev` is sufficient for demo)
- Rate limiting (deferred to a Cloudflare layer or similar in Phase 6+ if abuse appears)
- Email-based password reset / verification (Phase 4 explicitly out of scope; Phase 5 doesn't reopen)
- Sentry / Datadog / structured logging
- `pg_dump` cron / PITR (Fly volume snapshots cover the same need post-deploy if we configure them; not blocking)
- Redis / distributed cache (PROJECT.md "Out of Scope")
- Mapillary ingest cron in production (operator runs ingest manually per Phase 3 runbook)

## Existing codebase facts the researcher should verify

- `backend/app/main.py` lines 8-12 hardcode `CORSMiddleware(allow_origins=["*"])` — the SC #2 surgical fix lives here
- `backend/app/db.py` is the sole DB-handle convention; `get_connection()` is what the pool wrapper replaces
- `backend/app/routes/routing.py` has the connection-leak pattern (`with psycopg2.connect(...) as conn` only manages the txn) — SC #9 fix per Phase 3 plan 03's WR-04 / Phase 4 plan 03's WR-03 templates
- `backend/tests/test_migration_002.py` and `backend/tests/test_migration_003.py` reference `/db/migrations/<file>.sql` absolute paths — SC #8 fix is to use `Path(__file__).resolve().parents[N] / "db" / "migrations" / "<file>.sql"`
- `scripts/seed_data.py` does NOT call `pgr_createTopology` — SC #7 fix is to append it after the segment-load section (researcher to confirm exact point in the script)
- `frontend/src/api.ts` uses `import.meta.env.VITE_API_URL` already (Phase 0); no rewrite needed, but the build pipeline must set it
- `docker-compose.yml` is the local-dev manifest; production uses `fly.toml` files instead — `docker-compose.yml` is NOT modified by Phase 5
- `.env.example` already documents the env var names; researcher confirms Phase 5 adds `ALLOWED_ORIGINS` (and that's the only new one)

## Folded-in fix expectations (SC #7, #8, #9)

These were added to ROADMAP.md after Phase 4 closed. The planner MUST:

- **SC #7:** Add `pgr_createTopology('road_segments', 0.0001, 'geom', 'id', clean := true)` to `scripts/seed_data.py` after the segment INSERT loop. Add a "topology" guard to `/health`'s DB-reachability probe (or a dedicated `pre-deploy-check.py`) so we don't ship an unrouting deploy. Test: spin up a fresh DB via the docker init flow + run seed → assert `road_segments_vertices_pgr` non-empty.
- **SC #8:** Refactor `test_migration_00{2,3}.py` to compute migration paths from `Path(__file__).resolve().parents[2] / "db" / "migrations" / ...`. Verify: `docker compose exec backend pytest tests/test_migration_002.py tests/test_migration_003.py -m integration` returns 0 errors / 0 failures.
- **SC #9:** Wrap `psycopg2.connect()` in `routes/routing.py` with `contextlib.closing()` (mirror Phase 3's `fd9c24f` and Phase 4's `ab3d552`). Adopt the same pattern when wiring `SimpleConnectionPool` so pool slots release on exception. Verify: integration test that exercises a /route handler raising mid-query (mock psycopg2 to raise) and asserts pool size unchanged after recovery.

These three fold-ins are LOW-RISK additive fixes — the planner should consider whether they belong in Wave 0 (foundational, parallel-safe) or in Wave 1 alongside the cloud-deploy plumbing.

## Deferred Ideas (not lost — for future phases or M2)

- Custom domain (e.g., `road-quality-demo.example.com`) — flagged for Phase 6 if demo gains traction
- Cloudflare in front of Fly for WAF + caching — flagged, M2 if abuse appears
- Sentry error tracking — flagged, additive if Fly logs prove insufficient
- Structured logging (loguru / structlog) — flagged, prod-deploy reveal-driven
- Multi-region failover — flagged, only if demo audience shifts global
- Mapillary ingest cron — flagged, requires Phase 6 demo signal first
- `pg_dump` automated backup pipeline — flagged, additive on top of Fly volume snapshots
- Staging environment — flagged, useful if a 3rd person joins the project

## Research priorities (for gsd-phase-researcher)

The researcher should focus investigation on:

1. **Fly.io tri-app monorepo conventions (2026)** — single `fly.toml` at root with multiple `[[deploy.processes]]` vs. one `fly.toml` per service subdirectory. Check Fly's official docs and recent community templates. Recommend the cleaner pattern with reasoning.

2. **`postgresql-16-pgrouting` apt availability on `postgis/postgis:16-3.4`** — confirm the Debian package exists for the image's base, confirm the version is ≥ 3.6 (project requirement). If the image's base distro doesn't have pgRouting in apt, recommend pinning to a different base (e.g., `postgres:16-bookworm` + manual PostGIS install).

3. **Fly volume mount + `db/migrations/` init flow** — best practice for getting our existing `db/migrations/*.sql` files into the Postgres container at first boot. Options: (a) bake into the image via Dockerfile `COPY`; (b) mount a Fly file via `[mounts]`; (c) one-shot SSH + `psql` after first boot. Recommend the most idempotent option.

4. **`fly secrets set` and the cross-app DATABASE_URL** — how to compose the backend's `DATABASE_URL` from the db app's internal hostname + auto-generated password. Check if Fly Postgres apps expose a generated password env var that's referenceable from the backend's secrets.

5. **GitHub Actions deploy workflow shape (3 services, conditional jobs)** — recommended `actions/checkout` + `superfly/flyctl-actions/setup-flyctl` pattern. Path filters that skip jobs when only docs/planning files change. How to gate on the existing pytest suite (which needs `data_pipeline/` mounted — currently a friction point per SC #8).

6. **Vite build-time env var injection in a Dockerfile** — recommended pattern for `VITE_API_URL` via build arg. Show the Dockerfile snippet and the `fly deploy --build-arg` invocation.

7. **CORS env-driven configuration for FastAPI 0.136** — confirm the recommended pattern for env-driven `allow_origins`. Confirm `allow_credentials=True` (which we likely need for cookies/tokens, though Phase 4's JWT-in-localStorage pattern doesn't strictly require it) interacts correctly with explicit origin allowlists (it can't with wildcard).

8. **psycopg2 `SimpleConnectionPool` integration with FastAPI's threadpool** — recommend the dependency-injection pattern (FastAPI `Depends`-based `get_db()` that yields a pooled connection). Compare to the current `with get_connection() as conn` direct pattern. Suggest minimal-diff migration path.

9. **`/health` 503 LB probe convention** — confirm Fly's HTTP health check supports 503 as "unhealthy" out of the box and won't restart the machine on transient DB hiccups (we want the LB to depool the instance, not Fly to kill it).

10. **`pgr_createTopology` invocation timing** — best place in the seed flow to call it. Confirm idempotency (`clean := true` we already use locally). Confirm that re-running seed on a populated DB doesn't double the topology size.

11. **Fly Postgres backup snapshots** — what's the simplest, lowest-friction way to get nightly volume snapshots. Check if Fly enables them by default for volumes.

12. **Connection-string SSL requirements** — does Fly require `sslmode=require` in `DATABASE_URL` for inter-app traffic on the Fly internal network? Confirm.

The researcher should NOT investigate:
- Whether to use Fly vs other providers (locked → Fly)
- Whether to use managed Postgres (locked NO → custom Docker)
- Whether to bundle frontend into backend (locked NO → separate apps)
- Whether to use GH Actions vs other CI (locked → GH Actions)
- CORS removal (locked YES — it's the SC #2 fix)
- Refresh tokens, OAuth, password reset (Phase 4 out of scope)
- Multi-region, autoscaling, k8s (out of scope for M1)
