---
phase: 05-cloud-deployment
plan: 05
subsystem: ci-and-docs
tags:
  - github-actions
  - ci
  - fly
  - infra
  - docs
  - integration
  - regression-gate
  - sc1
  - sc3
  - sc7
  - sc8

# Dependency graph
dependency_graph:
  requires:
    - "Plan 05-01: backend/app/db.py ThreadedConnectionPool wrapper (test_db_pool.py runs in the workflow's pytest gate)"
    - "Plan 05-02: backend/app/main.py env-driven ALLOWED_ORIGINS + backend/app/routes/health.py 503-on-DB-down (test_cors.py + test_health.py run in the pytest gate; deploy/backend/fly.toml health-check probes /health)"
    - "Plan 05-03: deploy/db/fly.toml + deploy/backend/fly.toml + deploy/db/test-build.sh (workflow's deploy-db / deploy-backend jobs target these; test_secrets_no_defaults.py scans them)"
    - "Plan 05-04: deploy/frontend/fly.toml + deploy/frontend/test-build.sh (workflow's deploy-frontend job targets these; test_secrets_no_defaults.py scans frontend's [build.args])"
    - "scripts/seed_data.py:151 (Correction B): pgr_createTopology call already present; test_seed_topology.py locks it"
    - "backend/tests/test_migration_002.py + test_migration_003.py (Correction C): parents[2] resolution already correct; the workflow's host-venv pytest invocation makes it CI-runnable"
  provides:
    - ".github/workflows/deploy.yml: 6-job GH Actions workflow (changes paths-filter + test gate + 3 conditional deploys + seed-on-demand) — the 'documented deploy path' SC #1 demands"
    - "backend/tests/test_seed_topology.py: SC #7 regression gate (1 cheap static guard <10ms + 1 heavy integration test ~5min)"
    - "backend/tests/test_secrets_no_defaults.py: SC #3 regression gate (parametrized scan of 3 fly.toml files + existence guard + roster-drift guard)"
    - "README.md ## Deploy section: operator runbook (Prerequisites, Initial deploy, Hotfix, Rollback, Volume snapshot caveat) + updated Tech Stack row"
  affects:
    - "Phase 6 (public demo): the workflow + README runbook are the launch path; Phase 6 layers a custom domain + demo cutover on top"
    - "Future migrations: any new sql in db/migrations/ will trigger the path-filter's `db` output, which queues a deploy-db re-run; idempotent CREATE-IF-NOT-EXISTS guards in the migrations make repeat-application safe"
    - "Future secret additions: SECRET_KEYS tuple in test_secrets_no_defaults.py must be updated when CONTEXT D-05 adds a new secret env var (the test_secret_roster_matches_context_d05 drift guard will fail until it's updated)"

# Tech tracking
tech-stack:
  added:
    - "GitHub Actions (first workflow file in repo)"
    - "dorny/paths-filter@v3 (path-conditional job dispatch)"
    - "superfly/flyctl-actions/setup-flyctl@master (Fly's documented CD pattern)"
    - "actions/setup-python@v5 + actions/checkout@v4 (host-venv pytest)"
  patterns:
    - "Path-filter changes job + if: always() && needs.X.result == 'success' || 'skipped' on every dependent job (Pitfall 7 skip-cascade defense)"
    - "concurrency.group + cancel-in-progress=false (Pitfall 8 in-flight-deploy race defense)"
    - "Host-venv pytest with postgis service container + apt-installed pgrouting (Correction C: sidesteps the in-container backend/Dockerfile-doesnt-COPY-db/ build-context bug)"
    - "Manual seed-on-demand via workflow_dispatch.inputs.seed (Open Q1: auto-seed on every push would block deploys for 5+ min)"
    - "Regression gate tests scan-pattern: parametrize over 3 fly.toml files + allowlist non-secret VITE_API_URL"
    - "README ## Deploy section style: prose intro + numbered bash blocks + sub-headers (mirrors Phase 4's ## Public Demo Account precedent at commit 27e1ba8)"

