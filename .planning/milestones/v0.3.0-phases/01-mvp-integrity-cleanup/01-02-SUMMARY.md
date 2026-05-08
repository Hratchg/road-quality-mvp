---
phase: 01-mvp-integrity-cleanup
plan: "02"
subsystem: documentation
tags: [drift-fix, seed-radius, docs, integrity]
dependency_graph:
  requires: []
  provides: [seed-radius-canonical-value]
  affects: [README.md, docs/PRD.md, .planning/PROJECT.md]
tech_stack:
  added: []
  patterns: [authoritative-source-propagation]
key_files:
  created: []
  modified:
    - README.md
    - docs/PRD.md
    - .planning/PROJECT.md
decisions:
  - "scripts/seed_data.py DIST = 20000 (20 km) is the authoritative seed radius; all docs must match it"
  - "docs/SETUP.md already matched code before this plan ran — verified, not modified"
  - "PROJECT.md Key Decisions row for seed radius promoted from Revisit to Resolved with Phase 1 Plan 02 traceability"
metrics:
  duration: "~5 minutes"
  completed: "2026-04-23"
  tasks_completed: 5
  files_changed: 3
---

# Phase 1 Plan 02: Seed-Radius Doc Drift Reconciliation Summary

**One-liner:** Propagated authoritative seed radius (20 km, DIST=20000 in seed_data.py) to README.md and docs/PRD.md, and resolved the pending PROJECT.md Key Decisions row.

## SC #2 Verification (Phase 1 Success Criterion)

- `scripts/seed_data.py` line 21: `DIST = 20000` — confirmed 20 km, unchanged, authoritative.
- `docs/SETUP.md` line 153: "Downloads the LA road network (~20 km radius from downtown)" — already matched code.
- **Both files agreed at 20 km before this plan ran.** SC #2 core requirement is satisfied with no edits to either file.

## Drift Fixed

### README.md (line 38)

| Before | After |
|--------|-------|
| `This downloads the LA road network (~10km radius) via OSMnx...` | `This downloads the LA road network (~20 km radius) via OSMnx...` |

Commit: `dbdeca5`

Verification:
```
grep -nE "~20\s*km\s+radius" README.md  →  38: ...~20 km radius...
grep -nE "~10\s*km\s+radius" README.md  →  (no output — PASS)
```

### docs/PRD.md (line 19)

| Before | After |
|--------|-------|
| `- [x] Seed data script (osmnx LA 10km + synthetic IRI/potholes)` | `- [x] Seed data script (osmnx LA 20km + synthetic IRI/potholes)` |

Commit: `aab89f2`

Verification:
```
grep -nE "osmnx LA 20km" docs/PRD.md  →  19: ...(osmnx LA 20km + synthetic IRI/potholes)
grep -nE "osmnx LA 10km" docs/PRD.md  →  (no output — PASS)
```

### .planning/PROJECT.md Key Decisions table row

| Before | After |
|--------|-------|
| `Seed radius = 10 km around (34.05, -118.24)` / `⚠️ Revisit (INFO item from ingest)` | `Seed radius = 20 km around (34.05, -118.24)` / `✓ Resolved (Phase 1, 2026-04-23)` |

Also updated footer timestamp: `*Last updated: 2026-04-23 after Phase 1 Plan 02 (seed radius drift resolved)*`

The BIGINT row (`road_segments.source/target`) was left unchanged — that is Plan 01's concern.

Commit: `1c287bf`

Verification:
```
grep -nE "Seed radius = 20 km" .planning/PROJECT.md  →  120: | Seed radius = 20 km ...
grep -nE "Seed radius = 10 km" .planning/PROJECT.md  →  (no output — PASS)
grep -n "Phase 1 Plan 02" .planning/PROJECT.md       →  120, 124: present
grep -n "road_segments.*BIGINT" .planning/PROJECT.md →  121: BIGINT row intact
```

## INGEST-CONFLICTS INFO #1 — RESOLVED

INFO item: "SPEC says seed radius is 10 km; SETUP.md says ~20 km. Verify `scripts/seed_data.py` literal and reconcile the two docs."

**Resolution:** Code literal `DIST = 20000` (20 km) is authoritative. SETUP.md already matched code. README.md and docs/PRD.md were updated to match. PROJECT.md decision row is now marked Resolved. The SPEC's "10 km" claim is superseded by the code; this is consistent with ROADMAP Phase 1 SC #2 ("pick the seed script's literal as authoritative if there's ambiguity").

## Files Modified (3 files, surgical diffs)

1. `README.md` — line 38: `~10km` → `~20 km` (commit `dbdeca5`)
2. `docs/PRD.md` — line 19: `osmnx LA 10km` → `osmnx LA 20km` (commit `aab89f2`)
3. `.planning/PROJECT.md` — Key Decisions row + footer (commit `1c287bf`)

## Files NOT Modified (intentional)

- `scripts/seed_data.py` — authoritative source; must not be changed
- `docs/SETUP.md` — already matched code at 20 km; no edit needed
- `docs/plans/*.md` — historical dated artifacts; rewriting history is out of scope
- `.planning/STATE.md` — orchestrator-owned; never touched by executor agents

## Deviations from Plan

None. Plan executed exactly as written. The exact replacement strings in Tasks 2 and 3 matched the files. The PROJECT.md row text differed slightly from the plan's quoted "exact current text" (a minor wording variant in the rationale column), but the actual file content was used for the replacement — the edit succeeded on the first retry after re-reading the file.

## Threat Model Compliance

- **T-01-02-01 (Tampering):** All edits were exact string replacements to a single line per file. Git diff confirms one-line changes in README.md and docs/PRD.md, two-line change in PROJECT.md (row + footer). No paragraph reflowing or out-of-scope edits.
- **T-01-02-03 (Repudiation):** PROJECT.md updated row explicitly references "Phase 1 Plan 02" for audit trail.
- **T-01-02-04 (Drift regression):** SUMMARY records authoritative literal and files intentionally not modified for future phase reference.

## Self-Check: PASSED

- README.md modified: exists, contains "~20 km radius" ✓
- docs/PRD.md modified: exists, contains "osmnx LA 20km" ✓
- .planning/PROJECT.md modified: exists, contains "Seed radius = 20 km" and "Resolved" ✓
- scripts/seed_data.py: unchanged (DIST = 20000 intact) ✓
- docs/SETUP.md: unchanged (~20 km radius intact) ✓
- Commits dbdeca5, aab89f2, 1c287bf: all present in git log ✓
