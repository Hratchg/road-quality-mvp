---
gsd_state_version: 1.0
milestone: v0.4.0
milestone_name: Crash-Aware Routing
status: phase_complete
stopped_at: Phase 9 verified complete
last_updated: "2026-05-08T06:30:00.000Z"
last_activity: 2026-05-08 -- Phase 9 verified (5/5 must-haves, 31/31 tests pass)
progress:
  total_phases: 4
  completed_phases: 1
  total_plans: 4
  completed_plans: 4
  percent: 25
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-08)

**Core value:** Given any two points in LA, show the user a route that is demonstrably smoother than the fastest route, using real road-quality data.
**Current focus:** Phase 9 — Crash-Data Schema + LA City Ingest + Naive Snap-Match

## Current Position

Phase: 9 (Crash-Data Schema + LA City Ingest + Naive Snap-Match) — COMPLETE
Plan: 4 of 4 complete
Status: Phase 9 verified — passed (5/5 must-haves, 31/31 phase 9 tests pass on live PostGIS)
Last activity: 2026-05-08 -- Phase 9 execution + verification complete; ready for Phase 10
Next phase: 10 (Crash-Aware Scoring + Locked Weights)

## Performance Metrics

**Velocity:**

- Total plans completed (M0+M1): 41 (M1) + M0 baseline
- Average plan duration (M1): see milestones/v0.3.0-ROADMAP.md
- Total execution time (M1): 16 days (2026-04-22 → 2026-05-07)

**By Phase (M1 historical):**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1 | 4 | — | — |
| 2 | 5 | — | — |
| 3 | 5 | — | — |
| 4 | 5 | — | — |
| 5 | 5 | — | — |
| 6 | 4 | — | — |
| 7 | 7 | — | — |
| 8 | 5 | — | — |

**Recent Trend:**

- Last 5 plans (M1 Phase 8): see archive
- Phase 8 plan velocity: P01=12min, P02=3m16s, P03=25min, P05=2min

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.

**Carried forward from M1 v0.3.0 (load-bearing for v0.4.0):**