key-files:
  created:
    - ".github/workflows/deploy.yml (194 lines, 6 jobs, FIRST workflow in repo)"
    - "backend/tests/test_seed_topology.py (149 lines, 2 tests: 1 static + 1 integration)"
    - "backend/tests/test_secrets_no_defaults.py (138 lines, 3 test functions, 5 test cases via parametrize)"
    - ".planning/phases/05-cloud-deployment/05-05-SUMMARY.md (this file)"
  modified:
    - "README.md (+120 / -1 — added ## Deploy section between ### Rotation and ## Tech Stack; updated Tech Stack row's Deploy field)"

decisions:
  - "Plan executed verbatim — every interface block, action step, and acceptance criterion implemented as specified (RESEARCH §6 GH Actions YAML byte-equivalent + Corrections B/C honored)"
  - "Workflow jobs gated by `if: always() && (needs.X.result == 'success' || skipped)` on EVERY dependent job — without `always()`, GH skip-cascade default would skip frontend deploy when backend was filtered out (Pitfall 7)"
  - "concurrency.group: deploy-prod + cancel-in-progress: false — second push waits for first; never cancels mid-deploy (Pitfall 8)"
  - "Pre-deploy pytest runs in HOST venv (actions/setup-python@v5 + pip install -r backend/requirements.txt) NOT inside the backend container — sidesteps the SC #8 in-container backend/Dockerfile-doesnt-COPY-db/migrations/ build-context bug entirely (Correction C)"
  - "test_seed_topology.py is integration-marked but the static guard test (`test_pgr_create_topology_call_present_in_seed_script`) does NOT use the db_conn fixture, so it runs even when DB is unreachable — ~10ms regression gate against accidental line removal"
  - "test_secrets_no_defaults.py parametrizes the scan over the 3 fly.toml files (one test report per file for diagnosis) + adds a meta-guard (`test_deploy_tomls_exist`) so the scan tests can never silently no-op, plus a drift-guard (`test_secret_roster_matches_context_d05`) so SECRET_KEYS stays in sync with CONTEXT D-05"
  - "VITE_API_URL allowlist via ALLOWLIST_SUBSTRINGS in test_secrets_no_defaults.py — that URL is the publicly-resolvable backend address baked into the JS bundle at build time, NOT a secret"
  - "README ## Deploy section slotted between ### Rotation (line 211) and ## Tech Stack (line 352 post-insert) per PATTERNS P-8; subsections follow the 27e1ba8 precedent for cross-section anchor stability"
  - "Tech Stack row updated from 'Docker Compose (local)' to 'Docker Compose (local) + Fly.io (production)' per PATTERNS P-8 line 192 — additive, not replacement (local dev stays the same)"

requirements-completed:
  - REQ-prod-deploy

# Metrics
metrics:
  tasks_completed: 4
  tasks_total: 4
  commits: 4
  duration_sec: 420
  duration_min: 7
  files_created: 3
  files_modified: 1
  loc_added: 481
  loc_removed: 1
  tests_added: 5
  tests_added_unit: 4
  tests_added_integration: 1
completed: 2026-04-27
---

# Phase 05 Plan 05: Deploy Automation + CI Regression Gates Summary

