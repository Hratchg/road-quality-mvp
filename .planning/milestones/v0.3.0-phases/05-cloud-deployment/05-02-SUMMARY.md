---
phase: 05-cloud-deployment
plan: 02
subsystem: backend-cors-and-health
tags:
  - python
  - fastapi
  - cors
  - health-check
  - tdd
  - prod-hardening
dependency_graph:
  requires:
    - "Phase 4 backend/app/main.py CORSMiddleware wiring (origin: surgical replacement target)"
    - "Phase 4 backend/app/routes/health.py @router.get('/health') (origin: rewrite target)"
    - "Phase 4 .env.example block-section convention (origin: doc-style template)"
    - "Plan 05-01 backend/app/db.py get_connection() context-manager contract (consumed by /health SELECT 1; mocked in tests so order-of-merge does not matter)"
  provides:
    - "backend/app/main.py:ALLOWED_ORIGINS module-level list (consumed by future Plan 05-04 frontend deploy step that sets ALLOWED_ORIGINS via 'fly secrets set' to the deployed *.fly.dev frontend origin)"
    - "backend/app/routes/health.py:/health 503-on-DB-down contract (consumed by Plan 05-05 deploy workflow's HTTP health check + operator smoke 'curl https://<backend>.fly.dev/health')"
    - ".env.example:ALLOWED_ORIGINS env var (consumed by Plan 05-05 CI gate test_secrets_no_defaults that asserts ALLOWED_ORIGINS is set to a non-placeholder value in prod)"
    - "backend/tests/test_cors.py + test_health.py contract tests (regression guard for any future change that re-introduces wildcard or removes credentials or leaks DB errors)"
  affects:
    - "backend/app/main.py (modified — surgical CORS replacement)"
    - "backend/app/routes/health.py (rewritten — DB-reachability probe)"
    - "backend/tests/test_health.py (rewritten — 1 test → 3 tests)"
    - "backend/tests/test_cors.py (new — 5 tests)"
    - ".env.example (modified — new CORS block at end of file)"
tech_stack:
  added: []
  patterns:
    - "PATTERNS P-2: env-var read at module import with safe local-dev default — mirrored from backend/app/db.py's DATABASE_URL discipline (NOT AUTH_SIGNING_KEY's fail-fast — would break docker-compose dev)"
    - "PATTERNS P-5: HTTPException(status_code=N, detail=dict) — mirrored from backend/app/routes/auth.py:75-78 + 102-105"
    - "PATTERNS P-7: .env.example as canonical truth — new # ----- CORS (Phase 5, REQ-prod-deploy SC #2) ----- block follows the existing per-section header + comment-prose + var=default style"
    - "RESEARCH §3 Pattern 2 verbatim /health SELECT 1 + try/except + HTTPException(503, detail={...static dict...})"
    - "RESEARCH §3 Pattern 3 verbatim main.py CORS section: ALLOWED_ORIGINS = [o.strip() for o in raw.split(',') if o.strip()] + allow_credentials=True"
    - "TDD RED→GREEN gate sequence: Task 1 (test commit) precedes Tasks 2 + 3 (feat commits)"
key_files:
  created:
    - "backend/tests/test_cors.py (113 lines, 5 tests covering SC #2)"
    - ".planning/phases/05-cloud-deployment/05-02-SUMMARY.md (this file)"
  modified:
    - "backend/app/main.py (+15 / -1 — added module-level ALLOWED_ORIGINS, allow_credentials=True; removed allow_origins=['*'])"
    - "backend/app/routes/health.py (rewrite, 9 → 51 lines — added SELECT 1 + 503 fallthrough, T-05-07 no-leak invariant)"
    - "backend/tests/test_health.py (rewrite, 9 → 95 lines — 1 test → 3 tests covering SC #5)"
    - ".env.example (+10 — new # ----- CORS (Phase 5, REQ-prod-deploy SC #2) ----- block at end of file)"
