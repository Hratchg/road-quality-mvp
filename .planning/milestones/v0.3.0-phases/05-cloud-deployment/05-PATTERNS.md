---
phase: 05-cloud-deployment
created: 2026-04-25
status: ready_for_planning
inputs: [05-CONTEXT.md]
---

# Phase 05 — Cloud Deployment: Pattern Map

This file is consumed by `gsd-planner` to wire each new/modified file in Phase 5
to the closest existing analog in `road-quality-mvp`. Sections:

1. **File mapping** — new file → closest existing analog
2. **Surgical edit anchors** — exact files + line numbers the planner edits
3. **Shared patterns** — cross-cutting conventions every plan must follow
4. **CONTEXT.md corrections** — verified codebase facts that contradict
   the SC fold-in claims (planner MUST read this before writing plans)
5. **Confidence + open questions**

---

## 1. File Mapping (new file → closest existing analog)

| New / modified file | Mirror | Why |
|---|---|---|
| `deploy/db/Dockerfile` | `db/Dockerfile` (3-line PostGIS+pgRouting image) | Byte-identical image; `deploy/db/Dockerfile` is the same image relocated under `deploy/` so the Fly app build context is scoped tightly. May literally be `cp db/Dockerfile deploy/db/Dockerfile` plus a `COPY db/migrations/ /docker-entrypoint-initdb.d/` block. |
| `deploy/db/fly.toml` | (no analog — first `fly.toml` in repo) | Fly Postgres app config: 1 GB volume, `mount_path = "/var/lib/postgresql/data"`, internal-only ports. Researcher's recommended template is the source. |
| `deploy/backend/fly.toml` | (no analog) | Wraps the existing `backend/Dockerfile` (CONTEXT D-01 keeps it unchanged). Researcher confirms `[build] dockerfile = "../backend/Dockerfile"` vs. moving the Dockerfile under `deploy/backend/`. |
| `deploy/frontend/Dockerfile` | `backend/Dockerfile` (single-stage `python:3.12-slim`) is the closest pattern shape, but the multi-stage `node:20 → nginx:alpine` shape is greenfield. `frontend/Dockerfile` is **dev-only** (`npm run dev`) — NOT a usable analog for prod. | First production frontend image. Researcher Q6 (Vite `--build-arg VITE_API_URL`) drives the exact shape. |
| `deploy/frontend/nginx.conf` | (no analog — first nginx config in repo) | SPA fallback to `index.html`, cache headers for static assets. |
| `deploy/frontend/fly.toml` | (no analog) | Fly app config; `[build] args` injects `VITE_API_URL` at image build time. |
| `.github/workflows/deploy.yml` | (no analog — `.github/` directory does not exist; this is the FIRST workflow file in the repo) | Three jobs (db → backend → frontend) with `needs:` dependencies and `paths:` filters. Pre-deploy job runs the existing pytest suite. |
| `backend/app/db.py` (rewrite) | `scripts/compute_scores.py` lines 14-55 (Phase 3 WR-04 `contextlib.closing` pattern); `backend/app/routes/auth.py` lines 9-10, 60-72, 90-95, 117-123 (Phase 4 WR-03 reuse of the same pattern) | Pool wrapper that yields a pooled connection inside `contextlib.closing`-style context manager so `pool.putconn()` runs on every exit path. Module-level `pool = SimpleConnectionPool(2, 10, DATABASE_URL, cursor_factory=RealDictCursor)` mirrors the module-level `DATABASE_URL` pattern already in `db.py`. |
| `backend/app/routes/health.py` (rewrite) | `backend/app/routes/segments.py` lines 38-41 (the `with get_connection() as conn, conn.cursor() as cur` shape); `backend/app/routes/auth.py` lines 87-105 (HTTPException raise pattern) | Add `SELECT 1` reachability probe + raise `HTTPException(503, detail={"status": "unhealthy", "db": "unreachable"})` per CONTEXT D-08. |
| `backend/app/routes/routing.py` (modify lines 59 + 73) | `backend/app/routes/auth.py` lines 60-72 (`with closing(get_connection()) as conn, conn:` is the exact two-context pattern); `scripts/compute_scores.py` lines 54-55 (`with contextlib.closing(...) as conn:` script-side variant) | SC #9 surgical fix. Both `with get_connection() as conn:` blocks (lines 59 and 73) wrap into `with closing(get_connection()) as conn, conn:`. |
| `backend/app/main.py` (modify lines 8-13) | Own pattern — module-level env read mirrors `backend/app/db.py` line 5-7 (`os.environ.get("DATABASE_URL", default)`) | Surgical CORS fix: `ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*").split(",")` then pass into `CORSMiddleware(allow_origins=...)`. Default to `"*"` so local-dev still works without `.env` plumbing. |
| `backend/tests/test_migration_002.py` | **NO CHANGE NEEDED** — already uses `Path(__file__).resolve().parents[2] / "db" / "migrations"` at lines 21-22 | See §4: CONTEXT.md SC #8 description is stale. The real SC #8 work is the **container-runtime** path resolution, not editing this file. |
| `backend/tests/test_migration_003.py` | **NO CHANGE NEEDED** — already uses the correct pattern at lines 25-26 | Same as above. |
| `scripts/seed_data.py` | **NO CHANGE NEEDED** — already calls `pgr_createTopology` at line 151 | See §4: CONTEXT.md SC #7 description is stale. The real SC #7 work is wiring seed-or-equivalent into the deploy bootstrap, not editing this script. |
| `.env.example` (modify) | Existing `# ----- Auth (Phase 4 ...)` block at lines 54-64 (per-section header + multi-line comment + var assignment) | Add a new `# ----- CORS (Phase 5) -----` block above or below the Auth block: env var `ALLOWED_ORIGINS=` (empty default; comment explains comma-separated, prod sources from Fly secrets). |
| `README.md` (modify) | `## Public Demo Account` section (lines 175-231) — Phase 4's pattern: top-level `## Foo`, then `### Local setup`, `### Rotation`, fenced bash blocks numbered 1/2/3/4 with inline `# comment` headers | Add a new top-level `## Deploy` section. Subsections: `### Prerequisites`, `### One-time setup`, `### Hotfix path`. Mirrors the prose density and bash-block style of the demo-account section. |
| `frontend/src/api.ts` | **NO CHANGE NEEDED** — line 3 already reads `import.meta.env.VITE_API_URL` (Phase 0 wiring) | The `deploy/frontend/Dockerfile` build-arg supplies the value; api.ts is unchanged. |

