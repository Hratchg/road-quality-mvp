---
phase: 05-cloud-deployment
reviewed: 2026-04-25T00:00:00Z
depth: standard
files_reviewed: 21
files_reviewed_list:
  - backend/app/db.py
  - backend/app/main.py
  - backend/app/routes/auth.py
  - backend/app/routes/health.py
  - backend/tests/test_db_pool.py
  - backend/tests/test_routing_pool_release.py
  - backend/tests/test_cors.py
  - backend/tests/test_health.py
  - backend/tests/test_seed_topology.py
  - backend/tests/test_secrets_no_defaults.py
  - deploy/db/Dockerfile
  - deploy/db/fly.toml
  - deploy/db/test-build.sh
  - deploy/backend/fly.toml
  - deploy/frontend/Dockerfile
  - deploy/frontend/fly.toml
  - deploy/frontend/nginx.conf
  - deploy/frontend/test-build.sh
  - .github/workflows/deploy.yml
  - .env.example
  - README.md
findings:
  critical: 2
  warning: 5
  info: 6
  total: 13
status: issues_found
---

# Phase 5: Code Review Report

**Reviewed:** 2026-04-25T00:00:00Z
**Depth:** standard
**Files Reviewed:** 21
**Status:** issues_found

## Summary

Phase 5 introduces a clean, well-documented Fly.io deployment posture. The
backend pool wrapper (`db.py`), CORS allowlist (`main.py`), health probe
(`health.py`), and the test gates around them (`test_db_pool.py`,
`test_routing_pool_release.py`, `test_cors.py`, `test_health.py`,
`test_seed_topology.py`, `test_secrets_no_defaults.py`) are correctness-
focused and well-aligned with the SC #2 / #5 / #6 / #7 / #9 contracts
declared in the phase's PLAN docs. The Fly artifacts (`deploy/db/*`,
`deploy/frontend/*`, `nginx.conf`) are mostly sound and clearly separate
non-secrets from secrets.

Two Critical issues block a successful first deploy:

1. **`backend/Dockerfile` build-context mismatch** — `deploy/backend/fly.toml`
   uses repo-root build context, but the existing `backend/Dockerfile` is
   written for `backend/`-rooted context (`COPY requirements.txt .` resolves
   to `<repo>/requirements.txt`, which does not exist). The first
   `flyctl deploy` for the backend will fail at `COPY requirements.txt`.
2. **CI bypass on test failure** — `deploy-frontend` only depends on
   `deploy-backend` (not on `test`). When `test` fails, `deploy-backend` is
   `skipped`, which makes `deploy-frontend.if`'s `skipped`-fallback evaluate
   to true and the frontend deploys regardless of test results. Same shape
   defect for `seed-on-demand`.

Five Warnings cover hardening gaps (no security headers in `nginx.conf`,
fragile psycopg2 private-API access in a regression test, README's
documented `/health` shape that disagrees with the new endpoint contract,
default `AUTH_SIGNING_KEY` typo in `test:` step, and a missing
`needs.test` linkage in `seed-on-demand`). Six Info items are minor
documentation/consistency notes.

No regression of Phase 4's auth model. No `release_command` (deferred per
RESEARCH Open Q2). No `--reload` in production CMD. No new ORM imports.
No CORS regression. SC #3's secret-roster scan looks defensible.

## Critical Issues

### CR-01: Backend Dockerfile build-context mismatch will fail first deploy