decisions:
  - "Default ALLOWED_ORIGINS fallthrough is 'http://localhost:3000' (matches frontend/package.json vite dev port + docker-compose expectation), NOT '*' (which would defeat SC #2 if env var ever silently dropped) and NOT fail-fast RuntimeError (which would break docker-compose dev startup)"
  - "Single broad except Exception in /health (catches psycopg2.OperationalError + psycopg2.InterfaceError + psycopg2.pool.PoolError + any future wrapper error). Narrower catches would let some failure modes leak as 500s — the LB needs to see 503 specifically to depool the machine"
  - "Detail dict (not string) for HTTPException(503): FastAPI serializes dict details to JSON automatically. Test contract: body['detail']['db'] == 'unreachable'"
  - "Static error string only — no f-string interpolation of the exception, no logger.exception(...) in the route layer. Operator visibility comes from Fly's process-level stdout/stderr (psycopg2 logs there by default), NOT from the HTTP response body. Threat T-05-07 mitigated by Test H3 regression guard"
  - "allow_credentials=True kept (not False) for forward-compat with Phase 6+ cookie sessions; CORS spec only forbids credentials with allow_origins=['*'], not with explicit origins"
  - "Read at module import (not per-request): mirrors db.py's DATABASE_URL pattern. Runtime env changes require process restart, which Fly handles via 'fly secrets set' triggering a redeploy (RESEARCH Pitfall 8). Per-request reads add latency for no benefit"
metrics:
  tasks_completed: 3
  tasks_total: 3
  files_changed: 4
  files_created: 1
  tests_added: 7
  tests_total_after: 8
  duration_minutes: ~10
  completed_at: "2026-04-25"
---

# Phase 05 Plan 02: Production CORS + DB-Reachability /health Summary

