---
phase: 4
slug: 04-authentication
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-04-26
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 (backend, host venv `/tmp/rq-venv/bin/pytest`); vitest (frontend, present in `frontend/package.json`) |
| **Config file** | `backend/tests/conftest.py` (existing, will be extended in 04-02 Task 4 with `pytest_configure` for AUTH_SIGNING_KEY default and `db_conn` fixture); no separate pytest.ini |
| **Quick run command** | `/tmp/rq-venv/bin/pytest backend/tests/test_auth_passwords.py backend/tests/test_auth_tokens.py -q -m "not integration"` |
| **Full suite command (incl. integration)** | `docker compose exec backend pytest -q` (lives in container so live DB + AUTH_SIGNING_KEY env are present) |
| **Host-runnable pure unit subset** | `/tmp/rq-venv/bin/pytest backend/tests/ -q -m "not integration"` |
| **Estimated runtime (quick)** | ~1 sec for unit subset, ~10 sec for full integration tier |

---

## Sampling Rate

- **After every task commit:** Run `quick` command above (unit + import-graph + grep verifiers from each plan).
- **After every plan wave:** Run `full suite` against the live Docker stack.
- **Before `/gsd-verify-work`:** Full suite + manual UAT items pass.
- **Max feedback latency:** ~10 sec (quick subset) — well below the 30 sec Nyquist threshold.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | SC Ref | Test Type | Automated Command | File Exists | Status |
|---|---|---|---|---|---|---|---|---|
| 04-01-T01 | 01 | 1 | REQ-user-auth | SC #5 | grep + sql syntax | `grep -E "CREATE TABLE IF NOT EXISTS users" db/migrations/003_users.sql && grep -E "CREATE UNIQUE INDEX IF NOT EXISTS users_email_key" db/migrations/003_users.sql && ! grep -qi "INSERT INTO users" db/migrations/003_users.sql` | ❌ W0 | ⬜ pending |
| 04-01-T02 | 01 | 1 | REQ-user-auth | SC #5 | grep | `grep -E "003_users.sql:/docker-entrypoint-initdb.d/04-users.sql" docker-compose.yml` | ❌ W0 | ⬜ pending |
| 04-01-T03 | 01 | 1 | REQ-user-auth | SC #5 | integration pytest | `docker compose exec backend pytest backend/tests/test_migration_003.py -v -m integration` (5 tests: applies-cleanly, idempotent-double-apply, locked-shape, unique-email-rejects-dupe, demo-user-not-seeded) | ❌ W0 | ⬜ pending |
| 04-02-T01 | 02 | 2 | REQ-user-auth | SC #4 | grep | `grep -E "^pwdlib\[argon2\]>=0.2.1,<0.4" backend/requirements.txt && grep -E "^python-jose\[cryptography\]>=3.3.0,<4" backend/requirements.txt && grep -E "^email-validator>=2.0,<3" backend/requirements.txt` | ❌ W0 | ⬜ pending |
| 04-02-T02 | 02 | 2 | REQ-user-auth | SC #2, #4 | RED unit pytest (must FAIL) | `/tmp/rq-venv/bin/pytest backend/tests/test_auth_passwords.py backend/tests/test_auth_tokens.py -x` → exit code != 0 | ❌ W0 | ⬜ pending |
| 04-02-T03 | 02 | 2 | REQ-user-auth | SC #2, #4 | GREEN unit pytest (must PASS) | `/tmp/rq-venv/bin/pytest backend/tests/test_auth_passwords.py backend/tests/test_auth_tokens.py -q` → 15 passed | ❌ W0 | ⬜ pending |
| 04-02-T04 | 02 | 2 | REQ-user-auth | infra | conftest extension | `/tmp/rq-venv/bin/pytest backend/tests/ -q -m "not integration" --collect-only` collects without ImportError on `app.auth.tokens` | ❌ W0 | ⬜ pending |
| 04-03-T01 | 03 | 3 | REQ-user-auth | SC #1, #2, #3 | RED integration pytest (must FAIL) | `docker compose exec backend pytest backend/tests/test_auth_routes.py -x -m integration` → exit non-zero (404 on /auth/register, no Depends gating) | ❌ W0 | ⬜ pending |
| 04-03-T02 | 03 | 3 | REQ-user-auth | SC #1, #2 | GREEN integration pytest (subset) | `docker compose exec backend pytest backend/tests/test_auth_routes.py::TestRegister backend/tests/test_auth_routes.py::TestLogin -m integration` → 8 passed | ❌ W0 | ⬜ pending |
| 04-03-T03 | 03 | 3 | REQ-user-auth | SC #3 | GREEN integration pytest (full) | `docker compose exec backend pytest backend/tests/test_auth_routes.py -m integration` → 18 passed (incl. G1-G7 gating + H1 hash-in-db + O1 logout) | ❌ W0 | ⬜ pending |
| 04-04-T01 | 04 | 4 | REQ-user-auth | SC #1, #2 | grep + tsc | `grep -E "register\|login\|logout" frontend/src/api/auth.ts && grep -qE "rq_auth_token" frontend/src/api/auth.ts && cd frontend && npx tsc --noEmit` | ❌ W0 | ⬜ pending |
| 04-04-T02 | 04 | 4 | REQ-user-auth | SC #3 | grep | `grep -E "Authorization.*Bearer" frontend/src/api.ts && grep -E "401" frontend/src/api.ts` (interceptor sets header + handles 401) | ❌ W0 | ⬜ pending |
| 04-04-T03 | 04 | 4 | REQ-user-auth | SC #1 | grep + tsc | `grep -qE "Try as demo" frontend/src/components/SignInModal.tsx && cd frontend && npx tsc --noEmit && npx vitest run --passWithNoTests` | ❌ W0 | ⬜ pending |
| 04-04-T04 | 04 | 4 | REQ-user-auth | SC #1, #2 | grep | `grep -qE "SignInModal" frontend/src/pages/RouteFinder.tsx` | ❌ W0 | ⬜ pending |
| 04-04-T05 | 04 | 4 | REQ-user-auth | SC #3, #4 | **checkpoint:human-verify** | Manual: stack up, demo user seeded, click Find Route → modal opens → register new user → token in localStorage → /route returns 200 → logout clears token → modal reappears | ❌ W0 | ⬜ pending |
| 04-05-T01 | 05 | 4 | REQ-user-auth | SC #1, #4 | unit + grep | `/tmp/rq-venv/bin/python -c "import scripts.seed_demo_user as m; assert hasattr(m, 'main')" && grep -qE "ON CONFLICT \(email\) DO UPDATE" scripts/seed_demo_user.py` | ❌ W0 | ⬜ pending |
| 04-05-T02 | 05 | 4 | REQ-user-auth | SC #1 | grep | `grep -E "^AUTH_SIGNING_KEY=" .env.example && grep -E "secrets\.token_urlsafe" .env.example` | ❌ W0 | ⬜ pending |
| 04-05-T03 | 05 | 4 | REQ-user-auth | SC #1 | grep | `grep -E "AUTH_SIGNING_KEY: \\\${AUTH_SIGNING_KEY:-}" docker-compose.yml` | ❌ W0 | ⬜ pending |
| 04-05-T04 | 05 | 4 | REQ-user-auth | SC #1 | grep | `grep -E "## Public Demo" README.md && grep -E "demo@road-quality-mvp.dev" README.md && grep -E "scripts/seed_demo_user.py" README.md` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Sampling continuity:** Across all 19 tasks, the longest run of tasks without an automated verify is 0 — every task has a grep, pytest, or tsc invocation in its `<verify>` block. Task 04-04-T05 is the single human-verify checkpoint (the modal UX), explicitly out-of-band per CONTEXT.md D-04.

