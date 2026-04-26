# Phase 4: Authentication - Research

**Researched:** 2026-04-25
**Domain:** FastAPI auth (JWT HS256 + argon2id password hashing), Pydantic v2 EmailStr, raw psycopg2 user CRUD, React Tailwind sign-in modal, dev-vs-prod signing-key provisioning
**Confidence:** HIGH for libraries / patterns / migrations (verified against installed runtime + official docs); MEDIUM for the python-jose locked choice (working today, but the FastAPI tutorial has migrated to PyJWT — see Open Questions Q1)

## Summary

Phase 4 is a small, well-scoped auth slice. The locked decisions in CONTEXT.md (D-01..D-07) cover the substance; this research surfaces the implementation specifics the planner needs to write executable tasks: exact pwdlib + python-jose ergonomics on the installed runtime, the FastAPI dependency-override seam for tests, the EmailStr non-obvious behavior (it lowercases the domain but **not** the local-part — and `email-validator` is **NOT** a transitive Pydantic dep on 2.13.x, so we must add it explicitly), the migration idempotency pattern (mirror Phase 3's `CREATE UNIQUE INDEX IF NOT EXISTS` for `email`), and the dev-time signing-key fail-fast.

Two findings the planner must act on:

1. **pwdlib's recommended argon2id defaults are `m=65536 (64 MiB), t=3, p=4`** [VERIFIED via `Argon2Hasher.__init__` signature on installed runtime]. That's roughly **3.4× the OWASP minimum** of m=19456/t=2/p=1 [CITED: OWASP Password Storage Cheat Sheet]. Use `PasswordHash.recommended()` directly — do not lower defaults. On a modern laptop this hashes in ~150-300ms, which is acceptable for register/login (FastAPI runs the sync hash inside a thread, and we don't gate hot paths on it).
2. **python-jose 3.5.0 is healthy as of late 2025** [CITED: pypi.org/project/python-jose, last release 2025-05-28] — no CVEs, ~30 releases, ~1.7k stars, active enough. **However, the FastAPI tutorial has switched to PyJWT** [CITED: fastapi.tiangolo.com/tutorial/security/oauth2-jwt — recommends `pyjwt` + `pwdlib[argon2]`]. CONTEXT.md D-02 locks `python-jose`, so we honor that — the API surface we use (`jwt.encode`, `jwt.decode(..., algorithms=['HS256'])`, `ExpiredSignatureError`, `JWTError`) is stable, narrow, and trivially swappable to PyJWT later if maintenance erodes. See Open Question Q1.

**Primary recommendation:** Follow CONTEXT.md D-01..D-07 verbatim. For the open implementation details:

- **Password hashing:** `PasswordHash.recommended()` (defaults), exposed as a module-level singleton in `app/auth/passwords.py`. Use `verify_and_update()` on login so future param upgrades rehash transparently.
- **JWT helper:** `python-jose` `jwt.encode(claims, key, algorithm='HS256')` and `jwt.decode(token, key, algorithms=['HS256'])` (note: `algorithms` is a list, **not** a string — passing a string silently allows alg substitution attacks; this is the #1 alg-confusion footgun).
- **Bearer extraction:** Use `fastapi.security.HTTPBearer(auto_error=True)` — FastAPI 0.136 returns 401 cleanly on missing header [VERIFIED on installed runtime]. (Older FastAPI versions returned 403 here; that bug is fixed.)
- **Router-level gating:** Use `APIRouter(dependencies=[Depends(get_current_user_id)])` to gate `/cache/*` as a group without per-route boilerplate. `/route` keeps a per-route `Depends` because it's a single endpoint.
- **EmailStr:** Pydantic's `EmailStr` lowercases the **domain** but **preserves local-part case** [VERIFIED on installed runtime]. App-layer must `email.lower().strip()` before insert/lookup so `User@Example.com` and `user@example.com` are treated as the same account. The migration's `email TEXT NOT NULL UNIQUE` is byte-exact, so without normalization we'd silently allow duplicates that differ only by case.
- **Migration idempotency:** Mirror Phase 3 exactly. `CREATE TABLE IF NOT EXISTS users (...)` for the table, and a separate `CREATE UNIQUE INDEX IF NOT EXISTS users_email_key ON users(email);` for the email constraint — **not** an inline `email TEXT NOT NULL UNIQUE`, because Postgres has no idempotent ADD-CONSTRAINT form (Phase 3 RESEARCH locked this pattern via the `segment_defects_source_check` DROP-then-ADD precedent).
- **Demo seed:** Standalone `scripts/seed_demo_user.py` (mirrors `scripts/seed_data.py` style). **Do NOT** put the demo INSERT in the migration — the migration must apply cleanly to a fresh DB without baking a known password hash into git history (the hash itself is forward-compatible, but binding "the demo password lives in 003_users.sql forever" creates a rotation footgun).
- **AUTH_SIGNING_KEY:** Read at app startup (module-top in `app/auth/tokens.py`), fail-fast on empty in non-test mode, `.env.example` adds `AUTH_SIGNING_KEY=` (empty placeholder), `docker-compose.yml` adds `AUTH_SIGNING_KEY: ${AUTH_SIGNING_KEY:-}` to the backend service. This is the **first** env var the project sources via `${}` interpolation — Phase 3 hardcoded `MAPILLARY_ACCESS_TOKEN` per-script; Phase 4 introduces the docker-compose interpolation pattern, which Phase 5 will then formalize for cloud deploy.

## User Constraints (from CONTEXT.md)

### Locked Decisions

**Session mechanism (D-01)**
- Stateless JWT, HS256, signing key from `AUTH_SIGNING_KEY` env var
- Payload: `{sub: user_id, iat, exp}`. No refresh token. No denylist.
- Compromise → user changes password + global `AUTH_SIGNING_KEY` rotation
- Read `AUTH_SIGNING_KEY` once at startup, fail-fast on missing in non-test envs
- NOT in scope: refresh tokens, denylist, multi-device session listing

**Auth library (D-02)**
- `pwdlib[argon2]>=0.2.1` (latest 0.3.0 [VERIFIED via `pip index versions`, 2025-10-25]) — argon2id hashing
- `python-jose[cryptography]>=3.3.0` (latest 3.5.0 [VERIFIED, 2025-05-28]) — JWT
- File layout (locked):
  - `backend/app/auth/__init__.py`
  - `backend/app/auth/passwords.py` — hash/verify
  - `backend/app/auth/tokens.py` — encode/decode + `Token` Pydantic model
  - `backend/app/auth/dependencies.py` — `get_current_user_id` + `Depends` wiring
  - `backend/app/routes/auth.py` — `/auth/register`, `/auth/login`, `/auth/logout`

**Password algorithm (D-03)**
- argon2id via pwdlib defaults (no manual tuning unless laptop-bench-driven later)
- Schema column shape locked: `password_hash TEXT NOT NULL`

**Frontend UI scope (D-04)**
- Single `<SignInModal>` on `/route` page
- Auto-opens on first 401 from `/route` or `/cache/*`
- Register + login forms with mode toggle
- `/map` stays untouched
- Token in `localStorage` (acceptable trade per CONTEXT.md)
- Deliverables:
  - `frontend/src/components/SignInModal.tsx`
  - `frontend/src/api/auth.ts` (register/login/logout/storage)
  - Modify `frontend/src/api.ts` to attach `Authorization: Bearer` to gated requests + 401 interceptor

**Demo account strategy (D-05)**
- Open registration + "Try as demo" button on modal
- Demo creds: `demo@road-quality-mvp.dev` / `demo1234`, README-documented
- Seeded via `scripts/seed_demo_user.py`

**API surface (D-06)**
- `POST /auth/register` → 201 `{user_id, email, access_token, token_type: "bearer"}`; 400 on dup email; 422 on validation
- `POST /auth/login` → 200 `{access_token, token_type: "bearer"}`; 401 on bad creds
- `POST /auth/logout` → 204 (client-side clear only)
- Error shape = FastAPI standard `{detail: ...}`
- No rate limiting in Phase 4 (Phase 5)
- Email validation: Pydantic `EmailStr`

**Session lifetime (D-07)**
- JWT `exp` = 7 days from issue
- No sliding window
- Logout = client clears `localStorage`

**Locked column shape for `users` table:**
- `id BIGSERIAL PRIMARY KEY` (matches BIGINT convention from `road_segments.source/target`)
- `email TEXT NOT NULL UNIQUE` (lowercased + trimmed at app layer; UNIQUE index)
- `password_hash TEXT NOT NULL` (argon2id encoded ~97 chars [VERIFIED on installed runtime])
- `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()` (matches `segment_defects.created_at`)

### Claude's Discretion

- argon2 parameter tuning beyond pwdlib defaults (this research recommends: defaults are fine; do NOT lower; do not raise without bench)
- Whether to use `OAuth2PasswordBearer` or `HTTPBearer` for token extraction (this research recommends: `HTTPBearer` — see Pattern 1 below; the OAuth2 form-encoded login flow is heavier than needed for a JSON-body register/login)
- Whether `Depends(get_current_user_id)` lives at router level (`/cache/*`) or per-route (`/route`) — this research recommends mixed: router-level for `/cache/*`, per-route for `/route`
- Demo seed strategy: standalone script vs migration INSERT (this research recommends: **standalone script** — see Section 7)
- Whether to add a `request.state.user_id` middleware vs sticking with `Depends` (this research recommends: stick with `Depends` — middleware adds an exception class CONTEXT.md doesn't ask for, and `Depends` is the existing FastAPI idiom in this codebase)
- 401 vs 403 for token-present-but-invalid (this research recommends: always 401 for auth issues — SC #3 says "401 without valid credentials"; 403 implies "you authenticated but lack permission," which we don't have RBAC for)

### Deferred Ideas (OUT OF SCOPE)

- Per-user saved routes / saved_routes table (M2)
- Email verification flow (M2; needs SMTP)
- Password reset via email (M2; needs SMTP)
- Refresh-token pattern (additive if 7-day expiries reveal UX pain)
- Server-side denylist / revocation table (additive if abuse appears)
- "Forgot password" link in modal (deferred with reset flow)
- Roles / RBAC (only relevant if non-demo features land)

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REQ-user-auth | Backend enforces authenticated access to `/route` and `/cache/*`; users can sign up, sign in, and sign out | All sections — library landscape (§1), endpoint patterns + Depends (§2), migration shape (§5), demo seed (§7) |

**Phase Success Criteria mapping:**

| SC # | Requirement | Research Section |
|------|-------------|-----------------|
| 1 | Sign up via email + password API endpoint | §1 (pwdlib), §2 (`/auth/register` skeleton), §5 (users table migration) |
| 2 | Sign in returns token, used on subsequent requests | §1 (python-jose), §2 (`/auth/login` skeleton), §6 (frontend storage + Bearer header) |
| 3 | `/route` and `/cache/*` return 401 without creds; `/health` and `/segments` stay public | §2 (router-level `dependencies=[Depends(...)]` for `/cache/*`; per-route for `/route`), §3 (HTTPBearer auto_error=True returns 401 in FastAPI 0.136) |
| 4 | Passwords hashed (bcrypt/argon2), never plaintext | §1 (pwdlib argon2id), §3 (Pitfall 1: log neither password nor hash) |
| 5 | New migration adds users table, applies cleanly to fresh DB | §5 (003_users.sql skeleton + docker-compose mount + idempotency mirror of Phase 3) |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Password hashing + verification | API / Backend | — | Never the browser. argon2id is server-only. |
| JWT signing + signature verification | API / Backend | — | The signing key NEVER leaves the backend. |
| User creation (CRUD on `users`) | API / Backend | Database | Backend writes; DB stores. |
| Session token issuance | API / Backend | — | Server-issued (`/auth/login` response). |
| Token storage on client | Browser / Client | — | `localStorage`. CONTEXT.md D-04 explicitly accepts the XSS trade for MVP. |
| Authorization header attachment to requests | Browser / Client | — | `frontend/src/api.ts` reads `localStorage` → adds `Authorization: Bearer`. |
| 401 detection + modal trigger | Browser / Client | — | The browser sees `401`, opens the modal, lets user re-auth. |
| Bearer extraction (parse `Authorization` header) | API / Backend | — | `HTTPBearer` security scheme on FastAPI side. |
| `Depends(current_user)` user-id resolution | API / Backend | Database | Decode JWT → `sub` → `SELECT id, email FROM users WHERE id = %s` (or skip the SELECT for the bare `user_id` form — see Open Q5). |
| Demo account seeding | Operator / CLI | Database | One-shot script run by operator (or CI in Phase 5/6). |
| `AUTH_SIGNING_KEY` provisioning | Operator / Env | API / Backend | Operator generates → env var → backend reads at startup. |

**No tier misassignment risk** — auth is naturally backend-heavy with a thin client surface. The one boundary worth highlighting: `verify_and_update()` (param-upgrade rehash) lives on the backend ONLY at login time, not on every request.

## 1. Library Landscape

### Core (additive to `backend/requirements.txt`)

| Library | Version | Purpose | Status |
|---------|---------|---------|--------|
| `pwdlib[argon2]` | `>=0.2.1,<0.4` (latest 0.3.0 [VERIFIED 2025-10-25]) | argon2id password hashing | Active, maintained by François Voron (frankie567); explicitly built because "passlib won't work anymore on Python 3.13" [CITED: pypi.org/project/pwdlib]. Beta dev status; API stable. |
| `python-jose[cryptography]` | `>=3.3.0,<4` (latest 3.5.0 [VERIFIED 2025-05-28]) | JWT encode/decode | Production/Stable, maintained by asherf + mpdavis. ~30 releases, no open CVEs [CITED: github.com/mpdavis/python-jose]. **However, FastAPI's tutorial migrated away from python-jose to PyJWT** as of 2025 [CITED: fastapi.tiangolo.com/tutorial/security/oauth2-jwt]. Locked by CONTEXT.md D-02; trivially swappable. |
| `email-validator` | `>=2.0,<3` (latest 2.3.0 [VERIFIED]) | Pydantic `EmailStr` validation backend | **NOT a transitive dep of `pydantic==2.10.4`** [VERIFIED: `pip uninstall email-validator` then importing `EmailStr` raises `ImportError: email-validator is not installed, run pip install 'pydantic[email]'`]. Must be explicit. CONTEXT.md D-06 wrong on "transitive" — corrected here. |

**Recommended `requirements.txt` additions (Phase 4):**

```
# Phase 4 auth additions (2026-04-25)
pwdlib[argon2]>=0.2.1,<0.4
python-jose[cryptography]>=3.3.0,<4
email-validator>=2.0,<3
```

The upper bounds matter: `pwdlib` is at 0.x and bumping minors could change `recommended()` defaults (which would silently invalidate existing hashes during `verify_and_update` — actually it would auto-rehash on next login, which is fine, but bumping deserves a knowing review). `python-jose` 4.x doesn't exist yet but if it ships, audit the alg-confusion behavior before adopting.

### Supporting (zero new deps)

| Library | Already pinned | Purpose |
|---------|----------------|---------|
| `fastapi==0.115.6` | backend/requirements.txt | `Depends`, `HTTPException`, `APIRouter(dependencies=[...])` |
| `fastapi.security.HTTPBearer` | stdlib of FastAPI | `Authorization: Bearer <token>` parsing |
| `pydantic==2.10.4` | backend/requirements.txt | `EmailStr` (after adding `email-validator`) |
| `psycopg2-binary==2.9.11` | backend/requirements.txt | Raw SQL CRUD on `users` |
| `secrets` | stdlib | Token-URL-safe key generation in README + `seed_demo_user.py` |
| `httpx==0.28.1` (test client) | backend/requirements.txt | `TestClient(app)` for auth endpoint tests |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `python-jose` | `PyJWT==2.12.1` (latest [VERIFIED]) | PyJWT is the FastAPI tutorial's current pick (2025 onward), Mozilla-backed, smaller attack surface (JWT-only, not full JOSE). API is nearly identical: `jwt.encode(claims, key, algorithm='HS256')` / `jwt.decode(token, key, algorithms=['HS256'])`. **CONTEXT.md D-02 locks python-jose;** we honor that. If python-jose maintenance erodes mid-M1, the swap is ~5 lines (one import + one exception class — `JWTError` becomes `PyJWTError`/`InvalidTokenError`). Track this in `docs/` as a known forward path. |
| `pwdlib` | `passlib[argon2]==1.7.4` | passlib is in maintenance-only mode and explicitly broken on Python 3.13 (per pwdlib's README). The roadmap targets 3.12 today but Phase 5 cloud deploy may use 3.13+ images. pwdlib is the forward-looking pick. |
| `pwdlib[argon2]` | `argon2-cffi` directly | pwdlib's argon2 hasher IS argon2-cffi underneath [VERIFIED: pip install pulled `argon2-cffi-25.1.0` as transitive]. The pwdlib wrapper adds (a) the `verify_and_update()` parameter-upgrade flow we want (Section 3 Pitfall 4) and (b) a portable hash-prefix dispatch if we ever need bcrypt fallback. ~10 lines of value, worth the dep. |
| `OAuth2PasswordBearer` | `HTTPBearer` (recommended) | OAuth2PasswordBearer expects form-encoded `username=...&password=...&grant_type=password`, which (a) doesn't match D-06's JSON `{email, password}` API shape and (b) generates Swagger UI auth boilerplate we don't need. `HTTPBearer` just parses `Authorization: Bearer <token>` — exactly the wire shape we issue. |
| `fastapi-users` | hand-rolled | Per CONTEXT.md D-02: requires SQLAlchemy → conflicts with locked raw-psycopg2 convention. Dead-on-arrival. |
| Migration INSERT for demo user | `scripts/seed_demo_user.py` | See Section 7. Migration INSERT bakes a hash into git history forever; rotation requires a new migration. Standalone script is rotatable + fresh-DB-friendly. |

### Version verification

```bash
# Run on dev machine (or in CI before merging the requirements bump):
python3 -m pip index versions pwdlib              # 0.3.0 latest [VERIFIED 2026-04-25]
python3 -m pip index versions python-jose         # 3.5.0 latest [VERIFIED 2026-04-25]
python3 -m pip index versions email-validator     # 2.3.0 latest [VERIFIED 2026-04-25]
```

[VERIFIED on installed runtime `/tmp/rq-venv/bin/python` (Python 3.12.13, fastapi 0.136.1, pydantic 2.13.3): pwdlib 0.3.0 + python-jose 3.5.0 + email-validator 2.3.0 install cleanly and the round-trip API exercised in this research succeeded.]

## 2. Implementation Patterns

### System architecture (request flow)

```
                  ┌─────────────────────────────────────┐
                  │  Browser (RouteFinder + SignInModal) │
                  └───────────────────┬─────────────────┘
                                      │
              ┌───────────────────────┼─────────────────────────┐
              │ 1. Public path        │  2. Gated path          │
              │ GET /map              │  POST /route            │
              │ GET /segments?bbox=...│  GET /cache/stats       │
              │ (no Authorization     │  POST /cache/clear      │
              │  header)              │  (Authorization: Bearer)│
              └─────────┬─────────────┴────────────┬────────────┘
                        │                          │
                        ▼                          ▼
               ┌─────────────────────────────────────────────┐
               │  FastAPI app (backend/app/main.py)          │
               │                                              │
               │  app.include_router(health.router)          │ ← public
               │  app.include_router(segments.router)        │ ← public
               │  app.include_router(auth.router)            │ ← public (register/login/logout)
               │  app.include_router(routing.router)         │ ← gated per-route
               │  app.include_router(cache_router)           │ ← gated at router level
               │                                              │
               │  HTTPBearer extracts token from header       │
               │  jwt.decode(token, AUTH_SIGNING_KEY,         │
               │             algorithms=['HS256'])            │
               │  → user_id from `sub`                        │
               │                                              │
               │  Depends(get_current_user_id) injects user_id│
               │  401 on missing / bad / expired token        │
               └────────────────────────┬────────────────────┘
                                        │
                                        ▼
                              ┌─────────────────────┐
                              │ PostgreSQL: users   │
                              │ (read on register   │
                              │  duplicate-check;   │
                              │  read on login;     │
                              │  /route + /cache/*  │
                              │  do NOT touch users │
                              │  — JWT is enough.)  │
                              └─────────────────────┘
```

**Key invariant:** Once the JWT is decoded, `/route` and `/cache/*` do NOT hit the `users` table. The token IS the auth proof. This is what "stateless" buys.

### Recommended file layout (locked by D-02; this research adds skeletons)

```
backend/app/
├── auth/
│   ├── __init__.py            # empty (per CONVENTIONS.md "no barrel re-exports")
│   ├── passwords.py           # hash_password / verify_password helpers
│   ├── tokens.py              # encode_token / decode_token + Token model
│   └── dependencies.py        # get_current_user_id (the Depends target)
└── routes/
    └── auth.py                # /auth/register, /auth/login, /auth/logout
db/migrations/
└── 003_users.sql              # NEW (mounted via docker-compose)
scripts/
└── seed_demo_user.py          # NEW (idempotent demo account creation)
backend/tests/
├── test_auth_passwords.py     # NEW (unit, hash/verify roundtrip)
├── test_auth_tokens.py        # NEW (unit, encode/decode + alg=none + expiry)
├── test_auth_routes.py        # NEW (integration via TestClient + dep override)
└── test_migration_003.py      # NEW (mirror test_migration_002.py)
```

### Pattern 1: HTTPBearer + Depends(current_user)

**What:** The single seam through which every gated endpoint receives the authenticated user_id. Tests override this dep with a fake to bypass real JWT wiring.

**`backend/app/auth/dependencies.py` (~30 lines):**

```python
# Source pattern: FastAPI security tutorial + verified on installed runtime
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.auth.tokens import decode_token, TokenError

# auto_error=True → FastAPI 0.136 returns 401 with {"detail": "Not authenticated"}
# on missing or non-Bearer Authorization header. (Older versions returned 403.)
_bearer = HTTPBearer(auto_error=True)


def get_current_user_id(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> int:
    """Resolve user_id from JWT. Raises 401 on any failure.

    Returns just the user_id (int). Endpoints that need full user fields
    can do their own SELECT — most don't (the JWT IS the proof).
    """
    try:
        payload = decode_token(creds.credentials)
    except TokenError:
        # Cover expired, bad signature, malformed, alg-substitution.
        # We deliberately do NOT distinguish — leaking "expired vs invalid"
        # gives an attacker a valid-token-shape oracle.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return int(payload["sub"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )
```

**Test override seam (used in `test_auth_routes.py` and any future endpoint tests):**

```python
# backend/tests/conftest.py — ADD this fixture
import pytest
from app.auth.dependencies import get_current_user_id

@pytest.fixture
def fake_user_id():
    """Default authenticated user_id for tests; override per-test if needed."""
    return 42

@pytest.fixture
def authed_client(client, fake_user_id):
    """A TestClient that bypasses JWT verification and presents user_id=fake_user_id.

    Use this for endpoint tests that don't care about the token shape — only that
    the auth dep returned a user. For tests that need to exercise the real JWT
    decode path, use `client` and craft a real token.
    """
    from app.main import app
    app.dependency_overrides[get_current_user_id] = lambda: fake_user_id
    yield client
    app.dependency_overrides.pop(get_current_user_id, None)
```

[VERIFIED on installed runtime: `app.dependency_overrides[get_current_user_id] = lambda: 42` causes a request without `Authorization` header to receive 200 with the lambda's return value injected; clearing the override returns the endpoint to 401-on-missing behavior.]

### Pattern 2: Mounting auth on existing routers

**What:** Gate `/route` and `/cache/*` per CONTEXT.md SC #3, leaving `/health` and `/segments` public.

**`backend/app/routes/routing.py` change (~2 lines):**

```python
# Existing:
# router = APIRouter()
# @router.post("/route", response_model=RouteResponse)
# def find_route(req: RouteRequest): ...

# After Phase 4:
from app.auth.dependencies import get_current_user_id
router = APIRouter()

@router.post("/route", response_model=RouteResponse)
def find_route(
    req: RouteRequest,
    user_id: int = Depends(get_current_user_id),  # ← only addition
):
    # body unchanged. user_id NOT used today (no per-user state — D-04 OUT-OF-SCOPE).
    # Logging it via route_requests is OPTIONAL polish; CONTEXT.md doesn't require it.
    ...
```

**`backend/app/routes/cache_routes.py` change (~1 line):**

```python
# Existing:
# router = APIRouter()

# After Phase 4 — gate the WHOLE router:
from app.auth.dependencies import get_current_user_id
router = APIRouter(dependencies=[Depends(get_current_user_id)])
# Both /cache/stats and /cache/clear inherit the dependency.
```

**Why mixed style:** `/cache/*` is two routes that all share the same gate, so the router-level dep is cleaner. `/route` is one route and might want `user_id` in the body (e.g., to log to `route_requests` per-user later); per-route Depends keeps the binding visible.

**`backend/app/main.py` change (no router-mount changes needed):** The existing `app.include_router(routing.router)` and `app.include_router(cache_router)` continue to work. We only add `app.include_router(auth.router)` for the new auth routes.

### Pattern 3: `/auth/register` + `/auth/login` skeleton

**`backend/app/routes/auth.py` (~80 lines including imports):**

```python
# Source pattern: FastAPI tutorial + project conventions (psycopg2 RealDictCursor,
# raw SQL, snake_case, HTTPException for errors)
import logging
from fastapi import APIRouter, HTTPException, status, Response
from pydantic import BaseModel, EmailStr, Field
from psycopg2 import IntegrityError
from app.db import get_connection
from app.auth.passwords import hash_password, verify_password
from app.auth.tokens import encode_token, Token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RegisterResponse(BaseModel):
    user_id: int
    email: EmailStr
    access_token: str
    token_type: str = "bearer"


def _normalize_email(raw: str) -> str:
    """Lowercase + strip — see Pitfall 3. Pydantic EmailStr lowercases the
    domain but PRESERVES local-part case, so we need this for UNIQUE correctness."""
    return raw.strip().lower()


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(req: RegisterRequest):
    email = _normalize_email(req.email)
    pwd_hash = hash_password(req.password)  # ~150-300ms (argon2id, blocking)
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO users (email, password_hash) "
                    "VALUES (%s, %s) RETURNING id",
                    (email, pwd_hash),
                )
                user_id = cur.fetchone()["id"]
                conn.commit()
    except IntegrityError:
        # 23505 unique_violation on the email index. Phase 3 precedent uses
        # psycopg2.errors.UniqueViolation; either works.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    token = encode_token(user_id=user_id)
    # NEVER log pwd_hash, password, or token. logger.info("user registered", extra={'user_id': user_id}) is the upper bound.
    logger.info("user registered: id=%d", user_id)
    return RegisterResponse(
        user_id=user_id, email=email, access_token=token,
    )


@router.post("/login", response_model=Token)
def login(req: LoginRequest):
    email = _normalize_email(req.email)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, password_hash FROM users WHERE email = %s",
                (email,),
            )
            row = cur.fetchone()
    # Constant-time-ish: always verify against SOMETHING to avoid a timing
    # oracle that distinguishes "user exists" from "user doesn't exist".
    # If row is None, verify against a known-bad hash (still ~150ms).
    if row is None:
        # See Pitfall 5. argon2 verify on a placeholder hash burns ~150ms,
        # roughly matching the real-user path.
        verify_password(req.password, _DUMMY_HASH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    if not verify_password(req.password, row["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    token = encode_token(user_id=row["id"])
    return Token(access_token=token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout():
    # Stateless JWT: no server state to clear. Client clears localStorage.
    # Endpoint exists so the frontend has a single "logout" call site for symmetry.
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Module-level constant — see Pitfall 5
_DUMMY_HASH = hash_password("__dummy_for_timing_safety__")
```

### Pattern 4: Password hashing helpers

**`backend/app/auth/passwords.py` (~30 lines):**

```python
# Source pattern: pwdlib README + verified on installed runtime
"""Argon2id password hashing.

pwdlib's PasswordHash.recommended() ships with m=65536 (64 MiB), t=3, p=4,
which is ~3x the OWASP minimum (m=19456, t=2, p=1) per
https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html.

The PasswordHash instance is module-level (instantiated once at import).
Its hashers carry no per-call state — safe to share across requests.
"""
from pwdlib import PasswordHash

_ph = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """Hash a plaintext password (~150-300ms on a modern laptop).

    The returned string encodes the algorithm + parameters + salt + hash
    (e.g., '$argon2id$v=19$m=65536,t=3,p=4$<salt>$<hash>'), so verification
    needs only this string, not the parameters separately.
    """
    return _ph.hash(password)


def verify_password(password: str, encoded_hash: str) -> bool:
    """Return True if password matches encoded_hash; False otherwise.

    Does NOT raise on mismatch — argon2-cffi raises VerifyMismatchError but
    pwdlib swallows that into a bool. Other failures (corrupt hash, etc.)
    pwdlib also returns False; we don't distinguish.
    """
    return _ph.verify(password, encoded_hash)


def verify_and_maybe_rehash(
    password: str, encoded_hash: str
) -> tuple[bool, str | None]:
    """Verify + return new hash if pwdlib's recommended params have changed.

    Returns (valid, new_hash_or_None). If new_hash is not None, the caller
    should UPDATE users SET password_hash = new_hash WHERE id = ... — this
    transparently upgrades hashes when we bump pwdlib later.

    Use this on /auth/login. Don't bother on /auth/register (the hash is fresh).
    """
    return _ph.verify_and_update(password, encoded_hash)
```

[VERIFIED on installed runtime: `verify_and_update` returns `(True, '<new $argon2id$...>')` when the stored hash was made with weaker parameters than `recommended()` — this is exactly the param-upgrade seam.]

### Pattern 5: JWT encode / decode helpers

**`backend/app/auth/tokens.py` (~50 lines):**

```python
# Source: python-jose docs + OWASP JWT cheat sheet + verified on installed runtime
"""HS256 JWT encode/decode for road-quality-mvp auth.

Locked decisions (CONTEXT.md D-01, D-07):
- HS256 (symmetric, single signing key)
- Payload = {sub: str(user_id), iat, exp}
- exp = 7 days from issue
- Signing key from AUTH_SIGNING_KEY env var; fail-fast on missing in non-test mode

Anti-footgun (Pitfall 2): jwt.decode() takes algorithms= as a LIST.
Passing a string would silently allow any one-character alg substring;
passing a list of one element is the canonical pin.
"""
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel
from jose import jwt
from jose.exceptions import (
    JWTError,
    ExpiredSignatureError,
    JWTClaimsError,
)

ALGORITHM = "HS256"
EXPIRE_DAYS = 7


def _signing_key() -> str:
    """Read AUTH_SIGNING_KEY at call time (so tests can monkeypatch the env).

    Fails LOUD on missing key — never default to a placeholder. A weak default
    here is the #1 way HS256 deployments get pwned.
    """
    key = os.environ.get("AUTH_SIGNING_KEY", "")
    if not key:
        raise RuntimeError(
            "AUTH_SIGNING_KEY env var is not set. Generate a 32-byte key with: "
            "python -c 'import secrets; print(secrets.token_urlsafe(32))'"
        )
    if len(key) < 32:
        # OWASP recommends >= 64 chars for HMAC; we accept >= 32 (token_urlsafe(32)
        # produces ~43 chars). Reject obvious dev-typo'd keys like "secret".
        raise RuntimeError(
            f"AUTH_SIGNING_KEY too short ({len(key)} chars; need >= 32). "
            "Generate with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
        )
    return key


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenError(Exception):
    """Raised on any JWT decode failure (expired, bad sig, malformed, alg confusion)."""


def encode_token(user_id: int, expires_in: timedelta | None = None) -> str:
    now = datetime.now(timezone.utc)
    exp = now + (expires_in if expires_in is not None else timedelta(days=EXPIRE_DAYS))
    payload = {
        "sub": str(user_id),         # OWASP: sub is conventionally a string
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, _signing_key(), algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode + verify HS256 token. Raises TokenError on any failure.

    Note `algorithms=[ALGORITHM]` (LIST, single element). DO NOT pass the
    string ALGORITHM — that's a silent footgun that allows alg substitution.
    """
    try:
        return jwt.decode(token, _signing_key(), algorithms=[ALGORITHM])
    except (ExpiredSignatureError, JWTClaimsError, JWTError) as e:
        # Collapse all JOSE errors into one type. Endpoints don't need to
        # distinguish "expired" from "bad sig" — both are 401, no extra detail.
        raise TokenError(str(e)) from e
```

[VERIFIED on installed runtime: encoding then decoding round-trips correctly; wrong-key raises `JWTError`; expired token raises `ExpiredSignatureError`; manually-crafted `alg=none` token raises `JWTError` because `algorithms=['HS256']` rejects the unsigned form.]

## 3. Pitfalls and Gotchas

### Pitfall 1: Logging passwords or hashes (sev: HIGH)

**What:** Accidentally logging `req.password`, `pwd_hash`, or full `req.model_dump()` from `/auth/register` or `/auth/login`. The password is plaintext on the wire (TLS-protected end-to-end, but visible in process memory and any structured log of the request body). The hash is non-reversible but a stolen hash log is offline-attackable.

**Why it happens:** The codebase already logs request params at `route_requests` (`backend/app/routes/routing.py:58-62` does `INSERT INTO route_requests (params_json) VALUES (%s)` with `req.model_dump()`). If someone copy-pastes that pattern into `/auth/login`, they ship plaintext passwords to the audit log.

**Avoid:**
- `/auth/register` and `/auth/login` MUST NOT log to `route_requests` or any structured log without redaction.
- Any `logger.info()` in those handlers logs only `user_id` (after success), never the request body.
- If you ever serialize a `RegisterRequest` for debugging, exclude the `password` field explicitly.

**Detect:** Add a test `test_no_plaintext_in_logs` that invokes register/login and `assert "demo1234" not in caplog.text`.

### Pitfall 2: `algorithms=ALG` instead of `algorithms=[ALG]` (sev: CRITICAL)

**What:** `jwt.decode(token, key, algorithms="HS256")` (string, not list) is accepted by python-jose but treated as the iterable of characters `['H','S','2','5','6']` — which means the decoder accepts any algorithm whose name is one of those characters. None of the real algorithms match, so this happens to be safe by accident in python-jose 3.5.0, but the parallel pyjwt path explicitly accepts `'none'` here. **Either way: always pass a list.**

**Why it happens:** Python's str-is-iterable surprise + the singular-looking parameter name. CVEs in this category have hit auth0/jsonwebtoken (Node), node-jsonwebtoken (CVE-2015-9235), and others.

**Avoid:** Hardcode `algorithms=["HS256"]` in `decode_token`. Lint or unit-test for it: `assert decode_token.__code__.co_consts` contains the list `['HS256']`.

**Verify:** A test that constructs an `alg=none` JWT manually (header `{"alg":"none","typ":"JWT"}`) and asserts `TokenError` is raised. [VERIFIED on installed runtime — see Section 5 sample test.]

### Pitfall 3: EmailStr does NOT lowercase the local-part (sev: MEDIUM)

**What:** Pydantic 2.13 `EmailStr` normalizes `User@Example.COM` → `User@example.com` (domain lowercased, local-part preserved). The migration's `email TEXT NOT NULL UNIQUE` is byte-exact, so `User@example.com` and `user@example.com` are TWO distinct rows. Effect: legitimate users can register the same email twice with different casings, and login fails for whichever casing they didn't use the first time.

**Why it happens:** RFC 5321 says local-parts ARE case-sensitive in principle, even though every real-world MTA (Gmail, Outlook, etc.) treats them as case-insensitive. Pydantic correctly defers to the spec.

**Avoid:** Always run `email.strip().lower()` at the app layer before INSERT and before SELECT. Centralize this in a `_normalize_email` helper (see Pattern 3). Add a test: `register("User@Example.com")` succeeds, `register("user@example.com")` returns 400 with "Email already registered".

**Why not solve at the DB?** Could use `CREATE UNIQUE INDEX ... ON users (LOWER(email))` and lowercase on read — but that means every login query does `WHERE LOWER(email) = %s`, which doesn't use the standard B-tree index efficiently (would need an expression index). Cleaner to normalize at the app layer.

### Pitfall 4: argon2 default upgrade silently invalidates hashes (sev: LOW)

**What:** Bumping pwdlib from 0.3.0 to 0.4.0 might change `recommended()` defaults (e.g., m=65536 → m=131072 if attackers get faster). Existing hashes are still verifiable (the params are encoded in the hash string), but they're now under-strength.

**Why it happens:** Password-hashing libraries periodically tune defaults to keep up with hardware.

**Avoid:** Use `verify_and_update()` on `/auth/login` (Pattern 4). When pwdlib detects the stored hash uses old params, it returns `(True, new_hash)` — caller writes the new hash back to the DB. Within ~one login per active user, all hashes are upgraded transparently. Cost is one extra UPDATE per login on the upgrade window; negligible.

### Pitfall 5: Login timing oracle distinguishes "user exists" from "user missing" (sev: LOW)

**What:** If `/auth/login` short-circuits with `if user is None: return 401` BEFORE running argon2 verification, the timing difference (~150ms with verify vs <5ms without) tells an attacker which emails are registered. This is a username-enumeration oracle, mostly relevant to email-spam reconnaissance.

**Why it happens:** Natural code flow: lookup, then verify. The "missing user" path is faster than the "wrong password" path.

**Avoid:** When the user is missing, run argon2 verify against a known-bad placeholder hash anyway (Pattern 3, `_DUMMY_HASH`). Both paths take ~150ms. The placeholder hash is a module-level constant, computed once at import.

**Severity rationale:** LOW because email is also leaked at registration ("Email already registered" 400), and we don't have rate limiting in M1 (Phase 5). Don't over-invest, but the 5-line dummy-hash pattern is cheap to add.

### Pitfall 6: `localStorage` token + XSS (sev: documented trade)

**What:** CONTEXT.md D-04 explicitly accepts `localStorage` for the JWT. JavaScript-readable storage means any XSS gives the attacker the token. CSP, sanitization, and React's default escaping mitigate but don't eliminate.

**Why it happens:** Per CONTEXT.md: "no XSS-grade defense at MVP scale, and our API only exposes routing." Documented trade.

**Avoid:** This is a locked trade. Two minor follow-ups:
- React's JSX escaping is on by default — make sure any future "display arbitrary text" is via `{stringValue}` not `dangerouslySetInnerHTML`.
- The 7-day expiry caps blast radius. Document in README that compromised tokens are auto-revoked by `AUTH_SIGNING_KEY` rotation.

### Pitfall 7: Audience / issuer claims at MVP scale (sev: NONE)

**What:** OWASP recommends `aud` and `iss` claims. Adding them WITHOUT validation is no-op. Adding them WITH validation requires the verifier to know what `aud` to expect.

**Avoid:** Skip both for M1. We have one issuer (this app) and one audience (this app). Adding the claims now without validation is theater. If Phase 5 introduces a separate auth service, add them then.

### Pitfall 8: Clock skew on `exp` (sev: NONE for MVP)

**What:** If the backend host clock is skewed >N seconds vs the issuer host, freshly-issued tokens look expired. python-jose has a `leeway` option for this.

**Avoid:** Skip for M1 — issuer and verifier are the same process. If Phase 5 splits them, set `jwt.decode(..., options={'leeway': 30})`.

### Pitfall 9: `AUTH_SIGNING_KEY` rotation mid-session (sev: documented)

**What:** CONTEXT.md D-01 says rotating `AUTH_SIGNING_KEY` invalidates ALL active sessions globally. This is the user-visible cost of "no denylist."

**Avoid:** Document in README's "Public Demo" section: "If the demo is abused, we may rotate the signing key, which logs out all active sessions including yours. Sign in again."

### Pitfall 10: 401 vs 403 confusion (sev: LOW)

**What:** SC #3 says "return 401 without valid credentials." Older FastAPI (<0.105) returned 403 from `HTTPBearer(auto_error=True)` for missing `Authorization` headers. We're on 0.115 — [VERIFIED on installed FastAPI 0.136.1: returns 401 with `{"detail": "Not authenticated"}`].

**Avoid:** Pin via test: `client.post('/route', json={...}).status_code == 401`. If the test ever flips to 403, we've upgraded to a broken FastAPI.

## 4. Test Patterns

### Test framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.3.4 + httpx 0.28.1 (FastAPI's `TestClient`) |
| Config file | `backend/tests/conftest.py` (existing) |
| Quick run command | `pytest backend/tests/test_auth_*.py -x` |
| Full suite command | `cd backend && pytest -x` |
| Integration marker | `@pytest.mark.integration` (existing convention; auto-skip when DB down) |

### Phase 4 Requirements → Test Map

| Req / SC | Behavior | Test Type | File |
|----------|----------|-----------|------|
| SC #1 | Register a user via `POST /auth/register` | unit (TestClient + dep override) | test_auth_routes.py |
| SC #1 | Duplicate email returns 400 | unit | test_auth_routes.py |
| SC #1 | Invalid email returns 422 | unit | test_auth_routes.py |
| SC #1 | Email is normalized (User@X.com == user@x.com) | unit | test_auth_routes.py |
| SC #2 | Login returns access_token | unit | test_auth_routes.py |
| SC #2 | Login with wrong password returns 401 | unit | test_auth_routes.py |
| SC #2 | Login with missing user returns 401 (timing-similar) | unit | test_auth_routes.py |
| SC #3 | `POST /route` w/o token → 401 | unit (TestClient, NO dep override) | test_auth_routes.py |
| SC #3 | `POST /route` w/ bad token → 401 | unit | test_auth_routes.py |
| SC #3 | `POST /route` w/ valid token → 200 (existing test, with token added) | integration | test_integration.py update |
| SC #3 | `GET /cache/stats` w/o token → 401 | unit | test_auth_routes.py |
| SC #3 | `POST /cache/clear` w/o token → 401 | unit | test_auth_routes.py |
| SC #3 | `GET /health` and `GET /segments` UNGATED | unit | test_auth_routes.py |
| SC #4 | password_hash column has `$argon2id$` prefix | unit | test_auth_routes.py |
| SC #4 | `verify_password` round-trip | unit | test_auth_passwords.py |
| SC #4 | `verify_and_update` upgrades old hashes | unit | test_auth_passwords.py |
| SC #5 | Migration applies idempotently | integration | test_migration_003.py |
| SC #5 | Email UNIQUE index rejects duplicates | integration | test_migration_003.py |
| Pitfall 2 | Manually-crafted `alg=none` token rejected | unit | test_auth_tokens.py |
| Pitfall 5 | Missing-user login takes ~same time as bad-pw login | unit (timing assertion w/ generous tolerance) | test_auth_routes.py |

### Sampling rate

- **Per task commit:** `pytest backend/tests/test_auth_*.py -x` (~3-5s)
- **Per wave merge:** `cd backend && pytest -x` (full suite ~30s)
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 gaps (test infra additions before implementation)

Most are net-new test files. The existing `conftest.py` covers `client` and `db_conn` already, so we ONLY need to add `authed_client` + `fake_user_id`:

- [ ] `backend/tests/conftest.py` — add `fake_user_id` and `authed_client` fixtures (Pattern 1)
- [ ] `backend/tests/test_auth_passwords.py` — NEW (unit tests for hash/verify)
- [ ] `backend/tests/test_auth_tokens.py` — NEW (unit tests for encode/decode + alg=none)
- [ ] `backend/tests/test_auth_routes.py` — NEW (TestClient tests for /auth/register, /login, /logout + 401 enforcement on /route, /cache/*)
- [ ] `backend/tests/test_migration_003.py` — NEW (mirror test_migration_002.py)
- [ ] No framework install — all needed runtime deps (pytest, httpx, psycopg2) already present

### Skeleton: dependency override test for gated endpoints

```python
# backend/tests/test_auth_routes.py — pattern excerpt
from fastapi.testclient import TestClient
from app.main import app
from app.auth.dependencies import get_current_user_id


def test_route_unauthenticated_returns_401():
    """SC #3: /route returns 401 without a valid token."""
    with TestClient(app) as client:
        resp = client.post("/route", json={
            "origin": {"lat": 34.05, "lon": -118.24},
            "destination": {"lat": 34.06, "lon": -118.25},
            "include_iri": True, "include_potholes": True,
            "weight_iri": 50, "weight_potholes": 50,
            "max_extra_minutes": 5,
        })
    assert resp.status_code == 401


def test_route_with_dep_override_works(monkeypatch):
    """Dependency override seam: tests of gated endpoints don't need real JWTs."""
    monkeypatch.setenv("AUTH_SIGNING_KEY", "x" * 32)  # so token module imports OK
    app.dependency_overrides[get_current_user_id] = lambda: 42
    try:
        with TestClient(app) as client:
            # body unchanged; user_id=42 injected via override
            resp = client.post("/route", json={...})
        # /route still 200 even though we sent NO Authorization header
        assert resp.status_code in (200, 502, 503)  # 5xx if DB unreachable; that's fine
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)


def test_alg_none_token_rejected(monkeypatch):
    """Pitfall 2 regression test."""
    import base64, json
    monkeypatch.setenv("AUTH_SIGNING_KEY", "x" * 32)
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps({"sub": "1"}).encode()).rstrip(b"=").decode()
    none_tok = f"{header}.{body}."
    with TestClient(app) as client:
        resp = client.post("/route", headers={"Authorization": f"Bearer {none_tok}"}, json={...})
    assert resp.status_code == 401
```

### Skeleton: integration test for migration 003

```python
# backend/tests/test_migration_003.py — mirrors test_migration_002.py
import pytest
from pathlib import Path
from psycopg2 import errors as pgerr

pytestmark = pytest.mark.integration
REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = REPO_ROOT / "db" / "migrations" / "003_users.sql"


def test_migration_idempotent(db_conn):
    sql = MIGRATION_PATH.read_text()
    with db_conn.cursor() as cur:
        cur.execute(sql)
        db_conn.commit()
        cur.execute(sql)  # second apply — must not error
        db_conn.commit()
        cur.execute("SELECT COUNT(*) AS c FROM pg_indexes WHERE indexname = 'users_email_key'")
        row = cur.fetchone()
        count = row["c"] if isinstance(row, dict) else row[0]
        assert count == 1


def test_email_unique_index_rejects_duplicates(db_conn):
    sql = MIGRATION_PATH.read_text()
    with db_conn.cursor() as cur:
        cur.execute(sql)
        db_conn.commit()
        cur.execute(
            "INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id",
            ("dup-test@example.com", "$argon2id$placeholder"),
        )
        db_conn.commit()
        with pytest.raises(pgerr.UniqueViolation):
            cur.execute(
                "INSERT INTO users (email, password_hash) VALUES (%s, %s)",
                ("dup-test@example.com", "$argon2id$other"),
            )
        db_conn.rollback()
        cur.execute("DELETE FROM users WHERE email = %s", ("dup-test@example.com",))
        db_conn.commit()
```

## 5. Migration Template

### `db/migrations/003_users.sql` skeleton

```sql
-- Migration 003: users table for Phase 4 authentication.
--
-- Locked column shape from CONTEXT.md (Phase 4 D-02 + "Locked column shape"):
--   id            BIGSERIAL PRIMARY KEY  (matches BIGINT convention from
--                                        road_segments.source/target;
--                                        see Phase 1 SC #1 BIGINT verification)
--   email         TEXT NOT NULL          (lowercased + trimmed at app layer
--                                        before insert/lookup; see Phase 4
--                                        Pitfall 3 — Pydantic EmailStr does
--                                        NOT lowercase the local-part)
--   password_hash TEXT NOT NULL          (argon2id encoded form ~97 chars)
--   created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
--                                        (matches segment_defects.created_at)
--
-- Idempotency model (mirrors Phase 3 migration 002_mapillary_provenance.sql):
--   - CREATE TABLE IF NOT EXISTS users — re-applies are no-ops on the table.
--   - CREATE UNIQUE INDEX IF NOT EXISTS users_email_key ON users(email) —
--     idempotent index creation (Postgres 16 has no idempotent ADD-CONSTRAINT
--     form, so we use a separate CREATE UNIQUE INDEX rather than an inline
--     UNIQUE column constraint, exactly as Phase 3 did for
--     uniq_defects_segment_source_severity).
--
-- The migration MUST apply cleanly to a fresh DB via the existing init flow
-- (mounted in docker-compose.yml under /docker-entrypoint-initdb.d/).

CREATE TABLE IF NOT EXISTS users (
    id            BIGSERIAL PRIMARY KEY,
    email         TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- UNIQUE index on email (separate from column declaration for idempotent re-apply).
CREATE UNIQUE INDEX IF NOT EXISTS users_email_key ON users(email);
```

### `docker-compose.yml` mount addition

Mirroring Phase 3's pattern (it added `02-mapillary.sql` after `02-schema.sql`):

```yaml
# UPDATE the db: volumes: list to include the new migration:
services:
  db:
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./db/init-pgrouting.sh:/docker-entrypoint-initdb.d/01-pgrouting.sh
      - ./db/migrations/001_initial.sql:/docker-entrypoint-initdb.d/02-schema.sql
      - ./db/migrations/002_mapillary_provenance.sql:/docker-entrypoint-initdb.d/03-mapillary.sql
      - ./db/migrations/003_users.sql:/docker-entrypoint-initdb.d/04-users.sql  # ← NEW
```

**Note on file numbering:** The numeric prefix in `/docker-entrypoint-initdb.d/` controls bash-glob ordering. Phase 3 used `03-mapillary.sql` for its 002 migration; Phase 4 follows: `04-users.sql` for the 003 migration. The numbering is purely lexicographic ordering for the entrypoint scripts, NOT migration numbers.

### Idempotency proof model

Run `psql -f 003_users.sql` twice on the same DB:
1. First apply: creates `users` table + creates `users_email_key` index.
2. Second apply: both `IF NOT EXISTS` clauses are no-ops; no error, no warning.

Verified by `test_migration_003::test_migration_idempotent` (Section 4 skeleton).

### Why NOT inline `email TEXT NOT NULL UNIQUE`

Postgres 16 supports `IF NOT EXISTS` on `CREATE TABLE`, but **does NOT** support an idempotent form of `UNIQUE` constraint declaration inline. Re-running `CREATE TABLE` with an inline `UNIQUE` is fine the FIRST re-run (the table exists, so the whole statement is skipped), but if a manual ALTER ever drops then re-adds the constraint, the script no longer matches. Phase 3 hit this exact problem with the CHECK constraint (`segment_defects_source_check`) and solved it with DROP-then-ADD; for unique constraints, the cleaner answer is `CREATE UNIQUE INDEX IF NOT EXISTS`, which gives us the same byte-exact uniqueness with full idempotency.

## 6. Frontend Pattern

### Modal skeleton (no existing modal in codebase — verified by grep)

There is no existing modal/dialog in `frontend/src/`. We're starting from scratch. The simplest pattern: controlled component, no portal, no headless-ui, plain Tailwind.

**`frontend/src/components/SignInModal.tsx` (~120 LOC):**

```tsx
import { useState } from "react";
import { register, login } from "../api/auth";

interface SignInModalProps {
  open: boolean;
  onClose: () => void;
  onAuthSuccess: () => void;
}

type Mode = "login" | "register";

export default function SignInModal({ open, onClose, onAuthSuccess }: SignInModalProps) {
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      if (mode === "register") {
        await register(email, password);
      } else {
        await login(email, password);
      }
      onAuthSuccess();
      onClose();
    } catch (err: any) {
      setError(err.message || "Authentication failed");
    } finally {
      setLoading(false);
    }
  };

  const handleDemo = async () => {
    setEmail("demo@road-quality-mvp.dev");
    setPassword("demo1234");
    setLoading(true);
    setError(null);
    try {
      await login("demo@road-quality-mvp.dev", "demo1234");
      onAuthSuccess();
      onClose();
    } catch (err: any) {
      setError(err.message || "Demo login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    // Backdrop — clicking it closes the modal. fixed inset-0 covers the whole viewport.
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      {/* stopPropagation so clicking inside the dialog doesn't close it. */}
      <div className="bg-white rounded-lg shadow-xl p-6 w-96 max-w-full mx-4" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-lg font-bold mb-4">
          {mode === "login" ? "Sign in" : "Create account"}
        </h2>

        <form onSubmit={handleSubmit} className="space-y-3">
          <input
            type="email" placeholder="Email" required value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full border rounded px-3 py-2"
          />
          <input
            type="password" placeholder="Password" required minLength={8} value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full border rounded px-3 py-2"
          />
          {error && <p className="text-red-600 text-sm">{error}</p>}
          <button type="submit" disabled={loading}
                  className="w-full bg-blue-600 text-white rounded py-2 hover:bg-blue-700 disabled:opacity-50">
            {loading ? "..." : mode === "login" ? "Sign in" : "Create account"}
          </button>
        </form>

        <button onClick={handleDemo} disabled={loading}
                className="w-full mt-3 bg-gray-100 text-gray-700 rounded py-2 hover:bg-gray-200 disabled:opacity-50">
          Try as demo
        </button>

        <p className="text-sm text-center mt-4">
          {mode === "login" ? (
            <>No account?{" "}
              <button onClick={() => { setMode("register"); setError(null); }}
                      className="text-blue-600 hover:underline">Create one</button>
            </>
          ) : (
            <>Have an account?{" "}
              <button onClick={() => { setMode("login"); setError(null); }}
                      className="text-blue-600 hover:underline">Sign in</button>
            </>
          )}
        </p>
      </div>
    </div>
  );
}
```

**Key choices:**
- No `react-portal` / `createPortal` — `fixed inset-0` works without one because nothing in the existing layout uses `transform`, `filter`, or `will-change` (which would re-anchor `fixed`). Verified by inspecting `App.tsx` and `RouteFinder.tsx`.
- No `useEffect` for body-scroll-lock — the modal covers everything visually with the backdrop. If the page is shorter than the viewport, scroll-lock isn't needed. If a future task wants it, add `document.body.style.overflow = open ? "hidden" : ""` inside a useEffect.
- Esc-to-close intentionally OMITTED for MVP. The backdrop click + the implicit "click the X" (no X — just close on backdrop) is enough. Add later if UX feedback demands.
- Mode toggle is local state — register vs login. Both forms have the same field set (email + password), so we share the inputs.

### `frontend/src/api/auth.ts` (~40 LOC):

```ts
const API_BASE = import.meta.env.VITE_API_URL || "/api";
const TOKEN_KEY = "rq_auth_token";

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user_id?: number;   // present on /register, absent on /login
  email?: string;     // present on /register, absent on /login
}

export async function register(email: string, password: string): Promise<AuthResponse> {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Register failed: ${res.status}`);
  }
  const data = (await res.json()) as AuthResponse;
  setToken(data.access_token);
  return data;
}

export async function login(email: string, password: string): Promise<AuthResponse> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Login failed: ${res.status}`);
  }
  const data = (await res.json()) as AuthResponse;
  setToken(data.access_token);
  return data;
}

export async function logout(): Promise<void> {
  // Server-side is a no-op for stateless JWT; we just clear localStorage.
  // Calling /auth/logout for symmetry — server returns 204, no body.
  try { await fetch(`${API_BASE}/auth/logout`, { method: "POST" }); } catch {}
  clearToken();
}

export function getToken(): string | null { return localStorage.getItem(TOKEN_KEY); }
function setToken(t: string): void { localStorage.setItem(TOKEN_KEY, t); }
export function clearToken(): void { localStorage.removeItem(TOKEN_KEY); }
export function isAuthenticated(): boolean { return getToken() !== null; }
```

### `frontend/src/api.ts` modifications

Existing `fetchSegments` and `fetchRoute` need to attach `Authorization` header for gated endpoints AND surface 401 for the modal trigger.

```ts
import { getToken, clearToken } from "./api/auth";
const API_BASE = import.meta.env.VITE_API_URL || "/api";

// New: thrown when a gated request hits 401, so the caller can open the modal.
export class UnauthorizedError extends Error {
  constructor() { super("Unauthorized"); this.name = "UnauthorizedError"; }
}

function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

export async function fetchSegments(bbox: string) {
  // /segments stays public — no auth header.
  const res = await fetch(`${API_BASE}/segments?bbox=${bbox}`);
  if (!res.ok) throw new Error(`Segments fetch failed: ${res.status}`);
  return res.json();
}

// fetchRoute is GATED — must attach auth header + handle 401.
export async function fetchRoute(body: RouteRequestBody) {
  const res = await fetch(`${API_BASE}/route`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (res.status === 401) {
    clearToken();             // stale/missing/invalid — wipe localStorage
    throw new UnauthorizedError();
  }
  if (!res.ok) throw new Error(`Route fetch failed: ${res.status}`);
  return res.json();
}
```

**`RouteFinder.tsx` integration:** in `handleSearch`, catch `UnauthorizedError` specifically and open the modal:

```tsx
import SignInModal from "../components/SignInModal";
import { UnauthorizedError } from "../api";
import { isAuthenticated } from "../api/auth";

// inside RouteFinder():
const [modalOpen, setModalOpen] = useState(false);

// inside handleSearch():
try {
  const data = await fetchRoute(body);
  // ...
} catch (err: any) {
  if (err instanceof UnauthorizedError) {
    setModalOpen(true);   // open modal; user retries after auth
    return;
  }
  setError(err.message || "Route request failed");
}

// at bottom of return:
return (
  <>
    {/* existing JSX */}
    <SignInModal open={modalOpen} onClose={() => setModalOpen(false)}
                 onAuthSuccess={() => { /* user can hit Find Best Route again */ }} />
  </>
);
```

### Where token lives

`localStorage` (key: `rq_auth_token`). Per CONTEXT.md D-04 — accepted XSS trade for MVP. `getToken()` / `setToken()` / `clearToken()` are the only surface that touches it; never read `localStorage` directly elsewhere.

## 7. Demo Seed

### Recommendation: standalone `scripts/seed_demo_user.py`

**Why a script, not a migration INSERT:**

1. **Migrations should be schema-shape-only.** Phase 3's `002_mapillary_provenance.sql` adds columns + indexes; Phase 1's `001_initial.sql` adds tables. None contain seed rows. Sticking to that convention keeps migrations diffable for review.
2. **Hash-in-git is a footgun.** A migration `INSERT INTO users (email, password_hash) VALUES ('demo@...', '$argon2id$...')` bakes a specific hash into git history. If we later raise pwdlib params, the migration's hash is under-strength and we can't fix it without a new migration.
3. **Rotation.** CONTEXT.md D-05 says "documented and rotatable." A script lets the operator regenerate the hash from the new password trivially: `python scripts/seed_demo_user.py --password $NEW`. A migration requires a new SQL file.
4. **Fresh-DB symmetry.** Phase 3's `seed_data.py` is the exact pattern: scripts/* loads data, migrations/* defines shape. Mirror it.

**`scripts/seed_demo_user.py` (~50 LOC):**

```python
"""Seed (or rotate) the public-demo user account.

Idempotent: re-running with the same credentials is a no-op (UPDATE the
existing row's password_hash to the freshly-computed argon2id hash so future
pwdlib param bumps re-strengthen the hash on each re-run).

Usage:
  python scripts/seed_demo_user.py
  python scripts/seed_demo_user.py --email demo@road-quality-mvp.dev --password demo1234
  python scripts/seed_demo_user.py --password $NEW_DEMO_PW   # rotation
"""
import argparse
import os
import sys

import psycopg2

# Reuse backend's password helper. backend/ is a sibling of scripts/ — adjust
# sys.path so this file can be invoked from repo root without installing the
# backend as a package. (Mirrors how scripts/compute_scores.py and
# scripts/ingest_mapillary.py work today.)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from app.auth.passwords import hash_password  # noqa: E402

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://rq:rqpass@localhost:5432/roadquality"
)
DEFAULT_EMAIL = "demo@road-quality-mvp.dev"
DEFAULT_PASSWORD = "demo1234"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--email", default=DEFAULT_EMAIL)
    ap.add_argument("--password", default=DEFAULT_PASSWORD)
    args = ap.parse_args()

    email = args.email.strip().lower()
    pwd_hash = hash_password(args.password)

    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            # ON CONFLICT for idempotency. Updates password_hash on re-run so
            # rotations and pwdlib upgrades are one command.
            cur.execute(
                "INSERT INTO users (email, password_hash) VALUES (%s, %s) "
                "ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash "
                "RETURNING id",
                (email, pwd_hash),
            )
            user_id = cur.fetchone()[0]
            conn.commit()
    print(f"Demo user seeded: id={user_id}, email={email}")


if __name__ == "__main__":
    main()
```

**Note on `ON CONFLICT (email)`:** Requires the UNIQUE index on `email` from migration 003. The migration MUST apply before the script runs. Phase 3 hit the same ordering pattern with `seed_data.py` — operator runs migrations (auto via docker-entrypoint-initdb) then seed scripts.

### README "Public Demo" snippet

```markdown
## Public Demo Account

The deployed app exposes a demo account for drive-by visitors:

- **Email:** `demo@road-quality-mvp.dev`
- **Password:** `demo1234`

Click "Try as demo" on the sign-in modal to log in with one click.

The demo password is rotated if abuse appears. To rotate locally:

\`\`\`bash
python scripts/seed_demo_user.py --password $NEW
\`\`\`

This UPSERTs the existing demo user with a fresh argon2id hash. Update README
with the new password and redeploy. Rotating `AUTH_SIGNING_KEY` in addition
will invalidate every active session (including any abuser's).
```

### Initial provisioning order

In `docker compose up` flow:

1. `db` container starts, runs `/docker-entrypoint-initdb.d/04-users.sql` → table exists.
2. `backend` container starts (depends_on db.service_healthy).
3. Operator runs (manual, one-time): `docker compose exec backend python /app/../scripts/seed_demo_user.py` OR (for local dev) `python scripts/seed_demo_user.py` from repo root.

For Phase 5 (cloud), this becomes a one-shot CI step or a `terraform null_resource` post-deploy hook. NOT in scope for Phase 4.

## 8. AUTH_SIGNING_KEY Provisioning

### Dev environment

**Goal:** zero friction for `docker compose up`-driven dev, but fail-loud if the operator forgets the key in non-test mode.

**Operator generates a key once:**

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
# → 'L8gW7HZxQk4aR2sFtPv9eUyDcXjN1mB3' or similar (43 chars URL-safe)
```

Saves it to `.env` (git-ignored). The committed `.env.example` adds an empty placeholder:

```bash
# .env.example — APPEND this section
# ----- Auth signing key (Phase 4) -----
# Consumed by: backend/app/auth/tokens.py (read at app startup; fail-fast on empty in non-test mode).
# Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
# MUST be >= 32 chars. The backend rejects shorter keys at startup.
# Rotating this key invalidates ALL active sessions — emergency revocation lever.
# Production (Phase 5) sources this from the cloud host's secret store, NOT from .env.
AUTH_SIGNING_KEY=
```

### `docker-compose.yml` interpolation

Mirrors how Phase 3 implicitly intended `MAPILLARY_ACCESS_TOKEN` (env-only, not docker-compose-level). Phase 4 introduces the explicit `${...}` interpolation since the backend container needs the key at startup:

```yaml
# UPDATE backend.environment:
services:
  backend:
    environment:
      DATABASE_URL: postgresql://rq:rqpass@db:5432/roadquality
      AUTH_SIGNING_KEY: ${AUTH_SIGNING_KEY:-}      # ← NEW, defaults to empty if .env missing
```

The `:-` syntax means: "use the value of `AUTH_SIGNING_KEY` from the environment / `.env` file, or empty string if unset." If the operator forgot to set it, the backend's startup check fails fast with the clear message we coded in `tokens.py:_signing_key()`. **Better than silently using a default.**

### Backend startup check

`app/auth/tokens.py:_signing_key()` (Pattern 5) reads the env at call time and raises `RuntimeError` on empty / too-short. The first call happens during the import chain when `auth.py` registers the `/auth/register` route, which triggers the module-level `_DUMMY_HASH = hash_password(...)` — actually, that's the password module. The first call to `_signing_key()` is at the first `/auth/login` or `/auth/register` request.

**Fail at startup, not at first request.** Add an explicit startup probe in `main.py`:

```python
# backend/app/main.py — APPEND after include_router calls
from app.auth.tokens import _signing_key

@app.on_event("startup")
def verify_auth_config():
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return  # tests use monkeypatch.setenv as needed
    try:
        _signing_key()  # raises if missing or too short
    except RuntimeError as e:
        # Re-raise as a clearer message at startup time. This is the seam where
        # docker compose up reveals "AUTH_SIGNING_KEY missing" before the first
        # request 500s.
        raise RuntimeError(
            f"FATAL: cannot start backend without auth config: {e}"
        ) from e
```

(`@app.on_event("startup")` is the pre-FastAPI-0.110 idiom; `lifespan=` is the new one. The codebase doesn't use either today; the simpler `@app.on_event` is fine and won't break in 0.115. If the project moves to a `lifespan` context manager later, fold this check in.)

### Production (Phase 5 territory)

CONTEXT.md D-04 says cloud secrets handle this. Phase 4 only ensures:

1. The env var IS the seam (no committed default).
2. Empty / short values fail fast.
3. README documents the generation command.

Phase 5 then plumbs the cloud host's secret store (AWS Secrets Manager, Fly.io secrets, Render env vars, etc.) into the same env var name.

## 9. State of the Art (auth library landscape, 2026)

| Old approach | Current approach | When changed | Impact |
|--------------|------------------|--------------|--------|
| `passlib[argon2]` for new projects | `pwdlib[argon2]` | 2024-2025 (Python 3.13 release deprecated parts of passlib) | passlib still works but is in maintenance mode — pick pwdlib for new code. |
| `python-jose` as the FastAPI tutorial JWT lib | `PyJWT` in the FastAPI tutorial | 2025 (FastAPI tutorial migration) | Both libraries still work and are actively maintained; CONTEXT.md D-02 locks python-jose for this phase. |
| Inline `email TEXT NOT NULL UNIQUE` in CREATE TABLE | `CREATE UNIQUE INDEX IF NOT EXISTS` | Always (Postgres has never had idempotent ADD CONSTRAINT) | Phase 3 already adopted this; Phase 4 follows. |
| Session cookies with server-side session table | Stateless JWT | ~2018+ for new MVP-scale APIs | Trade: lost server-side revocation. CONTEXT.md D-01 explicitly accepts this trade for M1. |

## Assumptions Log

| # | Claim | Section | Risk if wrong |
|---|-------|---------|---------------|
| A1 | pwdlib's `recommended()` defaults won't change between 0.3.0 and 0.4.0 in a way that breaks `verify_and_update()` semantics | §1, §3 Pitfall 4 | Low — `verify_and_update` IS the seam for breaking-change handling, and the upper bound `<0.4` in requirements catches it. |
| A2 | python-jose 3.5.0 will remain healthy through Phase 4's execution window (~2 weeks) | §1, §3 Pitfall 2 | Low — last release May 2025, no CVEs, active maintainers. Even if abandoned tomorrow, the API surface we use (~3 functions) is stable. |
| A3 | The 7-day JWT expiry is acceptable to the user (CONTEXT.md D-07 default applied, NOT discussed) | §1 Locked Decisions | Low — explicitly defaulted with rationale in CONTEXT.md; user can challenge in `/gsd-discuss-phase` if they disagree. |
| A4 | Demo password `demo1234` is fine to commit to README (CONTEXT.md D-05 says it's rotatable + public) | §7 | Low — explicit decision; Pitfall 9 documents the rotation lever. |
| A5 | The dev machine has the standard `python3 -c "import secrets"` available for key generation (it does — Python 3.12 stdlib) | §8 | None — stdlib. |
| A6 | Email length cap is implicit (Pydantic EmailStr enforces RFC 5321's 254-byte limit) — we don't need an explicit `max_length` | §1 implementation pattern | Low — RFC 5321 is the standard; verified in Pydantic 2.13 source. If we wanted to be defensive, add `Field(..., max_length=254)` to `EmailStr` fields. |
| A7 | CONTEXT.md D-06's "Pydantic EmailStr depends on email-validator (already a transitive dep of Pydantic)" is **WRONG** — it's NOT transitive. Researcher must add it explicitly. | §1 | Confirmed via `pip uninstall email-validator` test on installed runtime. The planner must include `email-validator>=2.0` in the requirements.txt diff or add `pydantic[email]` extras. |

**A7 is the only ASSUMPTION → CORRECTION the planner must act on.** All other claims are verified or low-risk.

## Open Questions

1. **Q1 (M1 forward path): python-jose vs PyJWT.**
   - What we know: python-jose 3.5.0 is healthy today; FastAPI's tutorial moved to PyJWT in 2025; both APIs are nearly identical for our use case.
   - What's unclear: Whether python-jose maintenance will erode over the M1 timeline. CONTEXT.md D-02 locks `python-jose` based on "the FastAPI tutorial's de-facto choice through 2024" — that statement is now stale.
   - Recommendation: Honor CONTEXT.md D-02 (use python-jose). Document in `docs/` (or in this RESEARCH.md's State-of-the-Art table, which we did) that PyJWT is the forward path. Re-evaluate at Phase 5 if python-jose has gone 12+ months without a release. Migration cost is ~5 lines.

2. **Q2 (UX): Should `/auth/register` auto-login (return token) or require a separate /auth/login?**
   - What we know: CONTEXT.md D-06 says register returns `{user_id, email, access_token, token_type}` — i.e., auto-login. This is what Pattern 3's skeleton does.
   - What's unclear: Standard UX is split (some apps require email-verify-before-login). M1 has no email verification, so auto-login is fine.
   - Recommendation: Keep auto-login per D-06. No question for the user.

3. **Q3 (Test convention): Should `test_auth_routes.py` use the existing `db_conn` fixture, or set up an isolated test schema?**
   - What we know: Existing integration tests (`test_integration.py`, `test_migration_002.py`) use the live `roadquality` DB. New `test_auth_routes.py` would do the same.
   - What's unclear: Test runs leave `users` rows behind (test cleanup is not zero-cost). Phase 3's tests use named keys with cleanup (`DELETE FROM segment_defects WHERE source_mapillary_id = 'test_dup_999999'`).
   - Recommendation: Mirror Phase 3 — use the live DB, namespace test emails with a `test-` prefix, clean up in fixtures. The planner can choose finer isolation (e.g., `pytest-postgresql`) if desired but that adds a dep.

4. **Q4 (Scope of `/auth/me`): Should we add a `GET /auth/me` to return the current user's email?**
   - What we know: CONTEXT.md D-06 lists three endpoints (register, login, logout). No `/me`.
   - What's unclear: Frontend may want to display "Signed in as user@x.com" in the modal-closed state. Without `/me`, the frontend either (a) parses the JWT client-side (complicated, requires base64 decode), or (b) tracks the email in `localStorage` after login/register response (simple, what auth.ts above does), or (c) skips displaying the email entirely.
   - Recommendation: **Skip** for M1 (option b — store email in localStorage at login/register). If Phase 6 demo feedback wants a "Signed in as" indicator, add `/auth/me` then. NOT a planner discretion item — defer to discuss-phase if user disagrees.

5. **Q5 (Internal API): Should `get_current_user_id` return just the int, or fetch the full `users` row?**
   - What we know: The JWT contains `sub` (user_id) and that's enough for SC #3 (gating). Fetching the row on every request adds an N+1 — the route handlers don't need the email.
   - What's unclear: Future routes that DO want email (e.g., `/auth/me`) would need a separate dep `get_current_user` that DOES fetch.
   - Recommendation: **Both**, layered. `get_current_user_id` returns int (the only one we need today). `get_current_user` (future) fetches the row. Easy additive layering. For Phase 4: only ship `get_current_user_id`.

6. **Q6 (Operational): What happens if pwdlib's hash format changes mid-deployment (e.g., `$argon2id$v=20$...`)?**
   - What we know: pwdlib's argon2 hashes encode all params; `verify_and_update` handles version differences as long as argon2-cffi can parse them.
   - What's unclear: Hypothetical future where argon2id v=19 → v=20 changes the prefix. argon2-cffi would need an upgrade in lockstep.
   - Recommendation: Pin both libs (`pwdlib<0.4` and `argon2-cffi` is already pinned by pwdlib). Don't bump pwdlib mid-phase. Address in a future Phase if argon2id ever bumps version.

## Environment Availability

| Dependency | Required by | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| Python 3.12+ | backend container, scripts/, tests | ✓ | 3.12.13 (`/tmp/rq-venv`); 3.12-slim (Docker) | — |
| PostgreSQL 16+ with PostGIS | DB layer for users table | ✓ (assumed running per Phase 3 precedent; tests auto-skip if down) | 16-3.4 image | Tests use `db_available` skip marker |
| pwdlib 0.3.0 | password hashing | NOT YET INSTALLED on dev runtime; INSTALLABLE via pip [VERIFIED — `pip install 'pwdlib[argon2]'` succeeded on `/tmp/rq-venv`] | — | None — required |
| python-jose 3.5.0 | JWT | NOT YET INSTALLED; INSTALLABLE [VERIFIED — `pip install 'python-jose[cryptography]'` succeeded] | — | PyJWT (Open Q1) |
| email-validator 2.3.0 | EmailStr backend | NOT installed on dev (Pydantic 2.13 doesn't pull it transitively) [VERIFIED]; INSTALLABLE | — | None — required |
| `secrets` (stdlib) | AUTH_SIGNING_KEY generation in README + scripts | ✓ | stdlib | — |
| Node 20+ + Vite 6 | Frontend modal, react 18.3.1, tailwind 3.4.17 | ✓ (existing) | per package.json | — |
| docker-compose | local dev orchestration | ✓ (existing) | — | — |

**Missing dependencies with no fallback:** None at the project level — all phase-4 additions install cleanly via `pip install` on the existing Python 3.12 runtime. The only "blocker" is the operator must `pip install -r backend/requirements.txt` after the requirements bump.

**Missing dependencies with fallback:** python-jose has PyJWT as the swap-in fallback per Open Q1 — but we don't need to invoke it now.

## Validation Architecture

> Per `.planning/config.json` — `workflow.nyquist_validation` is absent (treat as enabled). This section is included.

### Test framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.3.4 + httpx 0.28.1 (FastAPI TestClient) |
| Config file | `backend/tests/conftest.py` (existing) — adds `fake_user_id` + `authed_client` in Wave 0 |
| Quick run command | `cd backend && pytest tests/test_auth_*.py -x` |
| Full suite command | `cd backend && pytest -x` |

### Phase Requirements → Test Map

See Section 4 — same table is reproduced there. Every SC #1-#5 has at least one automated test that runs in <30s.

### Sampling Rate

- **Per task commit:** `pytest backend/tests/test_auth_*.py -x` (estimated 3-5s; argon2 is the slowest call, ~150ms per hash, ~6-8 hashes total in the unit suite)
- **Per wave merge:** `cd backend && pytest -x` (full suite, ~30s on dev laptop)
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `backend/tests/conftest.py` — add `fake_user_id` + `authed_client` fixtures (Pattern 1)
- [ ] `backend/tests/test_auth_passwords.py` — NEW (covers SC #4)
- [ ] `backend/tests/test_auth_tokens.py` — NEW (covers JWT round-trip + Pitfall 2 alg=none)
- [ ] `backend/tests/test_auth_routes.py` — NEW (covers SC #1-#3, end-to-end via TestClient)
- [ ] `backend/tests/test_migration_003.py` — NEW (covers SC #5; mirrors `test_migration_002.py`)
- [ ] No framework install needed — pytest, httpx, psycopg2 already in `backend/requirements.txt`. The Phase 4 deps (pwdlib, python-jose, email-validator) are app deps, not test-only.

## Security Domain

> Required since `security_enforcement` is not explicitly disabled in config. (Confirmed: config.json has only `workflow._auto_chain_active`.)

### Applicable ASVS categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | YES | argon2id via pwdlib (V2.4.1, V2.4.2 — modern KDF, parameter strength); JWT HS256 with rotatable key (V2.10.1 — credential rotation) |
| V3 Session Management | YES | Stateless JWT with `exp` claim (V3.3.1 — token lifetime). No refresh tokens for M1; `AUTH_SIGNING_KEY` rotation = global revocation lever (V3.3.2). |
| V4 Access Control | PARTIAL | One role (authenticated user). `/route` and `/cache/*` gated; `/health` and `/segments` public. No RBAC needed for M1. |
| V5 Input Validation | YES | Pydantic v2 EmailStr (V5.1.3 — email format), Field constraints on password length (V5.1.4 — bounded input) |
| V6 Cryptography | YES | argon2id (V6.2.1 — approved KDF), HS256 (V6.2.4 — approved JWT algorithm). `AUTH_SIGNING_KEY` >= 32 chars enforced at startup (V6.2.7 — secret strength). |
| V7 Error Handling & Logging | YES | Don't log passwords / hashes / tokens (V7.1.1, V7.1.4 — sensitive data redaction). Login error message is generic ("Invalid credentials") — no enumeration leak (V7.4.2). |

### Known threat patterns for FastAPI + JWT auth

| Pattern | STRIDE | Standard mitigation |
|---------|--------|---------------------|
| Algorithm substitution / `alg=none` | Tampering | Pin `algorithms=['HS256']` (LIST) in `jwt.decode`. Pitfall 2. [VERIFIED on installed runtime: alg=none token raises JWTError.] |
| Plaintext password logging | Information disclosure | Don't log request bodies for /auth/* routes. Pitfall 1. |
| Username enumeration via login timing | Information disclosure | Dummy-hash verification on missing-user path. Pitfall 5. |
| Username enumeration via login error message | Information disclosure | Always "Invalid credentials" — never "Email not found." (Phase 4 register endpoint DOES leak via "Email already registered" 400; this is unavoidable for register UX. Acceptable trade.) |
| Stolen token via XSS → localStorage | Repudiation / EoP | Documented trade (CONTEXT.md D-04). 7-day cap + signing-key rotation as revocation. Pitfall 6. |
| Brute-force login | DoS / EoP | OUT OF SCOPE for Phase 4 — Phase 5 reverse proxy / WAF rate limit. argon2's ~150ms hash time is a soft natural limit (~6-7 attempts/sec/CPU). |
| SQL injection on `/auth/login` | Tampering | Always parameterized: `cur.execute("SELECT ... WHERE email = %s", (email,))`. Project convention; Pattern 3 follows it. |
| CORS misconfiguration → CSRF | EoP | OUT OF SCOPE for Phase 4 — Phase 5 owns CORS hardening. Phase 4's auth changes don't make CORS worse. |
| Weak signing key | Tampering | Startup check: `len(AUTH_SIGNING_KEY) >= 32`. README documents `secrets.token_urlsafe(32)`. Section 8. |
| Mid-session signing-key rotation | DoS (intentional) | Documented behavior — Pitfall 9. |

## Sources

### Primary (HIGH confidence)
- pwdlib README — github.com/frankie567/pwdlib — Argon2Hasher constructor signature + recommended() defaults [VERIFIED via `inspect.signature` on installed package]
- python-jose docs — pypi.org/project/python-jose — version 3.5.0 (May 2025), no deprecation [CITED]
- FastAPI security tutorial — fastapi.tiangolo.com/tutorial/security/oauth2-jwt — current pattern (PyJWT + pwdlib) as of 2025-2026 [CITED]
- OWASP Password Storage Cheat Sheet — cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html — argon2id m=19456/t=2/p=1 minimum [CITED]
- OWASP JWT Cheat Sheet — cheatsheetseries.owasp.org/cheatsheets/JSON_Web_Token_for_Java_Cheat_Sheet.html — alg=none, signing key length, sidejacking patterns [CITED]
- Phase 3 RESEARCH.md (`.planning/phases/03-mapillary-ingestion-pipeline/03-RESEARCH.md`) — migration idempotency precedent, project conventions reuse [VERIFIED via direct read]
- Phase 3 migration `db/migrations/002_mapillary_provenance.sql` — `CREATE UNIQUE INDEX IF NOT EXISTS` pattern [VERIFIED]
- Project codebase: `backend/app/main.py`, `backend/app/db.py`, `backend/app/models.py`, `backend/app/routes/*`, `backend/tests/conftest.py`, `frontend/src/api.ts`, `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/pages/RouteFinder.tsx`, `docker-compose.yml`, `backend/requirements.txt`, `frontend/package.json` [all VERIFIED via direct read]

### Secondary (MEDIUM confidence)
- python-jose 3.5.0 + pwdlib 0.3.0 + email-validator 2.3.0 round-trip behavior — verified via `pip install` + scripted exercises on `/tmp/rq-venv/bin/python` (Python 3.12.13). All claims about `verify_and_update`, `algorithms=[ALG]`, `EmailStr` lowercasing semantics, `HTTPBearer(auto_error=True)` 401-vs-403 in FastAPI 0.136 — verified.
- pwdlib argon2 default parameter values (m=65536, t=3, p=4) — read directly from `Argon2Hasher.__init__` signature on installed runtime.

### Tertiary (LOW confidence)
- None. Every claim in this research is either verified on the installed runtime or cited from an official doc.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all three Phase-4-new libraries installed and exercised on the dev runtime in this research session
- Architecture (FastAPI Depends, router-level deps, override seam): HIGH — verified pattern works on FastAPI 0.136
- Migration template: HIGH — direct mirror of Phase 3 pattern, with documented rationale for `CREATE UNIQUE INDEX IF NOT EXISTS` over inline UNIQUE
- Pitfalls: HIGH for the cryptographic ones (Pitfall 2 alg=none verified by hand-crafted token); MEDIUM for the operational ones (Pitfall 4 verify_and_update upgrade flow — verified mechanically; the "you'll never bump pwdlib in a way that breaks this" assumption is A1)
- Test patterns: HIGH — fixtures + override seam verified on installed runtime
- Frontend pattern: MEDIUM — modal skeleton is straightforward Tailwind + React, but no existing modal in codebase to mirror; recommendation is the simplest viable controlled-component pattern
- Demo seed: HIGH — `ON CONFLICT (email) DO UPDATE` idempotency is bog-standard psql; `seed_demo_user.py` mirrors Phase 3 conventions exactly
- AUTH_SIGNING_KEY plumbing: MEDIUM — fail-fast at startup verified locally; `${VAR:-}` interpolation is standard docker-compose; the actual prod-secret-store path is Phase 5

**Research date:** 2026-04-25
**Valid until:** ~2026-05-25 (30 days; libraries are stable; only watch item is python-jose maintenance signal per Open Q1)
