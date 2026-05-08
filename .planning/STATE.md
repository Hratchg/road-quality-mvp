---
gsd_state_version: 1.0
milestone: v0.4.0
milestone_name: Crash-Aware Routing
status: planning
last_updated: "2026-05-08T02:21:26.848Z"
last_activity: 2026-05-08
progress:
  total_phases: 0
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-23)

**Core value:** Given any two points in LA, show the user a route that is demonstrably smoother than the fastest route, using real road-quality data.
**Current focus:** Phase 08 — routing-performance

## Current Position

Phase: Not started (defining requirements)
Plan: —
Status: Defining requirements
Last activity: 2026-05-08 — Milestone v0.4.0 started

## Performance Metrics

**Velocity:**

- Total plans completed: 20 (M1)
- Average duration: —
- Total execution time: —

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| — | — | — | — |
| 02 | 5 | - | - |
| 03 | 5 | - | - |
| 04 | 5 | - | - |
| 05 | 5 | - | - |

**Recent Trend:**

- Last 5 plans: —
- Trend: —

*Updated after each plan completion*
| Phase 08-routing-performance P01 | 12min | 1 tasks | 1 files |
| Phase 08-routing-performance P02 | 3m 16s | 2 tasks | 2 files |
| Phase 08-routing-performance P03 | 25min | 3 tasks | 3 files |
| Phase 08-routing-performance P05 | 2 min | 2 tasks tasks | 2 files files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- M0 (shipped): Routing via pgRouting `pgr_ksp`, k=5, seed=42, Leaflet default + `VITE_MAPBOX_TOKEN` for Mapbox
- M0 (carryover): Seed radius = 10 km (SPEC); verify the literal in `scripts/seed_data.py` during Phase 1
- M0 (carryover): `road_segments.source`/`target` = BIGINT (SPEC); verify migration literal during Phase 1
- [Phase ?]: Phase 8 RED gate (08-01) installed: backend/tests/test_routing_performance.py asserts PERF-01 < 5s and PERF-02 <= 2s; gated by db_has_topology so CI auto-skips
- [Phase ?]: Two-phase SQL refactor under TDD: Plan 08-02 lands SQL constants + their unit-test contract; Plan 08-03 wires them into find_route(). Reviewer sees SQL shape locked separately from control-flow change.
- [Phase ?]: Env-var module constants tested via importlib.reload + monkeypatch.setenv pattern: read constant -> assert default; setenv + reload -> assert new value; finally-block delenv + reload to restore default for downstream tests.
- [Phase ?]: psycopg2 named-parameter binding (%(o_lon)s style) mandatory for SQL with untrusted lat/lon — never f-string or .format() lat/lon into SQL. Test pins this contract (T-08-02-01 mitigation).
- [Phase ?]: Plan 08-03 (replan): pgr_dijkstra x K with edge-weight perturbation (Yen's-style, linear in K) replaces pgr_ksp K=5 (super-linear, timed out at 12s on dense urban subgraphs). Industry-standard approach used by OSRM and Valhalla. K=5 output contract preserved (CON-route-selection-algorithm).
- [Phase ?]: Plan 08-03: 3-attempt fallback chain catches BOTH psycopg2.errors.QueryCanceled AND empty-result conditions, with conn.rollback() between attempts. The reverted Plan 08-03 only caught empty results -- timeouts bubbled to HTTP 500 (08-PERF-NUMBERS.md Fallback Chain Observation).
- [Phase ?]: Phase 8 docs closure: README perf claim cross-links 08-PERF-NUMBERS.md as source-of-truth; routing.py inline header at lines 272-298 cites RESEARCH §8 Pitfalls A and G to prevent re-introduction of the 2026-04-29 pgr_ksp-on-temp-table disaster.

### Pending Todos

From `.planning/codebase/CONCERNS.md` — these are flagged for M1 phases where they naturally belong:

- Phase 1: Reconcile BIGINT vs INTEGER on source/target columns, Mapbox env var, seed radius literal, psycopg2 pin
- Phase 2: Fix hardcoded YOLO model path (CWD-relative → env-var configurable)
- Phase 4: Replace dev defaults `rq`/`rqpass`/`roadquality` with proper secret management at sign-up/sign-in scope
- Phase 5: Lock down CORS, add DB connection pooling, deepen `/health` to check DB reachability, add retention policy for `route_requests` audit log, externalize `VITE_API_URL`

Tracked in-roadmap — not separately filed under `.planning/todos/`.

### Blockers/Concerns

None blocking Phase 1 start.

Carried forward to later phases (not blockers now, will be addressed in-phase):

- Frontend assumes localhost API URL — blocker for Phase 5, noted.
- No request ID correlation / structured logging — deferred (out of scope for M1).
- No `/segments` pagination — deferred unless demo triggers the issue.
- No DB backup strategy — worth revisiting in Phase 5 if deploy target offers managed backups.

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Observability | Structured logging, Prometheus metrics, request IDs | Deferred to post-M1 | 2026-04-23 (roadmap init) |
| Scale | Redis / distributed cache, `/segments` pagination | Deferred to post-M1 | 2026-04-23 (roadmap init) |
| Infra | Alembic migrations, SQLAlchemy migration | Deferred to post-M1 | 2026-04-23 (roadmap init) |
| Scope | Multi-city support, mobile native apps, OAuth/SSO | Deferred to post-M1 | 2026-04-23 (roadmap init) |

### Acknowledged at v0.3.0 milestone close (2026-05-07)

Items acknowledged and deferred at milestone close — operator-runbook walkthroughs that artifact-level verification covered but live-deploy validation did not. Does not block close; v0.3.0-MILESTONE-AUDIT.md status is `passed`.

| Category | Item | Status |
|----------|------|--------|
| uat | 02-HUMAN-UAT.md | partial — 4 pending operator runbook scenarios (real-data eval numbers) |
| verification | 02-VERIFICATION.md | human_needed — tooling verified; live-data numbers pending operator runbook |
| verification | 03-VERIFICATION.md | human_needed — pipeline verified; live Mapillary smoke + SC #4 ranking-diff demo pending operator runbook |
| verification | 05-VERIFICATION.md | human_needed — 9/9 SCs verified at artifact level; 5 live-deploy items pending in 05-HUMAN-UAT.md |

## Session Continuity

Last session: 2026-05-08T00:35:19.260Z
Stopped at: Phase 7 context gathered
Resume file: None

**Planned Phase:** 7 (LA-Trained Detector) — 8 plans — 2026-04-28T21:59:14.644Z
**Completed Phase:** 1 (MVP Integrity Cleanup) — 4 plans — 2026-04-23
**Phase 5 UAT walkthrough:** 2026-04-27 → 2026-04-28 — 16 defects surfaced + fixed inline (8 commits) — see .planning/phases/05-cloud-deployment/05-HUMAN-UAT.md