---

## Wave 0 Requirements

- [ ] `backend/tests/test_migration_003.py` — created in plan 04-01 task 3 (5 idempotency tests for SC #5)
- [ ] `backend/tests/test_auth_passwords.py` — created in plan 04-02 task 2 (5 unit tests for argon2id hash/verify, SC #4)
- [ ] `backend/tests/test_auth_tokens.py` — created in plan 04-02 task 2 (10 unit tests for JWT encode/decode + alg=none regression, SC #2, #4)
- [ ] `backend/tests/test_auth_routes.py` — created in plan 04-03 task 1 (18 integration tests for /auth/* + gating, SC #1, #2, #3)
- [ ] `backend/tests/conftest.py` — extended in plan 04-02 task 4 (pytest_configure sets AUTH_SIGNING_KEY default; `db_conn` fixture for integration tests reuses existing pattern from test_migration_002.py)
- [ ] No new framework install needed — pytest + httpx test client + psycopg2 already present.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|---|---|---|---|
| Sign-in modal UX | REQ-user-auth (SC #1, #3) | Modal-mount, focus trap, backdrop click, "Try as demo" autofill, 401-interceptor reopen — all visual + interaction-driven; vitest can assert prop-flow but not actual modal-feel | Plan 04-04 task 5 checkpoint:human-verify. Operator: `docker compose up -d` → seed demo user → open `/route` → click "Find Route" → modal opens → click "Try as demo" → verify auto-submit → verify token in localStorage → verify `/route` returns 200 → click sign-out → verify modal reappears on next gated call |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (1 human-verify checkpoint is intentional per CONTEXT.md D-04)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (max gap = 0)
- [x] Wave 0 covers all MISSING references (5 test files + 1 conftest extension)
- [x] No watch-mode flags (all commands are one-shot)
- [x] Feedback latency < 30s (host quick subset ~1s; container full suite ~10s)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-04-26
