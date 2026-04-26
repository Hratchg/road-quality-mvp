---
phase: 04-authentication
created: 2026-04-26
status: ready_to_research
requirements: [REQ-user-auth]
dependencies: [Phase 1 (integrity)]
---

# Phase 04 — Authentication: Decision Context

This document captures the locked decisions from the discuss-phase conversation. Downstream agents (`gsd-phase-researcher`, `gsd-planner`) consume it to know WHAT to investigate and WHAT NOT to re-ask.

## Phase goal (from ROADMAP.md)

> Users can sign up, sign in, and sign out; state-mutating and expensive endpoints require auth so the public demo can't be drained by anonymous traffic.

## Success Criteria (from ROADMAP — locked, do not negotiate)

1. User can sign up with email + password via an API endpoint (UI optional for M1)
2. User can sign in, receive a session token (or cookie), and use it on subsequent requests
3. `POST /route` and `/cache/*` return `401` without valid credentials; `GET /health` and `GET /segments` remain public
4. Passwords are hashed (bcrypt/argon2-equivalent), never stored as plaintext
5. A new migration in `db/migrations/` adds the users table; the migration applies cleanly to a fresh DB via the existing init flow

## What downstream agents need to know

### D-01 — Session mechanism: JWT (HS256, env-signed)

**Decision:** Stateless JWT with HS256, signing key from environment (`AUTH_SIGNING_KEY`). Payload = `{sub: user_id, iat, exp}`. No refresh token. No denylist for M1.

**Why:** Phase 5 SC #3 explicitly mentions "auth signing key" — JWT is the cleanest fit. Stateless avoids per-request DB hits at the auth layer. We don't need server-side revocation at MVP scale; if a session is compromised, the user changes password and we rotate `AUTH_SIGNING_KEY` globally (acceptable trade for ~30 lines saved).

**Implementation hint:** `python-jose[cryptography]` for encode/decode. Read `AUTH_SIGNING_KEY` once at app startup (similar to how `data_pipeline/detector_factory.py:49` reads `YOLO_MODEL_PATH_ENV`). Fail-fast on missing key in non-test environments.

**What's NOT in scope for M1 (deferred — additive if needed):**
- Refresh-token pattern
- Server-side denylist / revocation table
- Token rotation on use
- Multi-device session listing

### D-02 — Auth library: pwdlib + python-jose

**Decision:** Hand-roll. `pwdlib` (argon2id hashing — the modern successor to passlib) + `python-jose[cryptography]` (JWT). Three modules + one routes file.

**Why:** `fastapi-users` requires SQLAlchemy, which conflicts with the locked raw-psycopg2 convention from `CON-db-schema`. `passlib` works but is in maintenance mode; `pwdlib` is forward-looking and smaller. Hand-roll is ~150 lines, which is comparable to wiring up a framework anyway.

**Locked dependencies (additive to `backend/requirements.txt`):**
- `pwdlib[argon2]>=0.2.1` — argon2id password hashing
- `python-jose[cryptography]>=3.3.0` — JWT encode/decode

**Locked file layout (researcher should confirm against existing `backend/app/` patterns):**
- `backend/app/auth/__init__.py`
- `backend/app/auth/passwords.py` — hash/verify helpers
- `backend/app/auth/tokens.py` — JWT encode/decode + `Token` Pydantic model
- `backend/app/auth/dependencies.py` — FastAPI `Depends(current_user)` + `get_current_user_id` helper
- `backend/app/routes/auth.py` — `/auth/register`, `/auth/login`, `/auth/logout`

### D-03 — Password algorithm: argon2id

**Decision:** argon2id via pwdlib (default params). Not bcrypt.

**Why:** OWASP-recommended for new systems. No 72-byte input limit. Matches the SC's "bcrypt/argon2-equivalent" language. The migration locks the column shape (`password_hash TEXT NOT NULL` — argon2 hashes are ~100 chars, fit in TEXT).

### D-04 — Frontend UI scope: minimal sign-in modal on `/route`

