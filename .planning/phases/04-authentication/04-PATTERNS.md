# Phase 04 — Authentication: Pattern Map

**Mapped:** 2026-04-25
**Files analyzed:** 9 new files + 4 modified files
**Analogs found:** 12 / 13 (one frontend file has no close analog — see Confidence section)

This document tells the planner exactly which existing road-quality-mvp file each new auth file should mirror, and what concrete excerpts to copy. The file list is locked by `04-CONTEXT.md` (D-02, D-04). Pattern selection is pinned to currently-shipped code — not aspirational research.

---

## File Mapping

| New / Modified File | Mirror | Why |
|---|---|---|
| `backend/app/auth/__init__.py` | `backend/app/routes/__init__.py` (empty) | Package marker — match the existing zero-byte convention. |
| `backend/app/auth/passwords.py` | `backend/app/scoring.py` | Pure helper module. No DB, no FastAPI imports, narrow function surface, docstrings on every public symbol. Closest analog by role + data flow (transform). |
| `backend/app/auth/tokens.py` | `backend/app/cache.py` | Module-level constants + small typed-helper API + Pydantic model co-located. Cache reads `TTLCache(...)` at import time the way tokens.py will read `AUTH_SIGNING_KEY` at import time. |
| `backend/app/auth/dependencies.py` | `backend/app/routes/segments.py` (FastAPI primitives) + `data_pipeline/mapillary.py:124-129` (env-var fail-fast) | No existing `Depends(...)` factory in the repo, but `segments.py` is the canonical example of `HTTPException(status_code=…, detail=…)` shape. Mirror that for 401s. |
| `backend/app/routes/auth.py` | `backend/app/routes/cache_routes.py` (closest by size + simplicity) — fall back to `backend/app/routes/segments.py` for the `HTTPException` pattern and `backend/app/routes/routing.py` for raw-psycopg2 `with get_connection() as conn:` flow. | All four existing routes follow the same skeleton (`router = APIRouter()`, function per verb, `HTTPException` for errors). `cache_routes.py` is the cleanest minimal example for `/auth/logout`; `routing.py` shows the DB-write pattern needed for `/auth/register`. |
| `backend/app/auth/__init__.py` re-exports | n/a — keep empty | Existing `routes/__init__.py` is empty. Do NOT introduce barrel imports. |
| `backend/tests/test_auth.py` (unit-level) | `backend/tests/test_segments.py` (mocked-DB pattern with `@patch("app.routes.X.get_connection")`) | Same shape: `TestClient(app)` per function, `MagicMock` cursor wired through `__enter__`/`__exit__`, status code + JSON body asserts. |
| `backend/tests/test_auth_integration.py` (live DB) | `backend/tests/test_migration_002.py` + `backend/tests/test_integration.py` | Both use `pytestmark = pytest.mark.integration` at module top, the `db_conn` fixture from `conftest.py`, and `applied_migration` to bootstrap schema. Phase 4 should follow this exact pattern for any test that exercises the `users` table. |
| `db/migrations/003_users.sql` | `db/migrations/002_mapillary_provenance.sql` | Idempotent migration template. Must use `CREATE TABLE IF NOT EXISTS` + `CREATE UNIQUE INDEX IF NOT EXISTS`. Match the file's header-comment style (1-line summary, decision references, then SQL). |
| `frontend/src/api/auth.ts` (new module) | `frontend/src/api.ts` (existing single-file client) | Same `API_BASE` resolution, same `fetch(...)` + `if (!res.ok) throw` shape, same exported async functions returning `res.json()`. |
| `frontend/src/api.ts` (modified) | self — additive change only | Inject `Authorization: Bearer <token>` header in `fetchRoute`. Add a 401 hook (callback param or event) that the caller wires to the modal. |
| `frontend/src/components/SignInModal.tsx` | **No exact analog.** Closest reference: `frontend/src/components/AddressInput.tsx` (controlled-component + outside-click-close + Tailwind shape). Copy that file's structure for the modal panel and form fields. See Confidence section. |
| `frontend/src/hooks/useAuth.ts` (optional, only if researcher confirmed) | `frontend/src/hooks/useNominatim.ts` | Same custom-hook shape: `useState` + `useCallback`, returns object of `{state, action1, action2}`. If a context wrapper is preferred over a hook, defer to research. |

