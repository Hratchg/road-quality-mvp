---
phase: 08-routing-performance
plan: 05
subsystem: documentation
tags: [phase-08, wave-5, docs-closure, routing, readme, inline-citations]

# Dependency graph
requires:
  - phase: 08-routing-performance
    plan: 04
    provides: operator-approved Run 3 perf numbers (cross-LA 2.47s median, DTLA 0.385s median) in 08-PERF-NUMBERS.md
provides:
  - README.md "Current Status" addendum surfacing the cross-LA latency win with a measured number traceable to 08-PERF-NUMBERS.md Run 3
  - Inline-comment header (lines 272-298) above the second `with get_connection() as conn:` block in backend/app/routes/routing.py citing RESEARCH §8 Pitfalls A and G as load-bearing constraints for future maintainers
affects:
  - Phase 8 verification (gsd-verify-work) — documentation surfaces are now in place for the verifier to cross-check
  - Future routing optimization phases — inline citations make the contract explicit at the call site, preventing re-introduction of the 2026-04-29 disaster
  - README readers — first-time visitors see the post-Phase-8 reality (long routes work) instead of the M1-era assumption

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Inline pitfall citations at call sites (rather than relying on out-of-tree planning docs) for load-bearing structural decisions whose 'simplification' would re-introduce a known regression"
    - "README perf claims cross-link to .planning/phases/<phase>/<phase>-PERF-NUMBERS.md as source-of-truth — public-facing number stays auditable against measurement evidence"

key-files:
  created:
    - .planning/phases/08-routing-performance/08-05-SUMMARY.md (this file)
  modified:
    - backend/app/routes/routing.py (lines 272-298 — comment header added, no code change)
    - README.md (line 27 — single-paragraph perf addendum in Current Status)

key-decisions:
  - "Inline-comment header placed at function-body indent (4 spaces) immediately above the second `with get_connection() as conn:` block in find_route(). Cites Pitfall A (the 2026-04-29 disaster — commits 2278605 / 17bff0c / 704a70c) and Pitfall G (no btree on temp table source/target). Documents ROUTE_FILTER_BUFFER_DEG env-var override path inline so an operator reading the code finds it without grepping."
  - "README perf paragraph quotes 2.47s cross-LA + 0.385s DTLA exactly as measured in 08-PERF-NUMBERS.md Run 3. No rounding beyond the source-file precision. Cross-links 08-PERF-NUMBERS.md as source-of-truth so any future reader can audit the claim."
  - "Did NOT modify the M1 status paragraph or the Phase 7 negative-result note — those are out of scope per Plan 08-05 task body. The Phase 8 perf claim is added as a sibling paragraph, not a replacement."

patterns-established:
  - "Phase-closure docs plan: surface the perf reality in TWO places future readers look — (1) public-facing README, (2) inline at the call site in the source file. Out-of-tree planning docs are not enough; the call-site comment is what catches a future maintainer mid-edit."
  - "Plans that ship a load-bearing structural pattern (like the temp-table dance for pre-filtering) get an inline header documenting WHY the structure exists, citing the failed alternatives by commit hash. The cost is ~25 lines of comment; the benefit is preventing a regression that would cost a full re-execution cycle."

requirements-completed:
  - PERF-01 (cross-LA < 5s): documentation surface — measured number now in README
  - PERF-02 (DTLA ≤ 2s): documentation surface — measured number now in README
  - PERF-03 (no regression on existing tests): regression verified — 18/18 mocked routing tests pass after changes (test_route.py + test_routing_filter_helpers.py + test_routing_pool_release.py)

# Metrics
duration: 1m 58s
completed: 2026-05-08
---

# Phase 8 Plan 05 Summary — Docs Closure: README perf claim + routing.py inline pitfall citations

**README.md surfaces the post-Phase-8 reality (cross-LA 2.47s, DTLA 0.385s) with a cross-link to 08-PERF-NUMBERS.md; routing.py gains a 27-line inline header above the second `with get_connection() as conn:` block citing RESEARCH §8 Pitfalls A and G so future maintainers won't re-introduce the 2026-04-29 disaster.**

## Performance

- **Duration:** 1m 58s
- **Started:** 2026-05-08T00:31:30Z
- **Completed:** 2026-05-08T00:33:28Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- **routing.py inline contract header (lines 272-298):** Added a 27-line comment block at function-body indent immediately above the second `with get_connection() as conn:` block in `find_route()`. Documents the four-step structural contract (pre-filter via GiST → btree on temp table → fallback chain → 12s statement_timeout safety net), cites RESEARCH §8 Pitfall A by name with the disaster commit hashes (2278605 / 17bff0c / 704a70c), cites Pitfall G by name, and surfaces the `ROUTE_FILTER_BUFFER_DEG` env-var override path inline.
- **README.md Current Status addendum (line 27):** Added a single-paragraph perf claim quoting Run 3's measured medians (cross-LA 2.47s uncached, DTLA 0.385s) with a cross-link to `.planning/phases/08-routing-performance/08-PERF-NUMBERS.md` as source-of-truth. One-line algorithmic summary so a curious reader sees the contract (pgr_dijkstra × K with edge-weight perturbation, linear in K, replacing pgr_ksp's super-linear-in-K Yen's enumeration on dense urban subgraphs).
- **All other README sections preserved:** M1 status paragraph (line 25), Phase 7 negative-result note, Live Demo, Quick Start, How It Works, API Endpoints, Detector Accuracy, Real-Data Ingest, Frontend Pages, Tests, Deploy, Tech Stack, Documentation — all untouched per Plan 08-05 scope.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add inline-comment header to routing.py second `with` block** — `a0b9f9c` (docs)
2. **Task 2: Update README.md with the measured cross-LA latency claim** — `55d3f10` (docs)

