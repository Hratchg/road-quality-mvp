---
phase: 05-cloud-deployment
plan: 03
subsystem: infra

tags:
  - fly
  - docker
  - postgres
  - postgis
  - pgrouting
  - infra
  - toml
  - dockerfile

# Dependency graph
requires:
  - phase: 05-cloud-deployment
    provides: "Plan 05-02's GET /health endpoint with DB-reachability probe — referenced by deploy/backend/fly.toml's [[http_service.checks]].path = '/health' for the LB depool/repool loop"
  - phase: 04-user-management
    provides: "db/migrations/003_users.sql baked into deploy/db/Dockerfile alongside 001_initial.sql and 002_mapillary_provenance.sql"
  - phase: 03-mapillary-ingestion-pipeline
    provides: "db/migrations/002_mapillary_provenance.sql baked into deploy/db/Dockerfile"

provides:
  - "deploy/db/Dockerfile (PostGIS 3.4 + pgRouting 3.8.0 + 4 init scripts baked into /docker-entrypoint-initdb.d/)"
  - "deploy/db/fly.toml (road-quality-db Fly app: 1 GB pgdata volume, internal-only TCP 5432, auto-stop disabled)"
  - "deploy/backend/fly.toml (road-quality-backend Fly app: references existing backend/Dockerfile, /health LB probe, dev auto-reload override)"
  - "deploy/db/test-build.sh (local docker-build smoke test asserting pgRouting >= 3.6 + all 4 init scripts present)"

affects:
  - "Plan 05-04 (frontend Fly artifacts) — its [build].dockerfile path resolution mirrors this plan's repo-root-context decision"
  - "Plan 05-05 (GH Actions deploy workflow) — its `flyctl deploy --config deploy/{db,backend}/fly.toml .` invocations target the artifacts in this plan"
  - "Phase 6+ migrations — the lexicographic 00-/01-/02-/03- prefix scheme leaves headroom for 04-*.sql etc. without renumbering existing files"
  - "Phase 6+ optional release_command — RESEARCH Open Q2 deferred this; if added later, the [deploy] block goes in deploy/backend/fly.toml"

# Tech tracking
tech-stack:
  added:
    - "postgis/postgis:16-3.4 (Debian 11 bullseye base) as the deploy DB image"
    - "postgresql-16-pgrouting 3.8.0-1.pgdg110+1 (apt from bullseye-pgdg)"
    - "Fly.io app config (fly.toml) for road-quality-db and road-quality-backend"
  patterns:
    - "Repo-root build context: flyctl deploy --config deploy/{svc}/fly.toml . — the trailing `.` sets the build context to repo root so [build].dockerfile paths resolve relative to repo root"
    - "Migration baking: db/migrations/*.sql + db/init-pgrouting.sh COPY'd into /docker-entrypoint-initdb.d/ at image-build time, NOT mounted at runtime via Fly file-mount"
    - "[processes].web override: production CMD declared at the Fly process layer instead of editing the dev Dockerfile, preserving local-dev parity"
    - "Internal-only Fly app pattern: [[services]] without [http_service] = TCP-only service reachable from sibling Fly apps via *.internal:port over WireGuard-encrypted 6PN"
    - "Secrets-via-fly-secrets-set: [env] declares only public-ish identifiers (POSTGRES_DB, POSTGRES_USER, PYTHONUNBUFFERED); all credentials/tokens flow through `fly secrets set`"

key-files:
  created:
    - "deploy/db/Dockerfile"
    - "deploy/db/fly.toml"
    - "deploy/db/test-build.sh"
    - "deploy/backend/fly.toml"
  modified: []

