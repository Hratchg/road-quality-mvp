## Conflict Detection Report

### BLOCKERS (0)

No blockers. No LOCKED ADRs were ingested, no UNKNOWN-confidence-low classifications, no ADR-vs-existing-context contradictions (mode=new, no prior PROJECT/REQUIREMENTS/ROADMAP to compare against), and no content-dependency cycles in the ingest set.

### WARNINGS (0)

No warnings. Only one PRD was ingested, so no competing acceptance variants are possible. No precedence-inverted contradictions requiring user input were detected.

### INFO (7)

[INFO] Auto-resolved: SPEC > DOC on seed radius
  Found: docs/plans/2026-02-23-pothole-tracker-design.md (SPEC, section 8) declares seed area = LA ~10 km radius around (34.0522, -118.2437); docs/PRD.md corroborates ("LA ~10km radius").
  Note: docs/SETUP.md (DOC, "Seeding the Database") states "~20 km radius from downtown." Per precedence SPEC > DOC, the 10 km radius is authoritative in synthesized intel (constraints.md CON-seed-data-nfr, decisions.md DEC-seed-area). Ground truth is `scripts/seed_data.py`; downstream planning should verify the literal value there before asserting either.

[INFO] Auto-resolved: DOC + codebase override stale SPEC env-var name for Mapbox token
  Found: docs/plans/2026-02-23-pothole-tracker-design.md (SPEC, section 7) uses `REACT_APP_MAPBOX_TOKEN` (Create-React-App prefix); docs/SETUP.md and .planning/codebase/STACK.md use `VITE_MAPBOX_TOKEN` (Vite prefix).
  Note: Strict precedence says SPEC > DOC, but the SPEC's env-var name predates the project's Vite migration and does not match any implemented code path. The Vite-prefixed name is the operational reality and is recorded as such in constraints.md and context.md. SPEC choice "Leaflet default, Mapbox via env var" (DEC-map-provider) is preserved; only the env-var identifier is taken from current DOCs/codebase. If the user wants the SPEC to win literally, update SPEC or flip precedence in a manifest.

[INFO] Auto-resolved: SPEC > DOC on pgRouting source/target column type
  Found: docs/plans/2026-02-23-pothole-tracker-design.md (SPEC, section 4) declares `road_segments.source` and `road_segments.target` as BIGINT; docs/plans/2026-02-23-implementation-plan.md (DOC, Task 1 Step 3) declares them as INTEGER in the SQL DDL.
  Note: SPEC wins per precedence. constraints.md CON-db-schema records BIGINT. Codebase migrations at `db/migrations/001_initial.sql` should be inspected — if they match the DOC (INTEGER), that is an implementation gap to raise in roadmapping, not a doc conflict.

[INFO] Auto-resolved: DOC additively extends SPEC with cache admin endpoints
  Found: docs/SETUP.md (DOC, "API Reference") documents `GET /cache/stats` and `POST /cache/clear`; docs/plans/2026-02-23-pothole-tracker-design.md (SPEC, section 6) does not mention these endpoints.
  Note: Additive, non-contradictory. Recorded in constraints.md CON-cache-admin-api with attribution. SPEC predates the caching feature (see PRD "Implemented" bullet: "Caching layer ... admin endpoints"), so this is a real-world delta, not a conflict.

[INFO] Informational: PRD vs DOC test-count framing
  Found: docs/PRD.md describes "Integration tests against real DB (6 tests, auto-skip when DB down)"; docs/SETUP.md describes "19 tests total" across 8 files including `test_integration.py`.
  Note: Not a conflict — different scope. PRD's 6 refers only to integration tests; SETUP's 19 is the total backend suite. Both facts are preserved in requirements.md REQ-integration-tests and context.md "Test Inventory" topic.

[INFO] Informational: psycopg2 version drift between plan and codebase
  Found: docs/plans/2026-02-23-implementation-plan.md (DOC, Task 2 Step 1) pins `psycopg2-binary==2.9.10`; .planning/codebase/STACK.md reports `psycopg2-binary 2.9.11`.
  Note: Minor patch-level drift. No action required at synthesis time; roadmapping may choose to re-pin or bump. Captured in context.md "Backend Dependency Pins" topic.

[INFO] Informational: PRD<->SPEC mutual cross-reference (benign, not a synthesis cycle)
  Found: docs/PRD.md `cross_refs` points to `plans/2026-02-23-pothole-tracker-design.md`; docs/plans/2026-02-23-pothole-tracker-design.md `cross_refs` points back to `docs/PRD.md`.
  Note: Standard "see also" bidirectional reference between a PRD and its design doc. Both documents contain complete, standalone content; synthesis extracts each independently without recursion. Not treated as a content-dependency cycle (no BLOCKER raised). If stricter cycle enforcement is desired, shrink input via `--manifest` to include only one side.
