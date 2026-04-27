---
phase: 04-authentication
plan: 02
subsystem: backend/app/auth
tags: [python, auth, jwt, argon2, tdd, fastapi-deps]
requires:
  - REQ-user-auth (this plan implements helpers; route layer in 04-03)
  - backend/requirements.txt (existing 7-dep baseline preserved)
provides:
  - app.auth.passwords.hash_password
  - app.auth.passwords.verify_password
  - app.auth.passwords.verify_and_maybe_rehash
  - app.auth.tokens.encode_token
  - app.auth.tokens.decode_token
  - app.auth.tokens.Token
  - app.auth.tokens.TokenError
  - app.auth.tokens.EXPIRE_DAYS
  - app.auth.tokens.ALGORITHM
  - app.auth.dependencies.get_current_user_id
  - tests.conftest.fake_user_id
  - tests.conftest.authed_client
affects:
  - backend/requirements.txt (additive: 3 new pinned deps)
  - backend/tests/conftest.py (additive: env default + 2 fixtures)
tech-stack:
  added:
    - pwdlib[argon2]>=0.2.1,<0.4
    - python-jose[cryptography]>=3.3.0,<4
    - email-validator>=2.0,<3
  patterns:
    - argon2id via PasswordHash.recommended() (m=65536, t=3, p=4 — 3x OWASP minimum)
    - HS256 JWT with algorithms=[ALGORITHM] LIST (Pitfall 2 alg-substitution guard)
    - Call-time _signing_key() fail-fast (RuntimeError on missing/<32-char key)
    - HTTPBearer(auto_error=True) for FastAPI auth dep
    - pytest dependency_overrides override seam for endpoint tests
key-files:
  created:
    - backend/app/auth/__init__.py
    - backend/app/auth/passwords.py
    - backend/app/auth/tokens.py
    - backend/app/auth/dependencies.py
    - backend/tests/test_auth_passwords.py
    - backend/tests/test_auth_tokens.py
  modified:
    - backend/requirements.txt
    - backend/tests/conftest.py
decisions:
  - Wrap pwdlib's _ph.verify() in try/except so corrupt hashes return False (pwdlib's verify swallows VerifyMismatchError to bool but raises InvalidHashError on malformed input — Rule 1 bug fix to match the test contract)
  - Use single-line os.environ.setdefault() in conftest.py so the plan's grep verifier (which uses single-line patterns) matches
  - All test passwords/keys padded to >=32 chars to satisfy _signing_key() fail-fast threshold
metrics:
  duration_minutes: 5
  tasks_completed: 4
  tests_added: 15
  files_created: 6
  files_modified: 2
  completed_date: "2026-04-25"
commits:
  - 777ddf3 chore(04-02): add pinned auth dependencies (pwdlib, python-jose, email-validator)
  - 98c759a test(04-02): add failing unit tests for app.auth.passwords helpers
  - 343f508 feat(04-02): implement app.auth.passwords + tokens + dependencies (15 unit tests passing)
  - ae98ace chore(04-02): extend conftest.py with AUTH_SIGNING_KEY default + auth fixtures
---

# Phase 04 Plan 02: Password & JWT Helpers Summary

argon2id password hashing + HS256 JWT encode/decode + FastAPI HTTPBearer auth dependency, all delivered as standalone helper modules under `backend/app/auth/` with 15 passing unit tests and a dependency-override conftest seam for downstream route tests.

## Plan Goal

Land the helper layer (`passwords.py`, `tokens.py`, `dependencies.py`) plus the requirements bump and conftest seam so plan 04-03 can write its `/auth/register` and `/auth/login` route tests against a stable, reviewed contract. No routes or DB writes here — those come in 04-03.

## What Shipped

### 1. Three new pinned auth dependencies (Task 1)

Appended to `backend/requirements.txt` under a "Phase 4 auth additions" comment header:

| Dep | Pin | Why |
|-----|-----|-----|
| `pwdlib[argon2]>=0.2.1,<0.4` | D-02 + D-03 | argon2id hashing (modern passlib successor). `<0.4` upper bound because pwdlib is 0.x and a minor bump could change `recommended()` defaults — `verify_and_update` handles this safely but a knowing review is warranted. |
| `python-jose[cryptography]>=3.3.0,<4` | D-02 | HS256 JWT encode/decode. `[cryptography]` extras pulls in `cryptography` for HS256. |
| `email-validator>=2.0,<3` | RESEARCH A7 | **Correction to CONTEXT D-06.** D-06 claimed `email-validator` was a transitive dep of Pydantic 2.10.4 — the researcher verified it is NOT. Pydantic raises `ImportError` on `EmailStr` use without it. Explicit add keeps `requirements.txt` grep-able. |

