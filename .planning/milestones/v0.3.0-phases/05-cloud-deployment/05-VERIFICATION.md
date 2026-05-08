---
phase: 05-cloud-deployment
verified: 2026-04-25T00:00:00Z
status: human_needed
score: 9/9 must-haves verified (artifact-level); live-deploy verification requires operator
overrides_applied: 0
re_verification: false
human_verification:
  - test: "First production deploy from main"
    expected: "flyctl auth login + (one-time) flyctl apps create road-quality-{db,backend,frontend} + fly secrets set per README step 3 + push to main → all 3 Fly apps come up; deploy-db → deploy-backend → deploy-frontend cascade succeeds"
    why_human: "Requires authenticated Fly account, real Fly API token in GH Actions secrets, and live cloud resources. The artifact path is verified mechanically; the live execution must be the operator's first post-merge action."
  - test: "Seed deployed DB topology (SC #7 deploy-time)"
    expected: "gh workflow run deploy.yml --ref main -f seed=true → seed-on-demand job opens flyctl proxy 5432:5432, runs scripts/seed_data.py from GH runner host venv → road_segments populated, road_segments_vertices_pgr populated"
    why_human: "Requires PG_PASSWORD GH secret + live road-quality-db Fly app. The script's pgr_createTopology call is statically locked by test_seed_topology.py; the in-CI integration test (heavy ~5min, OSMnx download) is configured but must run against a real DB."
  - test: "CORS preflight from deployed frontend (SC #2 live)"
    expected: "curl -I -H 'Origin: https://road-quality-frontend.fly.dev' -H 'Access-Control-Request-Method: POST' -X OPTIONS https://road-quality-backend.fly.dev/route → 200 OK with access-control-allow-origin: https://road-quality-frontend.fly.dev (and not '*')"
    why_human: "Requires deployed apps reachable. Logic is verified by test_cors.py (5 tests pass); live preflight cannot run without flyctl deploy."
  - test: "Live /health DB-reachability probe (SC #5)"
    expected: "curl https://road-quality-backend.fly.dev/health → {\"status\":\"ok\",\"db\":\"reachable\"}; if road-quality-db is stopped → 503 + {\"detail\":{\"status\":\"unhealthy\",\"db\":\"unreachable\"}}"
    why_human: "test_health.py covers the logic with mocks (3 tests pass). Live DB-failure → 503 → Fly LB depool behavior cannot be observed without deployed apps."
  - test: "VITE_API_URL bake-in survives end-to-end (SC #4)"
    expected: "Open https://road-quality-frontend.fly.dev/, observe browser fetches against road-quality-backend.fly.dev (DevTools Network panel) — no localhost calls"
    why_human: "deploy/frontend/test-build.sh verifies the URL is in the JS bundle at Docker layer; live browser observation closes the loop end-to-end."
gaps: []
deferred: []
---

# Phase 5: Cloud Deployment Verification Report

**Phase Goal:** The stack runs on a cloud host from `main` with production-safe configuration — the prerequisite for a public demo.

**Verified:** 2026-04-25T00:00:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Verification Posture

This phase verifies the **deploy path and artifacts** exist and are correctly wired, NOT that they are actually running on Fly. Per the phase brief: *"given this branch on `main`, would a `flyctl auth login` + `gh workflow run deploy.yml` produce a working deployment?"*

The artifact-level answer is **yes for all 9 success criteria**. The remaining work is operator-side (Fly auth + first deploy), captured in the Human Verification section.

### Observable Truths (mapped to ROADMAP Success Criteria)

