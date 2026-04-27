---
phase: 04-authentication
reviewed: 2026-04-25T00:00:00Z
depth: standard
files_reviewed: 26
files_reviewed_list:
  - backend/app/auth/__init__.py
  - backend/app/auth/passwords.py
  - backend/app/auth/tokens.py
  - backend/app/auth/dependencies.py
  - backend/app/main.py
  - backend/app/routes/auth.py
  - backend/app/routes/cache_routes.py
  - backend/app/routes/routing.py
  - backend/requirements.txt
  - backend/tests/conftest.py
  - backend/tests/test_auth_passwords.py
  - backend/tests/test_auth_tokens.py
  - backend/tests/test_auth_routes.py
  - backend/tests/test_cache.py
  - backend/tests/test_integration.py
  - backend/tests/test_route.py
  - frontend/src/api/auth.ts
  - frontend/src/api.ts
  - frontend/src/components/SignInModal.tsx
  - frontend/src/pages/RouteFinder.tsx
  - scripts/seed_demo_user.py
  - db/migrations/003_users.sql
  - backend/tests/test_migration_003.py
  - docker-compose.yml
  - .env.example
findings:
  critical: 0
  warning: 4
  info: 7
  total: 11
status: issues_found
---

# Phase 4: Code Review Report

**Reviewed:** 2026-04-25
**Depth:** standard
**Files Reviewed:** 26
**Status:** issues_found

## Summary

Phase 4 (REQ-user-auth) implements HS256 JWT + argon2id password hashing with strong defenses against the JWT/auth pitfalls called out in 04-RESEARCH.md. The locked anti-footgun patterns are all in place:

- `algorithms=[ALGORITHM]` is a list (Pitfall 2 — alg substitution), with a regression test that crafts an alg=none token and asserts rejection.
- `_signing_key()` reads `AUTH_SIGNING_KEY` at call-time and fails LOUD on missing or <32-char keys.
- `_DUMMY_HASH` is computed once at import and used on the missing-user login path so wall-clock time matches the wrong-password path (Pitfall 5 — user enumeration).
- Email is normalized via `.strip().lower()` consistently across `register`, `login`, and `scripts/seed_demo_user.py` (Pitfall 3).
- `HTTPBearer(auto_error=False)` is configured in exactly one place (`backend/app/auth/dependencies.py:23`), with explicit `HTTPException(401, headers={"WWW-Authenticate": "Bearer"})` raises. SC #3 (401 vs 403) holds.
- Public/gated wiring is correct: `/health` and `/segments` have no auth dep; `/route` uses `Depends(get_current_user_id)`; `/cache/*` uses `APIRouter(dependencies=[Depends(get_current_user_id)])`.
- Migration 003 is idempotent (`CREATE TABLE IF NOT EXISTS` + `CREATE UNIQUE INDEX IF NOT EXISTS`) and contains no seed INSERTs. The demo seed is in `scripts/seed_demo_user.py` with `ON CONFLICT (email) DO UPDATE` for rotation safety.
- Frontend localStorage is touched only inside `frontend/src/api/auth.ts` (single seam). `api.ts` and `RouteFinder.tsx` consume only `getToken()`/`clearToken()` — no direct `localStorage.*` calls outside the seam.
- Test isolation is correct: `_override_auth` autouse fixtures in `test_cache.py`, `test_integration.py`, `test_route.py` install `dependency_overrides` and pop them on teardown. No cross-test global-state leakage observed.

Four warnings stand out: (a) `verify_and_maybe_rehash` is exported and documented as "Use this on /auth/login" but `routes/auth.py` calls plain `verify_password` (transparent param-bump rehashing not wired); (b) `SignInModal.tsx` mode-toggle buttons inside the `<form>` lack `type="button"` and trigger spurious form submit on click; (c) DB connections leak across `auth.py` + `routing.py` because `psycopg2`'s connection-as-context-manager only manages the transaction, not the connection (pre-existing pattern, but Phase 4 replicates it); (d) `seed_demo_user.py` defaults `--password` to `"demo1234"` in source — D-05 is explicit that the password is rotatable, but the literal lives in the script's `DEFAULT_PASSWORD` constant alongside the README/frontend, weakening the "single source of truth" intent.

