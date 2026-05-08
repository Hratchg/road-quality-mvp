---
phase: 01-mvp-integrity-cleanup
plan: 04
subsystem: infra
tags: [env-vars, configuration, dotenv, documentation]

# Dependency graph
requires: []
provides:
  - ".env.example at repo root listing all 3 env vars the stack reads (DATABASE_URL, VITE_API_URL, VITE_MAPBOX_TOKEN)"
  - "Contributor onboarding: copy .env.example to .env, fill in secrets, run the stack"
  - "Forward-compatibility template: Phases 3/4/5 extend this file additively"
affects: [phase-03-mapillary, phase-04-auth, phase-05-production]

# Tech tracking
tech-stack:
  added: []
  patterns: ["env-var documentation pattern: every new os.getenv/import.meta.env read must also add an entry to .env.example in the same plan"]

key-files:
  created:
    - .env.example
  modified: []

key-decisions:
  - "Excluded POSTGRES_DB/POSTGRES_USER/POSTGRES_PASSWORD from .env.example — these are Docker-service init vars (postgres image), not app-read via os.environ; Phase 5 handles proper secret management"
  - "VITE_MAPBOX_TOKEN value kept empty-string matching docker-compose.yml default — token not yet wired in frontend source, Leaflet+OSM is current default"
  - "DATABASE_URL placeholder uses well-known dev default already present in source as fallback — not a secret"

patterns-established:
  - "env-var template pattern: .env.example is committed; .env is git-ignored; new env vars added in same plan that introduces the os.getenv read"

requirements-completed: [REQ-mvp-integrity-cleanup]

# Metrics
duration: 10min
completed: 2026-04-22
---

# Phase 1 Plan 4: .env.example Template Summary

**.env.example created at repo root with documented placeholders for the 3 env vars the stack currently reads (DATABASE_URL, VITE_API_URL, VITE_MAPBOX_TOKEN), resolving CONCERNS.md "No .env.example File"**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-04-22T00:00:00Z
- **Completed:** 2026-04-22T00:10:00Z
- **Tasks:** 3 (Task 1: verify inventory [read-only]; Task 2: create file; Task 3: write SUMMARY)
- **Files modified:** 1 (.env.example created)

## Accomplishments

- Confirmed env-var inventory via grep: exactly 3 unique vars read by committed source (DATABASE_URL x4 Python files, VITE_API_URL x1 TypeScript file, VITE_MAPBOX_TOKEN declared in docker-compose.yml)
- Created `.env.example` at repo root with safe dev-default placeholders, inline comments explaining each var and where it is consumed
- VITE_MAPBOX_TOKEN left empty-string matching docker-compose.yml default — Mapbox tiles not yet wired in frontend source
- POSTGRES_DB/POSTGRES_USER/POSTGRES_PASSWORD intentionally excluded — Docker postgres image init vars, not consumed by application code via os.environ
- File is NOT git-ignored (`git check-ignore .env.example` exits non-zero); file was successfully committed and tracked by git

## Task Commits

Tasks were committed atomically:

1. **Task 1: Verify env-var inventory** - read-only grep, no commit needed
2. **Task 2: Create .env.example** - `98ff882` (chore)
3. **Task 3: Write plan SUMMARY** - included in final metadata commit

**Plan metadata:** included in final docs commit

## Files Created/Modified

- `.env.example` - Repo-root environment variable template listing DATABASE_URL, VITE_API_URL, and VITE_MAPBOX_TOKEN with safe dev-default placeholders and per-var comments explaining consumers and override guidance

## Decisions Made

- **POSTGRES_DB/USER/PASSWORD excluded:** These are Docker postgres image initialization vars, not read by application code via `os.environ.get`. Including them would normalize committing dev DB credentials into .env.example. Phase 5 will handle proper secret management for these. Matches plan spec.
- **DATABASE_URL placeholder = postgresql://rq:rqpass@localhost:5432/roadquality:** This is the well-known dev default already committed as a fallback in `backend/app/db.py`. It is not a production secret.
- **VITE_MAPBOX_TOKEN = empty string:** Matches docker-compose.yml line 38 default. Mapbox not yet wired in frontend source; Leaflet+OSM is current default. Template marks it as optional with "NEVER commit a real token" warning.

## Env-Var Inventory (Task 1 Evidence)

Grep results at execution time confirmed exactly 3 unique env-var names in committed source:

**Python (os.environ.get):**
- `backend/app/db.py:5` — DATABASE_URL
- `scripts/seed_data.py:15` — DATABASE_URL
- `scripts/compute_scores.py:6` — DATABASE_URL
- `scripts/ingest_iri.py:41` — DATABASE_URL

**TypeScript (import.meta.env):**
- `frontend/src/api.ts:1` — VITE_API_URL

**docker-compose.yml (YAML env block, not grepped by source pattern):**
- Line 37: VITE_API_URL=http://localhost:8000
- Line 38: VITE_MAPBOX_TOKEN="" (empty default)

No additional env vars were discovered. Inventory matches plan spec exactly.

## CONCERNS.md Closure — RESOLVED

The CONCERNS.md "No .env.example File" configuration smell is now resolved. `.env.example` exists at repo root, is committed to git, and covers every env var the stack currently reads.

## Forward Compatibility

Future M1 phases that introduce new env-var reads MUST extend `.env.example` in the same plan that introduces the read:

- **Phase 3** (Mapillary ingestion): add `MAPILLARY_ACCESS_TOKEN=` with empty-string placeholder and "never commit a real token" comment
- **Phase 4** (auth signing key): add `AUTH_SECRET_KEY=` with placeholder
- **Phase 5** (production hardening): add/update `VITE_API_URL` for deployed backend origin, add `DATABASE_URL` production override note; replace dev DB credentials with proper secret management

Do NOT edit existing entries in `.env.example` without a corresponding plan update.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `.env.example` template established; future phases extend it additively
- Phase 1 Plan 4 complete; Phase 1 is now fully executed (all 4 plans)

---
*Phase: 01-mvp-integrity-cleanup*
*Completed: 2026-04-22*