key-decisions:
  - "Migration baking strategy A (RESEARCH alternatives): COPY db/migrations/*.sql into the image's /docker-entrypoint-initdb.d/ at build time. Image IS the deploy artifact — no drift between volume snapshot and migration set. Rejected B (Fly file mounts at runtime), C (per-release psql via flyctl ssh), D (backend [deploy].release_command — Phase 6+ only)."
  - "Build context = repo root. flyctl deploy --config deploy/{db,backend}/fly.toml . runs from repo root; [build].dockerfile paths are relative to repo root (`deploy/db/Dockerfile` for db, `backend/Dockerfile` for backend). If A11 verification fails, fallback is `flyctl deploy /repo/root --config deploy/.../fly.toml`."
  - "Init script numbering 00/01/02/03 (one-prefix-lower than docker-compose.yml's 01/02/03/04) — leaves a 04-* slot for future Phase 6+ migrations without renumbering existing files."
  - "Hostname = .internal (NOT .flycast) for backend->db. Single-machine DB doesn't need Fly Proxy's autostart/loadbalancing; .internal is basic IPv6 DNS over the same WireGuard-encrypted private network."
  - "auto_stop_machines = false on db, auto_stop_machines = 'stop' on backend. DB must stay warm (T-05-17 mitigation: stale-data risk on auto-restart). Backend is fine to cold-start (~2-5s acceptable for demo)."
  - "[processes].web overrides backend/Dockerfile's dev CMD with the production uvicorn invocation. backend/Dockerfile stays unchanged for dev parity (CONTEXT D-01); the Fly process layer is the right place for environment-specific CMD differences."

patterns-established:
  - "Repo-root build context for monorepo Fly apps: trailing `.` in flyctl invocations + relative paths in [build].dockerfile"
  - "Internal-only Fly service shape: [[services]] block with TCP protocol + tcp_checks, NO [http_service]"
  - "Fly process-layer CMD override for dev/prod parity: keep one Dockerfile with the dev-friendly CMD, override at deploy time via [processes]"
  - "Secret-discipline in fly.toml: comments document WHERE secrets come from but never include the secret-name string in a way that could be mistaken for an [env] declaration; all credentials flow through `fly secrets set`"

requirements-completed:
  - REQ-prod-deploy

# Metrics
duration: 5min
completed: 2026-04-25
---

# Phase 05 Plan 03: Database & Backend Fly Artifacts Summary

**deploy/db/Dockerfile (PostGIS+pgRouting 3.8 + baked migrations) and 2 fly.toml files (internal-only db on a 1 GB volume + backend referencing the existing backend/Dockerfile with a /health LB probe and dev-reloader override)**

## Performance

- **Duration:** 5 min 10 sec
- **Started:** 2026-04-25T19:49:44Z
- **Completed:** 2026-04-25T19:54:54Z (approx; SUMMARY commit shortly after)
- **Tasks:** 3 atomic + 1 deviation fix
- **Files created:** 4
- **Files modified:** 0

## Accomplishments

