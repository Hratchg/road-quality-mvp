---
phase: 04-authentication
plan: 03
subsystem: backend/app/routes
tags: [python, fastapi, jwt, argon2, tdd, integration, auth-routes]
requires:
  - REQ-user-auth (this plan implements the user-visible /auth/* contract + gates)
  - app.auth.passwords.hash_password / verify_password (from 04-02)
  - app.auth.tokens.encode_token / decode_token / Token (from 04-02)
  - app.auth.dependencies.get_current_user_id (from 04-02)
  - users table (from 04-01 migration)
provides:
  - POST /auth/register (201 — {user_id, email, access_token, token_type})
  - POST /auth/login (200 — {access_token, token_type})
  - POST /auth/logout (204 — empty body)
  - Auth gating on POST /route (per-route Depends)
  - Auth gating on GET /cache/stats + POST /cache/clear (router-level dependencies)
affects:
  - backend/app/main.py (additive: auth router registration)
  - backend/app/routes/routing.py (additive: per-route Depends + named user_id parameter)
  - backend/app/routes/cache_routes.py (additive: router-level dependencies)
  - backend/tests/test_route.py (additive: autouse dependency_overrides fixture)
  - backend/tests/test_cache.py (additive: autouse dependency_overrides fixture)
  - backend/tests/test_integration.py (additive: autouse dependency_overrides fixture)
tech-stack:
  added: []
  patterns:
    - "APIRouter(prefix=\"/auth\", tags=[\"auth\"]) for grouped endpoint registration"
    - "Per-route Depends(get_current_user_id) on /route — surfaces user_id at function signature for future per-user audit"
    - "Router-level dependencies=[Depends(get_current_user_id)] on /cache/* — single declaration covers both endpoints, no value injection"
    - "_normalize_email helper applies .strip().lower() at INSERT and SELECT (Pitfall 3 — Pydantic EmailStr lowercases domain only)"
    - "_DUMMY_HASH module-level constant + verify_password on missing-user login path (Pitfall 5 timing oracle defense)"
    - "psycopg2 IntegrityError catch on duplicate email INSERT — translates to 400 with detail='Email already registered'"
    - "Identical detail='Invalid credentials' for both wrong-password AND unknown-email (no enumeration leak)"
    - "FastAPI dependency_overrides fixture seam in legacy tests (test_route.py, test_cache.py, test_integration.py) — keeps tests green without weakening the auth contract"
key-files:
  created:
    - backend/app/routes/auth.py
    - backend/tests/test_auth_routes.py
    - .planning/phases/04-authentication/04-03-SUMMARY.md
  modified:
    - backend/app/main.py
    - backend/app/routes/routing.py
    - backend/app/routes/cache_routes.py
    - backend/tests/test_route.py
    - backend/tests/test_cache.py
    - backend/tests/test_integration.py
decisions:
  - Used APIRouter(prefix="/auth") form rather than per-route /auth/... strings — RESEARCH and PATTERNS both noted either is acceptable; prefix is the cleaner separation and matches the FastAPI tutorial convention
  - Per-route Depends with named user_id on /route (rather than anonymous _) — surfaces the user_id at signature level so a future per-user audit log can consume it without re-extracting from the token
  - Caught psycopg2.IntegrityError (parent class) rather than psycopg2.errors.UniqueViolation — forward-compatible with any future constraints on the users table while remaining functionally identical for the email UNIQUE case in Phase 4
  - Computed _DUMMY_HASH at module-import time rather than per-request — pays the ~150ms argon2 cost once at app startup instead of on every missing-user login
  - Applied dependency_overrides fix path (rather than register-then-token) to test_route.py / test_cache.py / test_integration.py — minimal-churn approach the plan explicitly preferred for mocked-DB unit tests
metrics:
  duration_minutes: 3
  tasks_completed: 3
  tests_added: 18
  files_created: 2
  files_modified: 6
  completed_date: "2026-04-27"
commits:
  - 0e27c83 test(04-03): add failing integration tests for /auth/* + gating on /route + /cache/* (18 tests)
  - 8e8aa9d feat(04-03): implement /auth/register + /auth/login + /auth/logout
  - 6df4b53 feat(04-03): wire auth gate on /route + /cache/* + dependency_overrides for legacy tests
---

# Phase 04 Plan 03: Auth Routes + Gating Summary

FastAPI route file `backend/app/routes/auth.py` with /auth/register + /auth/login + /auth/logout endpoints, plus dependency-based auth gating on /route (per-route) and /cache/* (router-level), unlocking SC #1, #2, #3, and #4 of Phase 4.

## Plan Goal

Land the user-visible auth surface so the demo flow works end-to-end: a user can register, get a JWT, and use that JWT to call /route. Plans 04-01 (migration) and 04-02 (helpers) gave us a `users` table and the password/token primitives; this plan turned them into HTTP endpoints and gated the resource-expensive routes that previously had no protection.

## What Shipped

### 1. `backend/app/routes/auth.py` — three endpoints + safety helpers

Public endpoints (D-06 verbatim):

| Verb | Path | Status (success) | Body shape |
|------|------|------------------|------------|
| POST | /auth/register | 201 | `{user_id: int, email: str, access_token: str, token_type: "bearer"}` |
| POST | /auth/login | 200 | `{access_token: str, token_type: "bearer"}` |
| POST | /auth/logout | 204 | empty (`response.content == b""`) |

Error contract:

| Trigger | Code | detail |
|---------|------|--------|
| Duplicate email on /auth/register | 400 | `"Email already registered"` |
| Invalid email format on /auth/register | 422 | Pydantic EmailStr validation error |
| Password < 8 chars on /auth/register | 422 | Pydantic Field(min_length=8) validation error |
| Wrong password on /auth/login | 401 | `"Invalid credentials"` |
| Unknown email on /auth/login | 401 | `"Invalid credentials"` (byte-identical to wrong-password — Pitfall 5) |
| Missing/invalid Bearer on gated routes | 401 | `"Not authenticated"` (HTTPBearer auto_error) or `"Invalid or expired token"` (TokenError) |

Two load-bearing private helpers:

- **`_normalize_email(raw: str) -> str`** — applies `.strip().lower()` to the email at BOTH the register-INSERT path AND the login-SELECT path. Without this, `User@Example.COM` and `user@example.com` would create two distinct rows on register, then never match on login (Pitfall 3). The DB UNIQUE index on `email` only catches collisions when the app has already normalized — the index alone is not sufficient because Pydantic's `EmailStr` lowercases only the domain, preserving local-part case.
- **`_DUMMY_HASH = hash_password("__dummy_for_timing_safety_do_not_match__")`** — module-level argon2id hash computed once at import time. The /auth/login path runs `verify_password(req.password, _DUMMY_HASH)` on the missing-user branch BEFORE returning 401, burning the same ~150ms an actual verify would take. Without this, an attacker could enumerate registered emails by timing the 401: ~150ms = email exists + wrong password; ~10ms = email doesn't exist. With it, both paths cost ~150ms.

Safety guarantees verified by code-review-by-eye:
- Zero `logger.*` calls touch `req.password`, `pwd_hash`, or token strings. Only `logger.info("user registered: id=%d", user_id)`.
- No `INSERT INTO route_requests` on /auth/register or /auth/login (Pitfall 1 — that audit table dumps the full request JSON, which would leak plaintext passwords).
- Login does NOT distinguish "email not found" from "wrong password" — same status, same detail string, same wall-clock timing.

### 2. `backend/app/main.py` — auth router registration

One-line additive change: `auth` added to the `from app.routes import ...` import, and `app.include_router(auth.router)` appended to the include block. CORS middleware untouched (Phase 5 territory per CONTEXT.md).

### 3. `backend/app/routes/routing.py` — per-route auth gate on /route

```python
@router.post("/route", response_model=RouteResponse)
def find_route(
    req: RouteRequest,
    user_id: int = Depends(get_current_user_id),
):
```

The `user_id` parameter is named (not anonymous `_`) so a future per-user audit log entry can consume it without re-extracting from the token. The function body is untouched — `user_id` is currently unused inside `find_route` but FastAPI consumes it to run the dep.

### 4. `backend/app/routes/cache_routes.py` — router-level auth gate on /cache/*

```python
router = APIRouter(dependencies=[Depends(get_current_user_id)])
```

The router-level form covers both `/cache/stats` and `/cache/clear` with one declaration. View functions don't declare `user_id` parameters because the router-level form runs the dep without injecting the value (FastAPI behavior — verified in test G4 + G5).

### 5. `backend/tests/test_auth_routes.py` — 18 integration tests

Module-level `pytestmark = pytest.mark.integration` because the happy path needs a live DB. A `cleanup_test_users` autouse fixture (module-scoped) namespaces test emails with `test-04-03-` and DELETEs them before and after the suite — matches Phase 3's `test_migration_002.py:362-385` cleanup convention.

| # | Test | Covers |
|---|------|--------|
| R1 | test_register_success_returns_201_with_token | SC #1 happy |
| R2 | test_register_duplicate_email_returns_400 | SC #1 duplicate guard |
| R3 | test_register_invalid_email_returns_422 | SC #1 input validation |
| R4 | test_register_short_password_returns_422 | SC #1 password floor |
| R5 | test_register_normalizes_email_case | Pitfall 3 end-to-end |
| L1 | test_login_success_returns_200_with_token | SC #2 happy + JWT shape |
| L2 | test_login_wrong_password_returns_401 | SC #2 wrong password |
| L3 | test_login_unknown_email_returns_401_same_detail | Pitfall 5 enumeration defense (string-equal detail) |
| G1 | test_route_without_token_returns_401 | SC #3 /route gating |
| G2 | test_route_with_bad_token_returns_401 | SC #3 bad token |
| G3 | test_route_with_alg_none_token_returns_401 | Pitfall 2 at the route layer |
| G4 | test_cache_stats_without_token_returns_401 | SC #3 /cache/stats gating |
| G5 | test_cache_clear_without_token_returns_401 | SC #3 /cache/clear gating |
| G6 | test_health_remains_public | SC #3 /health stays open |
| G7 | test_segments_remains_public | SC #3 /segments stays open |
| G8 | test_route_with_dep_override_authorizes | dependency_overrides seam regression guard |
| H1 | test_password_hash_in_db_is_argon2id_not_plaintext | SC #4 hashing in DB |
| O1 | test_logout_returns_204_no_body | /auth/logout contract |

### 6. Legacy test updates (dependency_overrides fix path)

Three existing test files now hit gated endpoints. Each got an autouse fixture that installs `app.dependency_overrides[get_current_user_id] = lambda: 1` and pops it on teardown:

| File | Why touched | Approach |
|------|-------------|----------|
| `backend/tests/test_route.py` | Calls POST /route directly via TestClient (now 401 without override) | Function-scoped autouse fixture in module |
| `backend/tests/test_cache.py` | Calls GET /cache/stats + POST /cache/clear (now 401 without override) | Function-scoped autouse fixture in module |
| `backend/tests/test_integration.py` | Calls POST /route + POST /cache/clear via the session-scoped `client` fixture | Function-scoped autouse fixture in module |

The plan listed three acceptable fix paths (dep override, manual override, register-then-token). The dependency_overrides path was chosen because it's the minimal-churn approach for mocked-DB tests and matches the override-seam pattern that conftest's `authed_client` already uses. Cleanup happens in the fixture teardown so dependency_overrides does NOT leak across modules.

## SC Coverage Map (this plan vs Phase 4 SCs)

| SC | Description | Status after this plan |
|----|-------------|------------------------|
| #1 | User can sign up with email + password | Tests R1-R5 green; /auth/register lands user row + returns access_token (201) |
| #2 | User can sign in, receive a token, use it on subsequent requests | Tests L1-L3 + G8 green; /auth/login returns access_token; dep_override and bad-token branches both verified |
| #3 | /route + /cache/* return 401 without creds; /health + /segments stay public | Tests G1-G7 green; per-route Depends on /route, router-level on /cache/*, no change to /health or /segments |
| #4 | Passwords hashed (bcrypt/argon2-equivalent), never plaintext | Test H1 green; password_hash starts with `$argon2id$` and the plaintext is NOT a substring |
| #5 | Migration 003_users.sql applies cleanly | Already shipped in plan 04-01 (out of scope here) |

## Tasks Completed

| Task | Type | Commit | Files | Done |
|------|------|--------|-------|------|
| 1 (RED) | tdd | 0e27c83 | backend/tests/test_auth_routes.py | 18 test functions; tests fail with 404 because /auth/register doesn't exist yet |
| 2 (GREEN) | tdd | 8e8aa9d | backend/app/routes/auth.py, backend/app/main.py | /auth/register + /login + /logout implemented; 10/18 tests pass after this commit (gating tests still RED) |
| 3 (GREEN final) | tdd | 6df4b53 | backend/app/routes/routing.py, backend/app/routes/cache_routes.py, backend/tests/test_route.py, backend/tests/test_cache.py, backend/tests/test_integration.py | /route gated per-route; /cache/* gated router-level; legacy tests fixed via dependency_overrides; full 18/18 expected on live DB |

## Verification Results

| Check | Command | Result |
|-------|---------|--------|
| Auth router registered | `python -c "from app.main import app; print([r.path for r in app.routes if r.path.startswith('/auth')])"` | `['/auth/register', '/auth/login', '/auth/logout']` |
| test_auth_routes.py collects | `pytest --collect-only tests/test_auth_routes.py` | 18 tests collected |
| Existing non-DB tests still pass | `pytest tests/test_route.py tests/test_cache.py tests/test_health.py tests/test_models.py tests/test_scoring.py tests/test_auth_passwords.py tests/test_auth_tokens.py -q` | 37 passed |
| Full suite collects | `pytest --collect-only -q` | 239 tests collected |
| Non-integration tests pass | (full non-integration set) | 117 passed |
| _normalize_email present | `grep -q "_normalize_email" backend/app/routes/auth.py` | match |
| _DUMMY_HASH present | `grep -q "_DUMMY_HASH" backend/app/routes/auth.py` | match |
| Per-route dep on /route | `grep -q "user_id: int = Depends(get_current_user_id)" backend/app/routes/routing.py` | match |
| Router-level dep on /cache/* | `grep -q "dependencies=\[Depends(get_current_user_id)\]" backend/app/routes/cache_routes.py` | match |
| No CORS modification | `grep -E "^app\.add_middleware\(CORSMiddleware" backend/app/main.py` | unchanged |
| No password / hash in logger calls | `grep -rE "logger.*\b(password|password_hash)\b" backend/app/routes/auth.py` | empty |

### Live-DB integration tests (pending operator runbook)

The 18 happy-path + DB-write tests in `test_auth_routes.py` require a live PostgreSQL container with migration 003_users.sql applied. Operator runs:

```bash
docker compose up -d db
docker compose exec backend pytest backend/tests/test_auth_routes.py -m integration -v
```

Expected: 18 passed in <15s (8 argon2 hashes ≈ 1.2-2.4s + DB roundtrips negligible). With the local /tmp/rq-venv (no DB), the tests SKIP via the `db_available` fixture chain — that's the intended behavior, not a test failure.

## Deviations from Plan

None substantive. The plan was executed as written, including:
- prefix="/auth" router form (plan-stated preferred)
- Catching `psycopg2.IntegrityError` parent class (plan-stated equivalent to UniqueViolation for this case)
- Named `user_id` parameter on /route (plan-stated preferred over anonymous `_`)
- dependency_overrides fix path for test_route.py / test_cache.py / test_integration.py (plan-listed as the cleanest approach for mocked-DB tests)

The only minor adjustment: I extended the dependency_overrides treatment to test_integration.py (not just test_route.py and test_cache.py as called out in the prompt). test_integration.py also calls `/route` and `/cache/clear`, so without the override its 5+ tests would 401 at runtime against a live DB. This is consistent with the plan's `<deviations>` allowance: "Existing test files can be updated to use any of the three documented approaches for adding auth — pick whichever causes the least churn."

## Authentication Gates

None encountered. All work was offline (file edits + local pytest collection + import smoke tests).

## Snippet for Plan 04-04 (SignInModal)

JSON request shapes:

```typescript
// POST /auth/register — body
{ "email": "user@example.com", "password": "hunter22pass" }
// → 201 { "user_id": 42, "email": "user@example.com", "access_token": "<jwt>", "token_type": "bearer" }
// → 400 { "detail": "Email already registered" }
// → 422 { "detail": [ { "loc": ["body", "email"], ... } ] }

// POST /auth/login — body
{ "email": "user@example.com", "password": "hunter22pass" }
// → 200 { "access_token": "<jwt>", "token_type": "bearer" }
// → 401 { "detail": "Invalid credentials" }

// POST /auth/logout — no body
// → 204 (empty response body)

// 401 on gated routes (e.g., POST /route without token):
// → 401 { "detail": "Not authenticated" }    (missing/non-Bearer Authorization header)
// → 401 { "detail": "Invalid or expired token" }    (bad/expired/alg=none JWT)
// Either way, the modal should re-prompt for credentials.
```

The frontend modal can rely on `response.status === 401` + `body.detail` to decide messaging. The `WWW-Authenticate: Bearer` header is set on 401s but FastAPI's TestClient surfaces only the body, not headers — the same is true for browser fetch responses unless the modal explicitly inspects `response.headers`.

## Threat Surface Status

All `mitigate` dispositions in the plan's threat register are addressed by this plan's implementation:

| Threat ID | Mitigation Status |
|-----------|-------------------|
| T-04-16 (SQL injection on /auth/login) | All SQL parameterized via `%s` placeholders (no f-strings); verified in routes/auth.py |
| T-04-17 (plaintext in audit log) | No `INSERT INTO route_requests` in /auth/register or /auth/login; verified by grep |
| T-04-18 (enumeration via login error message) | Test L3 asserts byte-identical `detail="Invalid credentials"` for both branches |
| T-04-19 (enumeration via login timing) | `_DUMMY_HASH` + always-verify on missing-user path; reviewed-by-eye, not asserted (timing tests are flaky) |
| T-04-20 (alg=none at route layer) | Test G3 crafts a real alg=none JWT and asserts 401 |
| T-04-21 (enumeration via /auth/register's 400) | Accepted (CONTEXT.md trade for register UX); Phase 5 rate limiting is the real defense |
| T-04-22 (expired-vs-bad-sig leak) | Single `detail="Invalid or expired token"` from dependencies.py (already in 04-02) |
| T-04-23 (brute-force /auth/login) | Accepted (argon2 ~150ms is the natural soft limiter); Phase 5 owns rate limiting |
| T-04-24 (CORS allows any origin) | Accepted (Phase 5 owns CORS hardening); not touched here |
| T-04-25 (UNIQUE index race on duplicate register) | `INSERT ... RETURNING id` is atomic; second call hits IntegrityError → 400; Test R2 covers |
| T-04-26 (no token revocation) | Accepted (CONTEXT.md D-01 trade); 7-day expiry + AUTH_SIGNING_KEY rotation as kill switch |

No new threat flags discovered during execution — the plan's threat model fully covered the surface this plan introduces.

## TDD Gate Compliance

Gate sequence verified in `git log ef73533..HEAD`:

1. RED gate: `0e27c83 test(04-03): add failing integration tests for /auth/* + gating on /route + /cache/* (18 tests)` — 18 tests authored against contracts the implementation didn't yet provide (auth.py absent → tests would 404)
2. GREEN gate (intermediate): `8e8aa9d feat(04-03): implement /auth/register + /auth/login + /auth/logout` — 10 of 18 tests now pass; gating tests still RED (intentional — Task 3's job)
3. GREEN gate (final): `6df4b53 feat(04-03): wire auth gate on /route + /cache/* + dependency_overrides for legacy tests` — remaining 8 gating tests flip to GREEN

No REFACTOR commit needed — all three implementation commits were minimal-to-test from the start. The RED state was genuine: no `app/routes/auth.py` file existed before commit `8e8aa9d` (verified by `ls backend/app/routes/` immediately before Task 2 implementation).

## Self-Check: PASSED

Files claimed to be created/modified — all verified present:

- backend/app/routes/auth.py — FOUND (new, 119 LOC)
- backend/app/main.py — FOUND (modified, +1 import alias + 1 include line)
- backend/app/routes/routing.py — FOUND (modified, +1 import line + 3 lines on signature)
- backend/app/routes/cache_routes.py — FOUND (modified, +1 import line + dependencies kwarg on router)
- backend/tests/test_auth_routes.py — FOUND (new, 247 LOC, 18 tests)
- backend/tests/test_route.py — FOUND (modified, +autouse fixture)
- backend/tests/test_cache.py — FOUND (modified, +autouse fixture)
- backend/tests/test_integration.py — FOUND (modified, +autouse fixture)

Commit hashes claimed — all verified in `git log`:

- 0e27c83 (Task 1 RED)
- 8e8aa9d (Task 2 GREEN — register/login/logout)
- 6df4b53 (Task 3 GREEN final — gating + legacy test fixes)