---

## 2. Surgical Edit Anchors

The planner can paste these directly into plan action items.

| Target | Line(s) | What changes |
|---|---|---|
| `backend/app/main.py` | 1 (add `import os`) | Add module-level `import os` (currently missing from main.py) |
| `backend/app/main.py` | 8-13 | Replace `allow_origins=["*"]` with env-driven list. The locked diff shape: `allow_origins=os.environ.get("ALLOWED_ORIGINS", "*").split(",")`. `allow_methods`, `allow_headers`, `allow_credentials` unchanged. |
| `backend/app/db.py` | 1-11 (whole file rewrite) | Add `from psycopg2.pool import SimpleConnectionPool`, `from contextlib import contextmanager`. Module-level `_pool = SimpleConnectionPool(minconn=2, maxconn=10, dsn=DATABASE_URL, cursor_factory=RealDictCursor)`. Rewrite `get_connection()` as a `@contextmanager` that yields `_pool.getconn()` and runs `_pool.putconn(conn)` in a `finally:`. Existing call sites (`with get_connection() as conn:` in segments.py / routing.py / auth.py) keep working unchanged because `@contextmanager`-decorated generators ARE context managers. |
| `backend/app/routes/health.py` | 1-9 (whole file rewrite) | Add `from fastapi import HTTPException`, `from app.db import get_connection`. Wrap `SELECT 1` in `try/except` per CONTEXT D-08 verbatim block. |
| `backend/app/routes/routing.py` | 1 (add `from contextlib import closing`) | Add the same import auth.py line 10 already has |
| `backend/app/routes/routing.py` | 59 | Change `with get_connection() as conn:` to `with closing(get_connection()) as conn, conn:` (mirror auth.py line 63 verbatim) |
| `backend/app/routes/routing.py` | 73 | Same surgical change (mirror auth.py line 92 verbatim) |
| `.env.example` | After line 64 (end of Auth block) | Append a new `# ----- CORS (Phase 5, REQ-prod-deploy SC #2) -----` block defining `ALLOWED_ORIGINS=`. |
| `README.md` | After line 231 (end of `### Rotation`), before line 233 (`## Tech Stack`) | Insert new `## Deploy` section. |
| `backend/tests/test_health.py` | 1-9 (whole file rewrite) | Update assertions to match new health response shape: 200 with `{"status": "ok", "db": "reachable"}` on happy path. Add a 503-path test that monkeypatches `app.routes.health.get_connection` to raise `psycopg2.OperationalError` and asserts 503 + `{"db": "unreachable"}`. Note: this is a NEW test file modification not enumerated in CONTEXT — planner should add it as a follow-on action under SC #5. |