The remaining info items are minor (modal a11y, docker-compose default, dummy hash referenced before binding).

## Warnings

### WR-01: Login path does not use `verify_and_maybe_rehash`

**File:** `backend/app/routes/auth.py:102`
**Issue:** `backend/app/auth/passwords.py:54-57` defines `verify_and_maybe_rehash` and its docstring is explicit: "Use this on /auth/login (plan 04-03). Don't bother on /auth/register". But `routes/auth.py` line 102 calls `verify_password(req.password, stored_hash)` instead. This means future pwdlib param bumps (Pitfall 4) will NOT transparently upgrade existing user hashes — a planned strengthening lever is not wired.

The function is exported and tested (`test_verify_and_maybe_rehash_returns_tuple_with_no_rehash_for_fresh_hash`) but never called from production code, so this is a dead-code-path-from-the-API-surface bug, not just a missed feature.

**Fix:**
```python
# backend/app/routes/auth.py, in login()
valid, new_hash = verify_and_maybe_rehash(req.password, stored_hash)
if not valid:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
    )
if new_hash is not None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET password_hash = %s WHERE id = %s",
                (new_hash, user_id),
            )
            conn.commit()
token = encode_token(user_id=user_id)
return Token(access_token=token)
```
And update the import: `from app.auth.passwords import hash_password, verify_password, verify_and_maybe_rehash`.

### WR-02: SignInModal mode-toggle buttons missing `type="button"` — clicking submits the form