Existing 7 pins (`fastapi==0.115.6`, `uvicorn[standard]==0.34.0`, `psycopg2-binary==2.9.11`, `pydantic==2.10.4`, `pytest==8.3.4`, `httpx==0.28.1`, `cachetools>=5.3`) preserved verbatim. No `pyjwt` or `passlib` (deferred / declined per D-02).

### 2. `backend/app/auth/passwords.py` — argon2id hash/verify (Task 3)

Public API:

```python
def hash_password(password: str) -> str
def verify_password(password: str, encoded_hash: str) -> bool
def verify_and_maybe_rehash(password: str, encoded_hash: str) -> tuple[bool, str | None]
```

- Single module-level `_ph = PasswordHash.recommended()` (argon2id, m=65536/t=3/p=4 — ~3x OWASP minimum). pwdlib's hashers are stateless and thread-safe.
- `verify_password` wraps `_ph.verify()` in `try/except Exception` → `False` so callers don't have to wrap. Discovery deviation: pwdlib swallows `VerifyMismatchError` to bool but raises `InvalidHashError` on a malformed hash — the test `test_verify_password_rejects_corrupt_hash` made this contract explicit and the wrapper enforces it.
- `verify_and_maybe_rehash` returns `(valid, new_hash_or_None)` so plan 04-03's `/auth/login` can transparently upgrade hashes when pwdlib's defaults bump.
- ZERO `logger.*`/`print(...)` calls. The only `print` substring in the file is inside the `RuntimeError` message string showing the operator how to generate a key (literal Python source, not a runtime call).

### 3. `backend/app/auth/tokens.py` — HS256 JWT encode/decode (Task 3)

Public API:

```python
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class TokenError(Exception): ...

def encode_token(user_id: int, expires_in: timedelta | None = None) -> str
def decode_token(token: str) -> dict

ALGORITHM = "HS256"
EXPIRE_DAYS = 7  # D-07
```

Critical contracts (locked by tests):
- `decode_token` uses `algorithms=[ALGORITHM]` as a **LIST** — Pitfall 2 alg-substitution guard. The `test_decode_token_alg_none_rejected` test crafts a manual `alg=none` token and asserts `TokenError` — if anyone changes that to a string, this test fails.
- `_signing_key()` reads `AUTH_SIGNING_KEY` at **call time** (so test monkeypatching works) and raises `RuntimeError` on missing key OR `len < 32` chars. Both error messages point at `python -c 'import secrets; print(secrets.token_urlsafe(32))'`.
- `EXPIRE_DAYS = 7` per D-07. Payload shape `{sub: str(user_id), iat, exp}` per D-01 (sub stringified per OWASP convention).
- Encode wraps in single try/except that catches `ExpiredSignatureError | JWTClaimsError | JWTError` and re-raises as `TokenError(str(e)) from e` — single error type for callers but original chain preserved for debugging.

### 4. `backend/app/auth/dependencies.py` — FastAPI auth dep (Task 3)

Public API:

```python
def get_current_user_id(creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> int
```

- `HTTPBearer(auto_error=True)` returns 401 automatically on missing/non-Bearer header (FastAPI 0.115+ behavior verified in RESEARCH).
- Two error paths, both return `HTTPException(401, ..., headers={"WWW-Authenticate": "Bearer"})`:
  - `TokenError` from `decode_token` → `detail="Invalid or expired token"` (we deliberately do NOT distinguish expired-vs-bad-sig to avoid leaking a valid-token-shape oracle).
  - Bad payload (missing/non-int `sub`) → `detail="Invalid token payload"`.
- No tests in this plan; plan 04-03 exercises end-to-end via `TestClient` once `/route` and `/cache/*` are gated.

### 5. Two new test files — 15 unit tests, ~0.4s wall time (Tasks 2 + 3)

**`backend/tests/test_auth_passwords.py`** (7 tests, RED in Task 2 → GREEN in Task 3):

- `test_hash_password_returns_argon2id_encoded_string` — `$argon2id$` prefix, ≥60 chars
- `test_verify_password_roundtrip_succeeds`
- `test_verify_password_rejects_wrong_password` — returns False, no raise
- `test_verify_password_rejects_corrupt_hash` — returns False on malformed input
- `test_hash_password_produces_different_hashes_for_same_input` — per-call random salt
- `test_verify_and_maybe_rehash_returns_tuple_with_no_rehash_for_fresh_hash` — `(True, None)` shape
- `test_no_plaintext_in_encoded_hash` — SC #4 paranoia guard

**`backend/tests/test_auth_tokens.py`** (8 tests, GREEN in Task 3):