---

## 3. Shared Patterns (cross-cutting conventions)

These are conventions every Phase 5 plan must follow. Listed in priority order.

### P-1: `contextlib.closing` for all psycopg2 resource cleanup

**Locked precedents:** Phase 3 commit `fd9c24f` (`scripts/compute_scores.py`),
Phase 4 commit `ab3d552` (`backend/app/routes/auth.py`).

**Rule:** `psycopg2.connect(...)` as a context manager only manages the
transaction (commit/rollback) — it does NOT close the socket. Always pair with
`contextlib.closing()`.

**Two-line shape (route layer, current):**
```python
with closing(get_connection()) as conn, conn:
    with conn.cursor() as cur:
        cur.execute(...)
```

**Script-layer shape (`scripts/compute_scores.py:54`):**
```python
with contextlib.closing(psycopg2.connect(DATABASE_URL)) as conn:
    with conn.cursor() as cur:
        ...
```

**SC #6 / SC #9 application:** When `db.py` is rewritten to a pool wrapper,
the same discipline applies — `pool.putconn()` MUST run on every exit path,
including exceptions. The `@contextmanager` + `try/finally` in `db.py` is
the structural equivalent of `closing()` for pool resources.

### P-2: env-var read at module import, fail-fast on production-required vars, fall through to safe local default for dev

**Exemplars:**
- `backend/app/db.py:5-7` — `DATABASE_URL` falls through to a local-dev default (`postgresql://rq:rqpass@localhost:5432/roadquality`)
- `backend/app/auth/tokens.py:34-51` — `AUTH_SIGNING_KEY` raises `RuntimeError` when missing (fail-fast, no default)
- `scripts/seed_demo_user.py:47-50` — same `os.environ.get(..., default)` pattern at script entry

**Rule for `ALLOWED_ORIGINS` (D-06):** Mirror `DATABASE_URL`'s shape — fall
through to `"*"` so local dev with no `.env` still works. Production sets the
env var explicitly via `fly secrets set`. **Do NOT** mirror `AUTH_SIGNING_KEY`'s
fail-fast shape — that would break local-dev startup, regression in DX.

### P-3: Migration applied via Docker init-flow mount

**Exemplar:** `docker-compose.yml:9-13` mounts each `db/migrations/00X_*.sql`
into `/docker-entrypoint-initdb.d/0X-name.sql`. Postgres official image's
init script auto-runs every `*.sql` and `*.sh` it finds there, in
lexicographic order, on first volume init.

**Rule for `deploy/db/Dockerfile`:** Bake the migrations IN to the image
via `COPY db/migrations/ /docker-entrypoint-initdb.d/`. Do NOT use Fly
file-mounts (option (b) in CONTEXT research priority 3) — baking-in is
more idempotent (the image IS the deploy artifact; no drift between
volume snapshot and migration set).

### P-4: pytest `@pytest.mark.integration` for DB-touching tests

**Exemplars:** `test_migration_002.py:19`, `test_migration_003.py:23`,
`test_compute_scores_source.py`, `test_integration.py`. The marker is
declared in `conftest.py:19-20`; the `db_available` fixture
(`conftest.py:27-35`) auto-skips when `psycopg2.connect()` raises
`OperationalError`.

**Rule for any new health-503 test, any new pool-leak regression test:** mark
with `@pytest.mark.integration` and consume the `db_conn` / `db_available`
fixtures. CI gate runs `pytest -m integration` against a live Fly DB or a
docker-compose-spawned DB inside the GH Actions runner.

### P-5: `HTTPException` with explicit `status_code` and `detail` dict

**Exemplars:**
- `backend/app/routes/auth.py:75-78` — `status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"`
- `backend/app/routes/auth.py:102-105` — `status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"`
- `backend/app/routes/segments.py:13, 18` — `raise HTTPException(status_code=400, detail="...")`