---

## Pattern Assignments

### `backend/app/auth/passwords.py` (helper module, transform)

**Mirror:** `backend/app/scoring.py`

**Imports & module shape** (`backend/app/scoring.py:1-2`):
```python
def normalize_weights(
    include_iri: bool,
    include_potholes: bool,
    ...
) -> tuple[float, float]:
    """Normalize weights based on which parameters are enabled.
    ...
    """
```
- No imports beyond what's needed (scoring imports nothing — passwords.py will import only from `pwdlib`).
- Each public function has a 1-3 line docstring; argument types are annotated; return type is annotated.
- No classes, no module-level state — just functions.

**Apply:** Two functions — `hash_password(plaintext: str) -> str` and `verify_password(plaintext: str, hashed: str) -> bool`. Mirror the docstring style from `scoring.py:5-9` (one-line summary, Returns clause).

---

### `backend/app/auth/tokens.py` (helper module + Pydantic model)

**Mirror:** `backend/app/cache.py` (module structure) + `backend/app/models.py` (Pydantic style)

**Module-top constant + env read** (mirror `data_pipeline/mapillary.py:48-49`):
```python
# Module-top env read (matches backend/app/db.py:5-7 pattern)
MAPILLARY_TOKEN = os.environ.get("MAPILLARY_ACCESS_TOKEN")
```
- Read `AUTH_SIGNING_KEY` once at import time. Do NOT validate non-emptiness at import — the test runner sets it to a stub. Validate inside `encode_token()` / `decode_token()` and raise `RuntimeError` with the exact phrasing pattern used at `data_pipeline/mapillary.py:126-129`:

**Fail-fast pattern** (`data_pipeline/mapillary.py:125-129`):
```python
if not tok:
    raise RuntimeError(
        "MAPILLARY_ACCESS_TOKEN not set. Get one at "
        "https://www.mapillary.com/dashboard/developers"
    )
```
- Apply: `if not _SIGNING_KEY: raise RuntimeError("AUTH_SIGNING_KEY not set. Set it in .env (see .env.example).")`

**Pydantic model style** (`backend/app/models.py:1-7`):
```python
from pydantic import BaseModel, Field


class LatLon(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
```
- Pydantic v2 BUT the existing `models.py` uses **plain `BaseModel` without `model_config = ConfigDict(...)`**. No `frozen=True`, no `extra='forbid'` anywhere in the codebase as of 2026-04-25. Do NOT introduce these — match the loose style of `models.py`. Use `Field(...)` for constraints (e.g., `email: EmailStr`, `password: str = Field(min_length=8)`).
- New types to define here (per D-06): `Token` (returned to client) — `{access_token: str, token_type: str = "bearer"}`. `TokenPayload` (internal) — `{sub: int, iat: int, exp: int}`.

---

### `backend/app/auth/dependencies.py` (FastAPI dependency factory)

**Mirror:** Combine `backend/app/routes/segments.py:11-13` (HTTPException shape) with the env-var read pattern above.

**HTTPException shape** (`backend/app/routes/segments.py:11-13`):
```python
if len(parts) != 4:
    raise HTTPException(status_code=400, detail="bbox must be min_lon,min_lat,max_lon,max_lat")
```
- Apply for 401: `raise HTTPException(status_code=401, detail="Invalid or missing credentials")`. The `detail` string is the only public error info — match this terseness; do NOT include stack-trace-style detail.

**No analog for `Depends()` factories yet** — the codebase has no existing `Depends(...)` use. Recommend the FastAPI-canonical shape:
```python
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

def get_current_user_id(token: str = Depends(oauth2_scheme)) -> int:
    payload = decode_token(token)  # raises if invalid/expired
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or missing credentials")
    return payload.sub
```
- This is a planner skeleton, not a copy-paste — researcher should confirm `OAuth2PasswordBearer` vs custom header parsing (D-02 says JWT, so OAuth2PasswordBearer is the FastAPI-idiomatic match).

---

### `backend/app/routes/auth.py` (FastAPI route module)

**Mirror:** `backend/app/routes/cache_routes.py` (skeleton) + `backend/app/routes/routing.py` (DB-write flow) + `backend/app/routes/segments.py` (HTTPException for validation errors)

