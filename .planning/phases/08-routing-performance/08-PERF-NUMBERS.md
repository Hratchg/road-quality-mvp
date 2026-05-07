# Phase 8 — Measured Performance Numbers

**Measured:** 2026-05-04 (precondition check only — measurement BLOCKED, see Verdict)
**Hardware:** developer laptop, OS macOS Darwin 25.4 (arm64)
**DB:** PostgreSQL 16 + PostGIS 3.4.3 + pgRouting (Docker container `agent-a85c90f3-db-1`, mapped to host port 5432)
**Seed:** **NOT YET RUN** — `python scripts/seed_data.py` (DIST=20000, target ~209k segments) is the prerequisite
**Buffer:** ROUTE_FILTER_BUFFER_DEG = 0.03 (default, from Plan 08-02)

## Status: BLOCKED — DB not seeded

Plan 08-04 Task 1 sub-step 1.1 ("Confirm topology is built") explicitly gates the rest of the
plan: *"DO NOT proceed past sub-step 1.1 without a fully-seeded DB — perf numbers from a partial
seed are misleading (Pitfall F from RESEARCH §8)."* The local DB is reachable but unseeded:
neither the `road_segments` rows nor the `road_segments_vertices_pgr` topology table exists yet,
so the `db_has_topology` fixture in `backend/tests/conftest.py` would auto-skip both perf
regression tests (returning "skipped", not "passed"). That is not a measurement, so no perf
number can honestly be entered into the table below.

Per the plan body and the executor caveats: this surface is escalated to the operator via the
Task 2 checkpoint with the `revise: needs full seed first` recommendation.

## Pre-flight diagnostic state (2026-05-04)

| Check | Command | Observed |
|-------|---------|----------|
| Docker Compose stack up | `docker compose ps` | empty — compose stack not started |
| Postgres container reachable | `docker exec agent-a85c90f3-db-1 psql -U rq -d roadquality -c '\dt'` | OK — 42 relations across `public`, `tiger`, `topology` (postgis + pgrouting + tiger geocoder all installed) |
| `road_segments` row count | `SELECT count(*) FROM road_segments;` | **0** (RESEARCH §3 expectation: ~209,000) |
| `road_segments_vertices_pgr` table | `SELECT count(*) FROM road_segments_vertices_pgr;` | **ERROR: relation does not exist** (topology not built yet) |
| `users` row count | `SELECT count(*) FROM users;` | 0 (Phase 4 auth schema present but unseeded — fine, perf tests use `dependency_overrides[get_current_user_id]`) |
| Backend image cached | `docker images \| grep road-quality-mvp-backend` | `road-quality-mvp-backend:latest` present (326 MB, last built before pytest-timeout was added to requirements.txt) |
| pytest-timeout in cached backend image | `docker run --rm road-quality-mvp-backend:latest python -c 'import pytest_timeout'` | **ModuleNotFoundError: No module named 'pytest_timeout'** — image rebuild needed before perf suite can run with its `@pytest.mark.timeout(15)` markers |

## Latency Table

| Trip | Pre-fix (RESEARCH §1 baseline) | Post-fix (measured) | Budget | Status |
|------|-------------------------------|---------------------|--------|--------|
| 1 km DTLA-local cold | 1.4 s | NOT MEASURED — DB unseeded | ≤ 2.0 s | BLOCKED |
| 5 km cross-neighborhood cold | 1.8 s | NOT MEASURED — DB unseeded | (no formal budget) | BLOCKED |
| 20 km West LA → Pasadena cold | > 90 s (timeout) | NOT MEASURED — DB unseeded | < 5.0 s | BLOCKED |

## Test Results