**Decision:** One `<SignInModal>` component on the existing `/route` page. Opens automatically on first 401 from `/route` or `/cache/*`. Contains both register and login forms (toggle between modes). Public `/map` stays untouched.

**Why:** The roadmap explicitly says "UI optional for M1" but Phase 6 needs *some* visitor path to obtain a token. A modal is ~120 LOC, doesn't add new routes, doesn't pollute the headline `/map` experience.

**Implementation hint:** Use the existing Tailwind setup. Modal state lives in `RouteFinder.tsx` (or a small auth context if researcher determines it's needed for `/cache/*`). Token persists in `localStorage` (acceptable trade for stateless JWT; no XSS-grade defense at MVP scale, and our API only exposes routing).

**Frontend deliverables:**
- `frontend/src/components/SignInModal.tsx`
- `frontend/src/api/auth.ts` — `register()`, `login()`, `logout()`, token storage
- `frontend/src/api.ts` modification — attach `Authorization: Bearer <token>` to `/route` and `/cache/*` requests
- 401-response interceptor that triggers the modal

**What's NOT in scope:**
- Dedicated `/signin` or `/signup` routes (deferred — could be added in M2)
- "Forgot password" / password reset flow (deferred — explicitly out of scope per roadmap)
- Email verification (explicitly out of scope per roadmap)

### D-05 — Public demo account strategy: hybrid

**Decision:** Open registration + "Try as demo" button on the sign-in modal. Demo creds = `demo@road-quality-mvp.dev` / `demo1234`, documented in README.md. Demo account is seeded via `scripts/seed_demo_user.py` (or equivalent — researcher to determine cleanest path).

**Why:** Phase 6 SC #3 says "/route returns ... after sign-in, if auth gates /route". Friction directly hurts demo conversion. The hybrid approach gives drive-by visitors a one-click path AND lets stakeholders see the "real auth" story.

**Concrete deliverables:**
- "Try as demo" button on the modal — auto-fills the form with demo creds, submits
- README "Public Demo" section documents the credentials
- Seed script ensures the demo account exists (or migration includes an INSERT — researcher's call based on convention)

**Demo account hygiene:**
- Demo password is documented and rotatable. If abuse appears, rotate the password + update README + redeploy.
- The demo account has no special privileges — it's just a regular user that's known publicly.

### D-06 — Default API surface (NOT discussed; default applied)

**Decision (default):** Three endpoints on `/auth` prefix:
- `POST /auth/register` → 201 with `{user_id, email, access_token, token_type: "bearer"}` on success; 400 on duplicate email; 422 on validation errors
- `POST /auth/login` → 200 with `{access_token, token_type: "bearer"}` on success; 401 on bad creds
- `POST /auth/logout` → 204 (client-side only; no server state to clear)

Error shape uses FastAPI's standard Pydantic `{detail: ...}` shape — consistent with the rest of the API.

**No rate limiting in Phase 4.** Defer to Phase 5 (cloud deploy can add a reverse-proxy / WAF rate limit; an in-process limiter is duplicate work that gets thrown out).

**Email validation:** Pydantic `EmailStr` — depends on `email-validator` (already a transitive dep of Pydantic; researcher to confirm).

### D-07 — Default session lifetime (NOT discussed; default applied)

**Decision (default):** JWT `exp` set to **7 days from issue**. No sliding window in M1 (no refresh, so no point). Logout = client clears `localStorage`.

**Why:** Long enough that demo visitors don't get logged out mid-session. Short enough that abandoned tokens auto-expire. Matches typical MVP patterns.

## Out of scope for Phase 4 (explicit)

- CORS hardening — owned by Phase 5 SC #2
- Rate limiting on auth endpoints — defer to Phase 5 (reverse proxy / WAF)
- Email verification, password reset, forgot-password flow — out of scope per roadmap
- Per-user data (saved routes, history, preferences) — auth is JUST a gate; no per-user state beyond the user row itself
- Refresh tokens, denylist, multi-device session management — additive if needed post-M1
- OAuth / social login — explicitly not part of REQ-user-auth
- API key auth (separate from user auth) — not requested anywhere
- Roles / RBAC — only one user type for M1

## Existing codebase facts the researcher should verify

- `backend/app/main.py` has `CORSMiddleware` with `allow_origins=["*"]` (CONCERNS.md: known issue, owned by Phase 5)
- `backend/app/db.py` is the sole DB-handle convention; new `users` table reads/writes go through it
- `backend/app/routes/` directory holds endpoint modules (researcher: confirm current files)
- `db/migrations/` is the canonical migration location; mounted into `db` container per Phase 3's `002_mapillary_provenance.sql` precedent. Phase 4 migration filename: `003_users.sql`
- `frontend/src/api.ts` is the single API-client module
- `frontend/src/main.tsx` declares routes via react-router; `/map` and `/route` are the existing pages
- Tests live in `backend/tests/`. Test stack: pytest + httpx-based async test client. Phase 2/3 patterns use `@pytest.mark.integration` for DB-bound tests
- Python venv at `/tmp/rq-venv/bin/python` is the project's canonical Python 3.12 host runtime (per memory `road-quality-mvp_python_runtime.md`)

## Locked column shape for `users` table

Researcher MUST honor this exactly (so the migration is review-ready):

| Column | Type | Notes |
|---|---|---|
| `id` | `BIGSERIAL PRIMARY KEY` | Matches the BIGINT convention from `CON-db-schema` (`road_segments.source/target` are BIGINT). |
| `email` | `TEXT NOT NULL UNIQUE` | Lowercased + trimmed at the app layer before insert (researcher: confirm Pydantic does this consistently). UNIQUE index needed. |
| `password_hash` | `TEXT NOT NULL` | argon2id encoded form (~100 chars). Never log. |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT NOW()` | Matches `segment_defects.created_at` convention. |

## Deferred Ideas (not lost — for future phases or M2)

- Per-user saved routes (would need a `saved_routes` table) — flagged, M2 territory
- Email verification flow — flagged, M2 if real users emerge
- Password reset via email — flagged, M2; needs SMTP
- Refresh-token pattern — flagged, additive if M1 demo reveals UX pain with 7-day expiries
- Server-side session revocation (denylist table) — flagged, additive if abuse appears
- "Forgot password" link in modal — flagged, deferred with reset flow
- Roles / RBAC — flagged, only relevant if non-demo features land

## Research priorities (for gsd-phase-researcher)

The researcher should focus investigation on:

1. **`pwdlib` vs `passlib[argon2]` argon2id parameter recommendations** — what defaults are appropriate for ~MVP-scale traffic? Current OWASP guidance.
2. **`python-jose` vs `pyjwt` vs `authlib`** — verify python-jose is still actively maintained as of 2026 (was the de-facto FastAPI choice in 2024; check for any deprecation signal). Fall back to pyjwt if python-jose has issues.
3. **FastAPI `Depends(...)` patterns for current_user** — best-practice shape for both required and optional auth, since `/segments` stays public but `/route` is gated. Pattern that lets us test endpoints without wiring real JWTs.
4. **Pydantic v2 EmailStr** — confirm the dependency story (`email-validator`) and any pitfalls with our existing `models.py` module.
5. **Common JWT pitfalls in 2026** — `alg=none` confusion (HS256 should be hard-coded server-side), audience claim usage, key rotation strategy. Brief survey only — point to OWASP JWT cheat sheet.
6. **React modal state pattern** — does the existing frontend use a modal anywhere? If yes, follow that. If no, recommend the simplest pattern (controlled component, not portal-based at MVP scale).

The researcher should NOT investigate:
- Whether to use JWT vs sessions (locked → JWT)
- Whether to use SQLAlchemy (locked NO → raw psycopg2)
- Whether to add refresh tokens, denylists, OAuth (out of scope)
- CORS configuration (Phase 5)
- Rate limiting (Phase 5)