**Rule for new `/health` 503 path (SC #5):** mirror this shape exactly —
`raise HTTPException(status_code=503, detail={"status": "unhealthy", "db": "unreachable"})`.
The CONTEXT D-08 verbatim block uses a dict detail, which is consistent with
project convention (FastAPI serializes dict details to JSON automatically).

### P-6: raw psycopg2 + `RealDictCursor` (no SQLAlchemy)

**Exemplar:** `backend/app/db.py:3, 11` — `cursor_factory=RealDictCursor` is
the project default. All consumer code (`segments.py:43-54`, `routing.py:77,
80, 84`, `auth.py:71-72, 99, 106-107`) reads rows as dicts via `row["id"]` /
`row["password_hash"]`. Test code dual-handles dict-vs-tuple
(`test_migration_002.py:45` pattern — `row["id"] if isinstance(row, dict) else row[0]`)
to remain forward-compatible if `RealDictCursor` ever changes default.

**Rule for `db.py` pool rewrite:** the pool factory MUST preserve
`cursor_factory=RealDictCursor` so the dozens of `row["..."]` reads at call
sites do not break. SimpleConnectionPool accepts `cursor_factory` as a
**kwargs passthrough** to `psycopg2.connect()`.

### P-7: `.env.example` as canonical truth for env var names

**Exemplar:** `.env.example:1-65` documents every env var the codebase reads,
sectioned by consumer (`# ----- Database -----`, `# ----- Auth (Phase 4) -----`).
Production never reads from `.env`; production reads from Fly secrets. But
`.env.example` is the SoT for "what env vars exist, why, and how to populate
them locally."

**Rule for Phase 5:** `ALLOWED_ORIGINS` must get its own block in
`.env.example`. The block's prose MUST explain (a) the comma-separated
shape, (b) the prod source (Fly secrets), (c) the local dev fallback (defaults
to `"*"` if unset — see P-2), and (d) which file consumes it
(`backend/app/main.py`).

### P-8: README section anchored as a cross-plan reference

**Exemplars:**
- `## Public Demo Account` (Phase 4, README:175-231)
- `## Real-Data Ingest` (Phase 3, README:140-160)
- `## Detector Accuracy` (Phase 2, README:117-138)

**Pattern:** Each phase that ships an operator-visible feature gets exactly
one top-level `##` section in README. Style: prose intro (1-2 short paragraphs)
+ `### Local setup` subsection with a numbered bash block + optional
`### Rotation` / `### Hotfix` subsection.

**Rule for Phase 5:** New `## Deploy` section, slotted between
`### Rotation` (line 231) and `## Tech Stack` (line 233). Subsections:
`### Prerequisites` (`flyctl` install), `### Initial deploy` (numbered bash
block), `### Hotfix` (manual `fly deploy` invocation). Update the
`Deploy` row in the Tech Stack table (line 243) from `Docker Compose (local)`
to `Docker Compose (local) + Fly.io (production)`.

### P-9: Multi-stage Dockerfile (greenfield — recommend)

**No existing analog in this repo.** The two existing Dockerfiles
(`backend/Dockerfile`, `frontend/Dockerfile`) are both single-stage. The
existing `frontend/Dockerfile` is dev-only (CMD = `npm run dev`).

**Recommended shape for `deploy/frontend/Dockerfile`:**
```dockerfile
# Stage 1: build the Vite bundle
FROM node:20-slim AS builder
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
ARG VITE_API_URL
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build

# Stage 2: nginx serves static
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY deploy/frontend/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

The `ARG VITE_API_URL` + `ENV` is what makes Vite's `import.meta.env.VITE_API_URL`
resolve at build time (CONTEXT D-03 implementation hint, RESEARCH priority 6).

### P-10: GitHub Actions workflow (greenfield — recommend)

**No `.github/` directory exists in the repo.** Phase 5's `deploy.yml` is the
FIRST workflow file. Recommended shape (based on CONTEXT D-04 + research
priority 5):

```yaml
name: Deploy
on:
  push:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # docker compose up db; pip install; pytest -m integration
  deploy-db:
    needs: test
    runs-on: ubuntu-latest
    if: contains(github.event.head_commit.modified, 'deploy/db/')
    steps:
      - uses: actions/checkout@v4
      - uses: superfly/flyctl-actions/setup-flyctl@master
      - run: flyctl deploy --remote-only --config deploy/db/fly.toml
        env: { FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }} }
  deploy-backend:
    needs: deploy-db
    # ... same shape, --config deploy/backend/fly.toml
  deploy-frontend:
    needs: deploy-backend
    # ... same shape with --build-arg VITE_API_URL=https://<backend>.fly.dev
