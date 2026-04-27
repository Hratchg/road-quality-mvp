---
phase: 04-authentication
verified: 2026-04-25T00:00:00Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
re_verification:
  is_re_verification: false
requirements_coverage:
  - id: REQ-user-auth
    status: satisfied
    evidence: "All 5 acceptance bullets in REQUIREMENTS.md (sign up + sign in + 401 on gated endpoints + passwords hashed + no plaintext) verified against codebase + UAT results in 04-04-SUMMARY.md Task 5 section."
human_verification: []
---

# Phase 4: Authentication Verification Report

**Phase Goal:** Users can sign up, sign in, and sign out; state-mutating and expensive endpoints require auth so the public demo can't be drained by anonymous traffic.

**Verified:** 2026-04-25
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth (ROADMAP Success Criterion) | Status | Evidence |
|---|-----------------------------------|--------|----------|
| 1 | User can sign up with email + password via an API endpoint (UI optional for M1) | VERIFIED | `backend/app/routes/auth.py:50-84` defines `POST /auth/register` returning 201 with `{user_id, email, access_token, token_type}`. Frontend modal `frontend/src/components/SignInModal.tsx` exposes the register flow. UAT scenario #6 (04-04-SUMMARY.md Task 5) confirmed `POST /auth/register` returns 201 with valid response shape. |
| 2 | User can sign in, receive a session token (or cookie), and use it on subsequent requests | VERIFIED | `backend/app/routes/auth.py:87-125` defines `POST /auth/login` returning 200 with `{access_token, token_type:"bearer"}`. Token generated via `app.auth.tokens.encode_token` (HS256, 7-day expiry, sub=str(user_id)). Frontend `api.ts` injects `Authorization: Bearer <token>` on `fetchRoute` (line 40). UAT scenario #5 confirmed login → /route round-trip with `total_cost=45.65`. |
| 3 | POST /route and /cache/* return 401 without valid credentials; GET /health and GET /segments remain public | VERIFIED | `backend/app/routes/routing.py:42-45` injects `user_id: int = Depends(get_current_user_id)` on `/route`. `backend/app/routes/cache_routes.py:5` declares router-level `dependencies=[Depends(get_current_user_id)]`. `backend/app/routes/health.py` and `segments.py` are unchanged (no Depends). 401-vs-403 bug fixed in `backend/app/auth/dependencies.py:23,37-42` via `HTTPBearer(auto_error=False)` + explicit 401 raise. UAT scenarios #1-#4 confirmed all four behaviors mechanically. |
| 4 | Passwords are hashed (bcrypt/argon2-equivalent), never stored as plaintext | VERIFIED | `backend/app/auth/passwords.py:13-15` uses `pwdlib.PasswordHash.recommended()` (argon2id, m=65536/t=3/p=4). `backend/app/routes/auth.py:57` calls `hash_password(req.password)` before INSERT; line 108 calls `verify_and_maybe_rehash` (post-WR-01) on login with rehash-on-param-bump UPDATE at lines 117-123. Test `test_password_hash_in_db_is_argon2id_not_plaintext` (test_auth_routes.py) asserts `$argon2id$` prefix and plaintext absence. |
| 5 | A new migration in db/migrations/ adds the users table; the migration applies cleanly to a fresh DB via the existing init flow | VERIFIED | `db/migrations/003_users.sql` exists with locked column shape (BIGSERIAL id, TEXT email NOT NULL, TEXT password_hash NOT NULL, TIMESTAMPTZ created_at NOT NULL DEFAULT NOW()) + idempotent `CREATE UNIQUE INDEX IF NOT EXISTS users_email_key`. `docker-compose.yml:13` mounts at `/docker-entrypoint-initdb.d/04-users.sql`. UAT setup confirmed fresh `docker compose up -v` brings up DB with migration applied via init flow. `test_migration_003.py` defines 5 integration tests (idempotency + locked shape + UNIQUE rejects dups + case-sensitivity + no-demo-seed). |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `db/migrations/003_users.sql` | users table + UNIQUE email index | VERIFIED | 36 lines, contains BIGSERIAL/TEXT NOT NULL/TIMESTAMPTZ shape + `CREATE UNIQUE INDEX IF NOT EXISTS users_email_key`. No INSERT INTO users. |
| `docker-compose.yml` | Mount of 003_users.sql + AUTH_SIGNING_KEY env | VERIFIED | Line 13 mounts `003_users.sql:/docker-entrypoint-initdb.d/04-users.sql`. Line 29 declares `AUTH_SIGNING_KEY: ${AUTH_SIGNING_KEY:-}` on backend. |
| `backend/app/auth/passwords.py` | hash_password / verify_password / verify_and_maybe_rehash | VERIFIED | 58 lines; uses `PasswordHash.recommended()`; verify_password wraps in try/except for corrupt-hash safety. |
| `backend/app/auth/tokens.py` | encode_token / decode_token + Token + TokenError + _signing_key | VERIFIED | 85 lines; `algorithms=[ALGORITHM]` LIST (Pitfall 2 guard) at line 82; `EXPIRE_DAYS=7` at line 31; fail-fast on missing/short AUTH_SIGNING_KEY at lines 41-50. |
| `backend/app/auth/dependencies.py` | get_current_user_id raising 401 | VERIFIED | 59 lines; `HTTPBearer(auto_error=False)` + explicit 401 (post 401-vs-403 fix); single detail string for expired-vs-bad-sig (oracle defense). |
| `backend/app/routes/auth.py` | POST /auth/register, /auth/login, /auth/logout | VERIFIED | 138 lines; `APIRouter(prefix="/auth", tags=["auth"])`; `_normalize_email` (Pitfall 3) + `_DUMMY_HASH` (Pitfall 5) defenses; `verify_and_maybe_rehash` rehash-on-login wired (WR-01). |
| `backend/app/main.py` | auth router mounted | VERIFIED | Line 3 imports auth; line 19 calls `app.include_router(auth.router)`. CORS untouched per Phase 5 scope. |
| `backend/app/routes/routing.py` | /route gated via Depends | VERIFIED | Line 7 imports `get_current_user_id`; line 44 declares `user_id: int = Depends(get_current_user_id)` on `find_route`. |
| `backend/app/routes/cache_routes.py` | /cache/* gated router-level | VERIFIED | Line 3 imports get_current_user_id; line 5 `APIRouter(dependencies=[Depends(get_current_user_id)])`. |
| `frontend/src/api/auth.ts` | register/login/logout + token storage | VERIFIED | 75 lines; `TOKEN_KEY = "rq_auth_token"` (line 9); register/login/logout/getToken/clearToken/isAuthenticated exported; setToken NOT exported (private). |
| `frontend/src/api.ts` | fetchRoute auth + UnauthorizedError | VERIFIED | 53 lines; `UnauthorizedError extends Error` (line 7); `authHeaders()` only used by `fetchRoute` (lines 40); `fetchSegments` unmodified (line 20-24); 401 → clearToken + throw UnauthorizedError (lines 43-49). |
| `frontend/src/components/SignInModal.tsx` | login/register/Try-as-demo modal | VERIFIED | 146 lines; demo creds at lines 12-13; `z-[2000]` overlay + backdrop+stopPropagation pattern; `type="button"` on non-submit buttons (post WR-02 fix at lines 104, 117, 131); calls `register`/`login` from `../api/auth`. |
| `frontend/src/pages/RouteFinder.tsx` | catches UnauthorizedError → opens modal | VERIFIED | Line 8 imports SignInModal; line 9 imports UnauthorizedError; line 49 declares modalOpen state; line 85 catches UnauthorizedError; line 190 renders SignInModal. |
| `scripts/seed_demo_user.py` | idempotent demo-user UPSERT | VERIFIED | 108 lines; uses `from app.auth.passwords import hash_password`; `ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash`; `--password` is required (post WR-04 fix at line 62); never prints the password (only id + email). |
| `.env.example` | AUTH_SIGNING_KEY section | VERIFIED | Lines 54-64 contain the Auth section; empty placeholder (`AUTH_SIGNING_KEY=` at line 64) so backend's fail-fast triggers cleanly. |
| `README.md` | ## Public Demo Account section | VERIFIED | Section at line 175 contains demo creds, local setup, rotation procedure. (Minor doc drift on seed_demo_user.py invocation — see Anti-Patterns/Info below.) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `dependencies.py` | `tokens.py` | `from app.auth.tokens import decode_token, TokenError` | WIRED | line 17, used at line 44. |
| `tokens.py` | `AUTH_SIGNING_KEY` env var | `os.environ.get('AUTH_SIGNING_KEY', '')` inside `_signing_key()` | WIRED | line 40 in `_signing_key()`. |
| `routes/auth.py` | `passwords.py` | `from app.auth.passwords import hash_password, verify_password, verify_and_maybe_rehash` | WIRED | line 17; `hash_password` at line 57; `verify_and_maybe_rehash` at line 108 (post WR-01). |
| `routes/auth.py` | `tokens.py` | `from app.auth.tokens import encode_token, Token` | WIRED | line 18; `encode_token` at lines 79, 124. |
| `routes/auth.py` | DB | `from app.db import get_connection` + parameterized SQL | WIRED | line 16; INSERT at lines 65-69; SELECT at lines 94-97; UPDATE rehash at lines 120-123. |
| `routing.py` | `dependencies.py` | `Depends(get_current_user_id)` | WIRED | per-route at line 44. |
| `cache_routes.py` | `dependencies.py` | `dependencies=[Depends(get_current_user_id)]` | WIRED | router-level at line 5. |
| `main.py` | `routes/auth.py` | `app.include_router(auth.router)` | WIRED | line 19. |
| `frontend/api.ts` | `frontend/api/auth.ts` | `import { getToken, clearToken } from "./api/auth"` | WIRED | line 1; `getToken` used in `authHeaders` line 15; `clearToken` called on 401 line 47. |
| `SignInModal.tsx` | `frontend/api/auth.ts` | `import { register, login } from "../api/auth"` | WIRED | line 2; both called in handlers. |
| `RouteFinder.tsx` | `SignInModal.tsx` | `import SignInModal from "../components/SignInModal"` | WIRED | line 8; rendered at line 190. |
| `RouteFinder.tsx` | `api.ts` | `import { ... UnauthorizedError } from "../api"` | WIRED | line 9; `instanceof UnauthorizedError` check at line 85. |
| `seed_demo_user.py` | `passwords.py` | `from app.auth.passwords import hash_password` | WIRED | line 44 (after sys.path tweak). |
| `docker-compose.yml` | operator-supplied .env | `${AUTH_SIGNING_KEY:-}` interpolation | WIRED | line 29 (backend service). |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|---------|
| `routes/auth.py register()` | `user_id`, `email`, `token` | DB INSERT RETURNING id + `encode_token(user_id)` | Yes — RETURNING from real INSERT against users table | FLOWING |
| `routes/auth.py login()` | `stored_hash`, `user_id`, `token` | SELECT FROM users WHERE email = %s | Yes — real SELECT against migrated users table | FLOWING |
| `routing.py find_route()` | `user_id` | `Depends(get_current_user_id)` → JWT `sub` claim | Yes — extracted from real JWT signed via AUTH_SIGNING_KEY | FLOWING |
| `frontend/api.ts fetchRoute()` | `Authorization` header | `getToken()` → localStorage `rq_auth_token` | Yes — token written by `register`/`login` after live API call | FLOWING |
| `SignInModal.tsx` | `email`/`password` state | controlled inputs from user | Yes — passed to real `login`/`register` calls | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|---------|
| Auth unit tests pass | `AUTH_SIGNING_KEY="test_secret_do_not_use_in_production_padding_padding" /tmp/rq-venv/bin/python -m pytest backend/tests/test_auth_passwords.py backend/tests/test_auth_tokens.py -q` | `15 passed in 0.24s` | PASS |
| App routes mount cleanly | `cd backend && AUTH_SIGNING_KEY=... python -c "from app.main import app; ..."` | `/auth/login, /auth/logout, /auth/register, /cache/clear, /cache/stats, /health, /route, /segments` all present | PASS |
| Migration idempotent + correct shape | UAT scenario (04-04-SUMMARY.md Task 5): `docker compose down -v && docker compose up --build -d` brought up DB with migrations 001/002/003 applied via init flow | All 5 SCs exercised end-to-end | PASS |
| Seed script `--password` required | `/tmp/rq-venv/bin/python scripts/seed_demo_user.py` (no args) | `error: the following arguments are required: --password` | PASS (correct fail-fast post WR-04) |
| Integration tier (auth routes) | `docker compose exec backend pytest tests/test_auth_routes.py -m integration` | 18/18 passed (per 04-04-SUMMARY.md Task 5 + 04-03-SUMMARY.md) | PASS |

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|----------------|-------------|--------|----------|
| REQ-user-auth | 04-01, 04-02, 04-03, 04-04, 04-05 | Backend authentication gates state-mutating and expensive endpoints. Sign up + sign in via API, gated /route + /cache/*, hashed passwords, 401 on missing/invalid creds. | SATISFIED | All 4 acceptance bullets met: (a) sign up + sign in API endpoints exist and work end-to-end; (b) `/route` and `/cache/*` return 401 without creds, `/health` and `/segments` remain public; (c) invalid/missing creds return 401 (verified mechanically post 401-vs-403 fix); (d) passwords hashed via argon2id, no plaintext (test_password_hash_in_db_is_argon2id_not_plaintext + grep). |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `README.md` | 206 | Documents `python scripts/seed_demo_user.py` (no args), but post-WR-04 the script requires `--password`. Operator following the README literally would hit `error: the following arguments are required: --password`. | Info | Minor doc drift introduced by WR-04 fix. Does NOT affect any of the 5 success criteria (SC#5 is migration applies cleanly via init flow, not the seed script). The local-setup step would error out for an operator following it verbatim, but the error is self-explanatory and the next section (line 215) shows the correct `--password $NEW_DEMO_PASSWORD` form. Recommend follow-up: update line 206 to `python scripts/seed_demo_user.py --password demo1234` (or reference the README's documented current password). |

No blocker or warning anti-patterns found. All audit-level checks pass:
- No `logger.*`/`print(...)` of password/password_hash/AUTH_SIGNING_KEY/token bodies in `backend/app/auth/` or `backend/app/routes/auth.py` (only `logger.info("user registered: id=%d", user_id)` which logs only the integer id).
- No `INSERT INTO route_requests` in `/auth/register` or `/auth/login` (Pitfall 1 — no plaintext password leak via audit log).
- No `INSERT INTO users` in `db/migrations/003_users.sql` (D-05 — demo seeding lives in `scripts/seed_demo_user.py`).
- localStorage single-seam invariant holds: only `frontend/src/api/auth.ts` calls `localStorage.{get,set,remove}Item`.
- `fetchSegments` does NOT inject `Authorization` header (SC#3 negative — `/segments` stays public).
- `decode_token` uses `algorithms=[ALGORITHM]` LIST (Pitfall 2 — alg-substitution defense).

### Human Verification Required

None. Live UAT was already executed by the orchestrator on 2026-04-27 covering all 5 SCs end-to-end (8 scenarios documented in 04-04-SUMMARY.md Task 5 — Human-Verify Resolution section). Visual modal-styling items are explicitly deferred-to-operator in that section and are non-mechanical (do not affect any SC).

### Gaps Summary

No gaps blocking goal achievement. All 5 ROADMAP success criteria are satisfied:

1. **Sign up via API** — `POST /auth/register` ships, returns 201 with token, exercised by UAT.
2. **Sign in + token usable on subsequent requests** — `POST /auth/login` returns JWT, `Authorization: Bearer <token>` is consumed by gated endpoints, UAT scenario #5 confirmed end-to-end round-trip.
3. **401 on gated endpoints, public endpoints stay open** — `/route` per-route Depends, `/cache/*` router-level Depends, `/health` and `/segments` unchanged. Post-fix dependencies.py uses `auto_error=False` + explicit 401 (correctly returns 401 not 403).
4. **Passwords hashed (argon2id), never plaintext** — pwdlib's `PasswordHash.recommended()`; verify_and_maybe_rehash wired in login (post-WR-01); test_password_hash_in_db_is_argon2id_not_plaintext asserts the contract.
5. **Migration adds users table, applies cleanly via init flow** — `db/migrations/003_users.sql` mounts at `/docker-entrypoint-initdb.d/04-users.sql`; UAT confirmed fresh stack brings up the schema correctly.

REQ-user-auth (the only Phase 4 requirement per REQUIREMENTS.md) is fully satisfied.

One info-level documentation drift was found (README line 206 references `python scripts/seed_demo_user.py` without the now-required `--password` arg). This does not block goal achievement and is filed as info-level for follow-up polish.

---

_Verified: 2026-04-25_
_Verifier: Claude (gsd-verifier)_