**Router skeleton** (`backend/app/routes/cache_routes.py:1-4`):
```python
from fastapi import APIRouter
from app.cache import segments_cache, route_cache, clear_all_caches

router = APIRouter()
```
- New file: `from fastapi import APIRouter, HTTPException` + `from app.db import get_connection` + `from app.auth.passwords import hash_password, verify_password` + `from app.auth.tokens import encode_token, Token`.
- No prefix on the router itself (`APIRouter()` with no `prefix=`). Match the existing routes — they declare paths like `/health`, `/route`, `/segments` directly on `@router.get(...)`. Apply: `@router.post("/auth/register")` etc., NOT `APIRouter(prefix="/auth")`. (Researcher: this is a stylistic matching call; you may use `prefix="/auth"` if explicitly preferred, but be aware it diverges from the existing 4 route modules.)

**Mount in `main.py`** (`backend/app/main.py:3-18`):
```python
from app.routes import health, segments, routing
from app.routes.cache_routes import router as cache_router
...
app.include_router(health.router)
app.include_router(segments.router)
app.include_router(routing.router)
app.include_router(cache_router)
```
- Add: `from app.routes import auth` then `app.include_router(auth.router)`. Match either the dotted-module style (line 3) or the `as foo_router` style (line 4); the dotted style is dominant.

**DB-write flow** (`backend/app/routes/routing.py:55-62`):
```python
with get_connection() as conn:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO route_requests (params_json) VALUES (%s)",
            (json.dumps(req.model_dump()),),
        )
        conn.commit()
```
- Apply for `/auth/register`: same nested `with` block. Use parameterized SQL (`%s` placeholders, never f-strings). `conn.commit()` after the INSERT. Use `RETURNING id` to get the new user_id back from the INSERT (see how `cur.fetchone()["id"]` is used at `routing.py:73`).

**Error-shape contract** (D-06): use FastAPI `HTTPException(detail=...)` exactly like `segments.py:13`. Status codes: 400 on duplicate email (catch `psycopg2.errors.UniqueViolation`), 401 on bad creds, 422 falls out automatically from Pydantic.

---

### `backend/tests/test_auth.py` (mocked-DB unit tests)

**Mirror:** `backend/tests/test_segments.py:20-35`

**Mocked-DB shape** (`backend/tests/test_segments.py:20-30`):
```python
@patch("app.routes.segments.get_connection")
def test_segments_returns_geojson(mock_conn):
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = _mock_segments()
    mock_conn.return_value.__enter__ = lambda s: s
    mock_conn.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn.return_value.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.return_value.cursor.return_value.__exit__ = MagicMock(return_value=False)

    client = TestClient(app)
    response = client.get("/segments?bbox=-118.26,34.04,-118.23,34.07")
```
- Apply: `@patch("app.routes.auth.get_connection")` (note the path — patching at the import site, not at `app.db`). Wire `mock_cursor.fetchone.return_value` to return `{"id": 42}` for the `RETURNING id` flow.
- Reuse the helper `_setup_mock_conn` pattern from `backend/tests/test_route.py:42-50` if the test needs both fetchone and fetchall.

**TestClient pattern** (`backend/tests/test_health.py:1-9`):
```python
from fastapi.testclient import TestClient
from app.main import app


def test_health_returns_ok():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```
- Apply: assert `response.status_code` and `response.json()` — terse, no extra abstraction.

**AUTH_SIGNING_KEY in tests:** Tests must set `AUTH_SIGNING_KEY` to a stub. Mirror `backend/tests/test_integration.py:248`:
```python
monkeypatch.setenv("MAPILLARY_ACCESS_TOKEN", "stub_token_for_tests")
```
- Apply: `monkeypatch.setenv("AUTH_SIGNING_KEY", "test_secret_do_not_use")` in a session-scoped fixture or per-test. Or via pytest's `pytest_configure` in `conftest.py`.

---

### `backend/tests/test_auth_integration.py` (live-DB tests)

**Mirror:** `backend/tests/test_migration_002.py:1-32`

