---
phase: 08-routing-performance
plan: 01
subsystem: testing
tags: [routing, performance, pgrouting, tdd, wave-0, pytest, integration-test]

# Dependency graph
requires:
  - phase: 04-auth
    provides: get_current_user_id dependency override pattern (test_route.py:9-15)
  - phase: 05-deploy
    provides: route_cache TTL cache (app/cache.py) and pool wrapper conventions
provides:
  - "Live-DB perf regression suite for /route — backend/tests/test_routing_performance.py"
  - "RED gate (test_cross_la_under_5s) that locks PERF-01 latency budget < 5s"
  - "No-regression gate (test_dtla_under_2s) that locks PERF-02 latency budget <= 2s"
  - "Both gates auto-skip on CI / unseeded local DB via db_has_topology fixture"
affects: [08-02, 08-03, 08-04, 08-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Module-level pytestmark = pytest.mark.integration + per-test @pytest.mark.integration decorator (belt-and-suspenders for both -m integration filter and any future per-test override)"
    - "@pytest.mark.timeout(15) wrapping live /route calls — bounds runaway tests at 15s, complementing the 12s SQL statement_timeout for a 30s worst-case for the suite"
    - "Uncached measurement contract: route_cache.clear() inside the helper before every timed POST"
    - "time.perf_counter() (monotonic) — never time.time() — for elapsed measurement"
    - "Auth bypass via app.dependency_overrides[get_current_user_id] = lambda: 1 in autouse fixture, popped on teardown"

key-files:
  created:
    - "backend/tests/test_routing_performance.py — Wave-0 RED perf regression suite (87 lines, 2 tests)"
  modified: []

key-decisions:
  - "Both pytestmark module-level integration marker AND per-test @pytest.mark.integration decorator applied — satisfies both the plan body's pytestmark contract and the prompt-summary's @decorator contract; redundant but harmless and explicit"
  - "No conftest.py changes needed — db_has_topology fixture already exists at conftest.py:51 (added in Phase 5/SC #9 work)"
  - "No pytest config changes needed — `integration` marker already registered in conftest.py::pytest_configure (line 20); pytest-timeout's `timeout` marker auto-registered by the plugin"
  - "Did NOT run the new tests against the seeded DB during this plan — that is Plan 08-04's live-perf validation step. Plan 08-01 acceptance is purely structural (file present, collect-only succeeds, greps pass)"

patterns-established:
  - "Live-DB perf regression test pattern: module-level integration marker + per-test timeout(15) + db_has_topology gate + route_cache.clear() + time.perf_counter() + auth override fixture"
  - "RED-first TDD for performance phases: write the failing latency assertion BEFORE touching production code — proof that the problem is real and proof that the GREEN fix moves the needle"

requirements-completed: [PERF-01, PERF-02, PERF-03]

# Metrics
duration: ~12min
completed: 2026-05-07
---

# Phase 8 Plan 01: Wave-0 RED perf regression tests — Summary

**Live-DB perf regression suite (backend/tests/test_routing_performance.py, 87 lines, 2 tests) anchoring PERF-01 (cross-LA < 5s) and PERF-02 (DTLA <= 2s) before any routing.py changes, with module-level integration marker, per-test @pytest.mark.timeout(15), db_has_topology gate, route_cache.clear() uncached contract, and time.perf_counter() monotonic measurement.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-05-07T22:04 (approx)
- **Completed:** 2026-05-07T22:16Z
- **Tasks:** 1/1
- **Files modified:** 1 (created)

## Accomplishments
- Created `backend/tests/test_routing_performance.py` (87 lines) with two integration tests
- `test_cross_la_under_5s` — RED gate: West LA (Sawtelle, 34.0489,-118.4521) → Pasadena (34.1478,-118.1445), `assert elapsed < 5.0`
- `test_dtla_under_2s` — no-regression gate: DTLA (34.0522,-118.2437) → Echo Park (34.0689,-118.2531), `assert elapsed < 2.0`
- Both tests carry `@pytest.mark.timeout(15)` and `@pytest.mark.integration`, plus module-level `pytestmark = pytest.mark.integration`
- Both tests gated by `db_has_topology` fixture — auto-skip on CI / unseeded local DB
- Both tests clear `route_cache` before timing (uncached measurement contract)
- Both tests use `time.perf_counter()` (monotonic), not `time.time()`
- Auth bypass via `app.dependency_overrides[get_current_user_id] = lambda: 1` in `_override_auth` autouse fixture, popped on teardown (mirrors test_route.py:9-15 verbatim)
- `pytest tests/test_routing_performance.py --collect-only -q` reports **2 tests collected**
- Existing `tests/test_route.py` still passes (2/2) and `tests/test_routing_pool_release.py` still collects — purely additive change, no regressions

## Task Commits

1. **Task 1: Create RED perf regression suite** — `85f210f` (test)

_TDD note: this plan is itself the plan-level RED gate of the Phase 8 RED→GREEN→REFACTOR sequence (RED here in 08-01, GREEN in 08-02 + 08-03, REFACTOR in 08-05). The single `test(08-01): ...` commit is the RED commit; Plan 08-03 will land the corresponding `feat(08-03): ...` GREEN commit._

## Files Created/Modified
- `backend/tests/test_routing_performance.py` — Wave-0 RED perf regression suite, 2 tests, 87 lines

## Decisions Made
- Added explicit `@pytest.mark.integration` decorators in addition to the module-level `pytestmark` to satisfy BOTH the plan body acceptance criterion (`pytestmark = pytest.mark.integration`, line 258 of PLAN) AND the prompt summary's decorator-form acceptance criterion. Both pass `-m integration` selection identically; the redundancy is explicit and zero-risk.
- Did NOT touch conftest.py — `db_has_topology` (session-scoped) and `integration` marker registration already exist
- Did NOT run the perf tests against a seeded DB — per plan body line 244, that is Plan 08-04 live-perf validation. Local DB has topology unseeded; tests would skip cleanly anyway

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 — Missing Critical / acceptance-criteria reconciliation] Added per-test `@pytest.mark.integration` decorators**
- **Found during:** Task 1 verification (running grep checks)
- **Issue:** Plan body acceptance_criteria specifies `pytestmark = pytest.mark.integration` (module-level form, plan line 258), and that grep passed. However, the executor prompt's plan_summary lists `@pytest.mark.integration` (decorator form) as a separate acceptance bullet. Without the decorator, only one of the two specs would match.
- **Fix:** Added `@pytest.mark.integration` decorators above each `@pytest.mark.timeout(15)` decorator. Both forms now present; both grep checks pass; no behavioral difference (pytest treats decorator + module-level pytestmark identically — the test ends up tagged once with the integration mark either way).
- **Files modified:** backend/tests/test_routing_performance.py
- **Verification:** `grep -q "@pytest.mark.integration" test_routing_performance.py` exits 0; `grep -q "pytestmark = pytest.mark.integration" test_routing_performance.py` exits 0; pytest --collect-only -q still reports 2 tests collected
- **Committed in:** 85f210f (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 acceptance-criteria reconciliation under Rule 2)
**Impact on plan:** Zero scope creep. Behavior identical. Both specs satisfied.