- Long DDL on Fly DB MUST run via `flyctl ssh console -C "psql ..."`, NEVER `flyctl proxy` — wireguard timeouts trigger Postgres recovery crash loops (Phase 5 LESSONS-LEARNED). Locked anti-pattern.
- Fully-seeded LA dataset needs ≥2 GB DB memory + ≥3 GB volume; Migration 004 must verify free volume space pre-apply.
- pgr_dijkstra × K with edge-weight perturbation (Yen's-style, linear in K) replaced pgr_ksp K=5; routing.py:272-298 has inline anti-pattern pin citing RESEARCH §8 Pitfalls A and G. Phase 10 must NOT inline crash-aggregation SQL into routing.py — pre-bake in compute_scores.py only.
- 3-attempt fallback chain (filter → wide → full) catches BOTH `psycopg2.errors.QueryCanceled` AND empty-result conditions. Preserved unchanged through v0.4.0.
- Auth removed in commit `d0ef452` for public demo; backend modules dormant; re-enable via `AUTH_ENABLED=true` env var. Out of scope for v0.4.0.
- REQ-ID hygiene at supersede commits: any commit with "remove" / "supersede" / "drop" must update REQUIREMENTS.md + PROJECT.md in the same diff (v0.3.0 ce190d2 fix pattern). Audit gate at milestone close.

**v0.4.0-specific decisions (locked at scoping, recorded in REQUIREMENTS.md):**

- Option B end-to-end thin slice scope: LA City Socrata only (no SWITRS/TIMS), naive single-nearest-segment snap (no fractional intersection attribution), flat 5-year window (no exponential decay), no equity audit, no synthetic crash seed. SWITRS, fractional snap, decay, EQUITY_NOTE.md deferred to v0.4.1.
- Locked outer weights `W_IRI=0.40, W_POT=0.35, W_CRASH=0.25` as module constants in `backend/app/scoring.py`; user-tunable sliders removed from frontend; `/route` Pydantic model uses `extra='ignore'` for backwards-compat (silent ignore of `weight_iri` / `weight_potholes`).
- Severity weights `fatal:injury:pdo = 8:3:1` (literature-converged routing-cost ratio, NOT academic 100:10:1 which saturates `crash_norm`); per-segment raw sum / `GREATEST(length_km, 0.05)`; p95 cap; clipped to [0, 1].
- Crash storage: NEW table `crash_records` (NOT extend `segment_defects`); NEW additive column `segment_scores.crash_norm DEFAULT 0`. Migration 004 follows 002 idempotency precedent.
- Snap-match reuses `snap_match_image()` SQL primitive from `ingest_mapillary.py:255` with wider tolerance (default ~50m via `LACITY_SNAP_M`, env-tunable) — naive single-nearest-segment is acceptable for v0.4.0 with documented disclaimer about intersection attribution.
- Frontend anti-features locked OUT: no crash heatmap, no per-segment crash markers, no separate map layer, no severity-tier toggle, no "safer route" copy (use "lower historical crash density" / "crash-aware").

### Pending Todos

Mapped to v0.4.0 phases:

- Phase 9: Reuse `(source, source_record_id)` UNIQUE pattern from migration 002; `lacity_mocodes.py` Wave-0 RED test for unknown-code branch (v0.3.0 KEY LESSON 2 — silent code-set drift)
- Phase 10: `normalize_weights()` becomes dead code; mark `# DEPRECATED v0.4.0` rather than delete (test compatibility); fatal-overweighting smoke test against 5 known-safe arterials before declaring scoring done
- Phase 11: Disclaimer text is EXACT-string locked in REQUIREMENTS.md; do NOT paraphrase; verify no new map layer/toggle slips in (Pitfall 10 build-then-supersede risk)
- Phase 12: `df -h` Fly volume rehearsal BEFORE migration apply; `flyctl ssh console -C` for DDL (locked); document `ROUTE_FILTER_BUFFER_DEG` + `ROUTE_FILTER_WIDEN_FACTOR` in `.env.example` + README (carryforward from v0.3.0 Phase 8 tech debt)

### Blockers/Concerns

None blocking Phase 9 start.

Carried-forward from v0.3.0 close (not blockers; will be addressed in-phase or remain known limitations):

- 5 Mapillary integration tests hang on `subprocess.run` selectors.poll — pre-existing; do NOT fix in v0.4.0 unless Phase 9 ingest tests trip the same pattern
- README:312 stale prose (seed-on-demand description) — out of scope for v0.4.0
- Untracked: `data/eval_la/labels/test.cache` + `.planning/phases/03-mapillary-ingestion-pipeline/.Rhistory` — gitignore housekeeping; out of scope
- 4 deferred operator-runbook walkthroughs (02-HUMAN-UAT, 02/03/05-VERIFICATION) — known carry-forward; out of scope for v0.4.0

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Observability | Structured logging, Prometheus metrics, request IDs | Deferred to post-v0.4.0 | 2026-04-23 (roadmap init) |
| Scale | Redis / distributed cache, `/segments` pagination | Deferred to post-v0.4.0 | 2026-04-23 (roadmap init) |
| Infra | Alembic migrations, SQLAlchemy migration | Deferred to post-v0.4.0 | 2026-04-23 (roadmap init) |
| Scope | Multi-city support, mobile native apps, OAuth/SSO | Deferred to post-v0.4.0 | 2026-04-23 (roadmap init) |
| Crash data | SWITRS/TIMS source | Deferred to v0.4.1 | 2026-05-08 (Option B scoping) |
| Crash data | Fractional intersection snap-match | Deferred to v0.4.1 | 2026-05-08 (Option B scoping) |
| Crash data | Exponential recency decay (TAU=3y) | Deferred to v0.4.1 | 2026-05-08 (Option B scoping) |
| Crash data | EQUITY_NOTE.md cross-neighborhood audit | Deferred to v0.4.1 | 2026-05-08 (Option B scoping) |
| Crash data | Synthetic crash seed mode | Deferred (operator declined) | 2026-05-08 (Option B scoping) |
| Crash data | `record_status` provisional/final tracking | Deferred to v0.4.1 (only relevant with SWITRS) | 2026-05-08 |

### Acknowledged at v0.3.0 milestone close (2026-05-07)

Items acknowledged and deferred at milestone close — operator-runbook walkthroughs that artifact-level verification covered but live-deploy validation did not. Did not block close; v0.3.0-MILESTONE-AUDIT.md status is `passed`.

| Category | Item | Status |
|----------|------|--------|
| uat | 02-HUMAN-UAT.md | partial — 4 pending operator runbook scenarios (real-data eval numbers) |
| verification | 02-VERIFICATION.md | human_needed — tooling verified; live-data numbers pending operator runbook |
| verification | 03-VERIFICATION.md | human_needed — pipeline verified; live Mapillary smoke + SC #4 ranking-diff demo pending operator runbook |
| verification | 05-VERIFICATION.md | human_needed — 9/9 SCs verified at artifact level; 5 live-deploy items pending in 05-HUMAN-UAT.md |

## Session Continuity

Last session: 2026-05-08T04:23:29.316Z
Stopped at: Phase 9 context gathered
Resume file: .planning/phases/09-crash-data-schema-la-city-ingest-naive-snap-match/09-CONTEXT.md

**Planned Phase:** 9 (Crash-Data Schema + LA City Ingest + Naive Snap-Match) — plans TBD — 2026-05-08
**Completed Phase (most recent):** 8 (Routing Performance) — 5/5 plans — 2026-05-07
**Next action:** `/gsd-plan-phase 9` to decompose Phase 9 into executable plans
