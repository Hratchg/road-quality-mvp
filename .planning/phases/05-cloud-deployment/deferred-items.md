# Phase 05 — Deferred Items (Out-of-Scope Discoveries)

Items found during plan execution that are NOT caused by the current task's
changes. Logged per the executor SCOPE BOUNDARY rule. These belong to other
plans or other phases.

## ✅ RESOLVED 2026-04-28 — All items below were closed during the Phase 5 UAT walkthrough

The 6 test failures listed below were closed by commit `ec0fa67`
("close 19 CI test failures surfaced by UAT #1"), which added a
`db_has_topology` session fixture in `backend/tests/conftest.py` that
auto-skips dependent tests with a clear message when the DB doesn't
have a built routing topology. Local dev with seeded DB still exercises
the tests; CI's lightweight postgres service container cleanly skips.

This file is preserved for historical context (the "scope boundary" log
of what 05-01 punted) but is no longer an open item.

## Pre-existing test failures (DB has no seed data) — RESOLVED

Discovered while running the full `backend/tests/` suite during 05-01 execution
(2026-04-27). Reproduced both WITH and WITHOUT 05-01's changes (verified by
git stash → run → git stash pop). Root cause: the locally-running Docker DB
has the schema migrated but no seed data — `road_segments_vertices_pgr` is
empty (or absent), so every test that POSTs to `/route` against the live DB
fails with `psycopg2.errors.UndefinedTable`.

| Test | File | Error |
|------|------|-------|
| `test_route_with_dep_override_authorizes` | `backend/tests/test_auth_routes.py` | `relation "road_segments_vertices_pgr" does not exist` |
| `test_segments_returns_geojson` | `backend/tests/test_integration.py` | `assert 0 > 0` (no segments returned) |
| `test_route_real_points` | `backend/tests/test_integration.py` | `relation "road_segments_vertices_pgr" does not exist` |
| `test_route_respects_time_budget` | `backend/tests/test_integration.py` | `relation "road_segments_vertices_pgr" does not exist` |
| `test_route_with_weights` | `backend/tests/test_integration.py` | `relation "road_segments_vertices_pgr" does not exist` |
| `test_route_distant_points` | `backend/tests/test_integration.py` | `relation "road_segments_vertices_pgr" does not exist` |

These tests should be marked `@pytest.mark.integration` and gated on a fixture
that seeds the topology, OR a Phase 5 plan / runbook should document the
"run `scripts/seed_data.py` after `docker compose up`" prerequisite for the
integration suite. Phase 05's SC #7 (the `pgr_createTopology` fold-in) is the
correct phase to address this — likely Plan 05-04 territory.

Not in scope for 05-01 — 05-01 only owns SC #6 + SC #9.
