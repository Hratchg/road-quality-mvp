---
phase: 05-cloud-deployment
researched: 2026-04-27
domain: Fly.io tri-app deployment + production hardening
confidence: HIGH
requirements: [REQ-prod-deploy]
---

# Phase 5: Cloud Deployment — Research

**Researched:** 2026-04-27
**Domain:** Fly.io tri-app deploy (db / backend / frontend) + production hardening (CORS, secrets, pool, /health, conn-leak, topology seed)
**Confidence:** HIGH (most facts verified against either Fly docs, psycopg2 source, or live Docker build)

## Summary

CONTEXT.md locks the deploy target (Fly.io, three apps), the DB image strategy (custom Dockerfile inheriting `postgis/postgis:16-3.4` + apt `postgresql-16-pgrouting`), the frontend strategy (separate nginx app, cross-origin to backend), and the CI strategy (GitHub Actions on push to `main`). This research confirms each of those decisions is implementable with current 2026 tooling AND surfaces three implementation specifics the planner must scope:

1. **`SimpleConnectionPool` is wrong for FastAPI.** psycopg2's `SimpleConnectionPool` is documented as "can't be shared across different threads." FastAPI runs `def` (sync) handlers in AnyIO's threadpool (default 40 workers). `ThreadedConnectionPool` is the thread-safe variant and is the correct choice. CONTEXT D-07 said `SimpleConnectionPool`; the planner should override to `ThreadedConnectionPool`. This is not a "user override" — it's a verified-bug fix that matches CONTEXT's underlying intent ("pooled connections that don't exhaust PG limit under concurrent load").

2. **The `postgis/postgis:16-3.4` image is Debian 11 bullseye, not bookworm**, and the `bullseye-pgdg` repo it pre-configures ships `postgresql-16-pgrouting` version **3.8.0**. This is newer than the project's documented "≥ 3.6" floor and backwards-compatible. The 3-line Dockerfile in CONTEXT.md builds and produces a working pgrouting extension (verified by `docker build` + `ls /usr/share/postgresql/16/extension/pgrouting*`).

3. **SC #7 and SC #8 are already done in the codebase.** `scripts/seed_data.py:148-151` already calls `pgr_createTopology(...clean := true)`. `backend/tests/test_migration_002.py:21-22` and `test_migration_003.py:25-26` already use `Path(__file__).resolve().parents[2] / "db" / "migrations" / ...`. The planner should verify CONTEXT.md's "needs to add" claims against the actual files BEFORE writing tasks. CONTEXT.md is stale on these two — it was written before commits 11ac4bd's fold-in landed in the codebase. The actionable Phase 5 work for SC #7 / SC #8 is not "add the line" but "verify the line stays present + add a regression test" (SC #7) and "run the suite inside the deployed container in CI to prove the path resolves" (SC #8).

**Primary recommendation:** Use one `fly.toml` per service in `deploy/{db,backend,frontend}/`. Use `ThreadedConnectionPool(2, 12)`. Use the verified `postgis/postgis:16-3.4` + apt path. Wire the GitHub Actions workflow with three jobs and `dorny/paths-filter` for path-conditional execution.

## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Cloud provider = Fly.io. Three apps: `<project>-db`, `<project>-backend`, `<project>-frontend`. NOT discussing other providers.
- **D-02:** DB hosting = custom Dockerfile inheriting `postgis/postgis:16-3.4` + `apt install postgresql-16-pgrouting`, mounted on a Fly volume. NOT discussing managed Postgres.
- **D-03:** Frontend = separate Fly app (nginx multi-stage). Cross-origin to backend. NOT bundling frontend into backend.
- **D-04:** Deploy automation = GitHub Actions on push to `main`. `FLY_API_TOKEN` as repo secret. NOT discussing other CI providers.
- **D-05:** Secrets via `fly secrets set`. Roster: `DATABASE_URL`, `AUTH_SIGNING_KEY`, `MAPILLARY_ACCESS_TOKEN`, `ALLOWED_ORIGINS`, `YOLO_MODEL_PATH`.
- **D-06:** CORS = `allow_origins=ALLOWED_ORIGINS.split(",")` env-driven. Hardcoded `["*"]` removed.
- **D-07:** Connection pool = psycopg2 pool, minconn=2, maxconn=10. **(Researcher confirms this should be `ThreadedConnectionPool`, not `SimpleConnectionPool` — see Pitfall 1 + Pattern 1.)**
- **D-08:** `/health` = `SELECT 1` probe; 200 OK on success, 503 on DB failure.
- **D-09:** Observability = Fly built-in only. No Sentry, no structured logs, no Prometheus.

### Claude's Discretion

- Researcher to confirm Fly fly.toml layout (per-service vs root with `--config`).
- Researcher to confirm internal hostname format (`.internal` vs `.flycast`).
- Researcher to confirm pgRouting apt version on bullseye-pgdg.
- Researcher to confirm Vite `import.meta.env` is build-time.
- Researcher to confirm Fly health check 503 = depool (not restart).
- Researcher to refine pool maxconn against FastAPI threadpool size.
- Researcher to confirm SSL mode requirement on Fly internal traffic.
- Researcher to recommend `[mounts]` vs Dockerfile `COPY` for db/migrations init.
- Pool wrapper API surface: matches existing `with get_connection() as conn` minimal-diff path.

### Deferred Ideas (OUT OF SCOPE)

- Multi-region, autoscaling, blue/green, canary
- Staging environment + promotion gate
- Custom domain + Let's Encrypt (use `*.fly.dev` for demo)
- Rate limiting (Cloudflare layer in Phase 6+ if abuse appears)
- Email-based password reset (Phase 4 explicit out-of-scope)
- Sentry / Datadog / structured logging
- `pg_dump` cron / PITR (Fly volume snapshots cover the need)
- Redis / distributed cache
- Mapillary ingest cron in production (operator runs manually)

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SC #1 | Documented deploy path brings up db + backend + frontend in non-local env | §2 (Fly artifacts), §6 (GitHub Actions YAML) |
| SC #2 | CORS restricted to deployed origin; no `allow_origins=["*"]` in prod | §3 Pattern 3 (env-driven CORS edit) |
| SC #3 | All secrets from cloud secret mechanism; no committed defaults in prod | §2 (`fly secrets set` recipe), §6 (`FLY_API_TOKEN` handling) |
| SC #4 | Frontend `VITE_API_URL` points at deployed backend; no localhost in bundle | §2 (frontend Dockerfile build-arg), §4 Pitfall 4 (build-time-vs-runtime) |
| SC #5 | `/health` reports DB reachability for LB probes | §3 Pattern 2 (/health update), §4 Pitfall 5 (503 = depool) |
| SC #6 | DB connections pooled; pool doesn't exhaust PG limit under burst | §3 Pattern 1 (`ThreadedConnectionPool` wrapper), §4 Pitfall 1 |
| SC #7 | Fresh deploy initializes routable graph via `pgr_createTopology` | §3 Pattern 5 + ASSUMPTION CHECK A1 (already in seed_data.py:148-151) |
| SC #8 | Migration tests run cleanly inside deployed `backend` container | §5 + ASSUMPTION CHECK A2 (already use `parents[2]` — needs CI gate, not edit) |
| SC #9 | `routes/routing.py` releases conn on exception (`contextlib.closing`) | §3 Pattern 4 (routing.py fix; folds into Pattern 1's pool wrapper) |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Origin-restricted CORS | API / Backend | — | CORS is a server-side preflight response; only the API tier can enforce it |
| TLS termination | Fly Edge / Proxy | — | Fly auto-issues `*.fly.dev` certs and terminates at the edge before traffic reaches our containers |
| Static asset serving | Frontend container (nginx) | Fly Edge (cache headers) | nginx is the conventional static server for Vite SPA bundles; Fly proxies HTTP through to it |
| API routing + business logic | API / Backend (FastAPI) | — | Same as M0 — no change |
| Persistent state (segments, scores, users, defects) | Database / Storage (Fly volume + Postgres) | — | All durable data lives in `road-quality-db` volume |
| Connection pooling | API / Backend (psycopg2 pool, in-process) | — | Single-process FastAPI, single-Fly-machine backend → in-process pool, not pgbouncer |
| Health probing | API / Backend (`/health` returns 200/503) | Fly Proxy (interprets status) | Fly's HTTP health check probes our endpoint; we own the SQL roundtrip + status code |
| Secret distribution | Fly platform (`fly secrets set`) | API / Backend (reads as env vars) | Secrets encrypted at rest, exposed as env vars at runtime |
| Build-time env var injection | CI (GitHub Actions `--build-arg`) | Frontend container (build stage `ARG`) | Vite bakes `import.meta.env.VITE_*` at build, not runtime |
| Deployment orchestration | CI (GitHub Actions) | Fly platform (`flyctl deploy`) | GH Actions on push to main; flyctl uploads + remote-builds |
| Backups | Fly platform (volume snapshots, daily, 5-day retention default) | — | M1 demo accepts "rebuild from migration + seed" if snapshot fails |

## Library Landscape

### Core (verified versions)