Replaced `allow_origins=["*"]` in `backend/app/main.py` with an env-driven `ALLOWED_ORIGINS` list (SC #2) and rewrote `/health` to perform a `SELECT 1` round-trip with 503 fallthrough on DB failure (SC #5) — both via TDD with 8 new contract tests across 2 test files.

## Tasks executed

| Task | Type | Outcome | Commit |
|------|------|---------|--------|
| 1. Write failing tests for env-driven CORS + DB-reachability /health | tdd:RED | 7 of 8 tests fail (1 inadvertently passes — `test_cors_rejects_disallowed_origin` because wildcard origin echoes `*` not the requesting origin, satisfying the inequality assertion; the test still locks the contract correctly post-Task-2) | `d1a6b28` |
| 2. Modify backend/app/main.py to read ALLOWED_ORIGINS from env, append CORS block to .env.example | tdd:GREEN | 5 of 5 CORS tests pass | `be4da96` |
| 3. Rewrite backend/app/routes/health.py for SELECT 1 + 503 fallthrough | tdd:GREEN | 3 of 3 health tests pass | `a0c369c` |

## Files final shape

### `backend/app/main.py` — sha256 `c192114df20402c993e9a4f13a515840027e19d1256211496d784874a5e2ccc6`

The plan-05-05 CI gate (`scripts/pre_deploy_check.py` or `test_no_wildcard_cors.py`) can grep for the absence of `allow_origins=["*"]` and the presence of `os.environ.get("ALLOWED_ORIGINS"`:

```python
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import health, segments, routing, auth
from app.routes.cache_routes import router as cache_router

app = FastAPI(title="Road Quality Tracker", version="0.1.0")

# SC #2: CORS restricted to deployed frontend origin. Comma-separated allows
# adding a custom domain later without a code change. Default fallthrough to
# localhost dev origin so `docker compose up` keeps working without explicit
# ALLOWED_ORIGINS plumbing (PATTERNS P-2: mirror DATABASE_URL's safe default,
# NOT AUTH_SIGNING_KEY's fail-fast - fail-fast on CORS would break dev).
_allowed_origins_raw = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000")
ALLOWED_ORIGINS = [o.strip() for o in _allowed_origins_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,  # Forward-safe for Phase 6+ cookie sessions; CORS
                             # spec forbids credentials with origins=["*"], not
                             # with explicit origins (RESEARCH Pattern 3).
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(segments.router)
app.include_router(routing.router)
app.include_router(cache_router)
app.include_router(auth.router)
```

### `backend/app/routes/health.py` — sha256 `24aaa385f9044c074f1ffac1fefbafafdfd8b77b94289ead54d109eaa67acecb`

Plan 05-05's deploy-time smoke (`curl -s https://<backend>.fly.dev/health`) can assert:
- 200 happy path body shape: `{"status": "ok", "db": "reachable"}`
- 503 unhealthy path body shape: `{"detail": {"status": "unhealthy", "db": "unreachable"}}`
- Body MUST NOT contain DB error fragments (`secret-host.fly.dev`, `5432`, `password authentication`)

Final contents (51 lines):

```python
"""GET /health endpoint - Phase 5 SC #5: DB-reachability probe for LB checks.

200 + {status:"ok", db:"reachable"} on success (PRD M0 contract preserved
via the {status:"ok"} key; the {db:"reachable"} field is additive).
503 + {detail:{status:"unhealthy", db:"unreachable"}} on any DB failure.

Fly's HTTP health check treats non-2xx as unhealthy and DEPOOLS the machine
(does NOT restart it - see RESEARCH Pitfall 5). So 503 is the right code:
the LB stops sending traffic until the next probe succeeds, which gives the
DB a chance to recover from a transient hiccup without Fly tearing down the
machine and reseating it.

Threat T-05-07: psycopg2 error messages may include host:port and (rarely)
password fragments. The except clause catches Exception broadly and surfaces
ONLY the static "unreachable" string - never the underlying message. Operator
visibility comes from Fly's stderr logs, not from this public endpoint.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.db import get_connection

router = APIRouter()


@router.get("/health")
def health():
    """LB-probe-friendly health check.

    Returns 200 with {status:"ok", db:"reachable"} on success.
    Returns 503 with {detail:{status:"unhealthy", db:"unreachable"}} on
    any DB failure - Fly's HTTP health check treats non-2xx as unhealthy
    and depools the machine.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return {"status": "ok", "db": "reachable"}
    except Exception:
        # Threat T-05-07: don't leak DB details (host, password fragment in
        # error message) to public probes. The static string is what the LB
        # needs; operator debugging comes from Fly's process logs, not from
        # this endpoint's response body.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "unhealthy", "db": "unreachable"},
        )
```

### `.env.example` — new appended block

Plan 05-04 (frontend) and Plan 05-05 (deploy) executors should know this var is now defined and where to source it:

```bash
# ----- CORS (Phase 5, REQ-prod-deploy SC #2) -----
# Consumed by: backend/app/main.py (read at module import; default fallthrough
# to http://localhost:3000 if unset so docker-compose dev startup works).
# Comma-separated list of frontend origins allowed to make CORS requests.
# Production (Phase 5+) sets this via 'fly secrets set' to the deployed
# frontend's *.fly.dev URL (e.g., https://road-quality-frontend.fly.dev).
# Local dev: leave blank or unset — main.py falls through to localhost:3000.
# Future: add a custom domain by appending a comma-separated value, no code change.
# NEVER use '*' in production — defeats the entire SC #2 contract.
ALLOWED_ORIGINS=
```

## Test counts

| File | Before | After | Net |
|------|--------|-------|-----|
| `backend/tests/test_health.py` | 1 (`test_health_returns_ok`) | 3 (happy / 503 / no-leak) | +2 |
| `backend/tests/test_cors.py` | 0 (new file) | 5 (env-read / disallowed-reject / dev-default / whitespace / credentials) | +5 |
| **Total** | **1** | **8** | **+7** |

All 8 tests pass in 0.02s under `pytest tests/test_health.py tests/test_cors.py`. The full backend suite (74 tests in scope here, 39 skipped DB-integration tests) reports 0 failures.

## Phase 5 Success Criteria status

| SC | Status | Evidence |
|----|--------|----------|
| #1 (deploy path documented) | pending | Plans 05-03 (Dockerfile), 05-04 (frontend), 05-05 (GH Actions + README) |
| **#2 (CORS restricted, no `allow_origins=["*"]` in prod)** | **DONE (this plan)** | main.py uses env-driven `ALLOWED_ORIGINS`; tests `test_cors_*` lock the contract; `! grep allow_origins=\[".*"\] backend/app/main.py` returns true |
| #3 (secrets from cloud host) | pending | Plan 05-05 wires `fly secrets set` for `DATABASE_URL`, `AUTH_SIGNING_KEY`, `MAPILLARY_ACCESS_TOKEN`, `ALLOWED_ORIGINS`, `YOLO_MODEL_PATH` |
| #4 (`VITE_API_URL` to deployed backend) | pending | Plan 05-04 (frontend Dockerfile build-arg) |
| **#5 (`/health` reports DB reachability, not just `{status:ok}`)** | **DONE (this plan)** | health.py uses SELECT 1 round-trip; 503 + `{db:unreachable}` on failure; tests `test_health_*` lock the contract |
| #6 (DB connections pooled) | done by Plan 05-01 (parallel wave 1) | Plan 05-01's `db.py` rewrite to ThreadedConnectionPool |
| #7 (fresh deploy initializes routable graph) | pending | Plan 05-05 (deploy workflow first-deploy seed step) |
| #8 (migration tests resolve in-container) | pending | Plan 05-05 (`deploy/backend/fly.toml` build context fix) |
| #9 (routing.py releases connection on exception) | done by Plan 05-01 (parallel wave 1) | Plan 05-01's `contextlib.closing` wrap of routing.py:59 + 73 |

This plan closes 2 of 9 SCs end-to-end. Plan 05-01 closes 2 more in parallel (#6, #9). Remaining 5 SCs cluster in Plans 05-03 / 05-04 / 05-05 (subsequent waves).

## Threat model coverage

The plan's `<threat_model>` register flagged 6 threats (T-05-07 .. T-05-12). Disposition status:

- **T-05-07 (Info Disclosure — /health 503 leaks DB details)** — mitigated. Test H3 (`test_health_503_does_not_leak_db_error_details`) injects a psycopg2.OperationalError with `host=secret-host.fly.dev port=5432 password authentication failed` in the message and asserts none of those tokens appear in the response body. The except clause catches Exception broadly and surfaces only `{"status":"unhealthy","db":"unreachable"}`.
- **T-05-08 (Tampering / CSRF — wildcard CORS allows evil cross-origin credentialed requests)** — mitigated. `allow_origins=ALLOWED_ORIGINS` (env-driven, no wildcard). Test C2 (`test_cors_rejects_disallowed_origin`) verifies `https://evil.example.com` is NOT echoed in `access-control-allow-origin`. Default fallthrough is localhost-only (not internet-reachable from Fly).
- **T-05-09 (operator typos `ALLOWED_ORIGINS=*`)** — accepted. The env parser treats `*` as a literal string origin; CORSMiddleware then sees `allow_origins=["*"]` (the dangerous shape). Plan 05-05 will add a CI gate (`test_secrets_no_defaults.py`) to assert `ALLOWED_ORIGINS != "*"` in prod.
- **T-05-10 (DoS — /health hammers DB pool)** — accepted. Negligible at Fly's 30s probe cadence vs. pool capacity.
- **T-05-11 (Repudiation — operator can't tell transient vs. real outage from 503)** — accepted. Operator runbook (Plan 05-05 README "Deploy") will document `fly logs` as first-resort.
- **T-05-12 (future contributor adds error details to 503 detail)** — mitigated. Test H3 is the regression guard.

## Deviations from plan

None. The plan executed exactly as written. The `<action>` Step C explicitly noted that `test_cors_rejects_disallowed_origin` would be the only test that "inadvertently passes" in the RED state — and it did. All 8 acceptance criteria for Tasks 1-3 are met.

## Anti-patterns documented (do not undo)

The following anti-patterns are explicitly banned and have regression-guard tests:
1. **`allow_origins=["*"]` in `backend/app/main.py`** — banned by SC #2; regression guard: `test_cors_reads_allowed_origins_env` asserts `"*" not in main.ALLOWED_ORIGINS`.
2. **Including the exception message in `/health` 503 response body** — banned by T-05-07 + T-05-12; regression guard: `test_health_503_does_not_leak_db_error_details`.
3. **Adding a separate `/healthz` endpoint** — banned by CONTEXT D-08 + RESEARCH Open Q3 (one endpoint per concern; `/health` works for both LB-probe and operator-curl at Fly scale).
4. **Adding a topology check (`SELECT COUNT(*) FROM road_segments_vertices_pgr`) on the /health hot path** — banned by PATTERNS §4 SC #7 corrected guidance (deploy-time topology check belongs in `scripts/pre_deploy_check.py` or the GH Actions workflow, NOT on `/health`).
5. **Setting `allow_credentials=False`** — banned by RESEARCH Pattern 3 + Test C5 (`test_cors_allow_credentials_is_true`); CORS spec only forbids credentials with wildcard origins, not with explicit origins.
6. **Reading ALLOWED_ORIGINS at request time (per-request `os.environ.get`)** — banned by PATTERNS P-2 + RESEARCH Pitfall 8 (read at module import, restart on env change; Fly handles this via `fly secrets set` redeploy).
7. **Failing fast (RuntimeError) when ALLOWED_ORIGINS is missing** — banned by PATTERNS P-2 (mirror DATABASE_URL safe-default discipline; would break docker-compose dev startup).

## Cross-plan handoffs

- **Plan 05-01 (parallel wave 1):** This plan's Task 3 calls `with get_connection() as conn:` — works against both the pre-05-01 raw-psycopg2 implementation (during the unit-test mock path) and the post-05-01 ThreadedConnectionPool wrapper. Production live behavior depends on 05-01's pool wrapper being merged before deploy; the integration smoke (Plan 05-05) verifies end-to-end.
- **Plan 05-04 (frontend):** Will set `ALLOWED_ORIGINS` via Fly secrets to the deployed `https://<frontend>.fly.dev` origin. The `.env.example` block this plan added documents the shape.
- **Plan 05-05 (deploy):** GH Actions workflow + README "Deploy" section. Should add a CI gate that asserts `! grep "allow_origins=\[\".*\"\]" backend/app/main.py` and that `ALLOWED_ORIGINS` Fly secret is set to a non-placeholder value before deploy proceeds.

## Self-Check: PASSED

- backend/app/main.py: FOUND (sha256 c192114df20402c993e9a4f13a515840027e19d1256211496d784874a5e2ccc6)
- backend/app/routes/health.py: FOUND (sha256 24aaa385f9044c074f1ffac1fefbafafdfd8b77b94289ead54d109eaa67acecb)
- backend/tests/test_health.py: FOUND
- backend/tests/test_cors.py: FOUND
- .env.example with ALLOWED_ORIGINS block: FOUND
- Commit d1a6b28 (test RED): FOUND
- Commit be4da96 (feat CORS GREEN): FOUND
- Commit a0c369c (feat /health GREEN): FOUND
- 8/8 SC #2 + #5 tests pass: VERIFIED
- No wildcard `allow_origins=["*"]` in main.py: VERIFIED
- TDD gate sequence (test → feat → feat): COMPLIANT