**Module preamble + marker** (`backend/tests/test_migration_002.py:9-22`):
```python
from __future__ import annotations

import os
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import errors as pgerr

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = REPO_ROOT / "db" / "migrations" / "002_mapillary_provenance.sql"
```
- Apply: `MIGRATION_PATH = REPO_ROOT / "db" / "migrations" / "003_users.sql"`. The `pytestmark = pytest.mark.integration` line is REQUIRED — without it, the test runs in the default suite and fails on dev machines without DB.

**Migration-bootstrap fixture** (`backend/tests/test_migration_002.py:25-32`):
```python
@pytest.fixture
def applied_migration(db_conn):
    """Apply the migration before each test. Idempotent — safe to call repeatedly."""
    sql = MIGRATION_PATH.read_text()
    with db_conn.cursor() as cur:
        cur.execute(sql)
    db_conn.commit()
    return db_conn
```
- Apply: copy verbatim, change `MIGRATION_PATH` constant. The `db_conn` fixture is provided by `backend/tests/conftest.py:29-33` (already exists).

**Idempotency test** (`backend/tests/test_migration_002.py:48-71`):
```python
def test_migration_idempotent(db_conn):
    """Apply migration twice — second apply must not error."""
    sql = MIGRATION_PATH.read_text()
    with db_conn.cursor() as cur:
        cur.execute(sql)
        db_conn.commit()
        cur.execute(sql)  # second apply
        db_conn.commit()
```
- Apply: required for `003_users.sql` per phase 3 precedent. Add an assertion like "users table exists" via `pg_class` lookup.

---

### `db/migrations/003_users.sql`

**Mirror:** `db/migrations/002_mapillary_provenance.sql`

**Header-comment style** (`db/migrations/002_mapillary_provenance.sql:1-14`):
```sql
-- Migration 002: Mapillary provenance columns + UNIQUE index for idempotent ingest.
-- Phase 3, plans 03-01..03-05. Implements decisions D-05 (UNIQUE constraint),
-- D-06 (ON CONFLICT target), D-07 (source column with CHECK + DEFAULT 'synthetic').
--
-- Postgres 16 supports IF NOT EXISTS on column adds but does not support an
-- IF-NOT-EXISTS form for adding constraints. ...
```
- Apply: header references "Phase 4, REQ-user-auth. Implements decision D-03 (argon2id) and the locked column shape from 04-CONTEXT.md."
- Cite which Postgres-16 idempotency caveats apply (UNIQUE on `email` is idempotent via `CREATE UNIQUE INDEX IF NOT EXISTS`; the column itself uses `CREATE TABLE IF NOT EXISTS`).

**Idempotent shape** (`db/migrations/002_mapillary_provenance.sql:16-40`):
```sql
ALTER TABLE segment_defects
    ADD COLUMN IF NOT EXISTS source_mapillary_id TEXT;
...
CREATE UNIQUE INDEX IF NOT EXISTS uniq_defects_segment_source_severity
    ON segment_defects (segment_id, source_mapillary_id, severity);
```
- Apply for new table:
  ```sql
  CREATE TABLE IF NOT EXISTS users (
      id            BIGSERIAL PRIMARY KEY,
      email         TEXT NOT NULL UNIQUE,
      password_hash TEXT NOT NULL,
      created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );
  CREATE UNIQUE INDEX IF NOT EXISTS uniq_users_email ON users (LOWER(email));
  ```
- The `LOWER(email)` functional index is suggested because D-03/04-CONTEXT.md says emails are lowercased at app layer — the index ensures the DB enforces it too. Researcher to confirm.

**Column-type conventions** (`db/migrations/001_initial.sql:1-12`):
```sql
CREATE TABLE IF NOT EXISTS road_segments (
    id            SERIAL PRIMARY KEY,
    ...
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
```
- Note: `001_initial.sql` uses `SERIAL`. The CONTEXT.md locks `BIGSERIAL` for `users.id` (matching `road_segments.source/target BIGINT`). Honor CONTEXT.md, not the loose 001 precedent.
- `created_at` style: `TIMESTAMPTZ DEFAULT NOW()` (no `NOT NULL` on existing tables — but CONTEXT.md locks `NOT NULL DEFAULT NOW()` for users). Honor CONTEXT.md.

---

### `docker-compose.yml` modification (mount migration 003)

**Mirror:** `docker-compose.yml:9-12`