**Plan metadata commit:** to be created after this SUMMARY is written, per execute-plan protocol.

## Files Created/Modified

- `backend/app/routes/routing.py` — comment header inserted at lines 272-298 (immediately above the `with get_connection() as conn:` at line 299, which was line 272 pre-edit). No code change; comment-only addition. 27 inserted lines.
- `README.md` — line 27 paragraph added under `## Current Status` heading. 2 inserted lines (one paragraph + one blank line).
- `.planning/phases/08-routing-performance/08-05-SUMMARY.md` — this file.

## Decisions Made

- **Comment placement:** Above the SECOND `with get_connection() as conn:` block (line 299 post-edit), not the first (line 258 — audit-log block). The first block is unrelated to the perf-load-bearing structure; the second is where pre-filter / temp-table / fallback-chain all live. Plan body explicitly named "the second `with` block" so this matched the plan exactly.
- **Comment indent:** 4 spaces (function-body indent), matching the indent of the `with get_connection() as conn:` line itself. Plan body explicitly specified this. Pylint/ast-parse green post-edit.
- **README placement:** "Current Status" section, not "How It Works → Route Selection" (the alternative the plan body listed). Rationale: "Current Status" is what a casual reader scans first and is the natural home for a "what changed recently" perf note; "How It Works → Route Selection" is more about steady-state algorithmic shape and shouldn't be cluttered with phase-specific perf-tune narrative. Both locations were valid per plan; Current Status was higher-leverage for first-time visitors.
- **README number precision:** Quoted 2.47s and 0.385s exactly as measured in 08-PERF-NUMBERS.md Run 3 medians. Did not round to 2.5s or 0.4s — plan body explicitly forbade rounding to fewer than 1 decimal place and forbade inflation. The 0.385s carries 3 decimal places because that's what the source file carries; matching source precision is more honest than artificially adding a trailing zero.

## Deviations from Plan

None - plan executed exactly as written.

The plan's task action blocks were precise (exact comment text, exact placement, exact ROUTE_FILTER_BUFFER_DEG inline mention) and 08-PERF-NUMBERS.md provided unambiguous Run 3 medians. Both tasks landed on the first try; pytest stayed green; all grep-based acceptance criteria passed.

## Issues Encountered

- **Backend container `python` shim missing on host shell.** Initial `pytest` invocation hit `command not found: python`. Resolved per MEMORY.md note about `/tmp/rq-venv` being the host-level Python 3.12 venv for backend ops. Used `/tmp/rq-venv/bin/python -m pytest` for the test runs. No code change required.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

**Phase 8 is complete.** All 5 plans shipped:
- 08-01: PERF-01 / PERF-02 / PERF-03 RED gates installed (mocked + db-gated tests)
- 08-02: SQL constants for pre-filter + buffer config (TDD-style, separate from control-flow change)
- 08-03 v1: REVERTED at commit `9e51769` — pgr_ksp on temp table regressed DTLA 10×
- 08-03 v2: pgr_dijkstra × K with edge-weight perturbation + 3-attempt fallback chain + early_exit_at tuning
- 08-04: Operator-approved live perf validation (Run 3 — both budgets met with 2-5× headroom)
- 08-05: Docs closure (this plan)

**Acceptance criteria met:**
- ✅ README.md contains a routing perf note with measured cross-LA number (2.47s) traceable to 08-PERF-NUMBERS.md
- ✅ README.md preserves all existing content (no deletions; M1 status paragraph + Phase 7 negative-result note both intact)
- ✅ `grep -q "Pitfall A" backend/app/routes/routing.py` passes (line 277)
- ✅ `grep -q "Pitfall G" backend/app/routes/routing.py` passes (line 285)
- ✅ `grep -q "RESEARCH §" backend/app/routes/routing.py` passes (cited inline at Pitfall A and G)
- ✅ Phase 8 routing-performance contract header present
- ✅ ROUTE_FILTER_BUFFER_DEG env-var path documented inline in the comment block
- ✅ 18/18 mocked routing tests pass (test_route.py + test_routing_filter_helpers.py + test_routing_pool_release.py)

**Ready for `/gsd-verify-work` on Phase 8.** No blockers. No outstanding deferred items from this plan.

**Future tuning (deferred, not Phase 8 scope):** If production scale ever exceeds the local seed (~209k segments), revisit `early_exit_at` default + buffer floor. The locked CON-route-selection-algorithm K=5 invariant is preserved bit-for-bit. The inline header in routing.py points future maintainers at RESEARCH §8 first, which is the right entry-point.

---
*Phase: 08-routing-performance*
*Completed: 2026-05-08*

## Self-Check: PASSED

- ✅ FOUND: `.planning/phases/08-routing-performance/08-05-SUMMARY.md`
- ✅ FOUND: `backend/app/routes/routing.py` (modified, lines 272-298 contain the Phase 8 contract header)
- ✅ FOUND: `README.md` (modified, line 27 contains the perf claim)
- ✅ FOUND: commit `a0b9f9c` (Task 1 — routing.py inline header)
- ✅ FOUND: commit `55d3f10` (Task 2 — README perf claim)
- ✅ Verified `grep -q "Pitfall A" backend/app/routes/routing.py` (and Pitfall G; and "2.47s uncached" + "0.385s" in README)