```

Path filters via `paths:` on the `on.push` clause (per CONTEXT D-04
implementation hint) is cleaner than runtime `if: contains(...)`. Researcher
should confirm.

---

## 4. CONTEXT.md Corrections (verified codebase facts)

The CONTEXT.md fold-in section ("Folded-in fix expectations (SC #7, #8, #9)",
lines 181-187) describes work that is partially or fully ALREADY DONE. The
planner MUST read this section before drafting plans, otherwise plans 0X-SC7
and 0X-SC8 will scope no-op edits.

### SC #7 — `pgr_createTopology` in seed_data.py — **ALREADY DONE**

CONTEXT line 185: "Add `pgr_createTopology(...)` to `scripts/seed_data.py`
after the segment INSERT loop."

**Reality:** `scripts/seed_data.py:151` already calls
`SELECT pgr_createTopology('road_segments', 0.0001, 'geom', 'id', clean := true)`.
Lines 145-152 are the existing topology-build block. The seed script as it
stands today would satisfy SC #7's literal text.

**What SC #7 actually means in Phase 5:** the seed must run AT DEPLOY TIME, not
just locally. The Phase 5 work is wiring it into the GH Actions workflow OR a
one-shot Fly job, NOT editing seed_data.py. CONTEXT D-04 implementation hint
("Pre-deploy: run the existing pytest suite as a CI gate") implies the
deploy workflow shape — extend the same shape with a "first-deploy seed" job.

**Optional defensive add:** a `scripts/pre_deploy_check.py` that asserts
`SELECT COUNT(*) FROM road_segments_vertices_pgr > 0` before the workflow
proceeds to backend deploy. CONTEXT lines 184-185 hint at this ("Add a
'topology' guard to /health's DB-reachability probe (or a dedicated
pre-deploy-check.py)"). Recommend the dedicated script over polluting
`/health` — `/health` is hot-path; topology checks are deploy-time.

### SC #8 — migration test paths — **ALREADY DONE in source; runtime is the real bug**

CONTEXT line 175: "`backend/tests/test_migration_002.py` and
`backend/tests/test_migration_003.py` reference `/db/migrations/<file>.sql`
absolute paths."

**Reality:**
- `test_migration_002.py:21-22`:
  ```python
  REPO_ROOT = Path(__file__).resolve().parents[2]
  MIGRATION_PATH = REPO_ROOT / "db" / "migrations" / "002_mapillary_provenance.sql"
  ```
- `test_migration_003.py:25-26` uses the identical pattern.

Both files already do exactly what CONTEXT line 175 says they should do.

**What SC #8 actually means in Phase 5:** when these tests run INSIDE the
deployed `backend` container (per CONTEXT line 26), `Path(__file__).resolve().parents[2]`
resolves to `/` (because the container's `WORKDIR /app` only contains the
backend code — `db/migrations/` is NOT copied in by `backend/Dockerfile:8`'s
`COPY . .`). The fix is one of:

  - (A) Add `COPY ../db/migrations /app/db/migrations` to `backend/Dockerfile`
    (requires changing the build context to repo root)
  - (B) Add a docker-compose volume mount of `./db/migrations:/app/db/migrations`
    in the `backend` service block
  - (C) Refactor migration tests to read `MIGRATION_PATH` from an env var
    (e.g., `MIGRATIONS_DIR=/db/migrations`) so deploy-time configuration
    decouples from filesystem layout

Recommend (B) for local + (A) for prod (in `deploy/backend/fly.toml`'s build
context, set the context to repo root rather than `backend/`). CONTEXT D-04
implementation hint about the "data_pipeline mount" friction is a sibling
issue — the same context-root fix solves both.

**Planner action:** rephrase SC #8 in the plan as "migration tests pass when
run inside the deployed backend image" rather than "edit the test files."

### SC #9 — `routing.py` connection leak — **ACTUALLY needs the fix**

CONTEXT line 174: "`backend/app/routes/routing.py` has the connection-leak
pattern (`with psycopg2.connect(...) as conn` only manages the txn)."

**Reality:** `routing.py:59` and `routing.py:73` both use
`with get_connection() as conn:` without `contextlib.closing`. This DOES leak
the socket on the exception path. Fix is real and surgical — see §2 anchors.

After SC #6's pool wrapper rewrite of `db.py`, the leak window is even tighter
(every leak is a permanent pool-slot loss until process restart). The order
matters: SC #9 fix can happen independently, but SC #6 + SC #9 should land
together, otherwise the pool starts dropping connections under bursts.

---

## 5. Confidence + Open Questions

### High-confidence mappings

- `backend/app/main.py` line 8-13 surgical CORS edit (P-2 + locked CONTEXT D-06)
- `backend/app/routes/routing.py` lines 59 + 73 `contextlib.closing` wrap (P-1 + auth.py is verbatim template)
- `backend/app/routes/health.py` rewrite (CONTEXT D-08 ships the verbatim block)
- `.env.example` new `ALLOWED_ORIGINS` block (P-7)
- `README.md` new `## Deploy` section (P-8 + Phase 4's section is verbatim style template)