| # | Truth (Success Criterion) | Status | Evidence |
|---|-----|-----|-----|
| 1 | Documented deploy path brings up db + backend + frontend in non-local env | ✓ VERIFIED | `.github/workflows/deploy.yml` (194 lines, 6 jobs); README `## Deploy` (lines 242-359) with Prerequisites + Initial deploy + Hotfix + Rollback + Volume snapshot caveat; 3 fly.toml configs + 2 Dockerfiles |
| 2 | CORS restricted to deployed frontend origin; no `allow_origins=["*"]` in prod | ✓ VERIFIED | `backend/app/main.py:14-15` reads `os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000")`; `grep '\["\*"\]' backend/app/main.py` returns 0; 5 tests in test_cors.py pass |
| 3 | All secrets from cloud secret mechanism; no committed defaults in prod | ✓ VERIFIED | test_secrets_no_defaults.py scans 3 fly.toml files for SECRET_KEYS = (DATABASE_URL, AUTH_SIGNING_KEY, MAPILLARY_ACCESS_TOKEN, ALLOWED_ORIGINS, POSTGRES_PASSWORD, HUGGINGFACE_TOKEN); all 5 parametrized tests pass; only public identifiers (POSTGRES_DB, POSTGRES_USER, PYTHONUNBUFFERED, VITE_API_URL) committed |
| 4 | Frontend's VITE_API_URL points at deployed backend; no localhost in prod bundle | ✓ VERIFIED | `deploy/frontend/Dockerfile:39-42` ARG/ENV/RUN sequence; `deploy/frontend/fly.toml:25` `[build.args].VITE_API_URL = "https://road-quality-backend.fly.dev"`; `deploy/frontend/test-build.sh` enforces grep-positive for backend URL + grep-negative for `localhost:[0-9]+\|127\.0\.0\.1` |
| 5 | GET /health reports DB reachability (not just `{"status":"ok"}`) | ✓ VERIFIED | `backend/app/routes/health.py:36-50` runs `SELECT 1` and raises HTTPException(503, detail={"status":"unhealthy","db":"unreachable"}) on failure; 3 tests in test_health.py pass (happy / 503 / no-leak); README docs (line 93-103) match the new contract (WR-03 fix applied) |
| 6 | DB connections pooled (psycopg2 ThreadedConnectionPool or equivalent) | ✓ VERIFIED | `backend/app/db.py:48-63` initializes `ThreadedConnectionPool(minconn=2, maxconn=12, dsn=DATABASE_URL, cursor_factory=RealDictCursor)`; `grep SimpleConnectionPool backend/app/db.py` returns 0 (Correction A locked); 4 tests in test_db_pool.py pass |
| 7 | Fresh deploy initializes routable graph via `pgr_createTopology` | ✓ VERIFIED | `scripts/seed_data.py:151` contains `SELECT pgr_createTopology('road_segments', 0.0001, 'geom', 'id', clean := true)`; test_seed_topology.py static guard locks both `pgr_createTopology` AND `clean := true` literals; integration test runs end-to-end against deployed DB via `seed-on-demand` workflow_dispatch job |
| 8 | Migration tests resolve in-container (parents[2] paths, not absolute /db/...) | ✓ VERIFIED | `backend/tests/test_migration_002.py:21` and `test_migration_003.py:25` both use `Path(__file__).resolve().parents[2]`; CI runs them via host-venv (`actions/setup-python@v5` + `working-directory: backend`) per Correction C — sidesteps in-container path resolution by running outside the container |
| 9 | routing.py releases its psycopg2 connection on the exception path | ✓ VERIFIED | Pool wrapper in `backend/app/db.py:91-96` is `try: yield conn finally: p.putconn(conn)` — every `with get_connection() as conn:` exit path runs putconn (RESEARCH Pattern 4 + Correction D); routing.py source is intentionally unchanged (last commit 6df4b53 from Phase 4); 1 integration test in test_routing_pool_release.py is the regression gate |