**Migration mount pattern** (`docker-compose.yml:10-12`):
```yaml
volumes:
  - pgdata:/var/lib/postgresql/data
  - ./db/init-pgrouting.sh:/docker-entrypoint-initdb.d/01-pgrouting.sh
  - ./db/migrations/001_initial.sql:/docker-entrypoint-initdb.d/02-schema.sql
  - ./db/migrations/002_mapillary_provenance.sql:/docker-entrypoint-initdb.d/03-mapillary.sql
```
- Add: `- ./db/migrations/003_users.sql:/docker-entrypoint-initdb.d/04-users.sql`
- The `04-` numeric prefix matters: Postgres' init scripts run in lexicographic order. Phase 3 chose `03-`; phase 4 must use `04-`.

---

### `frontend/src/api/auth.ts` (new module)

**Mirror:** `frontend/src/api.ts:1-27`

**Module shape** (`frontend/src/api.ts:1-7`):
```typescript
const API_BASE = import.meta.env.VITE_API_URL || "/api";

export async function fetchSegments(bbox: string) {
  const res = await fetch(`${API_BASE}/segments?bbox=${bbox}`);
  if (!res.ok) throw new Error(`Segments fetch failed: ${res.status}`);
  return res.json();
}
```
- Apply: same `API_BASE` resolution, same `fetch + if (!res.ok) throw + return res.json()`. New functions: `register({email, password})`, `login({email, password})`, `logout()`, `getStoredToken()`, `setStoredToken(token)`, `clearStoredToken()`.
- Token storage key: `localStorage.getItem("rq_auth_token")`. Match the existing project naming (`rq_` prefix matches the `rq` DB user, `roadquality` DB name — pick the prefix that aligns with `frontend/src/main.tsx` if a precedent emerges; none exists currently, so `rq_auth_token` is the recommendation).

---

### `frontend/src/api.ts` (modified — additive)

**Mirror:** self (additive change only — preserve existing function signatures)

**Current `fetchRoute`** (`frontend/src/api.ts:19-27`):
```typescript
export async function fetchRoute(body: RouteRequestBody) {
  const res = await fetch(`${API_BASE}/route`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Route fetch failed: ${res.status}`);
  return res.json();
}
```
- Modification: read token from localStorage, conditionally add `Authorization: Bearer <token>` header. Throw a typed error (e.g., a custom `UnauthorizedError`) on 401 so `RouteFinder.tsx` can catch it and trigger the modal.
- Recommendation (no analog): introduce a thin internal `apiFetch(url, options)` wrapper that all auth-required calls share. Without this, each call site duplicates the 401 detection logic.

---

### `frontend/src/components/SignInModal.tsx`

**Mirror:** No exact analog — closest is `frontend/src/components/AddressInput.tsx`

**Pattern to copy** (`frontend/src/components/AddressInput.tsx:36-44`):
```typescript
// Close dropdown on outside click
useEffect(() => {
  function handleClick(e: MouseEvent) {
    if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
      setOpen(false);
    }
  }
  document.addEventListener("mousedown", handleClick);
  return () => document.removeEventListener("mousedown", handleClick);
}, []);
```
- Apply: the modal needs the same outside-click-to-close behavior. Use a ref + mousedown listener on the modal panel. (Or, accept that the modal blocks the page and skip outside-click — simpler.)

**Tailwind shape** (`frontend/src/components/AddressInput.tsx:62-77`):
```typescript
<div ref={wrapperRef} className="relative">
  <label className="flex items-center gap-1.5 text-sm font-medium mb-1">...</label>
  <input
    type="text"
    ...
    className="w-full border rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
  />
```
- Apply: match the rounded-border + `focus:ring-2 focus:ring-blue-400` styling. Buttons should mirror `RouteFinder.tsx:144-148`:
```typescript
<button
  onClick={handleSearch}
  disabled={!origin || !destination || loading}
  className="w-full bg-blue-600 text-white rounded py-2 hover:bg-blue-700 disabled:opacity-50"
>
  {loading ? "Searching..." : "Find Best Route"}