| Test | Result | Notes |
|------|--------|-------|
| `tests/test_routing_performance.py::test_dtla_under_2s` | NOT RUN (would auto-skip via `db_has_topology` fixture) | PERF-02 budget ≤ 2.0s |
| `tests/test_routing_performance.py::test_cross_la_under_5s` | NOT RUN (would auto-skip via `db_has_topology` fixture) | PERF-01 budget < 5.0s |
| `tests/test_integration.py::test_route_real_points` | NOT RUN (would auto-skip via `db_has_topology` fixture) | PERF-03 — no semantics regression |
| `tests/test_integration.py::test_route_respects_time_budget` | NOT RUN (would auto-skip via `db_has_topology` fixture) | PERF-03 |
| `tests/test_integration.py::test_route_with_weights` | NOT RUN (would auto-skip via `db_has_topology` fixture) | PERF-03 |
| `tests/test_integration.py::test_route_distant_points` | NOT RUN (would auto-skip via `db_has_topology` fixture) | PERF-03 |
| `tests/test_routing_pool_release.py` | NOT RUN | Pool-leak regression (Phase 5 SC #9) |

## Subgraph Size Observation

Run this once during validation to record what the temp table actually holds for each trip type:

```sql
-- Run inside `psql` while a /route request is in flight, OR re-derive via
-- a one-off query against road_segments using the same bbox the request used:
SELECT count(*) FROM road_segments
WHERE geom && ST_MakeEnvelope(
  LEAST(o_lon, d_lon) - 0.03, LEAST(o_lat, d_lat) - 0.03,
  GREATEST(o_lon, d_lon) + 0.03, GREATEST(o_lat, d_lat) + 0.03,
  4326
);
```

| OD pair | bbox-filtered edges | Pre-fix scan | Reduction |
|---------|---------------------|--------------|-----------|
| 1 km DTLA-local | NOT MEASURED | 209k | NOT MEASURED |
| 5 km cross-neighborhood | NOT MEASURED | 209k | NOT MEASURED |
| 20 km cross-LA | NOT MEASURED | 209k | NOT MEASURED |

## Fallback Chain Observation

Did any test trigger the wide-filter or full-graph fallback?

- NOT MEASURED — perf suite did not run because the DB is unseeded. The 3-attempt chain (filter at 0.03° → wide-filter at 0.06° → full-graph) wired in Plan 08-03 (commit `be277bf`) is verified by the mocked unit suite (9 passed, 3 expected-skip in `tests/test_route.py`, `test_routing_filter_helpers.py`, `test_routing_pool_release.py`, `test_routing_performance.py --collect-only`) but has not yet been exercised against real LA geometry.

## Sign-off

- [ ] PERF-01 cross-LA test passes with elapsed < 5.0s on a fully-seeded local DB
- [ ] PERF-02 DTLA test passes with elapsed ≤ 2.0s
- [ ] All 4 existing live-DB route integration tests still pass
- [ ] `test_routing_pool_release.py` still passes — no new leak path
- [ ] Numbers entered above are measured, not projected

**Operator:** PENDING — operator must seed the DB and re-run before sign-off
**Date:** PENDING

## Recovery Path (operator action required)

1. Confirm Docker Compose db service is up — the host already has the `agent-a85c90f3-db-1` container running on port 5432, mapped to the same `postgresql://rq:rqpass@localhost:5432/roadquality` DSN that `scripts/seed_data.py` defaults to. (No `docker compose up db -d` needed; the existing container is the project's DB.)
2. From the host (NOT inside the backend container — see `MEMORY.md` "road-quality-mvp Python runtime"), run the seed via the host venv:
   ```bash
   /tmp/rq-venv/bin/python scripts/seed_data.py
   ```
   Or, if the host venv is missing, recreate it with Python 3.12 and install `scripts/requirements.txt`. Expected runtime: ~5 minutes; expected output: ~209k rows in `road_segments` plus a populated `road_segments_vertices_pgr` after `pgr_createTopology`.
3. Rebuild the backend image so `pytest-timeout` (added in Plan 08-01's requirements.txt edit) lands in the test runner:
   ```bash
   docker compose build backend
   ```
   Or, if the operator prefers to skip the image rebuild, run the perf suite against the host venv directly (the perf tests already gracefully degrade if `@pytest.mark.timeout` is not registered — pytest emits a warning but does not fail). Defensive override: append `--timeout=30` to the pytest command line.
4. Verify the seeded counts:
   ```bash
   docker exec agent-a85c90f3-db-1 psql -U rq -d roadquality -c "SELECT count(*) FROM road_segments;"
   docker exec agent-a85c90f3-db-1 psql -U rq -d roadquality -c "SELECT count(*) FROM road_segments_vertices_pgr;"
   ```
   Expected: ~209,000 segments and ~74,000 vertices per RESEARCH §3.
5. Re-run Plan 08-04 Task 1 — the executor will replay sub-steps 1.1–1.5, fill in this file with measured numbers, and return a fresh checkpoint for sign-off.

## Verdict (interim)

- PERF-01: **BLOCKED** — measurement deferred until DB is seeded.
- PERF-02: **BLOCKED** — measurement deferred until DB is seeded.
- PERF-03 (no regression on existing tests): **BLOCKED** — measurement deferred until DB is seeded.

This file will be overwritten with measured numbers once the operator completes the recovery path above.