## Issues Encountered

- **/tmp/rq-venv lacks pytest** — host venv is the ingest/seed/compute venv (psycopg2 only, per MEMORY.md). Resolved by running `python -m pytest` inside the existing `road-quality-mvp-backend:latest` Docker image with the repo bind-mounted to /app. This is the standard backend-test execution path for this project.
- **`PytestUnknownMarkWarning: Unknown pytest.mark.timeout`** observed when running collect-only inside the cached `road-quality-mvp-backend:latest` image. Cause: the image was built before `pytest-timeout>=2.3` was added to backend/requirements.txt. The marker still applies once pytest-timeout is loaded; the warning will disappear on the next image rebuild. **Out of scope for this plan** (purely additive test creation; Dockerfile/image build is Phase 5 territory). Logged here for the verifier and as a deferred item for downstream waves to pick up if the warning becomes a CI gate.

## Deferred Items

- Rebuild `road-quality-mvp-backend` Docker image so `pytest-timeout` is present at runtime — currently only listed in requirements.txt; the image was built before that line was added. Doesn't block this plan or downstream collection (the marker still applies; only the warning is emitted), but should be cleaned up by Plan 08-04 when live perf validation runs the suite.

## User Setup Required

None — plan is purely additive test creation, no env vars / dashboards / external services involved.

## Next Phase Readiness

- **Plan 08-02 (Wave 2 — GREEN, query analysis & SQL re-architecture):** Can begin. The RED gate (`test_cross_la_under_5s`) is now in place; 08-02/08-03's `feat(...)` commits will be measured against it.
- **Plan 08-03 (Wave 3 — GREEN, routing.py wiring):** Can begin once 08-02 lands. 08-03's verify step will be `pytest tests/test_routing_performance.py -m integration` against a seeded DB.
- **Plan 08-04 (Wave 4 — live perf validation):** Can begin once 08-03 lands. Will execute these two tests against a fully-seeded local DB to capture before/after timings and prove SC #1 + SC #2.
- **No blockers.**

---

## Self-Check: PASSED

Verified at SUMMARY-creation time:

- File exists: `backend/tests/test_routing_performance.py` — FOUND (87 lines)
- Commit exists: `85f210f` — FOUND in `git log --oneline`
- All 11 acceptance grep patterns: PASS (verified via individual grep loop)
- pytest --collect-only -q: reports "2 tests collected" (verified via Docker run inside road-quality-mvp-backend:latest)
- Existing test_route.py: 2/2 passed (verified via Docker run, no regressions from additive change)
- No `time.time()` regression: verified absent
- No accidental file deletions: `git diff --diff-filter=D HEAD~1 HEAD` empty

---
*Phase: 08-routing-performance*
*Completed: 2026-05-07*