### Medium-confidence mappings

- `backend/app/db.py` pool rewrite — the FastAPI-Depends-vs-keep-`get_connection()`-as-contextmanager
  question (CONTEXT D-07 prescribes module-level pool + context-manager wrapper, but
  research priority 8 leaves the Depends path open as a "minimal-diff migration").
  Recommend: keep `get_connection()` signature as a `@contextmanager` so
  `segments.py:38` and `routing.py:59,73` and `auth.py:63,92,118` keep working
  unchanged. This is the smallest possible diff and preserves all existing call sites.
- `deploy/frontend/Dockerfile` — multi-stage shape is recommended (P-9) but
  research priority 6 may surface a different idiom Fly prefers.
- `.github/workflows/deploy.yml` shape — recommended structure in P-10 is
  the conservative option; researcher's priority 5 deliverable supersedes.

### Low-confidence / requires researcher input

- Whether `deploy/backend/fly.toml` should reference `../backend/Dockerfile`
  via `[build] dockerfile = ...` or whether the existing `backend/Dockerfile`
  should physically move under `deploy/backend/Dockerfile`. CONTEXT line 35
  says `backend/Dockerfile` is "kept unchanged" but the build-context
  question is unresolved.
- Whether the GH Actions test job runs `docker compose up db` + pytest
  inside the runner, or relies on a Fly-side ephemeral DB. CONTEXT D-04
  implies the former; research priority 5 should confirm.
- Whether SC #5's 503 path needs a separate `/healthz` endpoint (k8s
  convention) for Fly's HTTP health check, or whether `/health` works for
  both LB-probe and operator-curl. CONTEXT D-08 says "At Fly scale, `/health`
  works for both" — research priority 9 confirms.

### Confidence flags requiring planner attention

1. **No `.github/` directory exists.** `deploy.yml` is the first workflow.
   Plan should NOT assume any pre-existing CI scaffolding.
2. **`frontend/Dockerfile` is dev-only.** Production frontend image is fully
   greenfield — plan must allocate work for both `deploy/frontend/Dockerfile`
   AND `deploy/frontend/nginx.conf` (no analog to copy from).
3. **No `fly.toml`, no `deploy/` directory exists.** All three `fly.toml`
   files are first-of-their-kind in the repo.
4. **CONTEXT.md SC #7 and SC #8 fold-in descriptions are stale** (see §4).
   Planner must NOT scope plans around editing files that already do the right
   thing. Re-read SC #7 / SC #8 as deploy-time-wiring tasks, not source-edit
   tasks.
5. **The container-runtime path bug for migration tests (real SC #8)** is a
   build-context decision, not a code edit. Planner should ask the orchestrator
   whether to fold this into the `deploy/backend/fly.toml` plan or to make it
   a Wave-0 prerequisite.

---

## Metadata

- **Files analyzed:** 19 source files + 2 SQL files + docker-compose.yml + .env.example + README.md
- **Analog search scope:** `backend/app/`, `backend/tests/`, `scripts/`, `db/`, `frontend/`, `.planning/phases/`
- **First-of-kind files in this phase:** 7 (all of `deploy/**` + `.github/workflows/deploy.yml`)
- **Surgical edits:** 6 existing files (`main.py`, `db.py`, `health.py`, `routing.py`, `.env.example`, `README.md`) — plus 1 likely test edit (`test_health.py`)
- **No-op-claimed-but-already-done:** 3 (the SC #7 and SC #8 fold-ins listed in CONTEXT)
