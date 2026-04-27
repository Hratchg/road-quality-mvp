---
status: partial
phase: 05-cloud-deployment
source: [05-VERIFICATION.md]
started: 2026-04-27T20:00:00Z
updated: 2026-04-27T20:00:00Z
---

## Current Test

[awaiting human testing — all 5 items require Fly account auth + first deploy from main]

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