- `deploy/db/Dockerfile` builds locally: pgRouting **3.8.0** present at `/usr/share/postgresql/16/extension/pgrouting--3.8.0.sql`; all 4 init scripts (`00-init-pgrouting.sh`, `01-schema.sql`, `02-mapillary.sql`, `03-users.sql`) baked into `/docker-entrypoint-initdb.d/` (verified by `bash deploy/db/test-build.sh`).
- `deploy/db/fly.toml` configures `road-quality-db` as an internal-only TCP service (no `[http_service]`, no public ports) with a 1 GB `pgdata` volume mounted at `/var/lib/postgresql/data`, `auto_stop_machines = false`, `min_machines_running = 1`. Reachable by sibling Fly apps via `road-quality-db.internal:5432`.
- `deploy/backend/fly.toml` configures `road-quality-backend` referencing the **unchanged** `backend/Dockerfile`, with a production `[processes].web = "uvicorn app.main:app --host 0.0.0.0 --port 8000"` (no dev auto-reload), `force_https = true`, and a `[[http_service.checks]]` block hitting `GET /health` every 30s (the Plan 05-02 endpoint that returns 503 on DB unreachable).
- `deploy/db/test-build.sh` is a portable smoke test that future operators (and Plan 05-05's CI) can run to catch regressions in the db image build.

## Task Commits

Each task was committed atomically:

1. **Task 1: deploy/db/Dockerfile + test-build.sh** — `3366870` (feat)
2. **Task 2: deploy/db/fly.toml** — `fa6ef7e` (feat)
3. **Deviation fix: db/fly.toml secret-doc comment** — `1644c18` (docs)
4. **Task 3: deploy/backend/fly.toml** — `d8f6884` (feat)

## Content Hashes (for Plan 05-05 / future verifiers)

- `deploy/db/Dockerfile` sha256[0:16] = `1bf31abb15b27bd1`
- `deploy/db/fly.toml` sha256[0:16] = `0616513dad7d2a96`
- `deploy/backend/fly.toml` sha256[0:16] = `72bcf1a3c9ce2252`
- `deploy/db/test-build.sh` sha256[0:16] = `82dcc99c99e1c1c5`

## Files Created/Modified

- `deploy/db/Dockerfile` — PostGIS 3.4 base + apt-installed pgRouting 3.8.0 + 4 baked init scripts (one COPY per migration; explicit numeric-prefix destinations).
- `deploy/db/fly.toml` — Fly app config for `road-quality-db`: 1 GB pgdata volume, internal-only [[services]] on TCP 5432 with grace_period=30s tcp_checks, auto_stop disabled, lax primary, shared-cpu-1x/512mb VM.
- `deploy/db/test-build.sh` (mode 755) — local smoke test that asserts `docker build` succeeds, pgRouting version >= 3.6, and all 4 init scripts are present in the image.
- `deploy/backend/fly.toml` — Fly app config for `road-quality-backend`: references the existing `backend/Dockerfile`, [processes].web overrides the dev CMD, [http_service] internal_port=8000 with /health probe, [[vm]] shared-cpu-1x/512mb.

**Files NOT modified** (per CONTEXT and plan locks): `backend/Dockerfile`, `db/Dockerfile`, `docker-compose.yml`, `.planning/STATE.md`, `.planning/ROADMAP.md`. Verified via `git diff 605cf89..HEAD -- backend/Dockerfile db/Dockerfile docker-compose.yml` returning 0 lines.

## Migration-Baking Strategy: chosen vs. rejected alternatives

| Alt | Strategy | Verdict | One-liner rationale |
|-----|----------|---------|---------------------|
| **A** | **Bake `db/migrations/*.sql` + `db/init-pgrouting.sh` into the image via Dockerfile `COPY`** | **CHOSEN** | Image IS the deploy artifact; no drift between volume snapshot and migration set; matches Plan 05-05's "deploy from clean checkout" assumption. |
| B | Mount `db/migrations/` via Fly `[mounts]` at runtime | rejected | Fly mounts are for persistent data, not config; would create drift between image and migration files; runtime mount requires shipping the files separately to the deployer machine. |
| C | One-shot `flyctl ssh + psql` after first boot | rejected | Manual step; defeats SC #1's "documented deploy path"; doesn't survive redeploys onto a new volume. |
| D | Backend's `[deploy].release_command` runs migrations | rejected (M1) | RESEARCH Open Q2 explicitly defers this to Phase 6+; M1 keeps migrations in the db image's init-script flow. |

## Build context decision

`flyctl deploy --config deploy/{db,backend}/fly.toml .` — the trailing `.` makes the build context `<repo_root>`, so `[build].dockerfile = "deploy/db/Dockerfile"` (db) and `[build].dockerfile = "backend/Dockerfile"` (backend) both resolve correctly relative to repo root. This pattern is what Plan 05-05's GH Actions workflow MUST use; if the A11 `flyctl deploy --config X .` form ever fails on Fly's remote builder, the documented workaround is `flyctl deploy /path/to/repo/root --config X` (RESEARCH Assumption A11).

## Pitfall 6 — Volume snapshot restore loses post-init migrations

`/docker-entrypoint-initdb.d/` scripts run **only on the first boot of an empty `$PGDATA` volume**. If a Fly volume is restored from a snapshot taken before a migration was added, the snapshot's PGDATA is non-empty so init scripts are skipped — the new migration is silently NOT applied. **Recovery (M1):** `flyctl ssh console -C "psql -U rq -d roadquality < /docker-entrypoint-initdb.d/01-schema.sql"` (or whichever migration is missing). All migrations use `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` so re-application is idempotent. Phase 6+ may add `scripts/apply_migrations.py` to automate this; for now it's an operator runbook step.

## Secret roster (for Plan 05-05's `fly secrets set` invocations)

| App | Secret name | Source | Notes |
|-----|-------------|--------|-------|
| road-quality-db | DB password (env: `POSTGRES_PASSWORD`) | `python -c "import secrets; print(secrets.token_urlsafe(32))"` once locally, then `fly secrets set --app road-quality-db <name>=$VALUE` | Re-used in backend's connection string. |
| road-quality-backend | DB connection string | `postgres://rq:${PG_PASSWORD}@road-quality-db.internal:5432/roadquality` | Composed once after db is deployed. |
| road-quality-backend | Auth signing key | `python -c "import secrets; print(secrets.token_urlsafe(32))"` | Generated locally, never committed. |
| road-quality-backend | CORS allowlist | `https://road-quality-frontend.fly.dev` (Plan 05-04 will set the actual frontend URL) | Single comma-sep string. |
| road-quality-backend | Mapillary access token | Operator-provided | Optional — only needed when ingest runs. |
| road-quality-backend | YOLO model path | `keremberke/yolov8s-pothole-segmentation` | Optional — defaults to HF repo if unset. |

**Non-secrets in [env]** — committed to git on purpose: db's `POSTGRES_DB = "roadquality"`, db's `POSTGRES_USER = "rq"`, backend's `PYTHONUNBUFFERED = "1"`. These are public-ish identifiers (already in `docker-compose.yml` without secret protection).

## SC #1 partial closure

This plan delivers the **infrastructure half** of SC #1 (a documented deploy path brings up db + backend + frontend). Concretely:

- **Done:** db + backend Fly artifacts (Dockerfile + 2 fly.toml). `flyctl deploy --config deploy/db/fly.toml .` and `flyctl deploy --config deploy/backend/fly.toml .` are now mechanically possible (require flyctl auth + a Fly account).
- **Not yet done (Plan 05-05's territory):** the GH Actions workflow that wires this all together with secret-set commands and runs on `push: main`. SC #1's full closure happens when Plan 05-05 ships `.github/workflows/deploy.yml`.
- **Not in this plan (Plan 05-04's territory):** `deploy/frontend/{Dockerfile,nginx.conf,fly.toml}`. Zero overlap with this plan; safe-to-parallelize wave-2 sibling.

## Decisions Made

- **Migration init script numbering: 00/01/02/03** (one prefix lower than `docker-compose.yml`'s 01/02/03/04). Leaves headroom for future `04-*.sql` Phase 6+ migrations to slot in without renumbering existing scripts. Lexicographic order matches docker-compose.yml's intent exactly.
- **`primary_region = "lax"`** for both apps. LA is the dataset center (34.0522, -118.2437); `lax` is the closest Fly POP. `sjc` would also be West Coast US-equivalent but `lax` is RESEARCH §2's default.
- **`shared-cpu-1x` / 512mb VMs for both apps.** Fly's smallest billable VM (~$1.94/mo each). Acceptable for demo scale; bump to 1024mb if the operator's local Docker build shows OOM risk during pgRouting extension load.
- **Single COPY per migration in deploy/db/Dockerfile** (not `COPY db/migrations/*.sql /docker-entrypoint-initdb.d/`). Explicit per-file COPY preserves numeric-prefix destinations and is robust against future filename re-numbering edge cases.
- **`auto_start_machines = false` on the db** (not just `auto_stop_machines = false`). Together with `min_machines_running = 1`, this ensures a single primary that never auto-stops AND never spawns extras on traffic spikes.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Comment in deploy/db/fly.toml referenced `POSTGRES_PASSWORD` literal, breaking the plan's verify grep**

- **Found during:** Task 2 verification (running the full `<verification>` suite from the plan)
- **Issue:** My initial `[env]` comment in `deploy/db/fly.toml` said `# POSTGRES_PASSWORD set via 'fly secrets set --app road-quality-db POSTGRES_PASSWORD=<value>'`. No actual secret VALUE was committed (the must_not_haves rule), but the literal string `POSTGRES_PASSWORD` made the plan's verify grep `! grep -q 'POSTGRES_PASSWORD' deploy/db/fly.toml` fail.
- **Fix:** Reworded comment to "The DB password is intentionally absent from this file. It is set via `fly secrets set --app road-quality-db <SECRET_NAME>=<value>` per CONTEXT D-05 — never committed to git." Same operator-guidance intent (documenting where the secret comes from); zero references to the secret-name literal that the verify grep guards against.
- **Files modified:** `deploy/db/fly.toml`
- **Verification:** `! grep -q POSTGRES_PASSWORD deploy/db/fly.toml` passes; TOML still parses; `[env]` still declares only POSTGRES_DB and POSTGRES_USER.
- **Committed in:** `1644c18` (separate `docs(05-03): rewrite db/fly.toml secret-doc comment...` commit, after Task 2's `fa6ef7e`).

**2. [Rule 1 - Bug] Comments in deploy/backend/fly.toml referenced `--reload` literal and the secret-name strings DATABASE_URL/AUTH_SIGNING_KEY/etc., breaking verify greps**

- **Found during:** Task 3 verification (same full `<verification>` run as deviation 1)
- **Issue:** My initial header comment in `deploy/backend/fly.toml` said "overrides backend/Dockerfile's `--reload`" and listed "Secrets (DATABASE_URL, AUTH_SIGNING_KEY, ALLOWED_ORIGINS, MAPILLARY_ACCESS_TOKEN, YOLO_MODEL_PATH)". The `! grep -q -- '--reload' deploy/backend/fly.toml` and `! grep -q DATABASE_URL deploy/backend/fly.toml` (etc.) verify greps failed despite no actual `--reload` in the production CMD and no actual secret VALUES anywhere.
- **Fix:** Reworded the header comment to "the dev-only auto-reload flag" and "All runtime secrets (DB connection string, auth signing key, CORS allowlist, Mapillary API token, YOLO model path)". Same documentation intent; zero literal matches against the verify-grep guards.
- **Files modified:** `deploy/backend/fly.toml` (before its first commit, so no separate fix-commit was needed)
- **Verification:** `! grep -q -- '--reload' deploy/backend/fly.toml` passes; all `! grep -q <SECRET_NAME>` checks pass; TOML still parses; `[processes].web` still has the production uvicorn CMD without the dev reloader flag.
- **Committed in:** `d8f6884` (Task 3 commit; the comment was already cleaned up before staging).

---

**Total deviations:** 2 auto-fixed (both Rule 1 — bugs where my initial comment text caused verify-grep failures despite the underlying configuration being correct).

**Impact on plan:** Both deviations were comment-text-only — the actual configuration values (no hardcoded secrets, no `--reload` in the production CMD, no `[http_service]` on the db) all matched the plan's intent from the first draft. The fix was to reword the operator-guidance comments so they don't false-positive against the plan's anti-pattern verify greps. Zero scope creep; net effect is comments that are slightly less explicit about which Fly secret name to use, traded for verify-grep cleanliness.

## Issues Encountered

None.

## User Setup Required

None — this plan creates infrastructure-as-code only. The operator runs `fly secrets set` before the first deploy in Plan 05-05; that runbook lives in Plan 05-05's USER-SETUP, not here.

## Next Phase Readiness

- **Plan 05-04 (frontend Fly artifacts):** unblocked. Zero file overlap with this plan; can run in parallel.
- **Plan 05-05 (GH Actions deploy workflow):** unblocked. Both `deploy/db/fly.toml` and `deploy/backend/fly.toml` are ready for `flyctl deploy --config X .` invocations from a GH Actions runner. The repo-root build-context decision is locked; the secret roster is documented.
- **Phase 6+ migration additions:** unblocked. New migrations slot in as `04-*.sql` etc. into the next deploy/db/Dockerfile revision; idempotent CREATE-IF-NOT-EXISTS guards already present in 001-003.
- **No blockers.** The `flyctl deploy --build-only` dry-run is deferred to first-deploy in Plan 05-05 (requires authenticated flyctl which we don't have here).

## Self-Check: PASSED

Verified that all claimed files exist and all claimed commit hashes are in the git log:

- FOUND: `deploy/db/Dockerfile`
- FOUND: `deploy/db/fly.toml`
- FOUND: `deploy/db/test-build.sh` (mode 755)
- FOUND: `deploy/backend/fly.toml`
- FOUND commit: `3366870` (Task 1)
- FOUND commit: `fa6ef7e` (Task 2)
- FOUND commit: `1644c18` (deviation fix)
- FOUND commit: `d8f6884` (Task 3)

Plus: `find deploy -type f` returns exactly the 4 expected files; `git diff 605cf89..HEAD -- backend/Dockerfile db/Dockerfile docker-compose.yml` returns 0 lines (locked files unchanged); both fly.toml files parse via Python 3.12 `tomllib`; `bash deploy/db/test-build.sh` exited 0 with `pgRouting 3.8.0 installed; all 4 init scripts baked in`.

---
*Phase: 05-cloud-deployment*
*Plan: 03*
*Completed: 2026-04-25*