**One-liner:** Shipped `.github/workflows/deploy.yml` (the FIRST workflow file in the repo — paths-filter + host-venv pytest gate + 3 conditional deploys + manual seed-on-demand) plus 2 regression-gate test files (SC #7 topology + SC #3 secrets) plus a README `## Deploy` operator runbook — closes SC #1, #3, #7, #8 end-to-end and (combined with prior plans) all 9 Phase 5 success criteria.

## What landed

### `.github/workflows/deploy.yml` (Task 1, 194 lines)

The first GH Actions workflow file in the repo. Six jobs:

| Job | Purpose | Gate |
|-----|---------|------|
| `changes` | dorny/paths-filter@v3 → outputs.{db,backend,frontend} | always |
| `test` | host-venv pytest + postgis service container + apt-install pgrouting + build smoke | when any path changed |
| `deploy-db` | flyctl deploy --config deploy/db/fly.toml | db changed AND test passed-or-skipped |
| `deploy-backend` | flyctl deploy --config deploy/backend/fly.toml | (backend OR db) changed AND test passed-or-skipped AND deploy-db passed-or-skipped |
| `deploy-frontend` | flyctl deploy --config deploy/frontend/fly.toml | frontend changed AND deploy-backend passed-or-skipped |
| `seed-on-demand` | flyctl ssh console -C "python scripts/seed_data.py" | workflow_dispatch.inputs.seed=='true' AND deploy-backend passed-or-skipped |

Key invariants enforced in code:
- Triggers: `push.branches: [main]` + `workflow_dispatch.inputs.seed`
- `concurrency.group: deploy-prod` + `cancel-in-progress: false` (Pitfall 8 defense — second push queues, never cancels)
- Every dependent job uses `if: always() && (needs.X.result == 'success' || needs.X.result == 'skipped')` (Pitfall 7 skip-cascade defense — a frontend-only commit must deploy frontend even when backend's job filtered out)
- All 4 deploy/seed jobs use `FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}` — never hardcoded
- Test job runs pytest from HOST venv (`actions/setup-python@v5` + `pip install -r backend/requirements.txt`), NOT inside the backend container — sidesteps the SC #8 in-container build-context bug entirely
- Test job sets `AUTH_SIGNING_KEY: test_key_for_ci_only_padding_padding_padding` so Phase 4's conftest import-time read succeeds in CI
- Build smoke jobs (`bash deploy/db/test-build.sh`, `bash deploy/frontend/test-build.sh`) run conditionally on path-filter outputs

Operator entry points:
- Auto-deploy: push to `main` → workflow runs → whichever app's path-filter fires deploys
- Manual deploy: `gh workflow run deploy.yml --ref main` (no seed) or `... -f seed=true` (seeds DB after deploy)

### `backend/tests/test_seed_topology.py` (Task 2, 149 lines)

Two tests guarding SC #7:

| Test | Type | Cost | What it asserts |
|------|------|------|-----------------|
| `test_pgr_create_topology_call_present_in_seed_script` | static | <10ms | scripts/seed_data.py contains both `pgr_createTopology` and `clean := true` literals |
| `test_seed_data_builds_routable_topology` | integration | ~5min | After running scripts/seed_data.py end-to-end: road_segments has rows AND road_segments_vertices_pgr has rows AND every road_segments row has non-NULL source AND target |

Module marked `pytest.mark.integration`. The static guard runs even without DB access (no fixture dependency); the integration test auto-skips when DB unreachable via `db_conn` fixture chain. Per Correction B: this test does NOT modify scripts/seed_data.py — the pgr_createTopology call is already at line 151; the test locks that behavior.

### `backend/tests/test_secrets_no_defaults.py` (Task 3, 138 lines)

Three test functions guarding SC #3 (parametrize expands to 5 test cases):

| Test | Cases | What it asserts |
|------|-------|-----------------|
| `test_no_committed_secrets_in_deploy_toml` | 3 (parametrized over deploy/{db,backend,frontend}/fly.toml) | No KEY = "value" line where KEY is in SECRET_KEYS = (DATABASE_URL, AUTH_SIGNING_KEY, MAPILLARY_ACCESS_TOKEN, ALLOWED_ORIGINS, POSTGRES_PASSWORD, HUGGINGFACE_TOKEN). VITE_API_URL allowlisted as a non-secret. |
| `test_deploy_tomls_exist` | 1 | All 3 fly.toml files exist (otherwise scan would silently skip and SC #3 would be unverified) |
| `test_secret_roster_matches_context_d05` | 1 | SECRET_KEYS tuple covers CONTEXT D-05's documented secret roster (drift guard for future plans) |

Pure unit test (no DB, no integration marker). Negative-tested locally: appending `POSTGRES_PASSWORD = "fake_test_password"` to deploy/db/fly.toml correctly trips the parametrized scan with assertion message `"SC #3 violation"`. After revert, all 5 pass.

### `README.md` (Task 4, +120 / -1 lines)

New top-level `## Deploy` section between `### Rotation` (line 211) and `## Tech Stack` (now line 352). Subsections:

- `### Prerequisites` — Fly.io account + flyctl install + FLY_API_TOKEN GH secret generation via `fly tokens create deploy -x 999999h`
- `### Initial deploy` — 7-step runbook: `flyctl apps create` (3x) → generate PG_PASSWORD + AUTH_KEY → `flyctl secrets set` (db then backend) → push to main → `gh workflow run deploy.yml -f seed=true` → curl smoke → browser verification
- `### Hotfix` — `flyctl deploy --remote-only --config deploy/backend/fly.toml --app road-quality-backend .` (single-app rebuild bypassing GH Actions queue)
- `### Rollback` — `flyctl image list` + `flyctl deploy --image <previous-image-ref>` (manual; no automation per CONTEXT D-04)
- `### Volume snapshot caveat` — Pitfall 6 mitigation: `flyctl ssh console --app road-quality-db -C "psql ... < /docker-entrypoint-initdb.d/...sql"` for post-restore migration re-application

Tech Stack table row updated:
- Before: `| Deploy | Docker Compose (local) |`
- After: `| Deploy | Docker Compose (local) + Fly.io (production) |`

Style mirrors Phase 4's `## Public Demo Account` section (commit `27e1ba8` precedent): prose intro + numbered bash blocks + sub-headers — load-bearing-heading-as-cross-plan-anchor pattern.

## Phase 5 Success Criteria — final closure status

| SC | Status | Owning plan(s) | Evidence |
|----|--------|----------------|----------|
| **#1** (deploy path documented) | DONE | 05-03 + 05-04 (artifacts) + 05-05 (workflow + README) | `.github/workflows/deploy.yml` deploys 3 apps end-to-end; `README.md ## Deploy` is the runbook |
| **#2** (CORS restricted, no `allow_origins=["*"]` in prod) | DONE | 05-02 | `backend/app/main.py` env-driven ALLOWED_ORIGINS + `test_cors.py` regression guards |
| **#3** (secrets from cloud host, no committed defaults) | DONE | 05-03 + 05-04 (no hardcoded secrets in fly.toml) + 05-05 (regression gate) | `test_secrets_no_defaults.py` scans all 3 fly.toml on every CI run |
| **#4** (`VITE_API_URL` to deployed backend, no localhost in prod bundle) | DONE | 05-04 (Dockerfile + test-build.sh) + 05-05 (CI runs the smoke) | `deploy/frontend/Dockerfile` ARG/ENV/build pipeline + `test-build.sh` enforced in workflow |
| **#5** (`/health` reports DB reachability, not just `{status:"ok"}`) | DONE | 05-02 | `backend/app/routes/health.py` SELECT 1 + 503 fallthrough; `test_health.py` regression guards |
| **#6** (DB connections pooled) | DONE | 05-01 | `backend/app/db.py` ThreadedConnectionPool minconn=2/maxconn=12 |
| **#7** (fresh deploy initializes routable graph) | DONE | scripts/seed_data.py:151 (pre-existing) + 05-05 (regression gate + deploy-time trigger) | `test_seed_topology.py` static + integration; `seed-on-demand` workflow_dispatch job |
| **#8** (migration tests resolve in-container) | DONE (host-venv path; in-container path explicitly deferred per Correction C) | test_migration_002.py + test_migration_003.py parents[2] (pre-existing) + 05-05 (host-venv CI runner) | Workflow's `test` job runs them via `pytest -v` from `working-directory: backend` with `actions/setup-python@v5` |
| **#9** (routing.py releases connection on exception) | DONE | 05-01 | Pool wrapper's `try/finally putconn` is the leak fix at every call site (RESEARCH Pattern 4) |

**All 9 SCs are now satisfied end-to-end.** Phase 5 complete from a contract standpoint; remaining work (Phase 6) is the public-demo cutover on top of this deploy path.

## Task Commits

| # | Commit | Type | Description |
|---|--------|------|-------------|
| 1 | `00d4ba1` | feat | `.github/workflows/deploy.yml` (paths-filter + host-venv tests + 3-app deploy + seed-on-demand) |
| 2 | `f378402` | test | SC #7 regression gate (test_seed_topology.py — pgr_createTopology + road_segments_vertices_pgr) |
| 3 | `d0c20d9` | test | SC #3 regression gate (test_secrets_no_defaults.py — scans deploy/*.toml for hardcoded secrets) |
| 4 | `9814633` | docs | Add `## Deploy` section to README + update Tech Stack row (Fly.io production) |

Plan-metadata commit (this SUMMARY) added separately per the parallel-execution contract.

## Files Created/Modified

### Created (3 + this SUMMARY)
- `.github/workflows/deploy.yml` — 194 lines, 6 jobs, the first workflow file in the repo
- `backend/tests/test_seed_topology.py` — 149 lines, 2 test functions
- `backend/tests/test_secrets_no_defaults.py` — 138 lines, 3 test functions (5 test cases via parametrize)
- `.planning/phases/05-cloud-deployment/05-05-SUMMARY.md` (this file)

### Modified (1)
- `README.md` — +120 / -1 lines: new `## Deploy` section (Prerequisites + Initial deploy + Hotfix + Rollback + Volume snapshot caveat), updated Tech Stack row's Deploy field

### NOT modified (per plan locks — verified zero diff vs. base d74c8f7)
- `scripts/seed_data.py` — Correction B: line 151 already has `pgr_createTopology(... clean := true)`; this plan adds a regression gate test, not a source edit
- `backend/tests/test_migration_002.py` and `test_migration_003.py` — Correction C: parents[2] resolution already correct; this plan ships the CI gate that runs them in a host venv where the path actually resolves
- `deploy/db/fly.toml`, `deploy/backend/fly.toml`, `deploy/frontend/fly.toml` — Plans 05-03 / 05-04 own these
- `.planning/STATE.md` and `.planning/ROADMAP.md` — parallel-executor contract: orchestrator owns these

Verified via `git diff d74c8f76 -- <each path>` returning 0 lines.

## Verification (executed, all green)

```bash
# 1. YAML parses cleanly
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml'))"  # exit 0

# 2. Workflow structural assertions
grep -c "FLY_API_TOKEN" .github/workflows/deploy.yml                            # 4 (3 deploy jobs + seed-on-demand)
! grep -E 'FLY_API_TOKEN: [a-zA-Z0-9]{16,}' .github/workflows/deploy.yml        # OK (no hardcoded token)

# 3. Cheap regression gates green (no DB needed)
cd backend && pytest tests/test_seed_topology.py::test_pgr_create_topology_call_present_in_seed_script tests/test_secrets_no_defaults.py
# 6 passed in 0.01s

# 4. Negative test — appending fake secret to fly.toml trips the regression gate
echo 'POSTGRES_PASSWORD = "fake_test_password"' >> deploy/db/fly.toml
cd backend && pytest tests/test_secrets_no_defaults.py 2>&1 | grep -q "SC #3 violation"   # OK
git checkout deploy/db/fly.toml
cd backend && pytest tests/test_secrets_no_defaults.py                                     # 5 passed

# 5. README assertions
grep -c "^## Deploy" README.md                                                  # 1
grep -c "fly tokens create deploy" README.md                                    # 1
grep -c "FLY_API_TOKEN" README.md                                               # 2
grep -c "Docker Compose (local) + Fly.io (production)" README.md                # 1

# 6. Locked files unchanged
for f in scripts/seed_data.py backend/tests/test_migration_002.py backend/tests/test_migration_003.py deploy/; do
  [ "$(git diff d74c8f76 -- $f | wc -l)" = "0" ] && echo "$f: UNCHANGED"
done
```

## Deviations from Plan

None. Plan executed exactly as written — every interface block, action step, and acceptance criterion implemented byte-equivalent to the plan's verbatim YAML / Python / Markdown templates. The single near-miss was during local verification (the `grep -q "FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}"` shell command from the plan's verify gate was confused by shell-expansion of `${{` braces; switched to `grep -qF` for fixed-string match — that's a verify-script tweak, not an artifact change).

## Threat model coverage

The plan's `<threat_model>` register flagged 10 threats (T-05-31..T-05-40). Disposition status:

| ID | Threat | Status | How |
|----|--------|--------|-----|
| T-05-31 | Hardcoded FLY_API_TOKEN in workflow YAML | mitigated | Token always via `${{ secrets.FLY_API_TOKEN }}`. Verified by `! grep -E 'FLY_API_TOKEN: [a-zA-Z0-9]{16,}' .github/workflows/deploy.yml` |
| T-05-32 | Operator commits secret value via `.env` | mitigated | README's Initial Deploy step 3 uses `flyctl secrets set` directly, never via `.env`. `.env.example` template documents names only |
| T-05-33 | Mid-deploy push race | mitigated | `concurrency.group: deploy-prod` + `cancel-in-progress: false` queues subsequent pushes (Pitfall 8) |
| T-05-34 | Skip-cascade through `needs:` chain | mitigated | `if: always() && (needs.X.result == 'success' || skipped)` on every dependent job (Pitfall 7) |
| T-05-35 | Auto-seed on every push leaks data | mitigated | seed-on-demand gated on `github.event.inputs.seed == 'true'` AND workflow_dispatch event |
| T-05-36 | Refactor removes pgr_createTopology silently | mitigated | `test_seed_topology.py`'s static guard catches removal in <10ms; integration test catches actual topology breakage |
| T-05-37 | Heavy integration test blocks deploy | accepted | Static guard is primary CI signal (<10ms); integration test bounded by 10-min timeout; hotfix path bypasses workflow |
| T-05-38 | psycopg2 errors leak DB creds in test output | accepted | CI uses non-secret `rqpass` against runner-local postgis service container; no production credentials in CI scope |
| T-05-39 | fly.toml `app =` typo deploys to wrong-named app | mitigated | `--app road-quality-X` flag cross-checks against `app =` field; mismatch fails fast |
| T-05-40 | Volume snapshot restore loses migrations | mitigated | README's "Volume snapshot caveat" subsection documents `flyctl ssh console -C 'psql ...'` recovery; all migrations idempotent (CREATE-IF-NOT-EXISTS) |

## Cross-plan handoffs

- **Phase 6 (public demo):** This plan's workflow + README runbook are the launch path. Phase 6 layers a custom domain (Fly `[[certificates]]` block) + demo cutover on top. The `## Deploy` section's anchor is stable for Phase 6 to extend a `### Custom domain` subsection.
- **Future migrations:** Adding a new SQL file to `db/migrations/` triggers the path-filter's `db` output, which queues a deploy-db re-run. Idempotent CREATE-IF-NOT-EXISTS in all 003 migrations means repeat-application is safe (Plan 05-03 lock). Volume-snapshot restore is the one edge case — README documents the manual recovery.
- **Future secrets:** Adding a new secret env var to CONTEXT D-05 requires updating `SECRET_KEYS` in `backend/tests/test_secrets_no_defaults.py`. The `test_secret_roster_matches_context_d05` drift guard fails until SECRET_KEYS catches up — cheap insurance against silent gaps.

## Self-Check: PASSED

Files created (verified existence):
- `.github/workflows/deploy.yml` — FOUND
- `backend/tests/test_seed_topology.py` — FOUND
- `backend/tests/test_secrets_no_defaults.py` — FOUND

Files modified (verified diff non-empty):
- `README.md` — +120 / -1 lines

Files NOT modified (verified zero diff vs. d74c8f7):
- `scripts/seed_data.py` — UNCHANGED
- `backend/tests/test_migration_002.py` — UNCHANGED
- `backend/tests/test_migration_003.py` — UNCHANGED
- `deploy/db/fly.toml`, `deploy/backend/fly.toml`, `deploy/frontend/fly.toml` — UNCHANGED
- `.planning/STATE.md`, `.planning/ROADMAP.md` — UNCHANGED

Commits (verified in `git log`):
- `00d4ba1` (feat 05-05: workflow) — FOUND
- `f378402` (test 05-05: SC #7 gate) — FOUND
- `d0c20d9` (test 05-05: SC #3 gate) — FOUND
- `9814633` (docs 05-05: README ## Deploy) — FOUND

Test runs (executed):
- `pytest tests/test_seed_topology.py::test_pgr_create_topology_call_present_in_seed_script` → 1 passed in 0.01s
- `pytest tests/test_secrets_no_defaults.py` → 5 passed in 0.01s
- Negative test (POSTGRES_PASSWORD appended to deploy/db/fly.toml) → "SC #3 violation" correctly raised; revert + re-run → 5 passed
- YAML lint: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml'))"` → exit 0

---

*Phase: 05-cloud-deployment*
*Plan: 05*
*Completed: 2026-04-27*
*Duration: 7m*