**Score:** 9/9 truths verified at the artifact level.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/db.py` | ThreadedConnectionPool wrapper, lazy init, RealDictCursor preserved, get_pool_stats helper (WR-02 fix) | ✓ VERIFIED | 136 LOC; ThreadedConnectionPool referenced 5x; SimpleConnectionPool 0x; minconn=2/maxconn=12 present; cursor_factory=RealDictCursor present; @contextmanager + try/finally putconn present; get_pool_stats() public helper present |
| `backend/app/main.py` | env-driven ALLOWED_ORIGINS, allow_credentials=True, no wildcard | ✓ VERIFIED | 32 LOC; reads env at module import; CORSMiddleware wired; tests confirm wildcard absent + credentials enabled |
| `backend/app/routes/health.py` | SELECT 1 round-trip, 503 fallthrough, no error-message leak | ✓ VERIFIED | 51 LOC; static error string only (catches Exception broadly); HTTPException(503, detail=dict) shape |
| `backend/app/routes/auth.py` | 3 sites use `with get_connection() as conn, conn:`; no `from contextlib import closing`; no `closing(get_connection())` | ✓ VERIFIED | 0 imports of `closing`; 0 wrappers; 3 lines match the new shape |
| `backend/app/routes/routing.py` | UNCHANGED from base ffd8603 (pool wrapper IS the SC #9 fix) | ✓ VERIFIED | last commit 6df4b53 (Phase 4); no Phase 5 commits touched this file |
| `scripts/seed_data.py` | pgr_createTopology call with clean := true present at line 151 | ✓ VERIFIED | UNCHANGED in Phase 5 (pre-existing per Correction B); regression gate locks the literal |
| `backend/tests/test_db_pool.py` | 4 unit tests covering pool lifecycle | ✓ VERIFIED | 96 LOC; 4 tests pass |
| `backend/tests/test_routing_pool_release.py` | integration regression gate for SC #9; uses get_pool_stats() (WR-02) | ✓ VERIFIED | 102 LOC; uses public get_pool_stats() helper instead of pool._used; route_cache.clear() defends against test ordering |
| `backend/tests/test_seed_topology.py` | static guard + integration test for SC #7 | ✓ VERIFIED | 150 LOC; 2 tests (1 static + 1 integration); static test passes in 0.01s |
| `backend/tests/test_secrets_no_defaults.py` | parametrized scan of 3 fly.toml + drift guard | ✓ VERIFIED | 139 LOC; 5 test cases pass; SECRET_KEYS roster covers CONTEXT D-05 |
| `backend/tests/test_health.py` | rewrite from 1 test to 3 tests | ✓ VERIFIED | 92 LOC; 3 tests pass (happy / 503 / no-leak) |
| `backend/tests/test_cors.py` | 5 new tests covering env-read / disallowed / dev-default / whitespace / credentials | ✓ VERIFIED | 110 LOC; 5 tests pass |
| `backend/tests/test_migration_002.py`, `test_migration_003.py` | parents[2] path resolution (UNCHANGED — pre-existing per Correction C) | ✓ VERIFIED | both files use `Path(__file__).resolve().parents[2]` for REPO_ROOT |
| `deploy/db/Dockerfile` | PostGIS 3.4 + pgRouting 3.8 + 4 baked init scripts | ✓ VERIFIED | 35 lines; postgis/postgis:16-3.4 base; apt-installs postgresql-16-pgrouting; 4 explicit COPYs into /docker-entrypoint-initdb.d/ |
| `deploy/db/fly.toml` | road-quality-db, internal-only TCP 5432, 1 GB volume, lax region, no [http_service] | ✓ VERIFIED | 48 lines; valid TOML; [[services]] (not [http_service]); auto_stop=false; min_machines_running=1 |
| `deploy/db/test-build.sh` | local smoke test that asserts pgRouting >= 3.6 + 4 init scripts present | ✓ VERIFIED | 58 lines; mode 755; asserts pgRouting version >= 3.6 + 4 init scripts in /docker-entrypoint-initdb.d/ |
| `deploy/backend/fly.toml` | road-quality-backend, references existing backend/Dockerfile, /health probe, no --reload, post-CR-01 build context fix | ✓ VERIFIED | 68 lines; valid TOML; [build].dockerfile = "Dockerfile" (relative to backend/ context per CR-01); [processes].web sets prod uvicorn CMD without --reload; [[http_service.checks]] hits /health every 30s |
| `deploy/frontend/Dockerfile` | multi-stage Vite + nginx:alpine, ARG VITE_API_URL → ENV → npm run build | ✓ VERIFIED | 55 lines; node:20-alpine builder + nginx:alpine runtime; ARG/ENV/RUN sequence in correct order |
| `deploy/frontend/nginx.conf` | SPA fallback + cache split + WR-01 security headers (with location-block re-application) | ✓ VERIFIED | 68 lines; try_files $uri $uri/ /index.html; location ~* assets cache 1y immutable; X-Content-Type-Options/X-Frame-Options/Referrer-Policy/HSTS at server level + repeated in both location blocks (WR-01 inheritance gotcha addressed) |
| `deploy/frontend/fly.toml` | road-quality-frontend, [build.args].VITE_API_URL inline, force_https=true | ✓ VERIFIED | 44 lines; valid TOML; VITE_API_URL = "https://road-quality-backend.fly.dev" in [build.args] |
| `deploy/frontend/test-build.sh` | SC #4 regression gate (positive backend URL + negative localhost regex) | ✓ VERIFIED | 76 lines; mode 755; 4 assertions (URL baked + no localhost:port/127.0.0.1 + nginx config + index.html present); refined regex avoids react-router false-positive |
| `.github/workflows/deploy.yml` | 6 jobs: changes/test/deploy-db/deploy-backend/deploy-frontend/seed-on-demand; CR-01 + CR-02 + WR-04 + WR-05 fixes applied | ✓ VERIFIED | 264 lines; valid YAML; concurrency.group=deploy-prod, cancel-in-progress=false; dorny/paths-filter@v3 with `base: ${{ github.event.before \|\| 'main' }}` (WR-05); deploy-frontend AND seed-on-demand both have `needs.test.result == 'success' \|\| 'skipped'` gates (CR-02); deploy-backend uses `backend/` build context (CR-01); seed-on-demand uses host-venv + `flyctl proxy` (CR-01); AUTH_SIGNING_KEY 32-char floor documented inline (WR-04) |
| `.env.example` | ALLOWED_ORIGINS block added at end | ✓ VERIFIED | block at lines 66-75; documents fly-secrets-set production source + localhost:3000 dev fallthrough; warns against `*` |
| `README.md` | `## Deploy` top-level section + `### GET /health` doc update (WR-03 fix) + Tech Stack row updated | ✓ VERIFIED | `## Deploy` at line 242 with 5 subsections (Prerequisites/Initial deploy/Hotfix/Rollback/Volume snapshot caveat); GET /health doc at line 93-103 documents 200 + 503 paths; Tech Stack row at line 371 reads "Docker Compose (local) + Fly.io (production)" |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| backend/app/db.py | psycopg2.pool | `from psycopg2 import pool as _pool` | ✓ WIRED | import found |
| backend/app/routes/{auth,routing,health,segments}.py | backend/app/db.py | `from app.db import get_connection` | ✓ WIRED | all 4 routes import the pool wrapper's get_connection |
| backend/app/routes/health.py | DB reachability | `SELECT 1` round-trip via get_connection | ✓ WIRED | live query on every probe; 503 on any exception |
| backend/app/main.py | ALLOWED_ORIGINS env | `os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000")` | ✓ WIRED | module-import read; defensive parse (strip whitespace + filter empties) |
| deploy/backend/fly.toml | /health endpoint | `[[http_service.checks]] path = "/health"` | ✓ WIRED | LB depool/repool loop wired to the SELECT-1 probe |
| deploy/frontend/fly.toml | road-quality-backend | `[build.args].VITE_API_URL = "https://road-quality-backend.fly.dev"` | ✓ WIRED | URL matches backend's `app = "road-quality-backend"` |
| deploy/db/Dockerfile | db/migrations/*.sql | 4 explicit COPY directives into /docker-entrypoint-initdb.d/ | ✓ WIRED | postgres init flow auto-runs on first volume boot |
| .github/workflows/deploy.yml | deploy/db/fly.toml | `flyctl deploy --remote-only --config deploy/db/fly.toml --app road-quality-db .` | ✓ WIRED | repo-root build context for db |
| .github/workflows/deploy.yml | deploy/backend/fly.toml | `flyctl deploy --remote-only --config deploy/backend/fly.toml --app road-quality-backend backend/` | ✓ WIRED | backend/ build context (CR-01 fix) |
| .github/workflows/deploy.yml | deploy/frontend/fly.toml | `flyctl deploy --remote-only --config deploy/frontend/fly.toml --app road-quality-frontend .` | ✓ WIRED | repo-root build context for frontend |
| .github/workflows/deploy.yml seed-on-demand | scripts/seed_data.py | host-venv `pip install -r scripts/requirements.txt` + `flyctl proxy 5432:5432 --app road-quality-db &` + `python scripts/seed_data.py` | ✓ WIRED | CR-01 host-venv pattern; sidesteps "scripts/ not in image" |
| .github/workflows/deploy.yml test job | backend/tests/ | `working-directory: backend` + `pytest -v` (host-venv) | ✓ WIRED | runs full suite incl. test_db_pool, test_seed_topology, test_migration_00{2,3}, test_routing_pool_release, test_cors, test_health |
| .github/workflows/deploy.yml | deploy/db/test-build.sh | `bash deploy/db/test-build.sh` (gated on db path filter) | ✓ WIRED | build smoke runs only when db paths change |
| .github/workflows/deploy.yml | deploy/frontend/test-build.sh | `bash deploy/frontend/test-build.sh` (gated on frontend path filter) | ✓ WIRED | SC #4 regression gate enforced in CI |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|--------------------|--------|
| `backend/app/routes/health.py` | DB ping result | `SELECT 1` against pooled connection | Yes (real DB query, not static) | ✓ FLOWING |
| `backend/app/main.py` ALLOWED_ORIGINS | env var | `os.environ.get` at module import | Yes (operator-set; falls through to localhost:3000 in dev) | ✓ FLOWING |
| `deploy/frontend/Dockerfile` VITE_API_URL | build arg → env → bundle | `ARG VITE_API_URL` → `ENV VITE_API_URL=$VITE_API_URL` → `npm run build` consumes via `import.meta.env.VITE_API_URL` | Yes (literal baked at compile time per RESEARCH Pitfall 4) | ✓ FLOWING |
| `backend/app/db.py` ThreadedConnectionPool | DB connection slots | psycopg2 opens 2-12 sockets to DATABASE_URL | Yes (real Postgres connections; not mocked) | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| All Phase 5 unit tests pass | `pytest backend/tests/test_db_pool.py test_cors.py test_health.py test_secrets_no_defaults.py test_seed_topology.py::test_pgr_create_topology_call_present_in_seed_script -v` | 18 passed in 0.03s | ✓ PASS |
| Full backend unit suite (non-integration) passes | `pytest backend/tests/ -m "not integration"` | 209 passed, 49 deselected (integration-marked), 0 failures | ✓ PASS |
| Test collection succeeds (no import errors) | `pytest backend/tests/ --collect-only -q` | 258 tests collected (0 errors) | ✓ PASS |
| deploy.yml is valid YAML | `python -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml'))"` | exit 0 | ✓ PASS |
| All 3 fly.toml files are valid TOML | `python -c "import tomllib; [tomllib.load(open(p,'rb')) for p in ['deploy/db/fly.toml','deploy/backend/fly.toml','deploy/frontend/fly.toml']]"` | exit 0 | ✓ PASS |
| ThreadedConnectionPool present, SimpleConnectionPool absent | `grep -c ThreadedConnectionPool backend/app/db.py; grep -c SimpleConnectionPool backend/app/db.py` | 5 / 0 | ✓ PASS |
| `from contextlib import closing` removed from auth.py; 3 sites use `with get_connection() as conn, conn:` | `grep -c "import closing\|closing(get_connection())" backend/app/routes/auth.py; grep -c "with get_connection() as conn, conn:" backend/app/routes/auth.py` | 0 / 0 / 3 | ✓ PASS |
| pgr_createTopology call locked at scripts/seed_data.py:151 | `grep -n pgr_createTopology scripts/seed_data.py` | line 151: `SELECT pgr_createTopology('road_segments', 0.0001, 'geom', 'id', clean := true)` | ✓ PASS |
| Migration tests use parents[2] resolution | `grep "parents\[2\]" backend/tests/test_migration_002.py test_migration_003.py` | both files line 21/25 | ✓ PASS |
| Frontend test-build.sh enforces backend URL + bans localhost | (static read; can't run without Docker) | regex matches actual API misconfig signatures | ? SKIP (requires Docker) |
| DB test-build.sh asserts pgRouting + init scripts | (static read; can't run without Docker) | asserts version >= 3.6 + 4 init scripts | ? SKIP (requires Docker) |
| Live deploy succeeds end-to-end | (requires flyctl auth + Fly account) | n/a | ? SKIP (operator-side) |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-----------|-----|--------|----------|
| REQ-prod-deploy | 05-01-PLAN, 05-02-PLAN, 05-03-PLAN, 05-04-PLAN, 05-05-PLAN | The stack is deployable to a cloud host from `main` in a reproducible way, with production-safe config | ✓ SATISFIED (artifact-level) | 9/9 success criteria from ROADMAP.md verified; live deploy is operator-side (Human Verification section) |

REQ-prod-deploy maps to the 9 ROADMAP success criteria already verified above. No orphaned requirements: REQUIREMENTS.md only assigns `REQ-prod-deploy` to Phase 5, and all 5 plans declare it in their `requirements:` frontmatter.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| README.md | 312 | "runs `python scripts/seed_data.py` inside the deployed backend container" | ℹ️ Info | Stale prose: the actual workflow uses `flyctl proxy` + host-venv (per CR-01 fix), not `flyctl ssh console -C "python scripts/seed_data.py"`. The `gh workflow run` command on line 309 is correct; only the explanatory sentence on line 312 lags behind the implementation. Does NOT block deploy; user-facing seed instruction works correctly. |

No blocker or warning-level anti-patterns. Zero TODO/FIXME/PLACEHOLDER strings in the modified backend code or deploy artifacts.

### Human Verification Required

The phase artifact path is verified mechanically; the live execution must be the operator's first post-merge action. Five items require human verification against a real Fly account.

#### 1. First production deploy from main

**Test:** `flyctl auth login` + (one-time) `flyctl apps create road-quality-{db,backend,frontend}` + `fly secrets set` per README step 3 + push to main
**Expected:** All 3 Fly apps come up; deploy-db → deploy-backend → deploy-frontend cascade succeeds in GH Actions
**Why human:** Requires authenticated Fly account, real `FLY_API_TOKEN` in GH Actions secrets, and live cloud resources. Cannot be verified without operator credentials.

#### 2. Seed deployed DB topology (SC #7 deploy-time)

**Test:** `gh workflow run deploy.yml --ref main -f seed=true`
**Expected:** `seed-on-demand` job opens `flyctl proxy 5432:5432`, runs `scripts/seed_data.py` from GH runner host venv → `road_segments` populated, `road_segments_vertices_pgr` populated, every row has non-NULL source/target
**Why human:** Requires `PG_PASSWORD` GH secret + live road-quality-db Fly app. The script's `pgr_createTopology` call is statically locked by `test_seed_topology.py`; the integration test (heavy ~5min, OSMnx download) is configured but must run against a real DB.

#### 3. CORS preflight from deployed frontend (SC #2 live)

**Test:**
```bash
curl -I -H "Origin: https://road-quality-frontend.fly.dev" \
  -H "Access-Control-Request-Method: POST" \
  -X OPTIONS https://road-quality-backend.fly.dev/route
```
**Expected:** `200 OK` with `access-control-allow-origin: https://road-quality-frontend.fly.dev` (and not `*`)
**Why human:** Logic is verified by `test_cors.py` (5 tests pass). Live preflight cannot run without `flyctl deploy` first.

#### 4. Live /health DB-reachability probe (SC #5)

**Test:** `curl https://road-quality-backend.fly.dev/health`
**Expected:** `{"status":"ok","db":"reachable"}` when DB is up; `503 + {"detail":{"status":"unhealthy","db":"unreachable"}}` when DB stopped
**Why human:** `test_health.py` covers logic with mocks (3 tests pass). Live DB-failure → 503 → Fly LB depool behavior cannot be observed without deployed apps.

#### 5. VITE_API_URL bake-in survives end-to-end (SC #4)

**Test:** Open https://road-quality-frontend.fly.dev/ in browser; observe DevTools Network panel
**Expected:** Browser fetches against `road-quality-backend.fly.dev` — no `localhost` calls
**Why human:** `deploy/frontend/test-build.sh` verifies the URL is in the JS bundle at the Docker layer; live browser observation closes the loop end-to-end against the running frontend container behind Fly's TLS edge.

### Deferred Items

None. All 9 ROADMAP success criteria for Phase 5 are claimed by Phase 5 plans (no fold-forward to Phase 6). Phase 6 (Public Demo Launch) depends on Phase 5 but does not absorb any Phase 5 SC.

### Gaps Summary

**No artifact-level gaps.** All 9 success criteria are verified at the artifact level — code changes, config files, tests, and CI workflow are all present, correctly wired, and pass their static + unit-level regression gates.

The only outstanding work is operator-side: a `flyctl auth login`, a one-time `flyctl apps create` × 3, a `fly secrets set` for DB password / auth signing key / CORS allowlist, and a push to `main`. These are documented step-by-step in `README.md ## Deploy` (lines 242-359) and require live cloud resources that this verification environment does not provide.

**Recommendation:** Status `human_needed` is the correct closure: the artifact path is sound, the unit/integration test coverage is comprehensive (209 unit tests passing, 18 of which are Phase-5-specific), and CR-01 + CR-02 + WR-01..WR-05 review fixes have all been applied and verified. The operator can now proceed with the Initial Deploy runbook in README; the workflow + artifacts will execute as designed.

#### Minor finding (not a gap)

`README.md:312` describes the seed-on-demand job as running "inside the deployed backend container" — stale prose from the original plan. The actual workflow uses host-venv + `flyctl proxy` (per CR-01 fix). The user-facing command (`gh workflow run deploy.yml --ref main -f seed=true`) on line 309 is correct; only the explanatory sentence is out of date. Recommend a one-line tweak in a follow-up commit, but does NOT block this verification.

---

_Verified: 2026-04-25T00:00:00Z_
_Verifier: Claude (gsd-verifier)_
