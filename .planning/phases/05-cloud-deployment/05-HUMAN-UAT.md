---
status: partial
phase: 05-cloud-deployment
source: [05-VERIFICATION.md]
started: 2026-04-27T20:00:00Z
updated: 2026-04-27T23:05:00Z
---

## Current Test

[paused mid-walkthrough at 78% context, 2026-04-27T23:05Z; resume with frontend deploy + topology seed + browser-based CORS/VITE_API_URL]

## Live Deploy State (as of pause)

Manually deployed via `flyctl deploy --remote-only` (NOT via GH Actions yet — master→main rename + push deferred to next session).

Apps created (all `personal` org, region `lax`):
  - road-quality-db        → started, /health (TCP) passing, machine 918544e6c9e568
  - road-quality-backend   → started, /health (HTTP) passing, machine 91854462ad05d8
  - road-quality-frontend  → CREATED but NOT yet deployed

Volume: `rq_db` (1 GB, lax/zone a376, encrypted, daily snapshots default 5d retention)

Secrets staged + active:
  - road-quality-db: POSTGRES_PASSWORD
  - road-quality-backend: AUTH_SIGNING_KEY, MAPILLARY_ACCESS_TOKEN, ALLOWED_ORIGINS, DATABASE_URL

Live URLs:
  - https://road-quality-backend.fly.dev/health     → 200 {"status":"ok","db":"reachable"}  (SC #5 ✓)
  - https://road-quality-backend.fly.dev/segments   → 200 (empty bbox)  (SC #2 partial)
  - https://road-quality-backend.fly.dev/route      → 401 "Not authenticated" (auth gate working)
  - https://road-quality-frontend.fly.dev           → NOT YET DEPLOYED

## Bugs Found and Fixed Inline (Phase 5 plan/CONTEXT defects)

1. `deploy/db/fly.toml [env].PGDATA` — Fly volume `lost+found` breaks initdb. Added `PGDATA=/var/lib/postgresql/data/pgdata`. Commit `bca06a6`.
2. `deploy/db/fly-entrypoint.sh` — Volume mounts as root, postgres user can't mkdir. New chown wrapper. Commit `bca06a6`.
3. `deploy/db/fly.toml [[mounts]].source` — was `pgdata`, volume was `rq_db`. Aligned. Commit `bca06a6`.
4. `deploy/db/fly.toml [build].dockerfile` — was `deploy/db/Dockerfile`, flyctl resolves relative to toml dir → doubled path. Now `Dockerfile`. Commit `bca06a6`.
5. `deploy/backend/fly.toml [build].dockerfile` — was `Dockerfile`, looked for `deploy/backend/Dockerfile`. Now `../../backend/Dockerfile`. Commit `fdd8fd4`.
6. DATABASE_URL secret — RESEARCH/CONTEXT D-05 said `<app>.flycast`, but inter-app private DNS is `<app>.internal`. Plus had wrong user/db (`postgres/postgres` vs project's `rq/roadquality`). Rotated via `fly secrets set` (not committed — secrets only).
7. flyctl 0.4.40 first-deploy chicken-and-egg ("Verifying app config" needs ≥1 existing machine to validate against). Worked around by `cd backend/` first or by accepting first-attempt failure that creates the machine then re-deploying.

These should be folded into Phase 5.1 polish or a CONTEXT/RESEARCH amendment.

## Tests

### 1. First production deploy from main
expected: |
  Operator runs the README ## Deploy bootstrap (one-time):
    flyctl auth login
    flyctl apps create road-quality-db
    flyctl apps create road-quality-backend
    flyctl apps create road-quality-frontend
    flyctl volumes create rq_db --app road-quality-db --region <r> --size 1
    flyctl secrets set --app road-quality-backend AUTH_SIGNING_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
    flyctl secrets set --app road-quality-backend MAPILLARY_ACCESS_TOKEN=<token>
    flyctl secrets set --app road-quality-backend ALLOWED_ORIGINS=https://road-quality-frontend.fly.dev
    flyctl secrets set --app road-quality-backend DATABASE_URL=postgres://postgres:<gen>@road-quality-db.flycast:5432/postgres?sslmode=require
    flyctl secrets set --app road-quality-db POSTGRES_PASSWORD=<gen>

  Then push to main → GitHub Actions workflow runs.

  Pass criteria:
    - All 3 deploy jobs (deploy-db, deploy-backend, deploy-frontend) finish green in the Actions tab
    - `flyctl status -a road-quality-{db,backend,frontend}` shows each app running
    - Backend logs (`flyctl logs -a road-quality-backend`) show no startup errors
    - Frontend logs show nginx serving on port 8080 (or wherever fly.toml binds)
result: [pending]

### 2. Bootstrap topology after first deploy
expected: |
  Operator runs:
    gh workflow run deploy.yml --ref main -f seed=true

  Wait ~5 minutes. Confirm via:
    flyctl ssh console -a road-quality-db -C "psql -U postgres -c 'SELECT COUNT(*) FROM road_segments_vertices_pgr'"

  Pass criteria:
    - Workflow's seed-on-demand job exits 0
    - Vertex count > 0 (typically 50k-75k for the LA region)
result: [pending]

### 3. Live CORS preflight from deployed frontend
expected: |
  In a browser at https://road-quality-frontend.fly.dev, open DevTools Network panel.
  Click "Find Best Route" — modal opens. Sign in (or click "Try as demo").
  Observe the OPTIONS preflight to /route.

  Pass criteria:
    - OPTIONS /route returns 200 with Access-Control-Allow-Origin: https://road-quality-frontend.fly.dev
    - NOT `*` and NOT missing
    - No CORS errors in console
    - POST /route succeeds (200 with route response)
result: [pending]

### 4. Live /health probe behavior (200 + 503 paths)
expected: |
  Happy path:
    curl -s -o /dev/null -w "%{http_code}\n" https://road-quality-backend.fly.dev/health
    # → 200
    curl https://road-quality-backend.fly.dev/health
    # → {"status": "ok", "db": "reachable"}

  Optional 503 verification (requires temporarily breaking DB connectivity):
    flyctl machines stop -a road-quality-db <id>
    sleep 5
    curl -s -o /dev/null -w "%{http_code}\n" https://road-quality-backend.fly.dev/health
    # → 503 (Fly LB depools the backend; you may need to hit the machine directly via flycast)
    flyctl machines start -a road-quality-db <id>

  Pass criteria:
    - 200 with {db: reachable} on happy path
    - 503 with {db: unreachable} when DB is unavailable (no error message leak)
    - Fly's LB does NOT auto-restart the backend on transient 503 (depool only — confirm via `flyctl logs`)
result: [pending]

### 5. End-to-end VITE_API_URL browser fetch verification
expected: |
  In the deployed frontend's browser DevTools, Network tab, observe the actual fetch URL.

  Pass criteria:
    - Map View loads segments from `https://road-quality-backend.fly.dev/segments?bbox=...` (NOT localhost)
    - Sign-in modal posts to `https://road-quality-backend.fly.dev/auth/login` (NOT localhost)
    - Route Finder posts to `https://road-quality-backend.fly.dev/route` (NOT localhost)
    - View bundle source: search for "localhost" — should not appear in any non-comment code path
result: [pending]

## Summary

total: 5
passed: 0
issues: 0
pending: 5
skipped: 0
blocked: 0

## Gaps
