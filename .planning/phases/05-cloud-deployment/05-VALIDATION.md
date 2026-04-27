---
phase: 5
slug: 05-cloud-deployment
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-04-27
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 (host venv `/tmp/rq-venv/bin/pytest`); vitest (frontend, in `frontend/package.json`) |
| **Config file** | `backend/tests/conftest.py` (existing — adds AUTH_SIGNING_KEY default + `db_conn` fixture). No separate pytest.ini. |
| **Quick run command** | `/tmp/rq-venv/bin/pytest backend/tests/test_db_pool.py backend/tests/test_cors.py backend/tests/test_health.py -q -m "not integration"` |
| **Full backend suite** | `/tmp/rq-venv/bin/pytest backend/tests/ -q -m "not integration"` (host) — sidesteps the Phase 4 build-context bug per Correction C |
| **Integration tier** | `docker compose exec backend pytest backend/tests/ -q -m integration` (live DB) — but per Correction C, the CI runner runs from host venv to avoid the in-container `db/` mount issue |
| **Build smoke** | `bash deploy/db/test-build.sh` + `bash deploy/frontend/test-build.sh` (both ship in W2) |
| **Estimated runtime (quick)** | ~1 sec unit subset; ~5 sec full integration tier (against live PG); ~30s for build smokes |

---

## Sampling Rate

