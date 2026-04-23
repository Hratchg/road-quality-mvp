# Synthesis Summary

Entry point for downstream consumers (`gsd-roadmapper`). Produced by `gsd-doc-synthesizer` from classified ingest docs in `.planning/intel/classifications/`. Mode: `new`. Precedence: `SPEC > PRD > DOC` (no ADRs in this ingest set).

---

## Doc Inventory

- Docs synthesized: **4**
  - PRD: 1 — `docs/PRD.md`
  - SPEC: 1 — `docs/plans/2026-02-23-pothole-tracker-design.md`
  - DOC: 2 — `docs/plans/2026-02-23-implementation-plan.md`, `docs/SETUP.md`
  - ADR: 0

## Decisions

- **ADR-locked decisions: 0** (no ADRs ingested).
- **SPEC-level design decisions extracted: 7** from the SPEC's "Decisions" table:
  - DEC-project-path (informational; author Windows path, not project-wide)
  - DEC-routing-architecture (pgRouting / fully DB-driven)
  - DEC-seed-area (LA ~10km radius from 34.05,-118.24)
  - DEC-map-provider (Leaflet+OSM default, Mapbox via env var)
  - DEC-k-shortest-paths (k=5)
  - DEC-seed-determinism (seed=42)
  - DEC-prd-cadence (living document)
- File: `.planning/intel/decisions.md`

## Requirements

- **Total: 20**
  - Implemented (per PRD): 17
  - Planned / Post-MVP: 3
- IDs:
  - MVP: REQ-docker-compose-stack, REQ-db-schema, REQ-health-endpoint, REQ-segments-endpoint, REQ-route-endpoint, REQ-scoring-logic, REQ-max-time-rule, REQ-pydantic-models, REQ-ml-detector-protocol, REQ-yolov8-detector, REQ-seed-data, REQ-iri-ingestion, REQ-frontend-skeleton, REQ-map-view-page, REQ-route-finder-page, REQ-readme-docs, REQ-demo-launch, REQ-integration-tests, REQ-caching-layer
  - Post-MVP: REQ-mapillary-pipeline, REQ-user-auth, REQ-prod-deploy
- File: `.planning/intel/requirements.md`

## Constraints

- **Total: 17**
  - stack: 4 (backend, frontend, database, data-pipeline)
  - schema: 1 (CON-db-schema — four tables)
  - api-contract: 4 (/route, /segments, /health, /cache admin)
  - protocol: 3 (detector protocol, scoring math, route selection algorithm)
  - nfr: 5 (caching, ports, seed data, CORS, migrations)
- Authoritative source: SPEC. DOC-sourced additive items (cache admin endpoints, some NFR details) are attributed but flagged INFO in INGEST-CONFLICTS.md.
- File: `.planning/intel/constraints.md`

## Context

- **Topics: 11** — implementation plan structure, backend dependency pins, DB credentials (dev), environment variables, test inventory, quick starts (Docker + local), IRI ingestion CLI, detector factory, frontend UI notes, troubleshooting, author machine path.
- File: `.planning/intel/context.md`

## Conflicts

- **BLOCKERS: 0**
- **WARNINGS: 0**
- **INFO: 7** — see `.planning/INGEST-CONFLICTS.md` for details. Highlights:
  - SPEC > DOC wins on seed radius (10km vs ~20km)
  - SPEC > DOC wins on pgRouting source/target column type (BIGINT vs INTEGER)
  - DOC + codebase override stale SPEC env-var name for Mapbox token
  - DOC additively extends SPEC with cache admin endpoints
  - Minor psycopg2 version drift between plan and codebase
  - PRD vs DOC test-count framing (different scope, not a conflict)
  - PRD<->SPEC mutual cross-reference (benign, not a synthesis cycle)

## Pointers

- Per-type intel:
  - `.planning/intel/decisions.md`
  - `.planning/intel/requirements.md`
  - `.planning/intel/constraints.md`
  - `.planning/intel/context.md`
- Conflicts report: `.planning/INGEST-CONFLICTS.md`
- Codebase map (cross-checked during synthesis): `.planning/codebase/STACK.md`, `.planning/codebase/ARCHITECTURE.md`
- Classification inputs: `.planning/intel/classifications/*.json`

## Notes for the Roadmapper

- No ADRs exist yet. The SPEC's "Decisions" table is treated as **design decisions**, not locked ADRs. If the roadmapper determines any of these should be promoted to ADR form (particularly DEC-routing-architecture, DEC-k-shortest-paths, DEC-seed-determinism), that is a separate action.
- The PRD cleanly labels items as Implemented vs Planned. Most MVP work is already done; the roadmap should focus on Post-MVP (Mapillary pipeline, auth, prod deploy) and any follow-through implied by INFO entries (e.g., verifying migration column types match the SPEC BIGINT choice).
- `docs/SETUP.md` is a user-facing setup guide; it should be updated when `VITE_MAPBOX_TOKEN` semantics or the seed radius are finalized, but synthesis does not write to it.
