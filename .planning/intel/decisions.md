# Decisions Intel

Extracted decisions from classified ingest docs. No ADRs were ingested in this run; the decisions below come from the approved SPEC-class design document's "Decisions" table and are treated as design-level choices, not ADR-locked decisions.

---

## Source Inventory

- No ADR-class docs ingested.
- SPEC-class: `docs/plans/2026-02-23-pothole-tracker-design.md` (Status: Approved, date 2026-02-23). Contains a `Decisions` table enumerating 7 design choices.

---

## Design Decisions (from SPEC)

### DEC-project-path
- source: docs/plans/2026-02-23-pothole-tracker-design.md
- status: proposed (SPEC-level, not ADR-locked)
- scope: repo layout / local dev path
- decision: Project path `C:\Users\King Hratch\road-quality-mvp` (Windows author machine).
- rationale: Clean sibling to SkillShock.
- notes: Path is author-machine-specific and should NOT be treated as a project-wide requirement. Codebase map confirms repo now lives at `/Users/hratchghanime/road-quality-mvp` (macOS). Downstream consumers should ignore this decision as project-wide.

### DEC-routing-architecture
- source: docs/plans/2026-02-23-pothole-tracker-design.md
- status: proposed (SPEC-level)
- scope: routing algorithm implementation
- decision: Fully DB-driven routing via pgRouting (`pgr_ksp` in PostgreSQL).
- rationale: Production-grade routing in SQL; avoids in-process graph libraries.
- notes: Codebase map (STACK.md, ARCHITECTURE.md) confirms this is implemented.

### DEC-seed-area
- source: docs/plans/2026-02-23-pothole-tracker-design.md
- status: proposed (SPEC-level)
- scope: seed data coverage area for MVP
- decision: LA ~10km radius around (34.05, -118.24).
- rationale: Realistic demo, 10k+ segments.
- notes: SETUP.md (DOC) later says "~20 km radius from downtown." See INGEST-CONFLICTS.md INFO entry — SPEC > DOC, SPEC value (10km) wins in synthesized intel. Seed script (`scripts/seed_data.py`) is the ground truth and should be inspected at route time.

### DEC-map-provider
- source: docs/plans/2026-02-23-pothole-tracker-design.md
- status: proposed (SPEC-level)
- scope: frontend map tile provider
- decision: Leaflet + OSM as default; Mapbox upgrade path via env var (`REACT_APP_MAPBOX_TOKEN` per SPEC, `VITE_MAPBOX_TOKEN` per SETUP + codebase STACK).
- rationale: Free default, premium upgrade path.
- notes: Env var name differs between SPEC and current codebase/SETUP. See INGEST-CONFLICTS.md — DOC + codebase use `VITE_MAPBOX_TOKEN` (Vite convention); SPEC used stale React-prefixed name. SPEC is still higher precedence but the env var naming is implementation detail the codebase/SETUP have since corrected. Flagged INFO.

### DEC-k-shortest-paths
- source: docs/plans/2026-02-23-pothole-tracker-design.md
- status: proposed (SPEC-level)
- scope: routing candidate count
- decision: k=5 for pgRouting `pgr_ksp`.
- rationale: Good variety without perf issues.
- notes: Confirmed in SETUP.md (Step 2 of route selection algorithm) and codebase.

### DEC-seed-determinism
- source: docs/plans/2026-02-23-pothole-tracker-design.md
- status: proposed (SPEC-level)
- scope: synthetic data generation
- decision: Deterministic synthetic seed with `seed=42` for IRI + pothole data.
- rationale: Reproducible demos and tests.
- notes: Confirmed in SETUP.md (`ingest_iri.py --source synthetic --seed 42`).

### DEC-prd-cadence
- source: docs/plans/2026-02-23-pothole-tracker-design.md
- status: proposed (process-level)
- scope: PRD maintenance
- decision: PRD is a living document, updated at each checkpoint.
- rationale: Per user request.
- notes: Process/editorial decision, no technical impact.