- `test_encode_decode_roundtrip` — `sub`=str, `exp - iat == 7 days`
- `test_decode_token_with_wrong_key_raises_TokenError`
- `test_decode_token_expired_raises_TokenError` (uses `expires_in=timedelta(seconds=-1)`)
- `test_decode_token_alg_none_rejected` — **Pitfall 2 critical regression guard** (manually-crafted alg=none token)
- `test_decode_token_malformed_raises_TokenError` — `"not.a.jwt"` input
- `test_signing_key_raises_when_env_unset` — RuntimeError with `secrets.token_urlsafe` hint
- `test_signing_key_raises_on_short_key` — RuntimeError with `>= 32` hint
- `test_token_pydantic_model_default_token_type` — `Token(access_token=...).token_type == "bearer"`

### 6. `backend/tests/conftest.py` extension (Task 4)

Three additive pieces, existing fixtures (`db_available`, `client`, `db_conn`) preserved verbatim:

- **Module-top `os.environ.setdefault("AUTH_SIGNING_KEY", "test_secret_do_not_use_in_production_padding_padding")`** runs before `from app.main import app`, so any transitive import of `app.auth.tokens` during test collection has a valid signing key. The `do_not_use_in_production` phrase is a tripwire if it ever ends up in production logs.
- **`pytest_configure` hook also calls `setdefault`** — belt-and-suspenders if a test that monkeypatches the env didn't restore it. `setdefault` is idempotent, so an explicit CI override still wins.
- **`fake_user_id` (returns 42) + `authed_client` fixtures.** `authed_client` overrides `app.dependency_overrides[get_current_user_id]` inside the function-scoped fixture body — clean per-test setup/teardown, no bleed across tests. Inline `from app.auth.dependencies import get_current_user_id` keeps the import at fixture-call time (resolves only after Task 3 lands the module).

## Tasks Completed

| Task | Type | Commit | Files | Done Criteria |
|------|------|--------|-------|---------------|
| 1: Bump requirements.txt | auto | 777ddf3 | backend/requirements.txt | 10 dep lines, 3 new ones grep-match |
| 2 (RED): Failing password tests | tdd | 98c759a | backend/app/auth/__init__.py, backend/tests/test_auth_passwords.py | 7 test fns, ModuleNotFoundError observed |
| 3 (GREEN): Implement 3 modules + 8 token tests | tdd | 343f508 | backend/app/auth/{passwords,tokens,dependencies}.py, backend/tests/test_auth_tokens.py | 15 tests pass, no SQLAlchemy, algorithms=[ALGORITHM] LIST locked |
| 4: Extend conftest.py | auto | ae98ace | backend/tests/conftest.py | env setdefault + 2 fixtures, no regressions |

## Verification Results

End-of-plan checks (per the plan's `<verification>` block):

| Check | Command | Result |
|-------|---------|--------|
| All auth modules importable | `python -c "from app.auth.{passwords,tokens,dependencies} import *"` (with AUTH_SIGNING_KEY set) | `imports OK` |
| Auth unit tests pass | `pytest tests/test_auth_passwords.py tests/test_auth_tokens.py -v` | 15 passed in 0.37s |
| No regressions on existing tests | `pytest tests/test_health.py tests/test_models.py tests/test_scoring.py` | 13 passed (28 total with auth tests) |
| Pitfall 2 alg=none guard active | `pytest -k alg_none -v` | `test_decode_token_alg_none_rejected PASSED` |
| No SQLAlchemy / fastapi-users | `grep -rE "(sqlalchemy\|fastapi_users)" backend/app/auth/` | (empty) |
| No actual logger/print on secrets | `grep -rE "^\s*(logger\|log)\." backend/app/auth/` + `grep -rE "^\s*print\(" backend/app/auth/` | (empty) |
| algorithms is a LIST not string | `grep -E 'algorithms\s*=\s*"' backend/app/auth/tokens.py` | (empty — only `[ALGORITHM]` form) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Bug] `verify_password` wraps `_ph.verify()` in try/except**
- **Found during:** Task 3 (running test_auth_passwords.py)
- **Issue:** RESEARCH Pattern 4 line 535 claimed pwdlib swallows all verify failures into a bool. In practice (verified on pwdlib 0.2.x runtime), `_ph.verify()` swallows `VerifyMismatchError` (wrong password) into `False`, but raises `InvalidHashError` (or similar) on a malformed/corrupt hash. The test `test_verify_password_rejects_corrupt_hash` requires `False` for malformed input.
- **Fix:** Wrapped `_ph.verify(password, encoded_hash)` in `try/except Exception: return False`. Caller-friendly contract preserved; the test contract holds.
- **Files modified:** `backend/app/auth/passwords.py`
- **Commit:** `343f508`