| Library | Version | Purpose | Source |
|---------|---------|---------|--------|
| `postgis/postgis:16-3.4` | tag `16-3.4` (Debian 11 bullseye base) | DB base image | [VERIFIED: docker run + cat /etc/os-release shows `Debian GNU/Linux 11 (bullseye)`] |
| `postgresql-16-pgrouting` | 3.8.0-1.pgdg110+1 | pgRouting on bullseye-pgdg | [VERIFIED: `curl https://apt.postgresql.org/.../bullseye-pgdg/.../Packages.gz \| gunzip` returns Version: 3.8.0] |
| `psycopg2-binary` | 2.9.12 | Already pinned in backend/requirements.txt → bump from 2.9.11 | [VERIFIED: `/tmp/rq-venv/bin/python -c "import psycopg2; print(psycopg2.__version__)"` → 2.9.12; current pin in repo is 2.9.11 — leave at 2.9.11 OR bump to 2.9.12, planner's call] |
| `node:20-alpine` | latest 20.x LTS | Frontend build stage base | [CITED: docker hub node official 20-alpine LTS through 2027-04] |
| `nginx:alpine` | latest 1.27.x stable | Frontend runtime base | [CITED: nginx official Alpine variant ~50MB] |
| `superfly/flyctl-actions/setup-flyctl` | `@master` (Fly recommends pinning to a release; 0.1.140+ as of 2026-04) | GH Actions flyctl setup | [CITED: https://github.com/superfly/flyctl-actions README — "pin flyctl to a specific version to avoid unexpected behavior in edge releases"] |
| `actions/checkout` | `@v4` | Git checkout | [CITED: Fly's official continuous-deployment doc uses `@v4`] |
| `dorny/paths-filter` | `@v3` | Path-conditional job execution | [CITED: github marketplace, current major = v3 as of 2026-04] |

### Supporting

| Library | Version | Purpose | Use Case |
|---------|---------|---------|----------|
| `psycopg2.pool.ThreadedConnectionPool` | (stdlib of psycopg2) | Thread-safe DB pool | FastAPI runs sync handlers in 40-thread anyio pool — must use ThreadedConnectionPool, not SimpleConnectionPool |

### Alternatives Considered

| Instead of | Could Use | Tradeoff | Why we don't |
|------------|-----------|----------|--------------|
| `SimpleConnectionPool` | `ThreadedConnectionPool` | None — strict superset, identical API | This IS the recommendation (see Pitfall 1) |
| `ThreadedConnectionPool` | `psycopg_pool.AsyncConnectionPool` (psycopg3) | Requires migrating from psycopg2 → psycopg3 (different API) | Out of scope for M1 per project constraints (psycopg2 with RealDictCursor locked) |
| Custom Dockerfile + Fly volume | Fly Managed Postgres | Saves `apt install postgresql-16-pgrouting` step | LOCKED OUT by D-02 (Managed Postgres has no pgRouting per CONTEXT) |
| nginx-alpine for frontend | bundle frontend INTO backend container | One Fly app instead of two | LOCKED OUT by D-03 (we WANT to prove CORS works for Phase 6) |
| `fly-pr-review-apps` for ephemeral preview deploys | Skip preview deploys | One PR demo URL per branch | Out of scope for M1 (no staging env) |
| `flyctl deploy` direct | `gh workflow run` triggered by main push | Same outcome, same ergonomics | Equivalent — already locked to `on: push: branches: [main]` |

**Installation (db Dockerfile):**

```dockerfile
FROM postgis/postgis:16-3.4
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-16-pgrouting \
 && rm -rf /var/lib/apt/lists/*
COPY db/migrations/*.sql /docker-entrypoint-initdb.d/
COPY db/init-pgrouting.sh /docker-entrypoint-initdb.d/00-init-pgrouting.sh
```

**Version verification command (for the planner's task):**

```bash
docker build -f deploy/db/Dockerfile -t road-quality-db:test .
docker run --rm road-quality-db:test sh -c "ls /usr/share/postgresql/16/extension/pgrouting--*.sql | tail -1"
# Expected: pgrouting--3.8.0.sql or newer
```

Verified result on 2026-04-27: `pgrouting--3.8.0.sql` and `pgrouting--*--3.8.0.sql` upgrade paths present.

## Fly Artifacts

### File layout (per CONTEXT D-02 + D-03 + D-04)

```
deploy/
├── db/
│   ├── Dockerfile         # postgis + pgrouting + migrations baked in
│   └── fly.toml
├── backend/
│   └── fly.toml           # references existing /backend/Dockerfile via [build].dockerfile
└── frontend/
    ├── Dockerfile         # NEW: multi-stage node:20-alpine → nginx:alpine
    ├── nginx.conf         # NEW: SPA fallback + cache headers
    └── fly.toml
.github/
└── workflows/
    └── deploy.yml         # 3 conditional jobs
```

**Why per-service subdirs:** Fly's official monorepo doc supports both `--config` from root and per-subdirectory layouts. Per-service is "cleaner for our tri-service shape" per CONTEXT D-01. The root-config pattern would require all three fly.toml files to live at the repo root with names like `fly.db.toml` / `fly.backend.toml` / `fly.frontend.toml`, which is noisier and clashes with the existing `backend/Dockerfile` and `frontend/Dockerfile` paths. [VERIFIED: Fly's monorepo doc — "Choose based on your needs: subdirectory approach for isolated app contexts"]

### `deploy/db/fly.toml` (skeleton)

```toml
app = "road-quality-db"
primary_region = "lax"  # closest to LA dataset

[build]
  dockerfile = "deploy/db/Dockerfile"

[env]
  POSTGRES_DB = "roadquality"
  POSTGRES_USER = "rq"
  # POSTGRES_PASSWORD set via `fly secrets set` (NOT here)

[[mounts]]
  source = "pgdata"
  destination = "/var/lib/postgresql/data"
  initial_size = "1gb"
  # Fly snapshots run daily, 5-day retention by default — no extra config needed

# Internal-only — no [http_service], no [[services.ports]] with public handlers
# Other Fly apps reach this via road-quality-db.flycast:5432 (or .internal:5432)

[[services]]
  internal_port = 5432
  protocol = "tcp"
  auto_stop_machines = false  # DB must stay up
  auto_start_machines = false
  min_machines_running = 1

  [[services.tcp_checks]]
    grace_period = "30s"
    interval = "15s"
    timeout = "5s"

[[vm]]
  size = "shared-cpu-1x"
  memory = "512mb"
```

**Note on hostname:** Per Fly docs (verified), other apps reach this at `road-quality-db.internal:5432` (basic IPv6 DNS) OR `road-quality-db.flycast:5432` (Fly Proxy with load balancing). For M1, **`.internal` is sufficient** — we don't need Fly Proxy's autostart/loadbalance for a single-machine DB. [VERIFIED: Fly app-connection-examples doc]

### `deploy/backend/fly.toml` (skeleton)

```toml
app = "road-quality-backend"
primary_region = "lax"

[build]
  dockerfile = "backend/Dockerfile"  # existing, no changes needed
  # build context will be the repo root if we run `fly deploy --config deploy/backend/fly.toml`

[env]
  # Non-secrets only here. Secrets (DATABASE_URL, AUTH_SIGNING_KEY, etc.) via `fly secrets set`.
  PYTHONUNBUFFERED = "1"

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = "stop"
  auto_start_machines = true
  min_machines_running = 0  # demo scale; can bump if cold-start hurts

  [[http_service.checks]]
    grace_period = "10s"
    interval = "30s"
    method = "GET"
    timeout = "5s"
    path = "/health"
    # 2xx = healthy, anything else = depool (NOT restart) — see Pitfall 5

[[vm]]
  size = "shared-cpu-1x"
  memory = "512mb"
```

**Build context note:** `fly.toml`'s `[build].dockerfile` is RELATIVE to the working directory passed to `fly deploy`. If we run from repo root via `fly deploy --config deploy/backend/fly.toml .`, the dockerfile path becomes `backend/Dockerfile` (relative to repo root). The GH Actions YAML below uses this exact pattern.

### `deploy/frontend/fly.toml` (skeleton)

```toml
app = "road-quality-frontend"
primary_region = "lax"

[build]
  dockerfile = "deploy/frontend/Dockerfile"
  [build.args]
    VITE_API_URL = "https://road-quality-backend.fly.dev"

[http_service]
  internal_port = 80
  force_https = true
  auto_stop_machines = "stop"
  auto_start_machines = true
  min_machines_running = 0

  [[http_service.checks]]
    grace_period = "5s"
    interval = "30s"
    method = "GET"
    timeout = "3s"
    path = "/"
    # nginx serves index.html on `/` — 200 OK = healthy

[[vm]]
  size = "shared-cpu-1x"
  memory = "256mb"
```

**Note on `[build.args]`:** Fly's TOML supports passing build args inline. Alternative: `flyctl deploy --build-arg VITE_API_URL=https://...` from CI. Inline is more reproducible (the value lives in git); CLI is more flexible for env-specific deploys. **Recommended: inline** for the demo since the backend URL is locked.

### `deploy/frontend/Dockerfile` (multi-stage)

```dockerfile
# Stage 1: build the Vite bundle
FROM node:20-alpine AS build
WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

# VITE_API_URL is consumed by import.meta.env.VITE_API_URL at BUILD TIME.
# Runtime env vars (e.g., docker run -e VITE_API_URL=...) DO NOT propagate
# into the bundle. See Pitfall 4.
ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL

RUN npm run build  # produces /app/dist

# Stage 2: serve the static bundle
FROM nginx:alpine
COPY deploy/frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

### `deploy/frontend/nginx.conf` (SPA fallback + cache headers)

```nginx
server {
    listen 80 default_server;
    listen [::]:80 default_server;

    root /usr/share/nginx/html;
    index index.html;

    # SPA fallback — react-router-dom routes resolve client-side
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Cache static assets aggressively (Vite hashes filenames)
    location ~* \.(js|css|woff2?|png|jpg|svg)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # Don't cache index.html — it points to the latest hashed bundles
    location = /index.html {
        add_header Cache-Control "no-cache, must-revalidate";
    }
}
```

### `fly secrets set` recipe

```bash
# DATABASE_URL — composed once, after db app is deployed
fly secrets set --app road-quality-backend \
  DATABASE_URL="postgres://rq:${PG_PASSWORD}@road-quality-db.internal:5432/roadquality"

# AUTH_SIGNING_KEY — generated locally, never in git
fly secrets set --app road-quality-backend \
  AUTH_SIGNING_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"

# CORS allowlist — must match the frontend Fly app's *.fly.dev URL
fly secrets set --app road-quality-backend \
  ALLOWED_ORIGINS="https://road-quality-frontend.fly.dev"

# DB-side: set POSTGRES_PASSWORD
fly secrets set --app road-quality-db \
  POSTGRES_PASSWORD="$PG_PASSWORD"

# YOLO_MODEL_PATH (optional — defaults to HF repo if unset)
fly secrets set --app road-quality-backend \
  YOLO_MODEL_PATH="keremberke/yolov8s-pothole-segmentation"
```

**Cross-app password sharing:** Fly Postgres apps DO NOT auto-expose their generated password to other apps' env. The pattern is: generate `$PG_PASSWORD` ONCE locally, set it as a secret on BOTH the db app (as `POSTGRES_PASSWORD`) and the backend app (embedded into `DATABASE_URL`). [VERIFIED: Fly community thread + connection-internal doc — "give the Postgres connection string to another Fly app by passing it as a secret"]

**SSL mode:** Fly internal `.internal` traffic runs over WireGuard (encrypted at the network layer). `sslmode=require` is **NOT required** in the `DATABASE_URL` for inter-app traffic. If we ever switch to `.flycast` or expose the DB publicly, sslmode=require should be added. [CITED: Fly private-networking doc — IPv6 6PN is encrypted]

## Implementation Patterns

### Pattern 1: `ThreadedConnectionPool` wrapper in `backend/app/db.py`

**What:** Replace single-connection `get_connection()` with a module-level pool + a context-manager wrapper that hands a connection to the caller and returns it on exit. Existing call sites (`with get_connection() as conn:` in segments.py, routing.py, auth.py) keep working with NO syntax changes — only the import semantics change (the function returns a context manager that wraps a pooled conn instead of a fresh socket).

**When to use:** Every backend DB call. This is the SC #6 implementation.

**Why ThreadedConnectionPool, not SimpleConnectionPool:** psycopg2 source documents `SimpleConnectionPool` as "A connection pool that can't be shared across different threads." `ThreadedConnectionPool` adds a `threading.Lock` around `getconn`/`putconn`. FastAPI runs `def` (sync) handlers via `anyio.to_thread.run_sync` in the **default 40-worker threadpool**. Two concurrent requests will hit `getconn` from different threads. `SimpleConnectionPool` will race or corrupt internal state under that contention. [VERIFIED: psycopg2 source — `inspect.getsource(pool.SimpleConnectionPool)` and `pool.ThreadedConnectionPool`; FastAPI/AnyIO threadpool size verified at https://anyio.readthedocs.io]

**Code:**

```python
# backend/app/db.py
import os
from contextlib import contextmanager
from typing import Iterator

import psycopg2
from psycopg2 import pool as _pool
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://rq:rqpass@localhost:5432/roadquality"
)

# Module-level pool — created once at import. ThreadedConnectionPool because
# FastAPI runs sync `def` handlers in AnyIO's threadpool (40 workers default);
# SimpleConnectionPool is documented as not thread-safe.
#
# minconn=2: keep 2 warm connections (tests, /health probe, demo traffic).
# maxconn=12: bounded by FastAPI threadpool (40) AND PG max_connections (100,
# leaving headroom for psql sessions, seed scripts, in-machine tooling). Burst
# above 12 will block on getconn (that's correct: graceful backpressure, not
# a "connection exhausted" 500).
_connection_pool: _pool.ThreadedConnectionPool | None = None


def _get_pool() -> _pool.ThreadedConnectionPool:
    """Lazy-init the pool. Lazy because tests may need to set DATABASE_URL
    via fixture BEFORE the pool tries to open connections."""
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = _pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=12,
            dsn=DATABASE_URL,
            cursor_factory=RealDictCursor,
        )
    return _connection_pool


@contextmanager
def get_connection() -> Iterator[psycopg2.extensions.connection]:
    """Borrow a pooled connection. Always returns it to the pool on exit,
    even if the caller raised — guards against the SC #9 leak pattern.

    Usage (unchanged from the pre-pool API — minimal-diff migration):
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(...)
    """
    p = _get_pool()
    conn = p.getconn()
    try:
        yield conn
    finally:
        # putconn does NOT auto-rollback — that's the caller's job via
        # `with conn:` (psycopg2's transaction context manager) or explicit
        # commit/rollback. We just guarantee the slot is released.
        p.putconn(conn)


def close_pool() -> None:
    """Optional teardown for tests / shutdown. Production rarely calls this."""
    global _connection_pool
    if _connection_pool is not None:
        _connection_pool.closeall()
        _connection_pool = None
```

**Migration cost at call sites:** ZERO. `with get_connection() as conn:` was already the pattern; the `as conn` now binds the pooled connection (psycopg2.extensions.connection) just like before. The only behavioral change is that the connection's underlying socket is reused across requests instead of opened fresh.

**One subtle change:** the existing code in `auth.py` uses `with closing(get_connection()) as conn, conn:`. With the new wrapper, `closing(...)` would call `.close()` on the context-manager object (which is wrong — we want putconn). The planner must update these three call sites in auth.py to drop `closing(...)` and use the simpler `with get_connection() as conn, conn:` pattern (or `with get_connection() as conn:` + explicit commit/rollback).

**Wait — there's a subtler issue.** `with conn:` (psycopg2's connection context manager) does `commit()` on success / `rollback()` on exception, BUT does NOT close the connection. With pooled connections, that's exactly what we want — keep the socket, hand it back via putconn. So `with get_connection() as conn, conn:` is the correct triple-pattern: outer manages pool slot, inner manages transaction.

### Pattern 2: `/health` DB-reachability probe

**What:** Replace the trivial `{"status": "ok"}` with a `SELECT 1` roundtrip. Returns 503 if the DB is unreachable so Fly's HTTP health check depools the instance. [VERIFIED: Fly health-checks doc — "HTTP checks expect a 2xx response"; non-2xx fails the check]

```python
# backend/app/routes/health.py
from fastapi import APIRouter, HTTPException, status
from app.db import get_connection

router = APIRouter()


@router.get("/health")
def health():
    """LB-probe-friendly health check.

    Returns 200 with {db: "reachable"} on success.
    Returns 503 with {db: "unreachable"} on any DB failure — Fly's HTTP
    health check treats non-2xx as unhealthy and depools the machine
    (does NOT restart it; see RESEARCH Pitfall 5).

    SC #5: not just `{status: ok}`. The shape preserves the existing
    `{status: ok}` key for client compat (PRD M0 contract); `db` field
    is additive.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return {"status": "ok", "db": "reachable"}
    except Exception:
        # Don't leak DB details (host, password fragment in error message)
        # to public probes. Log internally if needed; surface only the bit
        # the LB needs.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "unhealthy", "db": "unreachable"},
        )
```

**Note:** the old endpoint returned `{"status": "ok"}` — the new endpoint returns `{"status": "ok", "db": "reachable"}` (additive — no break). Existing test `backend/tests/test_health.py` will need updating to match.

### Pattern 3: env-driven CORS edit (`backend/app/main.py`)

**What:** Replace `allow_origins=["*"]` with `allow_origins=ALLOWED_ORIGINS.split(",")` reading from env. Surgical edit — lines 8-12 only.

```python
# backend/app/main.py
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import health, segments, routing, auth
from app.routes.cache_routes import router as cache_router

app = FastAPI(title="Road Quality Tracker", version="0.1.0")

# SC #2: CORS restricted to deployed frontend origin. Comma-separated allows
# adding a custom domain later without a code change. Empty string falls back
# to localhost dev origins so `docker compose up` keeps working.
_allowed_origins_raw = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000")
ALLOWED_ORIGINS = [o.strip() for o in _allowed_origins_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,  # OK with explicit origins; would FAIL with ["*"]
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(segments.router)
app.include_router(routing.router)
app.include_router(cache_router)
app.include_router(auth.router)
```

**Why `allow_credentials=True`:** Phase 4's JWT-in-localStorage pattern doesn't strictly require credentials (Authorization header isn't a credential per CORS spec). But keeping `allow_credentials=True` is the safer default — if Phase 6+ moves to cookie sessions, no CORS rewire needed. [VERIFIED: MDN CORS spec + FastAPI docs — `allow_origins=["*"]` + `allow_credentials=True` is invalid; explicit origins + `allow_credentials=True` is fine]

### Pattern 4: `routing.py` connection-leak fix (SC #9)

**Problem (current code, lines 59 + 73):**

```python
with get_connection() as conn:
    with conn.cursor() as cur:
        cur.execute(...)
```

With the OLD `get_connection()` (returns a fresh `psycopg2.connect()`), `with conn:` only commits/rollbacks the txn and does NOT close the socket — so the connection leaks on the exception path. With the NEW pooled `get_connection()` from Pattern 1, the OUTER `with` is the pool wrapper (which calls putconn on `__exit__`), so the slot ALWAYS releases. **Pattern 1's pool wrapper IS the SC #9 fix.** No separate `contextlib.closing()` needed at the call sites — the wrapper handles it.

**What still needs editing:** the `auth.py` call sites that use `with closing(get_connection()) as conn, conn:`. With the new context-manager-based `get_connection()`, that pattern doesn't compose (`closing()` expects a thing with a `.close()` method, but `get_connection()` now returns a context manager). The planner replaces those three sites with `with get_connection() as conn, conn:`.

**Compatibility surface:**

| File | Lines | Old pattern | New pattern | Action |
|------|-------|-------------|-------------|--------|
| `routing.py` | 59, 73 | `with get_connection() as conn:` | `with get_connection() as conn:` | **No change** — works as-is via Pattern 1 |
| `segments.py` | 38 | `with get_connection() as conn:` | `with get_connection() as conn:` | **No change** |
| `auth.py` | 63, 92, 118 | `with closing(get_connection()) as conn, conn:` | `with get_connection() as conn, conn:` | **Edit 3 sites — drop `closing()` import + usage** |

This is the smallest-diff migration consistent with CONTEXT D-07's intent.

### Pattern 5: `pgr_createTopology` already in seed_data.py (SC #7)

**Status:** ALREADY DONE. `scripts/seed_data.py:148-152` already calls `pgr_createTopology` after segment INSERT and IRI normalization, BEFORE the final count. The exact line:

```python
cur.execute("SELECT pgr_createTopology('road_segments', 0.0001, 'geom', 'id', clean := true)")
conn.commit()
```

`clean := true` means the function nukes existing `source`/`target` values and re-runs cleanly. Re-running on a populated DB does NOT double the topology — `clean := true` resets first. [VERIFIED: pgRouting docs — `pgr_createTopology(..., clean := true)` truncates `<table>_vertices_pgr` before rebuilding]

**Phase 5 actionable work for SC #7:** NOT "add the line." Instead:

1. **Verify the line stays present** — add a regression test that asserts `pgr_createTopology` is invoked when seed_data runs (could be a grep test, or an integration test that asserts `road_segments_vertices_pgr` is non-empty after seeding).
2. **Trigger seed_data on first deploy** — the planner needs a way to run `python scripts/seed_data.py` against the deployed DB. Options:
   - **Option A (recommended):** A one-shot `flyctl ssh console -C "python scripts/seed_data.py"` step in the GH Actions deploy workflow, gated by an env var `SEED_ON_DEPLOY=1` so it doesn't re-seed every push.
   - **Option B:** A `[deploy].release_command` in backend's fly.toml that runs `python scripts/seed_data.py` on every release. Wasteful.
   - **Option C:** Manual operator runbook step. Lowest automation but matches Phase 6's "operator runs ingest manually" posture.

Recommended: **Option A**. The planner should scope a small task: "Add a `seed: false` repo variable to GH Actions; manual `gh workflow run --input seed=true` triggers the seed."

**Folded fix expectation re-stated:** CONTEXT.md said "scripts/seed_data.py does NOT call pgr_createTopology — SC #7 fix is to append it." This is **stale** — the call IS present (commit 11ac4bd or earlier). The planner should verify by reading the file, then scope deploy-time invocation, not source edit.

### Pattern 6: `fetchone()[]` pattern under RealDictCursor

The existing routing.py uses `cur.fetchone()["id"]` — works because `db.py` passes `cursor_factory=RealDictCursor`. The pool wrapper preserves this (passed via `dsn=DATABASE_URL, cursor_factory=RealDictCursor`). No change needed.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Connection pooling | Custom dict-of-connections + threading.Lock | `psycopg2.pool.ThreadedConnectionPool` | Battle-tested, handles edge cases (idle eviction, broken connection detection via `closeall`) |
| TLS for `*.fly.dev` | Let's Encrypt acme client | Fly's auto-TLS | Fly issues + auto-renews certs for every app name; you literally don't configure it |
| Static SPA serving | Custom Python static server | nginx stable-alpine | nginx handles cache headers, gzip, range requests, SPA fallback in 10 lines of conf |
| GitHub Actions secret rotation | Custom rotation script | GitHub repo secrets + Fly's `fly tokens create deploy -x 999999h` | GH-native, no custom infra |
| Build-time env vars in Vite | Inline `<script>` tags + `window.__ENV` shim | Vite's `import.meta.env` + Docker `ARG` | Vite docs explicitly support this; bundlers fold the literal at build time |
| Daily DB backups | pg_dump cron | Fly volume snapshots (daily, 5-day retention default) | Fly does it for free, restores via `fly volumes snapshots create` |
| CORS preflight | Hand-written OPTIONS handler | FastAPI `CORSMiddleware` | M0 already uses it — just change the args |
| HTTP health check format | Custom JSON schema | Fly + standard 2xx/non-2xx convention | Fly's HTTP probe just checks status code; no body parsing |

**Key insight:** Phase 5 is mostly *configuration*, not code. The temptation to write custom orchestration scripts (build a custom deployer, write a backup cron) is misplaced — Fly's platform primitives + GH Actions cover ~95% of the deploy mechanics out of the box. Code edits are limited to: db.py (pool), main.py (CORS env), health.py (DB probe), auth.py (3 call sites).

## Common Pitfalls

### Pitfall 1: `SimpleConnectionPool` is not thread-safe

**What goes wrong:** Two concurrent FastAPI requests both hit `pool.getconn()` from different anyio threadpool workers. `SimpleConnectionPool`'s internal `_pool` list and `_used` dict are mutated without a lock. Result: same connection handed to two threads, OR a connection lost (never returned), OR a slot leaked. Symptoms range from intermittent "connection already closed" errors to deadlocks where the pool reports full but no transactions are running.

**Why it happens:** psycopg2 source explicitly documents `SimpleConnectionPool` as "A connection pool that can't be shared across different threads." FastAPI's default execution model for sync `def` handlers runs them in AnyIO's threadpool (40 workers by default); under burst the pool's internal state corrupts.

**How to avoid:** Use `psycopg2.pool.ThreadedConnectionPool` instead (same API, plus a `threading.Lock` around getconn/putconn). [VERIFIED: psycopg2 source inspected via `/tmp/rq-venv/bin/python -c "import inspect; from psycopg2 import pool; print(inspect.getsource(pool.ThreadedConnectionPool))"`]

**Warning signs:**
- Intermittent "connection in use" errors under load
- Apparent pool deadlock (all 10 slots "used" but no in-flight requests)
- `putconn` called twice with the same connection
- Crashes you can't reproduce with one client thread

### Pitfall 2: `with conn:` doesn't close the connection

**What goes wrong:** A developer reads `with psycopg2.connect(...) as conn:` and assumes the `with` block closes the connection on exit. It doesn't — psycopg2's connection context manager only manages the transaction (commit on success, rollback on exception). The socket leaks until GC.

**Why it happens:** The Python community convention "context managers close the resource" is violated by psycopg2's design choice (connection is reusable across multiple transactions). [VERIFIED: psycopg2 docs — "Note that the connection is not closed by the context and it can be used for several contexts."]

**How to avoid:**
- For a fresh `psycopg2.connect()`: wrap in `contextlib.closing(...)` so close() runs on exit. (This is what scripts/compute_scores.py and routes/auth.py already do — Phase 3+4 fix pattern.)
- For a pooled connection: rely on the pool wrapper's `try/finally putconn()` — closing happens implicitly when the connection is put back. (This is Pattern 1 above.)

**Warning signs:**
- `pg_stat_activity` shows growing connection count over time despite stable request load
- "FATAL: too many connections for role" under 50–100 concurrent users
- Idle connections accumulating in PG even after backend restart (until GC kicks in)

### Pitfall 3: `pgr_createTopology` is idempotent ONLY with `clean := true`

**What goes wrong:** Re-running `pgr_createTopology('road_segments', 0.0001, 'geom', 'id')` (no `clean :=`) on an already-topologized DB produces UNDEFINED behavior — vertex IDs may be re-assigned, breaking foreign references in other tables.

**How to avoid:** `clean := true` (already in seed_data.py:151). The pgRouting docs say `clean := true` truncates `<table>_vertices_pgr` and resets `source`/`target` to NULL before rebuilding. Re-running is safe. [VERIFIED: pgRouting 3.x docs]

**Warning signs:** route_requests with mysteriously bad routes after a re-seed; vertex count changing across re-seeds when it shouldn't.

### Pitfall 4: `import.meta.env.VITE_API_URL` is build-time, not runtime

**What goes wrong:** Operator builds the frontend image with `VITE_API_URL` unset, then sets `-e VITE_API_URL=https://...` at `docker run` / `flyctl secrets`. The bundle still has whatever value (or empty) was bundled at `npm run build`. The frontend hits `localhost:8000` in production. CORS errors everywhere.

**Why it happens:** Vite resolves `import.meta.env.VITE_*` at compile time and inlines the literal. Runtime env vars never reach the bundle. [VERIFIED: Vite docs — "Variables prefixed with VITE_ will be exposed in client-side source code after Vite bundling."]

**How to avoid:** Pass `VITE_API_URL` as a Docker build ARG (not env), via `[build.args]` in `deploy/frontend/fly.toml` OR `flyctl deploy --build-arg VITE_API_URL=https://...`. Verify by running `grep -r road-quality-backend.fly.dev /usr/share/nginx/html/assets/` inside the running container — the URL should appear in the JS bundle.

**Warning signs:**
- Browser network tab shows requests to `localhost:8000` from a deployed frontend
- `import.meta.env.VITE_API_URL` is `undefined` despite being set in fly secrets
- CORS preflight failures (because the actual origin is wrong)

### Pitfall 5: Fly's HTTP health check depools, but does NOT restart

**What goes wrong:** Operator assumes a 503 from `/health` will trigger Fly to restart the unhealthy machine. It will NOT — Fly's HTTP service check only **stops routing traffic to that machine** (depool). The machine keeps running indefinitely. If ALL machines are unhealthy, users get 503s from the proxy. No auto-recovery happens at the platform level.

**Why it happens:** Fly's design: HTTP health checks affect routing, not lifecycle. Restart-on-failure is a separate concept (machine checks, only run during deploys). [VERIFIED: Fly health-checks doc — "Machines won't automatically restart or stop due to failing their health checks, this needs to be done manually."]

**How to avoid (acceptable for M1):** Live with it. A transient DB hiccup → backend goes 503 → Fly depools → DB recovers → next probe succeeds → Fly re-pools. No restart needed. The only operator action is during a real outage: `fly machines restart` or `fly deploy` to force a new machine.

**Phase 6+ alternative:** Add an in-app `[[checks]]` (top-level, not under `[http_service]`) that Fly DOES use for restart logic. Out of scope for M1.

**Warning signs:** Stuck-unhealthy machine that never serves traffic but never dies either. Fix: `fly machines list` + `fly machines restart <id>`.

### Pitfall 6: Fly volume restore loses post-init migrations

**What goes wrong:** Operator restores a volume snapshot from N days ago. The restored volume already has the pgdata directory populated, so PG's docker-entrypoint-initdb.d scripts don't run (they only run when `$PGDATA` is empty). Migrations 002 / 003 / future Phase 6 migrations are lost from the new volume.

**Why it happens:** PG's init scripts are first-boot-only (the entrypoint checks `[ -z "$(ls -A $PGDATA)" ]` before running them). A restored volume is non-empty.

**How to avoid:** Treat migrations as "always re-applicable, idempotent SQL" (which they already are — `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`). On restore, manually run `flyctl ssh console -C "psql ... < /docker-entrypoint-initdb.d/02-schema.sql"` (or equivalent). The planner should add a `scripts/apply_migrations.py` shim that's idempotent and can be invoked from `flyctl ssh` post-restore. M2-territory; flag for now.

**Warning signs:** Fresh deploy on restored volume → backend can't find the `users` table (Phase 4 migration didn't apply).

### Pitfall 7: Dependent jobs in GH Actions silently skip on path-filter

**What goes wrong:** Workflow has `db → backend → frontend` with `needs:` chain. Operator does a frontend-only commit. Path filter skips `db` and `backend` jobs. `frontend` has `needs: backend` → frontend SKIPS too because its dependency was skipped. Frontend never deploys.

**Why it happens:** GitHub Actions' default behavior for `needs:` is "if any required job is skipped or failed, this job is skipped." The fix is `if: needs.backend.result != 'failure'` or `if: always()` on the dependent.

**How to avoid:** Use `dorny/paths-filter` to compute changed paths in a single setup job, then reference its outputs via `if: needs.changes.outputs.frontend == 'true'` on each downstream job. Don't chain `needs:` for path-conditional jobs — chain `needs:` only for ordering (e.g., db migration must complete before backend swaps to a new schema).

**See §6 GitHub Actions YAML below for the working pattern.**

### Pitfall 8: `fly secrets set` triggers a redeploy

**What goes wrong:** Operator updates `ALLOWED_ORIGINS` for a domain change. The set command implicitly redeploys the app (machines restart with new env). If the secret change happens DURING a planned deploy, two deploys race and one fails.

**Why it happens:** Fly's secrets are exposed as env vars at boot — changing them requires restarting the process.

**How to avoid:** Batch secret changes outside of deploy windows. Or use `fly secrets set --stage` (stages the secret without restarting; takes effect on next deploy). [CITED: fly secrets CLI docs]

**Warning signs:** Deploy fails with "machine in unrecoverable state" after a secret change races with a deploy.

### Pitfall 9: psycopg2 wrong package import (`psycopg2.pool` is NOT auto-imported)

**What goes wrong:** Developer writes `import psycopg2` then `psycopg2.pool.ThreadedConnectionPool(...)`. ImportError — `psycopg2.pool` is a separate submodule that must be explicitly imported.

**How to avoid:** Always `from psycopg2 import pool` or `import psycopg2.pool`. The Pattern 1 code uses `from psycopg2 import pool as _pool` to be explicit and prefix-disambiguate.

**Warning signs:** AttributeError at module import; `pool` member not found on `psycopg2`.

## Code Examples

### Module-level pool init (`backend/app/db.py`)

See Pattern 1 above for the complete code. Key invariants:
- Pool is module-level (created once per process)
- `get_connection()` is a `@contextmanager` that wraps getconn/putconn
- `cursor_factory=RealDictCursor` propagates to all connections (so `cur.fetchone()["id"]` keeps working)

### CORS env-driven setup (`backend/app/main.py`)

See Pattern 3 above. Key invariants:
- Default fallback to `http://localhost:3000` so docker-compose dev keeps working
- Strip + filter empty entries (handles trailing comma in `ALLOWED_ORIGINS=a,b,`)
- Keep `allow_credentials=True` (forward-safe for cookie sessions)

### `/health` DB probe (`backend/app/routes/health.py`)

See Pattern 2 above. Key invariants:
- 200 + `{status: "ok", db: "reachable"}` on success
- 503 + `{status: "unhealthy", db: "unreachable"}` on failure
- No DB error details leaked in the response (security: don't expose host/port/role)

### routing.py SC #9 fix

After Pattern 1 lands, **`routing.py` requires no edit** — the existing `with get_connection() as conn:` becomes the pool wrapper's `__enter__`/`__exit__`, which guarantees putconn-on-exception. The "wrap in `contextlib.closing()`" framing in CONTEXT.md was correct ONLY for the pre-pool world; after Pattern 1, the pool wrapper IS `closing()`'s job. **One regression test required:** mock `cur.execute` to raise mid-query, assert the pool's slot count is unchanged after the request resolves.

### Migration test path (`backend/tests/test_migration_002.py`, `test_migration_003.py`)

**Status: ALREADY USES THE CORRECT PATTERN.** Both files have:

```python
REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = REPO_ROOT / "db" / "migrations" / "002_mapillary_provenance.sql"
```

`parents[2]` = `backend/tests/<file>` → `backend/tests` → `backend` → `<repo_root>`. CORRECT. CONTEXT.md's "uses absolute `/db/migrations/`" claim is **stale**. The planner should verify by reading the actual file, then scope SC #8 work as "run these tests in CI inside the deployed container to prove the path resolves there too" — NOT as "edit the path."

**SC #8 in-container verification step (for the planner):**
```bash
docker compose exec backend pytest tests/test_migration_002.py tests/test_migration_003.py -m integration --tb=short
# Expected: all green, no collection errors. The integration marker means tests
# will skip if DB is unreachable, so they need the live DB up first.
```

## Test Patterns

### Test the pool wrapper without a live DB

**Goal:** Unit test that `get_connection()` returns a context manager that yields a conn and calls `putconn` on exit, including on exception.

```python
# backend/tests/test_db_pool.py
from unittest.mock import MagicMock, patch
import pytest
from app import db


def test_get_connection_calls_putconn_on_success():
    fake_conn = MagicMock()
    fake_pool = MagicMock()
    fake_pool.getconn.return_value = fake_conn
    with patch.object(db, "_get_pool", return_value=fake_pool):
        with db.get_connection() as conn:
            assert conn is fake_conn
            fake_pool.getconn.assert_called_once()
        fake_pool.putconn.assert_called_once_with(fake_conn)


def test_get_connection_calls_putconn_on_exception():
    """SC #9 invariant: the pool slot must release even if the caller raises."""
    fake_conn = MagicMock()
    fake_pool = MagicMock()
    fake_pool.getconn.return_value = fake_conn
    with patch.object(db, "_get_pool", return_value=fake_pool):
        with pytest.raises(ValueError):
            with db.get_connection() as conn:
                raise ValueError("boom mid-query")
        fake_pool.putconn.assert_called_once_with(fake_conn)
```

### Test `/health` 503 path

```python
# backend/tests/test_health.py — extend existing
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_ok_when_db_reachable():
    """Existing PRD M0 contract: /health returns 200 + {status: ok, ...}."""
    with patch("app.routes.health.get_connection") as mock_conn:
        mock_cm = mock_conn.return_value
        mock_cm.__enter__.return_value.cursor.return_value.__enter__.return_value.fetchone.return_value = (1,)
        r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["db"] == "reachable"


def test_health_503_when_db_unreachable():
    """SC #5: 503 on DB failure so Fly LB depools the instance."""
    import psycopg2
    with patch("app.routes.health.get_connection") as mock_conn:
        mock_conn.side_effect = psycopg2.OperationalError("connection refused")
        r = client.get("/health")
    assert r.status_code == 503
    body = r.json()
    assert body["detail"]["status"] == "unhealthy"
    assert body["detail"]["db"] == "unreachable"
```

### Test CORS env override

```python
# backend/tests/test_cors.py
import importlib
import os
from fastapi.testclient import TestClient


def test_cors_reads_allowed_origins_env(monkeypatch):
    """SC #2: ALLOWED_ORIGINS env splits to allow_origins list."""
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://a.example.com,https://b.example.com")
    # Re-import to re-read env at module level
    from app import main
    importlib.reload(main)
    assert "https://a.example.com" in main.ALLOWED_ORIGINS
    assert "https://b.example.com" in main.ALLOWED_ORIGINS
    assert "*" not in main.ALLOWED_ORIGINS


def test_cors_rejects_disallowed_origin(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://allowed.fly.dev")
    from app import main
    importlib.reload(main)
    client = TestClient(main.app)
    r = client.options(
        "/health",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    # FastAPI/CORSMiddleware: disallowed origin → no `access-control-allow-origin` header
    assert r.headers.get("access-control-allow-origin") != "https://evil.example.com"
```

## GitHub Actions YAML

Full deploy.yml skeleton with 3 jobs, path-filter, and dependency chain:

```yaml
# .github/workflows/deploy.yml
name: Deploy to Fly

on:
  push:
    branches: [main]
  workflow_dispatch:
    inputs:
      seed:
        description: 'Run seed_data.py against deployed DB after deploy'
        required: false
        default: 'false'

concurrency:
  group: deploy-prod
  cancel-in-progress: false

jobs:
  changes:
    name: Detect changed paths
    runs-on: ubuntu-latest
    outputs:
      db: ${{ steps.filter.outputs.db }}
      backend: ${{ steps.filter.outputs.backend }}
      frontend: ${{ steps.filter.outputs.frontend }}
    steps:
      - uses: actions/checkout@v4
      - uses: dorny/paths-filter@v3
        id: filter
        with:
          filters: |
            db:
              - 'deploy/db/**'
              - 'db/**'
            backend:
              - 'backend/**'
              - 'deploy/backend/**'
            frontend:
              - 'frontend/**'
              - 'deploy/frontend/**'

  test:
    name: Pre-deploy CI gate
    runs-on: ubuntu-latest
    needs: changes
    # Only run tests if backend changed (db migrations land via backend's release_command)
    if: needs.changes.outputs.backend == 'true' || needs.changes.outputs.db == 'true'
    services:
      postgres:
        image: postgis/postgis:16-3.4
        env:
          POSTGRES_DB: roadquality
          POSTGRES_USER: rq
          POSTGRES_PASSWORD: rqpass
        ports: ['5432:5432']
        options: >-
          --health-cmd pg_isready --health-interval 5s --health-timeout 5s --health-retries 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - name: Install pgRouting
        run: |
          docker exec ${{ job.services.postgres.id }} sh -c 'apt-get update && apt-get install -y postgresql-16-pgrouting'
          docker exec ${{ job.services.postgres.id }} sh -c 'psql -U rq -d roadquality -c "CREATE EXTENSION IF NOT EXISTS pgrouting;"'
      - name: Apply migrations
        env:
          PGPASSWORD: rqpass
        run: |
          for f in db/migrations/*.sql; do psql -h localhost -U rq -d roadquality -f "$f"; done
      - name: Install backend deps
        working-directory: backend
        run: pip install -r requirements.txt
      - name: Run pytest (incl. SC #8 migration tests)
        working-directory: backend
        env:
          DATABASE_URL: postgresql://rq:rqpass@localhost:5432/roadquality
          AUTH_SIGNING_KEY: test_key_for_ci_only_padding_padding_padding
        run: pytest -v -m "not integration or integration"  # all tests; SC #8 path test runs here

  deploy-db:
    name: Deploy DB
    needs: [changes, test]
    if: |
      always() &&
      needs.changes.outputs.db == 'true' &&
      (needs.test.result == 'success' || needs.test.result == 'skipped')
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: superfly/flyctl-actions/setup-flyctl@master
      - run: flyctl deploy --remote-only --config deploy/db/fly.toml --app road-quality-db
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}

  deploy-backend:
    name: Deploy backend
    needs: [changes, test, deploy-db]
    if: |
      always() &&
      (needs.changes.outputs.backend == 'true' || needs.changes.outputs.db == 'true') &&
      (needs.test.result == 'success' || needs.test.result == 'skipped') &&
      (needs.deploy-db.result == 'success' || needs.deploy-db.result == 'skipped')
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: superfly/flyctl-actions/setup-flyctl@master
      - run: flyctl deploy --remote-only --config deploy/backend/fly.toml --app road-quality-backend
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}

  deploy-frontend:
    name: Deploy frontend
    needs: [changes, deploy-backend]
    if: |
      always() &&
      needs.changes.outputs.frontend == 'true' &&
      (needs.deploy-backend.result == 'success' || needs.deploy-backend.result == 'skipped')
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: superfly/flyctl-actions/setup-flyctl@master
      - run: flyctl deploy --remote-only --config deploy/frontend/fly.toml --app road-quality-frontend
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}

  seed-on-demand:
    name: Seed DB (manual trigger only)
    needs: deploy-backend
    if: github.event.inputs.seed == 'true'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: superfly/flyctl-actions/setup-flyctl@master
      - name: Run seed_data.py inside backend container
        run: flyctl ssh console --app road-quality-backend -C "python scripts/seed_data.py"
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
```

**Key design choices:**

- `concurrency: deploy-prod / cancel-in-progress: false` — only one deploy at a time; if a second push comes in, queue it (don't cancel the in-flight deploy mid-DB-migration)
- `dorny/paths-filter@v3` — single source of truth for "did X change"; downstream jobs branch on the outputs
- `if: always() && ...` — defeats GH Actions' default skip-cascade so that frontend can deploy independently of an unchanged backend (Pitfall 7)
- `--remote-only` on every `flyctl deploy` — builds happen on Fly's infra, not the GH runner (faster, no Docker Hub rate limits, no need for Buildx setup)
- Pre-deploy `test` job — runs the full backend pytest suite including SC #8 migration tests INSIDE a Postgres+pgRouting service container. This is the SC #8 CI gate: if `Path(__file__).resolve().parents[2]` resolves wrong, this job fails and blocks deploy.
- `seed-on-demand` job — manual `gh workflow run --ref main -f seed=true` triggers the seed; doesn't run on every push

**Token setup (one-time, operator):**
```bash
fly tokens create deploy -x 999999h --name "github-actions-deploy"
# Copy the output, add as `FLY_API_TOKEN` repo secret in GitHub Settings → Secrets → Actions
```

## Migration Init Flow

### Recommended: Bake migrations into the DB image

```dockerfile
# deploy/db/Dockerfile
FROM postgis/postgis:16-3.4

RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-16-pgrouting \
 && rm -rf /var/lib/apt/lists/*

# Copy migrations to PG's auto-init dir. Files in /docker-entrypoint-initdb.d/
# run in lexicographic order on FIRST boot of an EMPTY $PGDATA volume.
COPY db/init-pgrouting.sh /docker-entrypoint-initdb.d/00-init-pgrouting.sh
COPY db/migrations/001_initial.sql /docker-entrypoint-initdb.d/01-schema.sql
COPY db/migrations/002_mapillary_provenance.sql /docker-entrypoint-initdb.d/02-mapillary.sql
COPY db/migrations/003_users.sql /docker-entrypoint-initdb.d/03-users.sql

# Future Phase 6+ migrations get appended here via new `04-*.sql` etc.
```

### How Fly volume + PG init script interact

| Scenario | Volume state | Init scripts run? | Migrations applied? |
|----------|--------------|-------------------|---------------------|
| First-ever deploy | EMPTY (new Fly volume) | YES | YES — fresh schema |
| Subsequent deploy | populated | NO (pgdata not empty) | NO — need manual `psql` |
| Volume snapshot restore | populated (restored from N days ago) | NO | NO — Pitfall 6 applies |
| `fly volumes destroy` + redeploy | empty (recreated) | YES | YES — but data lost |

**Idempotency:** All migration files use `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` (verified by reading 001_initial.sql, 002_mapillary_provenance.sql, 003_users.sql). Manual re-application is safe.

**Recommended posture for M1:** Accept that "schema changes need a manual `flyctl ssh console -C 'psql ... < new_migration.sql'` step." Document this in README's deploy section. Phase 6+ can add a `scripts/apply_migrations.py` shim that's auto-invoked by backend's `[deploy].release_command`.

### Alternatives considered (rejected for M1)

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **A) Bake into image (recommended)** | Idempotent for first boot; one source of truth; no extra infra | Doesn't auto-apply on subsequent deploys | ✅ Use this |
| B) Mount `db/migrations/` via Fly `[mounts]` | "Live" — edit migration on the volume | Mounts are for persistent DATA, not config; abuse of the primitive | ❌ Reject |
| C) `flyctl ssh` + `psql` per release | Explicit; matches operator-runs-ingest pattern | Manual; easy to forget | ❌ Phase 6 territory |
| D) Auto-run via `[deploy].release_command` on backend | Automatic | Backend would need psql + write access to db; cross-app coupling | ❌ Add complexity later |

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `psycopg2.SimpleConnectionPool` | `psycopg2.ThreadedConnectionPool` (or async psycopg3 pool) | psycopg2 docs have been clear on this since 2.7 (~2017); the FastAPI ecosystem is migrating to psycopg3 + AsyncConnectionPool | M1 stays on psycopg2 (locked); use ThreadedConnectionPool |
| Hardcoded `allow_origins=["*"]` | Env-driven `ALLOWED_ORIGINS.split(",")` | OWASP guidance (forever); FastAPI tutorial recommends explicit origins | Required for prod, M1 closes this |
| `psycopg2.connect()` per request | Module-level pool | psycopg2 1.x onwards | M1 closes this |
| Trivial `/health` | DB-roundtrip `/health` | Standard LB convention | M1 closes this |
| Bullseye-pgdg pgRouting 3.4 (vanilla bookworm) | Bullseye-pgdg pgRouting 3.8 | apt.postgresql.org keeps a more current pgRouting than vanilla Debian | We get 3.8 for free |

**Deprecated/outdated:**
- **`postgresql-16-pgrouting` ≥ 3.6 floor:** Project requirement met by 3.8.0 from bullseye-pgdg. No tracking needed.
- **`docker compose` v1 syntax:** Already on v2 (no `version:` key in docker-compose.yml). Fine.
- **`uvicorn --reload` in prod Dockerfile:** Existing `backend/Dockerfile` line 10 has `--reload`. Fine for dev, BUT it forks a reloader child + spawns workers. In prod we want `--reload` REMOVED. **Planner action item: verify whether to override the CMD in fly.toml's `[processes]` or edit backend/Dockerfile.** Recommended: leave Dockerfile alone (dev parity matters); add a `[processes].web` override in `deploy/backend/fly.toml`:
  ```toml
  [processes]
    web = "uvicorn app.main:app --host 0.0.0.0 --port 8000"
  ```

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `scripts/seed_data.py` already calls `pgr_createTopology` | §3 Pattern 5 | LOW — verified by reading file at lines 148-152; CONTEXT.md was stale on this |
| A2 | `test_migration_002.py` and `test_migration_003.py` already use `parents[2]` | §5 + §3 Pattern 6 | LOW — verified by reading both files at lines 21-22 and 25-26 |
| A3 | `dorny/paths-filter@v3` is the current major version | §1 Library Landscape | LOW — recent searches confirm v3 is current as of 2026-04 |
| A4 | `flyctl-actions/setup-flyctl@master` is the recommended pin (NOT a release tag) | §1 + §6 | MEDIUM — Fly's own README says "pin to a release version" but their continuous-deployment doc uses `@master`. Both work; release-pin is safer for reproducibility |
| A5 | `auto_stop_machines = "stop"` syntax is current | §2 fly.toml skeletons | LOW — confirmed in Fly's reference/configuration page |
| A6 | Fly volume snapshots default to 5-day retention with no extra config | §2 db/fly.toml | LOW — verified in Fly's volumes/snapshots doc |
| A7 | `*.flycast` and `*.internal` both work; `.internal` is sufficient for M1 | §2 secrets recipe | LOW — confirmed in Fly's connecting-internal doc |
| A8 | `sslmode=require` is NOT required on Fly internal traffic | §2 secrets recipe | MEDIUM — Fly docs say private network is encrypted (WireGuard); we don't add `sslmode=require`, but if Fly tightens defaults, the `DATABASE_URL` may need it. Verify via `psql` SSH'd into a backend machine on first deploy |
| A9 | `nginx:alpine` SPA fallback `try_files $uri $uri/ /index.html` works for react-router v7 | §2 nginx.conf | LOW — standard SPA pattern; react-router-dom v7 client-side routing is unaffected |
| A10 | `[build.args]` in fly.toml is supported and forwards to Docker `ARG` | §2 frontend fly.toml | LOW — confirmed in Fly's reference/configuration |
| A11 | Build context for `flyctl deploy --config deploy/backend/fly.toml` is the directory containing the toml, NOT repo root | §2 backend fly.toml | **MEDIUM — if wrong, the `dockerfile = "backend/Dockerfile"` path won't resolve.** Verify with a dry-run `fly deploy --build-only` early in plan execution. Workaround: pass `flyctl deploy /path/to/repo/root --config deploy/backend/fly.toml` to set build context explicitly |
| A12 | psycopg2's `RealDictCursor` propagates through ThreadedConnectionPool's `cursor_factory` arg | §3 Pattern 1 | LOW — same kwargs forwarding as `psycopg2.connect`; verified by reading psycopg2 source |
| A13 | The frontend's `import.meta.env.VITE_API_URL` is the only place the API URL leaks; no other hardcoded `localhost` references | §3 Pattern (no separate pattern) | LOW — verified by reading `frontend/src/api.ts:3` (`const API_BASE = import.meta.env.VITE_API_URL \|\| "/api"`); planner should grep frontend/ for "localhost" to be safe |

**A1, A2 are CRITICAL for the planner:** they invalidate two of CONTEXT.md's "fold-in" claims. The planner should NOT scope tasks for "add pgr_createTopology to seed_data.py" (already there) or "fix migration test path bug" (already fixed). The actual SC #7 / SC #8 work is regression-test-and-CI-gate, NOT source-edit.

## Open Questions

1. **Should we run the seed automatically on first deploy, or require a manual trigger?**
   - What we know: `scripts/seed_data.py` takes ~5 minutes (downloads OSMnx data). It's heavy — we don't want it on every deploy.
   - What's unclear: For M1, will operators DEFINITELY want a fresh seed at deploy time, or do they prefer to run it manually after verifying the DB came up?
   - Recommendation: **Manual via `gh workflow run -f seed=true`** (per §6 YAML). Safer default.

2. **Does the operator need a `release_command` to apply Phase 6+ migrations?**
   - What we know: Migration files use `CREATE TABLE IF NOT EXISTS` (idempotent).
   - What's unclear: Should `[deploy].release_command = "python scripts/apply_migrations.py"` be added to `deploy/backend/fly.toml` now (proactive) or in Phase 6 (reactive)?
   - Recommendation: **Defer to Phase 6+.** M1 has migrations 001-003 already baked into the db image's `/docker-entrypoint-initdb.d/`. The hypothetical migration 004 doesn't exist yet.

3. **Is `min_machines_running = 0` acceptable for the demo?**
   - What we know: Fly's auto-stop will hibernate idle machines, saving ~$5/mo. Cold start is ~2-5s.
   - What's unclear: Is a 2-5s cold start acceptable for the public demo's first-load UX?
   - Recommendation: **Start with 0 (cheap), bump to 1 if Phase 6 reveals UX hit.** This is reversible via `flyctl scale count 1 --app road-quality-backend`.

4. **Where do we set the FastAPI threadpool size?**
   - What we know: AnyIO defaults to 40. With `maxconn=12` on the pool, requests #13-40 will block on `getconn`.
   - What's unclear: Is 40 too high (oversubscribes the pool), or fine (pool is cheap; threads at sub-pool count just queue gracefully)?
   - Recommendation: **Don't tune the threadpool size.** With 12 connections and 40 threads, threads 13-40 will block on `getconn` — that IS the backpressure we want. PG won't be flooded. If the demo reveals queue depth issues, bump `maxconn=20` (still well under PG's 100 limit).

5. **Should the GH Actions test job apply migrations from `db/migrations/` or use the deploy/db/Dockerfile?**
   - What we know: §6 YAML applies them via `psql` loops in the test job. This is a duplicate of the Dockerfile's `COPY` — risk of drift.
   - What's unclear: Worth refactoring to "test job builds the same Dockerfile as deploy"?
   - Recommendation: **Defer.** The current loop is 3 lines and the migration files are version-controlled — drift risk is low. If it bites in Phase 6, refactor.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `flyctl` CLI | Local hotfix deploys, operator runbook | OPERATOR-LOCAL — not on dev machine necessarily | — | GH Actions deploys cover the happy path |
| `gh` CLI | Trigger `seed=true` workflow_dispatch | OPERATOR-LOCAL | — | Web UI: GitHub Actions tab → "Run workflow" |
| Docker | Build images locally for testing | ✓ | 29.4.1 (verified) | Push to a branch, let GH Actions build |
| `python3.12` | Run pytest, scripts | ✓ | 3.12 (verified via /tmp/rq-venv) | — |
| `psql` client | Manual migration application post-restore | OPERATOR-LOCAL — likely yes (Postgres .app or Homebrew) | — | `flyctl ssh console -C "psql ..."` from any machine |
| `fly` Postgres app | Custom DB image already covers this | N/A — we run our own | — | — |
| GitHub repo + Actions enabled | Deploys | ASSUMED ✓ — repo exists | — | Manual `flyctl deploy` from operator machine |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:**
- `flyctl` on the operator machine — for hotfix deploys outside CI. Install via `curl -L https://fly.io/install.sh | sh`.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.3.4 (existing) |
| Config file | `backend/tests/conftest.py` (existing; defines `db_conn`, `db_available`, `client`, `authed_client` fixtures) |
| Quick run command | `cd backend && pytest -x` |
| Full suite command | `cd backend && pytest` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SC #1 | Fly apps deploy + reachable | smoke (manual) | `curl https://road-quality-backend.fly.dev/health` post-deploy | ❌ Wave 0 (manual UAT step in plan) |
| SC #2 | CORS rejects disallowed origin | unit | `cd backend && pytest tests/test_cors.py -x` | ❌ Wave 0 — `test_cors.py` to be created |
| SC #3 | Secrets sourced from env, no committed defaults | unit (grep test) | `cd backend && pytest tests/test_secrets_no_defaults.py -x` | ❌ Wave 0 — new file checks `os.environ.get(...) is not None` for prod env vars |
| SC #4 | Frontend bundle has deployed backend URL baked in | smoke | `docker run --rm <fe-img> grep -r road-quality-backend.fly.dev /usr/share/nginx/html/` | ❌ Wave 0 (manual UAT) |
| SC #5 | `/health` returns 503 on DB failure | unit | `cd backend && pytest tests/test_health.py::test_health_503_when_db_unreachable -x` | ❌ Wave 0 — extend existing test_health.py |
| SC #6 | Pool releases slot on success and exception | unit | `cd backend && pytest tests/test_db_pool.py -x` | ❌ Wave 0 — `test_db_pool.py` to be created |
| SC #7 | Topology built on fresh DB | integration | `cd backend && pytest tests/test_seed_topology.py -m integration -x` | ❌ Wave 0 — new test asserts `road_segments_vertices_pgr` non-empty after seeding |
| SC #8 | Migration tests resolve paths via project root inside container | integration | `docker compose exec backend pytest tests/test_migration_002.py tests/test_migration_003.py -m integration` | ✅ Test files exist with correct paths (verified) — Wave 0 task is the CI gate that runs them |
| SC #9 | routing.py `/route` releases pool slot on exception | integration | `cd backend && pytest tests/test_routing_pool_release.py -m integration -x` | ❌ Wave 0 — new test mocks pgr_ksp to raise, asserts pool currsize unchanged |

### Sampling Rate

- **Per task commit:** `cd backend && pytest -x` (fail-fast unit suite)
- **Per wave merge:** `cd backend && pytest -m "not integration"` (full unit) + `docker compose up -d && cd backend && pytest -m integration` (full integration; live DB required)
- **Phase gate:** Full suite green inside the deployed container (`docker compose exec backend pytest`) before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `backend/tests/test_db_pool.py` — covers SC #6 (Pattern 1 invariants — getconn/putconn lifecycle)
- [ ] `backend/tests/test_health.py` — extend with 503 path covering SC #5
- [ ] `backend/tests/test_cors.py` — covers SC #2 (env-driven origins)
- [ ] `backend/tests/test_secrets_no_defaults.py` — covers SC #3 (env vars must be set, not defaulted)
- [ ] `backend/tests/test_seed_topology.py` — covers SC #7 (post-seed `road_segments_vertices_pgr` non-empty)
- [ ] `backend/tests/test_routing_pool_release.py` — covers SC #9 (pool currsize unchanged after route handler raises)
- [ ] CI gate (`.github/workflows/deploy.yml`) — runs `test_migration_00{2,3}.py` to satisfy SC #8 (the test file itself is unchanged, but proving it runs in CI is the SC)
- [ ] Smoke UAT runbook — covers SC #1 + SC #4 (manual; documented in README's Deploy section)

## Security Domain

`security_enforcement` is not explicitly disabled in `.planning/config.json` — assume enabled.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes (Phase 4 already shipped) | pwdlib argon2id (existing) |
| V3 Session Management | yes | JWT HS256 with 32-byte signing key (existing); rotation = redeploy with new `AUTH_SIGNING_KEY` |
| V4 Access Control | yes | FastAPI `Depends(get_current_user_id)` on `/route`, `/cache/*` (existing) |
| V5 Input Validation | yes | Pydantic v2 on all bodies (existing); psycopg2 parameterized queries (existing) |
| V6 Cryptography | yes | TLS auto-provisioned by Fly at `*.fly.dev`; HMAC-SHA256 for JWT |
| V8 Data Protection | yes | DB password from `fly secrets`, never committed; Mapillary token same |
| V14 Configuration | yes | `.env` git-ignored; `.env.example` committed; SC #3 enforces no defaults in prod |

### Known Threat Patterns for Fly + FastAPI + Postgres

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| CORS misconfiguration → CSRF | Tampering / Information Disclosure | `ALLOWED_ORIGINS` env-driven (Pattern 3) |
| DB credential exposure via git | Information Disclosure | `fly secrets set`; never commit `.env` (already enforced) |
| JWT signing key in source | Spoofing | `AUTH_SIGNING_KEY` from env, fail-fast on absence (Phase 4 RESEARCH §8) |
| Connection pool exhaustion DoS | Denial of Service | `maxconn=12` cap, blocks gracefully via getconn lock |
| Volume snapshot exfiltration | Information Disclosure | Fly snapshots are tied to org; only org members can `fly volumes snapshots restore` |
| `sslmode=disable` on public DB | Information Disclosure | DB is internal-only (`.internal`); never exposed publicly. If we ever expose, force `sslmode=require` |
| `*.fly.dev` subdomain takeover | Spoofing | Fly retains the subdomain even after app deletion until manually released; standard cloud-CNAME hygiene |
| Health endpoint info leak | Information Disclosure | Pattern 2 returns a STATIC error string; doesn't include exception details |

## Sources

### Primary (HIGH confidence)

- `psycopg2.pool` source via `inspect.getsource(...)` on `/tmp/rq-venv/bin/python` — verified `SimpleConnectionPool` thread-unsafe, `ThreadedConnectionPool` uses `threading.Lock`
- `psycopg2.__version__` on host venv → 2.9.12; `fastapi.__version__` → 0.136.1
- `docker run --rm postgis/postgis:16-3.4 cat /etc/os-release` → "Debian GNU/Linux 11 (bullseye)"
- `docker run --rm postgis/postgis:16-3.4 cat /etc/apt/sources.list.d/pgdg.list` → "deb apt.postgresql.org bullseye-pgdg main 16"
- `curl https://apt.postgresql.org/pub/repos/apt/dists/bullseye-pgdg/main/binary-amd64/Packages.gz | gunzip | grep postgresql-16-pgrouting` → Version 3.8.0-1.pgdg110+1
- `docker build -f /tmp/test-db.Dockerfile` (3-line Dockerfile from CONTEXT.md) → built successfully on linux/amd64
- `docker run --rm test-pgrouting ls /usr/share/postgresql/16/extension/pgrouting*` → confirms pgrouting--3.8.0.sql installed
- [Fly health-checks doc](https://fly.io/docs/reference/health-checks/) — "Machines won't automatically restart or stop due to failing their health checks"
- [Fly volumes snapshots doc](https://fly.io/docs/volumes/snapshots/) — daily snapshots, 5-day default retention
- [Fly monorepo doc](https://fly.io/docs/launch/monorepo/) — both per-subdir and root-with-config patterns supported
- [Fly continuous deployment doc](https://fly.io/docs/launch/continuous-deployment-with-github-actions/) — `actions/checkout@v4` + `superfly/flyctl-actions/setup-flyctl@master` + `FLY_API_TOKEN` from secrets
- [Fly app-connection-examples](https://fly.io/docs/postgres/connecting/app-connection-examples/) — DATABASE_URL `.internal` hostname pattern verified
- [Vite env-and-mode doc](https://vite.dev/guide/env-and-mode) — VITE_* vars are build-time, baked into bundle
- [psycopg2 connection docs](https://www.psycopg.org/docs/connection.html) — "the connection is not closed by the context"
- Repo file inspection: `scripts/seed_data.py:148-152` (pgr_createTopology), `backend/tests/test_migration_00{2,3}.py:21-26` (parents[2] path)

### Secondary (MEDIUM confidence)

- [psycopg2 pool docs](https://www.psycopg.org/docs/pool.html) — SimpleConnectionPool vs ThreadedConnectionPool descriptions
- [Fly process groups doc](https://fly.io/docs/launch/processes/) — process groups require shared image (rules out for tri-app)
- [GitHub Actions paths-filter](https://github.com/dorny/paths-filter) — v3 current major
- [superfly/flyctl-actions README](https://github.com/superfly/flyctl-actions/blob/master/README.md) — pin guidance + FLY_API_TOKEN env pattern
- [Fly community: flycast vs internal](https://community.fly.io/t/flycast-for-postgres/10628) — both work, .internal is simpler

### Tertiary (LOW confidence — flagged for validation)

- A4 (`@master` vs release tag for setup-flyctl) — Fly's own docs are inconsistent; either works
- A11 (build context resolution for `--config deploy/.../fly.toml`) — verify on first deploy with `--build-only`

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every version pin verified by tool (docker run, curl apt repo, psycopg2 inspect)
- Architecture (3-app split, fly.toml shape): HIGH — Fly docs explicitly support this layout
- Pool wrapper (Pattern 1): HIGH — based on psycopg2 source + FastAPI threadpool docs; corrects CONTEXT.md D-07's `SimpleConnectionPool` bug
- /health 503 = depool (Pitfall 5): HIGH — Fly docs clear on this
- Vite build-time arg (Pitfall 4): HIGH — Vite docs unambiguous
- pgr_createTopology already in seed_data.py (A1): HIGH — read the file, line 151 is unambiguous
- Migration test paths already correct (A2): HIGH — read the files, parents[2] resolves correctly from `backend/tests/<file>` → repo root
- GitHub Actions YAML: MEDIUM — composed from documented patterns; specific job-skip behavior with paths-filter requires real-CI verification (A3, plus the `if: always() && ...` pattern is well-documented but not bulletproof)
- Build context resolution (A11): MEDIUM — Fly docs are ambiguous on whether `flyctl deploy --config deploy/backend/fly.toml` uses `.` or the toml's directory as build context; recommended early dry-run

**Research date:** 2026-04-27
**Valid until:** 2026-05-27 (30-day window — Fly's GA APIs are stable; longer if no Phase 5 plan changes land)