- **After every task commit:** Run quick subset (unit + grep verifiers in each plan's `<verify>` block).
- **After every plan wave:** Run full suite + applicable build smoke.
- **Before `/gsd-verify-work`:** Full suite + manual `flyctl deploy --build-only` against db, backend, frontend (no actual deploy — just confirm the build context resolves and the artifacts assemble).
- **Max feedback latency:** ~10s for unit subset; well below 30s Nyquist threshold.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | SC Ref | Test Type | Automated Command | File Exists | Status |
|---|---|---|---|---|---|---|---|---|
| 05-01-T01 | 01 | 1 | REQ-prod-deploy | SC #6, #9 | RED unit pytest (must FAIL) | `/tmp/rq-venv/bin/pytest backend/tests/test_db_pool.py backend/tests/test_routing_pool_release.py -x` → exit non-zero | ❌ W0 | ⬜ pending |
| 05-01-T02 | 01 | 1 | REQ-prod-deploy | SC #6, #9 | GREEN unit + integration pytest | Same command → all pass; grep `! grep -q "SimpleConnectionPool" backend/app/db.py`; grep `grep -E "ThreadedConnectionPool" backend/app/db.py` | ❌ W0 | ⬜ pending |
| 05-01-T03 | 01 | 1 | REQ-prod-deploy | SC #6, #9 | grep + pytest | `grep -c "contextlib.closing(get_connection())" backend/app/routes/auth.py` → 0; pytest auth integration still passes | ❌ W0 | ⬜ pending |
| 05-02-T01 | 02 | 1 | REQ-prod-deploy | SC #2, #5 | RED unit pytest (must FAIL) | `/tmp/rq-venv/bin/pytest backend/tests/test_health.py backend/tests/test_cors.py -x` → exit non-zero | ❌ W0 | ⬜ pending |
| 05-02-T02 | 02 | 1 | REQ-prod-deploy | SC #2 | GREEN CORS subset + grep | `pytest backend/tests/test_cors.py -q`; `! grep -E 'allow_origins=\[.\*.\]' backend/app/main.py`; `grep -E 'ALLOWED_ORIGINS' backend/app/main.py` | ❌ W0 | ⬜ pending |
| 05-02-T03 | 02 | 1 | REQ-prod-deploy | SC #5 | GREEN /health subset | `pytest backend/tests/test_health.py -q`; verify 503 path via mock-DB-down test | ❌ W0 | ⬜ pending |
| 05-03-T01 | 03 | 2 | REQ-prod-deploy | SC #1 | docker build | `docker build -f deploy/db/Dockerfile -t rq-db:test deploy/db/` succeeds; image has `pgrouting >= 3.6` (verify via `docker run rq-db:test apt list --installed 2>/dev/null \| grep pgrouting`) | ❌ W0 | ⬜ pending |
| 05-03-T02 | 03 | 2 | REQ-prod-deploy | SC #1 | YAML lint + grep | `python -c "import tomllib; tomllib.loads(open('deploy/db/fly.toml').read())"`; grep `[mounts]` in deploy/db/fly.toml | ❌ W0 | ⬜ pending |
| 05-03-T03 | 03 | 2 | REQ-prod-deploy | SC #1 | TOML lint | Same TOML lint for `deploy/backend/fly.toml`; grep `dockerfile = "../../backend/Dockerfile"` (or equivalent path) | ❌ W0 | ⬜ pending |
| 05-04-T01 | 04 | 2 | REQ-prod-deploy | SC #4 | docker build + bundle inspection | `docker build --build-arg VITE_API_URL=https://test.fly.dev -f deploy/frontend/Dockerfile -t rq-fe:test .`; `docker run --rm rq-fe:test grep -r "test.fly.dev" /usr/share/nginx/html` succeeds; `! grep -r "localhost" /usr/share/nginx/html` | ❌ W0 | ⬜ pending |
| 05-04-T02 | 04 | 2 | REQ-prod-deploy | SC #1 | nginx -t | `nginx -t -c deploy/frontend/nginx.conf` (or via container test) | ❌ W0 | ⬜ pending |
| 05-04-T03 | 04 | 2 | REQ-prod-deploy | SC #1, #4 | TOML lint + grep | TOML lint deploy/frontend/fly.toml; grep `[build.args]` block with `VITE_API_URL` | ❌ W0 | ⬜ pending |
| 05-05-T01 | 05 | 3 | REQ-prod-deploy | SC #1 | YAML lint | `actionlint .github/workflows/deploy.yml` (or equivalent — `python -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml'))"`); grep all 3 service jobs present | ❌ W0 | ⬜ pending |
| 05-05-T02 | 05 | 3 | REQ-prod-deploy | SC #7 | static + integration regression | Static: `grep -E "pgr_createTopology.*clean := true" scripts/seed_data.py`. Integration: `pytest backend/tests/test_seed_topology.py -m integration` against fresh DB → asserts `road_segments_vertices_pgr` non-empty | ❌ W0 | ⬜ pending |
| 05-05-T03 | 05 | 3 | REQ-prod-deploy | SC #3 | static scan | `pytest backend/tests/test_secrets_no_defaults.py -q` — parameterized over all 3 fly.toml files, scans for AUTH_SIGNING_KEY / POSTGRES_PASSWORD / MAPILLARY_ACCESS_TOKEN / DATABASE_URL hardcoded values | ❌ W0 | ⬜ pending |
| 05-05-T04 | 05 | 3 | REQ-prod-deploy | SC #1 | grep | `grep -E "## Deploy" README.md`; verify mentions `flyctl`, `fly secrets set`, `gh workflow run` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Sampling continuity:** Every task has an automated `<verify>` invocation. Max consecutive tasks without automation: 0. No human-verify checkpoints in Phase 5 (the actual cloud deploy itself is operator-driven post-merge — that's Phase 6's UAT).

---

## Wave 0 Requirements

- [ ] `backend/tests/test_db_pool.py` — created in Plan 05-01 Task 1 (unit + integration tests for ThreadedConnectionPool wrapper, SC #6)
- [ ] `backend/tests/test_routing_pool_release.py` — created in Plan 05-01 Task 1 (regression gate for SC #9 — pool slot release on routing.py exception path)
- [ ] `backend/tests/test_cors.py` — created in Plan 05-02 Task 1 (env-driven CORS allowlist, SC #2)
- [ ] `backend/tests/test_health.py` — rewritten in Plan 05-02 Task 1 (503-on-DB-down, SC #5)
- [ ] `backend/tests/test_seed_topology.py` — created in Plan 05-05 Task 2 (regression gate for SC #7 — pgr_createTopology already in seed_data.py:151)
- [ ] `backend/tests/test_secrets_no_defaults.py` — created in Plan 05-05 Task 3 (parameterized scan across all 3 fly.toml files, SC #3)
- [ ] `deploy/db/test-build.sh` — created in Plan 05-03 Task 1 (docker build smoke + pgrouting version assertion)
- [ ] `deploy/frontend/test-build.sh` — created in Plan 05-04 Task 1 (docker build smoke + bundle assertion VITE_API_URL baked, no localhost)
- [ ] No new framework install needed — pytest + actionlint (optional) cover the surface

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|---|---|---|---|
| First-time `fly auth login` + `fly apps create road-quality-{db,backend,frontend}` | REQ-prod-deploy (SC #1) | One-time operator setup; can't be automated without leaking flyctl token to CI | Operator runs once: `fly auth login` (browser), then for each service: `fly apps create road-quality-<svc>`, set secrets via `fly secrets set ...`, attach volume for db (`fly volumes create rq_db --region <r> --size 1`) |
| First push to main triggering deploy | REQ-prod-deploy (SC #1) | Deploy itself is a side-effect; Phase 5 ships the workflow, the actual deploy is the operator's first post-merge action | Operator pushes to main, watches Actions tab, validates 3 jobs all green, hits `https://road-quality-frontend.fly.dev/` and confirms map loads |
| Bootstrap topology after first deploy | REQ-prod-deploy (SC #7) | Manual gh workflow run -f seed=true (per RESEARCH Open Q1 — auto-seed on every deploy is a footgun) | Operator runs: `gh workflow run deploy.yml -f seed=true` (or equivalent UI). After: `curl https://road-quality-backend.fly.dev/route -X POST ...` succeeds |
| Verify Fly secrets are set + no defaults visible | REQ-prod-deploy (SC #3) | `fly secrets list` shows secret NAMES but not values; operator confirms expected names exist | `fly secrets list -a road-quality-backend` shows AUTH_SIGNING_KEY, MAPILLARY_ACCESS_TOKEN, DATABASE_URL, ALLOWED_ORIGINS |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: 0 tasks without automated verify
- [x] Wave 0 covers all MISSING references (6 new test files + 2 build-smoke scripts)
- [x] No watch-mode flags
- [x] Feedback latency < 30s (host quick subset ~1s; build smokes ~30s)
- [x] `nyquist_compliant: true` in frontmatter

**Approval:** approved 2026-04-27