**File:** `frontend/src/components/SignInModal.tsx:115-122,128-135`
**Issue:** The "Create one" / "Sign in" mode-switch buttons live inside the `<form onSubmit={handleSubmit}>` element. HTML default for `<button>` inside `<form>` is `type="submit"`. Clicking either toggle button will:
1. Trigger form submission (running `handleSubmit`, which calls register/login with whatever's in the email/password fields),
2. THEN run the onClick handler that flips `mode`.

If the user is mid-typing and clicks "Create one" to switch modes, the form fires a login attempt with the partial credentials before the mode flips. The "Try as demo" button (line 103) and the toggle buttons all need `type="button"`.

**Fix:**
```tsx
<button
  type="button"
  onClick={() => { setMode("register"); setError(null); }}
  className="text-blue-600 hover:underline"
>
  Create one
</button>
```
Apply the same `type="button"` to the "Sign in" toggle (line 128) and the "Try as demo" button (line 103) — the demo button currently works only because it sets state synchronously before any submit propagation, but it's the same latent footgun.

### WR-03: DB connection leak in `auth.py` (and pre-existing in `routing.py`)

**File:** `backend/app/routes/auth.py:58-67,86-92`; `backend/app/routes/routing.py:59-65,73-80`
**Issue:** `app.db.get_connection()` returns `psycopg2.connect(...)`. When used as `with get_connection() as conn:`, psycopg2's connection-as-context-manager **only manages the transaction** (commit on success, rollback on exception); it does NOT close the connection. From the psycopg2 docs: *"the connection will not be closed and can be used by following statements."*

Every `/auth/register`, `/auth/login`, `/route` call leaks one TCP connection to Postgres. With FastAPI's threadpool sizing and a few hundred requests, this exhausts the Postgres `max_connections` (default 100). The pattern was pre-existing in `routing.py` before Phase 4, but `auth.py` (new this phase) inherits it.

**Fix:** Wrap with explicit `try/finally` or use `contextlib.closing`:
```python
from contextlib import closing

# in register()
with closing(get_connection()) as conn, conn:
    with conn.cursor() as cur:
        ...
```
The double `with` is the idiom: outer `closing` ensures `conn.close()`, inner `conn` (transaction context) handles commit/rollback. Alternatively introduce a connection pool (`psycopg2.pool.ThreadedConnectionPool`) and dispense with per-request connect/close. Either way, fix `routing.py` at the same time — they share the bug.

### WR-04: `seed_demo_user.py` defaults password to `"demo1234"` literal

**File:** `scripts/seed_demo_user.py:49,57`
**Issue:** The phase brief calls out: "Demo seed: ON CONFLICT DO UPDATE for rotation-safe re-seed; password not in source code (README only)." The ON CONFLICT logic is correct (line 68-72), but the password literal `"demo1234"` lives in `DEFAULT_PASSWORD` (line 49) and the argparse default (line 57). The frontend modal also hardcodes it (`SignInModal.tsx:13`) — that one is unavoidable for the "Try as demo" UX. But the seed script's default is pure convenience; if someone rotates `demo1234` to a new value in README/frontend but forgets the seed script, `python scripts/seed_demo_user.py` (no args) silently re-seeds the OLD password.

This is a coupling/correctness issue, not a leak — the password is already public in README. The risk is rotation drift across the three sites (README, `SignInModal.tsx`, `seed_demo_user.py`).

**Fix:** Either (a) make `--password` required (no default), forcing the operator to pass it explicitly each time; or (b) read from an env var `DEMO_PASSWORD` so all three sites pull from the same place. Option (a) is simpler:
```python
ap.add_argument("--password", required=True,
                help="Demo password (rotatable; see README for current value)")
```
Then update the README "Quick start" snippet and CI invocations to pass `--password demo1234`. This makes the password live in exactly two places: the README (truth source for humans) and `SignInModal.tsx:13` (truth source for the demo button).

## Info

### IN-01: `_DUMMY_HASH` is referenced (line 95) before its definition (line 121)

**File:** `backend/app/routes/auth.py:95,121`
**Issue:** Module-level definition order: `def login()` references `_DUMMY_HASH` on line 95, but `_DUMMY_HASH = hash_password(...)` is defined on line 121. This works at runtime because the name lookup happens only when `login()` is CALLED (after module import completes), not at function-def time. But it's confusing on first read and most linters/IDEs flag the apparent forward reference.
**Fix:** Move the `_DUMMY_HASH = hash_password("__dummy_for_timing_safety_do_not_match__")` line to just below the `_normalize_email` helper (e.g., after line 47) so readers see the definition before the reference. Add a comment that this runs ~150-300ms at import, intentionally.

### IN-02: `docker-compose.yml` passes `AUTH_SIGNING_KEY: ${AUTH_SIGNING_KEY:-}` — empty default

**File:** `docker-compose.yml:29`
**Issue:** The `:-` syntax falls back to empty string if `AUTH_SIGNING_KEY` is unset on the host. `_signing_key()` will then raise `RuntimeError` on the first auth-touching request (not at backend startup), giving a misleading "first /auth/login request fails" symptom rather than "container fails to start." The `.env.example` requires the operator to fill in the key, but if they forget, the failure mode is delayed.
**Fix:** Either (a) drop the `:-` default so docker-compose itself errors with `WARN The AUTH_SIGNING_KEY variable is not set` when missing; or (b) add a startup-time check (e.g., FastAPI `@app.on_event("startup")` that calls `_signing_key()` once and lets the exception abort startup). Option (b) makes the failure mode "container exits with traceback" instead of "200 OK on /health, 500 on first login" — clearer for operators.

### IN-03: SignInModal lacks ARIA roles, focus management, and Escape-to-close

**File:** `frontend/src/components/SignInModal.tsx:62-141`
**Issue:** The modal div has no `role="dialog"`, no `aria-modal="true"`, no `aria-labelledby`. Initial focus is not moved into the modal on open; focus is not trapped while open; pressing Escape does not close. Backdrop-click-to-close (line 65) works, but keyboard-only users have no equivalent. Screen readers see this as just another `<div>`.
**Fix:**
```tsx
<div
  role="dialog"
  aria-modal="true"
  aria-labelledby="signin-modal-title"
  className="fixed inset-0 z-[2000] ..."
  onClick={onClose}
  onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}
>
  <div onClick={(e) => e.stopPropagation()} className="...">
    <h2 id="signin-modal-title" className="...">{mode === "login" ? "Sign in" : "Create account"}</h2>
    ...
```
Add a `useEffect` with `useRef` on the email `<input>` to call `.focus()` when `open` flips to true. A full focus-trap is overkill for a 2-input form; first-input-focus + Escape-to-close covers 90% of the gap.

### IN-04: `EmailStr` validation does not enforce normalization — relies on app layer

**File:** `backend/app/routes/auth.py:24,29,42-46`
**Issue:** Pydantic `EmailStr` validates the format (RFC 5322-ish) and lowercases the domain part (per email-validator's defaults), but **preserves the local-part case**. The code correctly `.strip().lower()`s inside `_normalize_email`. The risk: if a future contributor writes a new endpoint that uses `EmailStr` and queries `users` directly without going through `_normalize_email`, the case-insensitivity invariant breaks. The migration test `test_email_uniqueness_is_case_sensitive_at_db_layer` documents that the DB stores byte-exact, so this is the intentional contract — but the contract lives in three places (helper, migration comment, test) and isn't enforced by a Pydantic validator.
**Fix (optional):** Add a Pydantic field validator that performs the normalization, so any model declaring `email: EmailStr` gets normalized form for free:
```python
from pydantic import field_validator

class _NormalizedEmail(BaseModel):
    email: EmailStr
    @field_validator("email", mode="after")
    @classmethod
    def _norm(cls, v: str) -> str: return v.strip().lower()
```
Or accept the current contract and add a comment in `_normalize_email` pointing to the migration test as the regression guard.

### IN-05: Demo password constant duplication across three sites

**File:** `frontend/src/components/SignInModal.tsx:13`; `scripts/seed_demo_user.py:49`; `README.md:180`
**Issue:** Companion to WR-04. The literal `"demo1234"` appears in three independent files with no shared truth source. WR-04 covers the seed script; the frontend hardcoding is intrinsic to the "Try as demo" button (it has to send the literal password). Document the rotation procedure in `04-CONTEXT.md D-05` so future operators know to update all three.
**Fix:** Add a `Rotation procedure` checklist to README right after the demo-creds section:
```
To rotate the demo password:
1. Update README.md (this section).
2. Update frontend/src/components/SignInModal.tsx DEMO_PASSWORD.
3. Run: python scripts/seed_demo_user.py --password $NEW_PW
```
No code change strictly required, but the doc note prevents drift.

### IN-06: `Token` Pydantic model unused in `RegisterResponse`

**File:** `backend/app/routes/auth.py:35-39,107-108`
**Issue:** `RegisterResponse` redeclares `access_token: str` and `token_type: str = "bearer"` instead of composing/inheriting `Token`. Login uses `Token` directly. The shapes match, but if someone bumps `Token` (e.g., adds `expires_in`), `RegisterResponse` won't inherit the change.
**Fix:** Either compose:
```python
class RegisterResponse(BaseModel):
    user_id: int
    email: EmailStr
    token: Token  # nested
```
or inherit:
```python
class RegisterResponse(Token):
    user_id: int
    email: EmailStr
```
Inheritance preserves the flat JSON shape that the frontend already expects. Style choice; not a functional bug.

### IN-07: `backend/app/auth/__init__.py` is empty (zero bytes)

**File:** `backend/app/auth/__init__.py`
**Issue:** Empty `__init__.py` makes the `app.auth` package a namespace package with no public surface. Imports use the fully-qualified path (`from app.auth.tokens import ...`), which works. No bug.
**Fix (optional):** Add `__all__` or re-exports for ergonomics:
```python
"""Authentication subpackage: argon2id passwords + HS256 JWT tokens."""
from .tokens import encode_token, decode_token, Token, TokenError  # noqa: F401
from .passwords import hash_password, verify_password, verify_and_maybe_rehash  # noqa: F401
from .dependencies import get_current_user_id  # noqa: F401
```
Skip if you prefer explicit fully-qualified imports throughout the codebase.

---

_Reviewed: 2026-04-25_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