</button>
```

**Modal-overlay skeleton (no analog — recommended shape):**
```typescript
{open && (
  <div className="fixed inset-0 z-[2000] bg-black/40 flex items-center justify-center">
    <div className="bg-white rounded-lg shadow-xl p-6 w-96">
      {/* form here */}
    </div>
  </div>
)}
```
- z-index: existing code uses `z-[1000]` (`MapView.tsx:104`) and `z-50` (`AddressInput.tsx:82`). The modal should be above both — use `z-[2000]`.
- The modal does NOT need react-portal at MVP scale (per D-04 implementation hint).

---

### `frontend/src/hooks/useAuth.ts` (optional)

**Mirror:** `frontend/src/hooks/useNominatim.ts:17-77`

**Custom-hook shape** (`frontend/src/hooks/useNominatim.ts:17-23`):
```typescript
export function useNominatim() {
  const [results, setResults] = useState<NominatimResult[]>([]);
  const [loading, setLoading] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const search = useCallback((query: string) => {
    ...
  }, []);
```
- Apply: `useState` for `{token, user_id}`, `useCallback` for `login`/`logout`/`register`. Return an object with these fields. Use `localStorage` for persistence.
- Defer to research on whether a hook is needed — D-04 says "Modal state lives in `RouteFinder.tsx` (or a small auth context if researcher determines it's needed for `/cache/*`)". If `/cache/*` calls happen outside `RouteFinder.tsx`, a context/hook is needed.

---

## Shared Patterns (cross-cutting)

### 1. env-var-read-at-startup-fail-fast
**Where exemplified:** `data_pipeline/mapillary.py:48-49`, `data_pipeline/detector_factory.py:49`, `backend/app/db.py:5-7`
**Pattern:** Read env var at module import time into a module-level constant. Validate inside the function that needs it (NOT at import — tests rely on import-without-env). Raise `RuntimeError` with a hint pointing to `.env.example`.
**Apply to:** `backend/app/auth/tokens.py` reading `AUTH_SIGNING_KEY`. The validation phrasing must match: `"AUTH_SIGNING_KEY not set. Set it in .env (see .env.example)."`

### 2. migration-mounted-via-docker-init-flow
**Where exemplified:** `docker-compose.yml:11-12`
**Pattern:** Migrations live in `db/migrations/NNN_name.sql` and are mounted into `/docker-entrypoint-initdb.d/NN-name.sql` (note: numeric prefix is independent — `02-schema.sql`, `03-mapillary.sql`). Order matters: Postgres runs them lexicographically.
**Apply to:** `docker-compose.yml` gets `- ./db/migrations/003_users.sql:/docker-entrypoint-initdb.d/04-users.sql`. The migration must be idempotent because the volume is reused on `docker compose up` after init completes.

### 3. pytest-marker-integration-for-db-tests
**Where exemplified:** `backend/tests/test_migration_002.py:19`, `backend/tests/test_integration.py:11`, `backend/tests/test_compute_scores_source.py:108-178`
**Pattern:** Module-top `pytestmark = pytest.mark.integration` (or per-test `@pytest.mark.integration`). Marker is registered in `backend/tests/conftest.py:9-10`. Tests skip automatically when DB is unreachable via the `db_available` fixture chain.
**Apply to:** `backend/tests/test_auth_integration.py` MUST set `pytestmark = pytest.mark.integration`. Unit tests in `test_auth.py` (mocked DB only) must NOT set it.

### 4. pydantic-v2-model-style
**Where exemplified:** `backend/app/models.py:1-39`
**Pattern:** Plain `BaseModel` import from `pydantic`. No `ConfigDict`, no `model_config`, no `frozen=True`, no `extra='forbid'` anywhere in the existing codebase. Use `Field(...)` for constraints. Default values inline. `from __future__ import annotations` is NOT used.
**Apply to:** `backend/app/auth/tokens.py` Pydantic models. Researcher might recommend `extra='forbid'` for security on register/login payloads — that's a stricter-than-codebase choice; flag explicitly to planner if introducing it.

### 5. response-shape-for-errors (FastAPI HTTPException)
**Where exemplified:** `backend/app/routes/segments.py:13`, `backend/app/routes/segments.py:18`
**Pattern:** `raise HTTPException(status_code=NNN, detail="terse human string")`. No custom error classes, no JSON envelope, no error codes. FastAPI serializes to `{"detail": "..."}` automatically.
**Apply to:** All auth endpoints. 400 on duplicate email: `detail="Email already registered"`. 401 on bad creds: `detail="Invalid credentials"`. Match terseness — no PII (don't echo the email).

### 6. env-example-as-canonical-truth-for-required-vars
**Where exemplified:** `.env.example:1-52` (every var the codebase reads is documented)
**Pattern:** Every `os.environ.get()` call in the backend has a corresponding section in `.env.example` with: section header (` # ----- Section Name -----`), consumer file paths, default value or empty placeholder, security notes if applicable.
**Apply to:** Add a new `# ----- Auth -----` section after the Mapillary section, e.g.:
```
# ----- Auth (Phase 4, REQ-user-auth) -----
# Consumed by: backend/app/auth/tokens.py
# HMAC signing key for JWT tokens. Must be at least 32 chars.
# In production (Phase 5), generate with: python -c "import secrets; print(secrets.token_urlsafe(48))"
# NEVER commit a real key — this template stays empty.
AUTH_SIGNING_KEY=
```

### 7. README-section-anchored-as-cross-plan-reference
**Where exemplified:** `README.md:117-156` (Detector Accuracy + Real-Data Ingest sections)
**Pattern:** Each major phase that ships a user-facing capability adds a top-level `## ` heading to README.md, with a 2-3 paragraph summary, a `Quick start` code block, and a doc cross-reference.
**Apply to:** Add a `## Public Demo` section (D-05) somewhere between `## API Endpoints` and `## Tech Stack`. Document the demo creds. Include a 2-line `Quick start` showing the login curl call.

### 8. raw-psycopg2-with-RealDictCursor convention
**Where exemplified:** `backend/app/db.py:10-11`, used by `backend/app/routes/segments.py:38-41`, `backend/app/routes/routing.py:55-78`
**Pattern:** ALL DB access goes through `app.db.get_connection()`. Cursor is `RealDictCursor` (rows are dicts). Use `with get_connection() as conn:` + `with conn.cursor() as cur:` nesting. Parameterized queries via `%s` placeholders. Explicit `conn.commit()` after writes.
**Apply to:** `backend/app/routes/auth.py` — register/login both go through `get_connection()`. SELECT to check email uniqueness, INSERT with `RETURNING id` to get user_id, fetch via `cur.fetchone()["id"]`.

### 9. frontend-localStorage-key-naming
**Where exemplified:** none (no current localStorage usage in the codebase)
**Pattern:** No precedent — recommend `rq_auth_token` to align with the `rq` DB user prefix and avoid collisions if the demo is run alongside other apps on the same origin.
**Apply to:** `frontend/src/api/auth.ts` — `localStorage.getItem("rq_auth_token")` / `localStorage.setItem("rq_auth_token", token)`.

### 10. 401-interceptor-pattern
**Where exemplified:** none (no existing interceptor)
**Pattern:** No precedent. Recommendation: `frontend/src/api.ts` exports a module-level `onUnauthorized` callback registry (`let unauthorizedHandler: (() => void) | null = null; export function setUnauthorizedHandler(fn) {...}`). On 401, call the handler before throwing. `RouteFinder.tsx` registers a handler in `useEffect` that opens the modal.
**Apply to:** `frontend/src/api.ts` modification + `frontend/src/pages/RouteFinder.tsx` to wire the modal trigger. Researcher may prefer a custom event (`window.dispatchEvent(new CustomEvent('rq:unauthorized'))`) — both are acceptable; pick one and document.

---

## No Analog Found

| File | Reason | Recommendation |
|---|---|---|
| `frontend/src/components/SignInModal.tsx` | No existing modal component in `frontend/src/components/`. Closest analogs (AddressInput's overlay dropdown, MapView's z-1000 control panels) are partial. | Use the skeleton in the `SignInModal.tsx` section above. Pattern: fixed overlay + centered card + Tailwind. No portal needed at MVP scale. |
| `frontend/src/api/auth.ts` (token interceptor) | No existing 401-handling pattern in `frontend/src/api.ts`. | Module-level callback registry pattern recommended above. |

---

## Confidence

| Mapping | Confidence | Notes |
|---|---|---|
| `passwords.py` → `scoring.py` | **High** | Identical role (pure helper, no DB, no FastAPI). |
| `tokens.py` → `cache.py` + `models.py` + `mapillary.py:48-49` | **High** | Three precedents for the env-read pattern; `cache.py` for module shape; `models.py` for Pydantic style. |
| `dependencies.py` → `segments.py` HTTPException + recommended OAuth2PasswordBearer | **Medium** | No existing `Depends()` factory in repo. Recommend FastAPI-canonical shape. Researcher should confirm `OAuth2PasswordBearer` over custom `Authorization` header parsing. |
| `routes/auth.py` → `cache_routes.py` + `routing.py` + `segments.py` | **High** | All four existing route modules follow the same skeleton. Mounting in `main.py` is mechanical. |
| `test_auth.py` → `test_segments.py` mock pattern | **High** | Mock-DB pattern is canonical and used in 3+ existing test files. |
| `test_auth_integration.py` → `test_migration_002.py` | **High** | Phase 3 migration test is an exact template. The `applied_migration` fixture pattern transfers verbatim. |
| `003_users.sql` → `002_mapillary_provenance.sql` | **High** | Migration 002 is the most recent and most carefully-commented precedent. CONTEXT.md locks the column shape — do NOT improvise. |
| `docker-compose.yml` mount addition | **High** | One-line addition matching the existing 3-line precedent. |
| `frontend/src/api/auth.ts` → `frontend/src/api.ts` | **High** | Same shape, additive split. |
| `frontend/src/api.ts` modification (header injection + 401 hook) | **Medium** | Header injection is mechanical. The 401-interceptor pattern has no precedent — recommendation included above. |
| `SignInModal.tsx` → `AddressInput.tsx` (partial analog) | **Low — flagged** | **No existing modal in the codebase.** AddressInput shares Tailwind conventions and outside-click handling, but is not a modal. Planner should treat this file as "build from skeleton" using the recommended overlay shape above; expect more LOC than other components because there's no exact pattern to copy. |
| `useAuth.ts` (if needed) → `useNominatim.ts` | **Medium** | Custom-hook shape transfers cleanly, but D-04 leaves the question of "hook vs context vs component-local state" open for the researcher. |

### Specific Flags

1. **`backend/tests/conftest.py` (lines 1-33) does NOT have any auth-relevant fixtures.** It has `db_available`, `client`, `db_conn`. None set `AUTH_SIGNING_KEY`. The Phase 4 test file MUST either: (a) add a session-scoped fixture in `conftest.py` that sets `AUTH_SIGNING_KEY` before `app` is imported, or (b) use `monkeypatch.setenv` per-test. Option (a) is cleaner because `app.main` imports `app.auth.tokens` transitively, and the env var must be present at first-import time. **Recommend: add a `pytest_configure` hook to `conftest.py` that calls `os.environ.setdefault("AUTH_SIGNING_KEY", "test_secret_do_not_use")`.**

2. **No existing modal component.** The Phase 4 frontend deliverable that is least pattern-supported is `SignInModal.tsx`. Expect the planner to write more bespoke code here than for the backend files. The skeleton above is sufficient as a starting point.

3. **`backend/requirements.txt` has no auth deps.** Current contents:
   ```
   fastapi==0.115.6
   uvicorn[standard]==0.34.0
   psycopg2-binary==2.9.11
   pydantic==2.10.4
   pytest==8.3.4
   httpx==0.28.1
   cachetools>=5.3
   ```
   Add `pwdlib[argon2]>=0.2.1` and `python-jose[cryptography]>=3.3.0` per D-02. Pin minor versions to match the existing convention (most deps are `==`, one is `>=`).

4. **Pydantic `EmailStr` requires `email-validator`.** It is NOT a transitive dep of `pydantic==2.10.4` by default — it must be installed explicitly. Researcher should confirm whether to add `pydantic[email]` (the recommended extras form) or `email-validator` directly. CONTEXT.md D-06 flags this as a research item.

5. **No auth precedent in any file.** This is a greenfield phase. The patterns above are the closest matches but several (`Depends()` factory, modal, 401 interceptor, localStorage key) are recommendations rather than copies.

## Metadata

**Analog search scope:** `backend/app/`, `backend/tests/`, `db/migrations/`, `docker-compose.yml`, `frontend/src/`, `data_pipeline/` (env-read patterns only), `.env.example`, `README.md`
**Files scanned:** 27
**Pattern extraction date:** 2026-04-25