**File:** `deploy/backend/fly.toml:7`, `backend/Dockerfile:5`
**Issue:** `deploy/backend/fly.toml` declares `dockerfile = "backend/Dockerfile"`
and the workflow runs `flyctl deploy --remote-only --config deploy/backend/fly.toml --app road-quality-backend .`
from the repo root. The trailing `.` makes the build context the repo root.
But the existing `backend/Dockerfile` was written for a `backend/`-rooted
context (as `docker-compose.yml`'s `build: ./backend` uses). Specifically:

- `backend/Dockerfile:5` — `COPY requirements.txt .` resolves to
  `<repo_root>/requirements.txt`, which does not exist (the file lives at
  `<repo_root>/backend/requirements.txt`). The build will fail at this
  step on Fly's remote builder with "COPY failed: file not found".
- `backend/Dockerfile:8` — `COPY . .` would copy the entire repo (frontend,
  data, node_modules, .git, .planning, deploy/, db/, scripts/, etc.) into
  the backend image, bloating it from ~150 MB to multiple GB and exposing
  unrelated artifacts.

Verification: `ls /Users/hratchghanime/road-quality-mvp/requirements.txt`
returns "No such file or directory". `grep "build:" docker-compose.yml`
shows `build: ./backend` — the only context this Dockerfile has ever been
built against.

This contradicts CONTEXT D-01's claim that the Dockerfile is unchanged
AND build-context is repo-root: only one of those can be true.

**Fix:** Two options, pick one:

Option A (preferred — minimal Dockerfile change, repo-root context kept):

```dockerfile
# backend/Dockerfile
FROM python:3.12-slim
WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .
COPY scripts/ /scripts/   # so flyctl ssh -C "python scripts/seed_data.py" works
COPY db/migrations/ /db/migrations/

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

Option B (keep Dockerfile unchanged, fix the deploy invocation):

```toml
# deploy/backend/fly.toml — point Fly at backend/ as the build context
[build]
  dockerfile = "Dockerfile"   # relative to the working directory below
```

```yaml
# .github/workflows/deploy.yml — pass backend/ as the working directory
- run: flyctl deploy --remote-only --config deploy/backend/fly.toml --app road-quality-backend backend
```

Note: Option B breaks `seed-on-demand` because `scripts/` and
`db/migrations/` won't be in the image. Option A is the durable fix — it
also makes the `scripts/seed_data.py` invocation in `seed-on-demand`
actually work, and limits the image to just `backend/` + `scripts/` +
`db/migrations/`. Add a `.dockerignore` to keep image size bounded.

### CR-02: deploy-frontend and seed-on-demand bypass test failures

**File:** `.github/workflows/deploy.yml:167-178, 180-194`
**Issue:** `deploy-frontend` and `seed-on-demand` declare `needs:` and `if:`
in a way that lets them run when the `test` job FAILS:

```yaml
deploy-frontend:
  needs: [changes, deploy-backend]
  if: |
    always() &&
    needs.changes.outputs.frontend == 'true' &&
    (needs.deploy-backend.result == 'success' || needs.deploy-backend.result == 'skipped')
```

When `test` fails, `deploy-backend.if` resolves to `false` (because
`needs.test.result == 'success' || needs.test.result == 'skipped'` is false),
so `deploy-backend` is `skipped`. That makes
`needs.deploy-backend.result == 'skipped'` true in `deploy-frontend.if`,
which then runs **even though the test gate failed**. This silently
ships untested frontend changes to prod.

Same shape on `seed-on-demand` — it only depends on `deploy-backend`, not
on `test`, so a `test` failure cascades through `deploy-backend` (skipped)
and then `seed-on-demand` runs against an unhealthy or stale backend.

This is the inverse of the Pitfall 7 problem the workflow comment
mentions defending against — the `skipped`-fallback is too permissive.

**Fix:** Add `test` as an explicit dependency and gate on its result:

```yaml
deploy-frontend:
  name: Deploy frontend
  needs: [changes, test, deploy-backend]
  if: |
    always() &&
    needs.changes.outputs.frontend == 'true' &&
    (needs.test.result == 'success' || needs.test.result == 'skipped') &&
    (needs.deploy-backend.result == 'success' || needs.deploy-backend.result == 'skipped')

seed-on-demand:
  name: Seed DB (manual trigger only — SC #7 deploy-time bootstrap)
  needs: [test, deploy-backend]
  if: |
    always() &&
    github.event.inputs.seed == 'true' &&
    (needs.test.result == 'success' || needs.test.result == 'skipped') &&
    (needs.deploy-backend.result == 'success' || needs.deploy-backend.result == 'skipped')
```

A failed `test` now correctly blocks frontend deploys and seed runs.
`deploy-db` and `deploy-backend` already have this gate; the asymmetry
in `deploy-frontend` and `seed-on-demand` is the bug.

## Warnings

### WR-01: nginx.conf has no security headers

**File:** `deploy/frontend/nginx.conf:14-42`
**Issue:** The nginx server block emits no `X-Frame-Options`,
`X-Content-Type-Options`, `Referrer-Policy`, or HSTS header. Even though
Fly auto-issues TLS and enforces HTTPS at the edge (via `force_https =
true`), the application is missing the lightweight defense-in-depth
headers that a publicly exposed SPA should carry. M1 demo posture is OK
without a full CSP, but the cheap headers belong in scope.

**Fix:**

```nginx
server {
    listen 80 default_server;
    listen [::]:80 default_server;

    root /usr/share/nginx/html;
    index index.html;

    # Cheap defense-in-depth headers — applied to every response.
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    # HSTS is also enforced at the Fly edge via force_https, but a duplicate
    # in the origin response is harmless and useful for direct-IP probes.
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    location / {
        try_files $uri $uri/ /index.html;
    }
    # ...rest unchanged
}
```

Note: nginx's `add_header` is NOT inherited into `location` blocks once
ANY `add_header` is set inside that block. Because the existing config
has `add_header Cache-Control ...` inside `/index.html` and `*.{js,css,...}`
location blocks, those blocks will silently lose the security headers.
Use the `always` flag and either repeat the headers in each location or
move the cache-control headers up into the `location /` block. The
canonical fix is the `include /etc/nginx/conf.d/security-headers.conf;`
trick.

### WR-02: test_routing_pool_release.py reaches into psycopg2 private API

**File:** `backend/tests/test_routing_pool_release.py:40,86`
**Issue:** The test reads `pool._used` (a psycopg2-internal attribute) to
count borrowed connections. While this is the only practical way to
observe pool occupancy without instrumenting the wrapper, it is fragile:
psycopg2 makes no API stability guarantee on `_used`, and a future minor
upgrade or a switch to psycopg2-binary could break the gate silently.

**Fix:** Either (a) accept the fragility and add a comment explaining the
trade-off (currently undocumented), or (b) wrap the pool with a thin
counter that exposes a public `borrowed_count()` method:

```python
# backend/app/db.py
class _PoolWithCounter:
    def __init__(self, inner): self._inner = inner; self._borrowed = 0
    def getconn(self): self._borrowed += 1; return self._inner.getconn()
    def putconn(self, conn): self._borrowed -= 1; return self._inner.putconn(conn)
    def borrowed_count(self) -> int: return self._borrowed
    # ...delegate other methods
```

Option (a) is acceptable for M1. Add a comment near the `_used` access:

```python
# Accessing pool._used is reaching into psycopg2's private API; if a future
# psycopg2 upgrade renames or removes this attribute, this gate will fail
# loud at AttributeError, not silently. That's an acceptable trade-off for
# the SC #9 leak-detection precision.
baseline_used = len(pool._used)
```

### WR-03: README's GET /health response shape is stale

**File:** `README.md:93-94`
**Issue:** README documents:

```
### GET /health
Returns `{"status": "ok"}`
```

The Phase 5 endpoint actually returns `{"status": "ok", "db": "reachable"}`
on success and `{"detail": {"status": "unhealthy", "db": "unreachable"}}` /
503 on DB failure. The PRD M0 contract is preserved (additive `db` field),
but operators and external monitors reading the README will not know about
the additive field or the 503-on-DB-down behavior.

**Fix:**

```markdown
### GET /health

LB-probe-friendly DB-reachability check.

- Success: `200` + `{"status": "ok", "db": "reachable"}`
- DB unreachable: `503` + `{"detail": {"status": "unhealthy", "db": "unreachable"}}`

Fly's HTTP health check treats non-2xx as unhealthy and depools the
machine (does not restart it), so the 503 path is the right code for a
transient DB hiccup.
```

### WR-04: AUTH_SIGNING_KEY in CI test step is shorter than 32 chars but happens to pass via padding

**File:** `.github/workflows/deploy.yml:121`
**Issue:** The CI test step sets:

```yaml
AUTH_SIGNING_KEY: test_key_for_ci_only_padding_padding_padding
```

This string is 44 chars, so it passes the `>= 32 chars` fail-fast in
`backend/app/auth/tokens.py`. Acceptable. But the env-var inline assignment
in YAML is positional — if a future reviewer trims the literal (e.g., to
match a code-quote's 80-char limit), the CI will break in a confusing way
because the validation is at runtime in tokens.py.

**Fix:** Document the 32-char floor inline:

```yaml
env:
  DATABASE_URL: postgresql://rq:rqpass@localhost:5432/roadquality
  # AUTH_SIGNING_KEY: must be >= 32 chars per backend/app/auth/tokens.py.
  # This is a test-only value; production uses `fly secrets set`.
  AUTH_SIGNING_KEY: test_key_for_ci_only_padding_padding_padding
```

Low priority; flag as Warning rather than Info because of the indirect
runtime-validation chain.

### WR-05: dorny/paths-filter behavior on first push / workflow_dispatch

**File:** `.github/workflows/deploy.yml:56-68`
**Issue:** `dorny/paths-filter@v3` resolves changed paths by comparing
against a base ref. On `push to main`, base = previous commit on main.
On `workflow_dispatch`, the action falls back to comparing against the
default branch — which on a manual `gh workflow run deploy.yml -f seed=true`
typically yields ALL outputs as `false` (no paths "changed" since main).

That is exactly what we want for a "seed-only" manual run: the deploy
jobs all skip, and only `seed-on-demand` runs. But on the FIRST push to
main, paths-filter has no base ref, and behavior depends on the action
version's heuristic. The plan does not address this edge case.

**Fix:** Test the workflow on a fresh-clone scratch repo before relying on
it for the real-deploy bootstrap, OR explicitly set a base ref:

```yaml
- uses: dorny/paths-filter@v3
  id: filter
  with:
    base: ${{ github.event.before || 'HEAD~1' }}
    filters: |
      ...
```

For the v1 demo this is acceptable — operators run the initial deploy
manually via `flyctl deploy` from their workstation per README. Flag as
Warning because the workflow's deploy-on-first-push narrative may not
match the actual `paths-filter` behavior.

## Info

### IN-01: Inconsistent transaction-context style between routes

**File:** `backend/app/routes/auth.py:63,95,121`, `backend/app/routes/routing.py:59,73`
**Issue:** `auth.py` consistently uses the double-context pattern
`with get_connection() as conn, conn:` (outer = pool slot release, inner =
psycopg2 commit/rollback), but `routing.py:59-66` uses
`with get_connection() as conn: ... conn.commit()` and relies on an
explicit `conn.commit()` call. Both are correct — the `with conn:` block
auto-commits on success, the explicit `commit()` does the same — but the
mixed style is harder to reason about during code review.

**Fix:** Pick one style and use it everywhere. The double-context is
slightly more defensive (auto-rollback on exception), so converging
routing.py would be the safer move:

```python
# routing.py:59
with get_connection() as conn, conn:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO route_requests (params_json) VALUES (%s)",
            (json.dumps(req.model_dump()),),
        )
# the inner `, conn:` commits on success / rollbacks on exception
```

### IN-02: README "Deploy" curl verification omits CORS smoke check

**File:** `README.md:305-316`
**Issue:** The deploy verification section runs `/health` and a `HEAD /` on
the frontend, but does not verify that SC #2 (CORS) is actually
enforcing. Operators will not know if `ALLOWED_ORIGINS` was set wrong
until a frontend user hits the missing CORS header. This is the SC #2
contract — worth a one-line preflight check.

**Fix:**

```bash
# Verify CORS preflight from the frontend origin is allowed (SC #2)
curl -I -H "Origin: https://road-quality-frontend.fly.dev" \
  -H "Access-Control-Request-Method: POST" \
  -X OPTIONS https://road-quality-backend.fly.dev/route
# Expected: 200 OK with access-control-allow-origin: https://road-quality-frontend.fly.dev
```

### IN-03: deploy/db/Dockerfile pins postgis/postgis:16-3.4 without digest

**File:** `deploy/db/Dockerfile:21`
**Issue:** `FROM postgis/postgis:16-3.4` is a moving tag — the upstream
image is rebuilt periodically with new bullseye package versions. A
deterministic pin would survive into Phase 6 hardening.

**Fix:** Pin to a digest so a future `docker build --pull` doesn't silently
upgrade the base:

```dockerfile
FROM postgis/postgis:16-3.4@sha256:<verified-digest>
```

Acceptable to defer to Phase 6+; flag as Info because the M1 demo posture
explicitly tolerates moving tags.

### IN-04: deploy/db/fly.toml has no [http_service] but defines [[services]] — verify this matches Fly's Postgres pattern

**File:** `deploy/db/fly.toml:33-43`
**Issue:** The fly.toml uses `[[services]]` (TCP-only) instead of
`[http_service]`, which is correct for an internal-only Postgres app.
However, `auto_stop_machines = false` plus `[[services.tcp_checks]]`
without an explicit health-check command means Fly assumes a TCP-connect
to port 5432 is healthy. That works for Postgres because it accepts TCP
on 5432 from the moment it boots, but the comment in the file doesn't
make this assumption explicit.

**Fix:** Add a one-line comment clarifying that the TCP probe is enough
for Postgres:

```toml
[[services.tcp_checks]]
  grace_period = "30s"
  interval = "15s"
  timeout = "5s"
  # TCP-connect probe is sufficient for Postgres — pg_isready is overkill
  # for liveness; we want the LB to depool only when the listener is gone,
  # not when the DB is briefly busy.
```

### IN-05: test_secrets_no_defaults.py is missing a negative test for the scanner

**File:** `backend/tests/test_secrets_no_defaults.py:67-100`
**Issue:** The test scans for hardcoded secrets in deploy/*.toml but does
not include a negative case proving the scanner trips when a secret IS
hardcoded. Without this, a future refactor that breaks the regex (e.g.,
strips trailing whitespace or comment-comparison) could silently make the
test always pass.

**Fix:** Add a parametrized negative case with an inline tmp_path fixture:

```python
def test_scanner_trips_on_injected_hardcoded_secret(tmp_path):
    """Negative gate: the scanner MUST detect a hardcoded secret value."""
    bad_toml = tmp_path / "fake_fly.toml"
    bad_toml.write_text(
        '[env]\n'
        'AUTH_SIGNING_KEY = "leaked_secret_for_test_only"\n'
    )
    text = bad_toml.read_text()
    found = any(
        line.strip().startswith(f"{k} =")
        for line in text.splitlines()
        for k in SECRET_KEYS
    )
    assert found, "scanner regex must trip on AUTH_SIGNING_KEY = '...'"
```

This locks the regex's correctness, not just its application.

### IN-06: test_seed_topology.py rebuilds DSN string-by-string from db_conn.dsn

**File:** `backend/tests/test_seed_topology.py:61-70`
**Issue:** The test parses `db_conn.dsn` (a keyword string like
`host=localhost port=5432 dbname=...`) into a dict and reconstructs a
postgresql:// URL. This is fragile — psycopg2's DSN format may include
extra keys (sslmode, application_name, options) that the manual parser
silently drops. The reconstruction also hardcodes fallback defaults
that mask configuration bugs.

**Fix:** Use the `DATABASE_URL` env var directly when present, falling
back to the manual reconstruction only as a last resort:

```python
db_url = os.environ.get("DATABASE_URL")
if not db_url:
    # Fall back to dsn parsing for legacy fixtures
    dsn_kv = dict(token.split("=", 1) for token in db_conn.dsn.split() if "=" in token)
    db_url = (
        f"postgresql://{dsn_kv.get('user', 'rq')}:{dsn_kv.get('password', 'rqpass')}@"
        f"{dsn_kv.get('host', 'localhost')}:{dsn_kv.get('port', '5432')}/"
        f"{dsn_kv.get('dbname', 'roadquality')}"
    )
env = os.environ.copy()
env["DATABASE_URL"] = db_url
```

CI sets `DATABASE_URL` directly (workflow line 120), so this short-circuits
the parser in the path that actually runs in CI.

---

_Reviewed: 2026-04-25T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