**2. [Rule 3 — Blocking] Single-line `os.environ.setdefault()` to satisfy plan grep verifier**
- **Found during:** Task 4 (running plan's verify command)
- **Issue:** Initial conftest.py edit used multi-line `os.environ.setdefault(\n  "AUTH_SIGNING_KEY",\n  "...",\n)` for readability. Plan's verify grep `grep -q "os.environ.setdefault.*AUTH_SIGNING_KEY"` is single-line and didn't match.
- **Fix:** Reformatted both call sites to single-line so the plan-supplied verifier passes. Functionally identical.
- **Files modified:** `backend/tests/conftest.py`
- **Commit:** `ae98ace`

No other deviations. Plan executed substantively as written.

## Authentication Gates

None encountered. All work was offline (pip install + local pytest).

## Interfaces Plan 04-03 Should Consume

```python
# Password handling for /auth/register, /auth/login
from app.auth.passwords import hash_password, verify_password, verify_and_maybe_rehash

# JWT issuance for /auth/register, /auth/login response shape
from app.auth.tokens import encode_token, Token

# FastAPI dep for gated endpoints (/route, /cache/*)
from app.auth.dependencies import get_current_user_id

# Test seam for endpoint tests
# (already wired in conftest.py — just request the fixture)
def test_route_with_auth(authed_client, fake_user_id):
    r = authed_client.post("/route", json={...})
    assert r.status_code == 200
```

`dependencies.py`'s end-to-end correctness is verified in plan 04-03 (TestClient + 401 on missing/invalid token + 200 on valid token).

## Threat Surface Status

All `mitigate` dispositions in the plan's threat register are addressed by helper-layer code:

| Threat ID | Mitigation Status |
|-----------|-------------------|
| T-04-08 (alg-substitution) | ✅ `algorithms=[ALGORITHM]` LIST + `test_decode_token_alg_none_rejected` regression guard |
| T-04-09 (weak signing key) | ✅ `_signing_key()` raises on empty/<32 chars + `test_signing_key_raises_on_short_key` regression guard |
| T-04-10 (plaintext-in-log) | ✅ Zero `logger.*`/`print(...)` runtime calls in `backend/app/auth/`. The only `print` substring is inside an operator-hint string literal (RuntimeError message showing the secrets-generation command). |
| T-04-11 (token-shape oracle) | ✅ `dependencies.py` returns single `detail="Invalid or expired token"` for both expired and bad-sig paths |
| T-04-12 (test-key-in-prod) | ✅ Test default contains `do_not_use_in_production` tripwire substring |
| T-04-13 (param drift) | ✅ `verify_and_maybe_rehash` returns `(valid, new_hash_or_None)` — plan 04-03 will wire the UPDATE writeback in `/auth/login` |
| T-04-14 (string-form algorithms regression) | ✅ Two-layer defense: structural grep `algorithms=[ALGORITHM]` + runtime test `test_decode_token_alg_none_rejected` |
| T-04-15 (argon2 RAM DoS) | accept (Phase 5 reverse proxy / WAF rate limit is the real defense) |

No new threat flags discovered during execution.

## TDD Gate Compliance

Gate sequence verified in `git log e91acd1..HEAD`:

1. ✅ RED gate: `98c759a test(04-02): add failing unit tests for app.auth.passwords helpers`
2. ✅ GREEN gate: `343f508 feat(04-02): implement app.auth.passwords + tokens + dependencies (15 unit tests passing)`
3. (no REFACTOR commit — implementations were minimal-to-test from the start; no cleanup pass needed)

The RED commit's tests genuinely failed with `ModuleNotFoundError: app.auth.passwords` before the GREEN commit landed `passwords.py`. No fail-fast violation.

## Self-Check: PASSED

Files claimed to be created/modified — all verified present:

- ✅ `backend/requirements.txt` (modified — 10 lines, 3 new auth deps)
- ✅ `backend/app/auth/__init__.py` (created — 0 bytes)
- ✅ `backend/app/auth/passwords.py` (created — 56 LOC)
- ✅ `backend/app/auth/tokens.py` (created — 87 LOC)
- ✅ `backend/app/auth/dependencies.py` (created — 49 LOC)
- ✅ `backend/tests/conftest.py` (modified — +38 LOC additive)
- ✅ `backend/tests/test_auth_passwords.py` (created — 7 tests, 81 LOC)
- ✅ `backend/tests/test_auth_tokens.py` (created — 8 tests, 90 LOC)

Commit hashes claimed — all verified in `git log`:

- ✅ 777ddf3 (Task 1)
- ✅ 98c759a (Task 2 RED)
- ✅ 343f508 (Task 3 GREEN)
- ✅ ae98ace (Task 4)
