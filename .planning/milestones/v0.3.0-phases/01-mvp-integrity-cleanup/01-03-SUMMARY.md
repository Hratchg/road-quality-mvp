---
phase: 01-mvp-integrity-cleanup
plan: "03"
subsystem: docs
tags: [mapbox, env-var, vite, documentation, design-doc]

# Dependency graph
requires: []
provides:
  - "docs/plans/2026-02-23-pothole-tracker-design.md updated: REACT_APP_MAPBOX_TOKEN retired, VITE_MAPBOX_TOKEN is now the sole Mapbox env-var identifier across code and docs"
affects: [future planners reading design doc, Phase 2+ Mapbox integration work]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Env-var naming: VITE_ prefix (Vite-era) is canonical; CRA REACT_APP_ prefix is retired"

key-files:
  created: []
  modified:
    - "docs/plans/2026-02-23-pothole-tracker-design.md"

key-decisions:
  - "VITE_MAPBOX_TOKEN is the single canonical Mapbox env-var identifier; REACT_APP_MAPBOX_TOKEN is fully retired per Phase 1 Success Criterion #3"
  - "Historical design doc (dated 2026-02-23) received a surgical one-line factual correction, not a narrative rewrite — consistent with INGEST-CONFLICTS INFO row 2 resolution"

patterns-established:
  - "Env-var alignment: always prefer Vite prefix (VITE_) for frontend env vars in this Vite/React project"

requirements-completed: [REQ-mvp-integrity-cleanup]

# Metrics
duration: ~5min
completed: "2026-04-23"
---

# Phase 1 Plan 03: REACT_APP_MAPBOX_TOKEN Retirement Summary

**Single-line surgical rename of `REACT_APP_MAPBOX_TOKEN` to `VITE_MAPBOX_TOKEN` in the 2026-02-23 design doc, closing INGEST-CONFLICTS INFO row 2 and making `VITE_MAPBOX_TOKEN` the sole Mapbox env-var identifier repo-wide.**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-04-23T06:20:00Z
- **Completed:** 2026-04-23T06:25:12Z
- **Tasks:** 3 (Task 1: discovery grep, Task 2: surgical edit + commit, Task 3: SUMMARY)
- **Files modified:** 1 (docs/plans/2026-02-23-pothole-tracker-design.md)

## Accomplishments

- Confirmed pre-edit scope: exactly one occurrence of `REACT_APP_MAPBOX_TOKEN` in the repo (at `docs/plans/2026-02-23-pothole-tracker-design.md:156`)
- Applied one-line surgical replacement: `REACT_APP_MAPBOX_TOKEN` → `VITE_MAPBOX_TOKEN` inside backticks on the Mapbox bullet
- Verified post-edit: zero occurrences of `REACT_APP_MAPBOX_TOKEN` remain in the repo (excluding `.git`, `node_modules`, `.planning`, `dist`)
- INGEST-CONFLICTS INFO row 2 (Mapbox env-var name mismatch — CRA prefix vs Vite prefix) — RESOLVED

## Pre-edit Grep Evidence

```
$ grep -rnE "REACT_APP_MAPBOX_TOKEN" --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.planning --exclude-dir=dist .

./docs/plans/2026-02-23-pothole-tracker-design.md:156:- Full-screen Leaflet map (Mapbox if token set via `REACT_APP_MAPBOX_TOKEN`)
```

**Result:** Exactly 1 hit. File: `docs/plans/2026-02-23-pothole-tracker-design.md`. Line 156. Matches plan scope.

## Post-edit Grep Evidence

```
$ grep -rnE "REACT_APP_MAPBOX_TOKEN" --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.planning --exclude-dir=dist .

(no output)
```

**Result:** ZERO hits. `REACT_APP_MAPBOX_TOKEN` is fully retired from code and docs.

## Edit Applied

**File:** `docs/plans/2026-02-23-pothole-tracker-design.md`, line 156

```diff
-  - Full-screen Leaflet map (Mapbox if token set via `REACT_APP_MAPBOX_TOKEN`)
+  - Full-screen Leaflet map (Mapbox if token set via `VITE_MAPBOX_TOKEN`)
```

Only the env-var identifier inside the backticks changed. No other content on the line was modified. No surrounding context was changed.

## INGEST-CONFLICTS Resolution

**INFO #2 (Mapbox env-var name) — RESOLVED.**

The SPEC (`docs/plans/2026-02-23-pothole-tracker-design.md:156`) used the Create React App prefix `REACT_APP_MAPBOX_TOKEN`, which predates the project's Vite migration. Operational reality (docker-compose.yml:38, docs/SETUP.md:392, docs/plans/2026-02-23-implementation-plan.md:132) already uses `VITE_MAPBOX_TOKEN`. This plan aligned the SPEC with operational reality.

## Task Commits

Each task was committed atomically:

1. **Task 1: Pre-edit grep to confirm scope** - No commit (read-only discovery)
2. **Task 2: Replace REACT_APP_MAPBOX_TOKEN with VITE_MAPBOX_TOKEN in design doc** - `3e31af4` (fix)
3. **Task 3: Write plan SUMMARY** - committed in plan metadata commit (docs)

## Files Created/Modified

- `docs/plans/2026-02-23-pothole-tracker-design.md` — One-line surgical edit: `REACT_APP_MAPBOX_TOKEN` → `VITE_MAPBOX_TOKEN` on line 156 (Mapbox bullet in Frontend section)

## Files Intentionally NOT Modified

- `docker-compose.yml` — Already uses `VITE_MAPBOX_TOKEN` (line 38); no change needed
- `docs/SETUP.md` — Already uses `VITE_MAPBOX_TOKEN` (line 392); no change needed
- `docs/plans/2026-02-23-implementation-plan.md` — Already uses `VITE_MAPBOX_TOKEN` (line 132); no change needed
- No frontend source files — No frontend source currently reads either identifier; Mapbox tile integration is future work

## Decisions Made

- Applied Phase 1 Success Criterion #3 ("replace every hit") over the planner default ("don't rewrite history") — the design doc line is descriptive of a configuration contract that future readers will try to apply, so leaving the wrong identifier would actively mislead
- Treated the edit as a factual correction (identifier alignment), not a narrative rewrite — no context text, timestamps, or surrounding content was changed

## Deviations from Plan

None — plan executed exactly as written. One hit pre-edit, zero hits post-edit. Single-line replacement applied. SUMMARY records pre/post evidence.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required. This plan is documentation-only.

## Threat Model Compliance

Per plan threat register:
- **T-01-03-01 (Tampering — over-edit):** Mitigated. `git diff` shows exactly one line changed, identifier inside backticks only.
- **T-01-03-02 (Integrity — drift regression):** Mitigated. Pre-edit grep confirmed 1 hit; post-edit grep confirmed 0 hits. Same exclude set used for both.
- **T-01-03-03 (Repudiation):** Accepted. This SUMMARY provides the audit trail (what changed, why, from which ingest-conflict row).

## Known Stubs

None — documentation-only plan, no data flow stubs.

## Threat Flags

None — documentation-only change, no new network endpoints, auth paths, file access patterns, or schema changes.

## Next Phase Readiness

- `VITE_MAPBOX_TOKEN` is now the sole documented Mapbox env-var identifier across all code and docs
- Future Mapbox tile integration (Phase 2+) can reference `VITE_MAPBOX_TOKEN` consistently without ambiguity
- Phase 1 Success Criterion #3 satisfied

---
*Phase: 01-mvp-integrity-cleanup*
*Completed: 2026-04-23*
