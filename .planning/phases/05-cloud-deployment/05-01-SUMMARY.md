---
phase: 05-cloud-deployment
plan: 01
subsystem: backend/db
tags: [python, psycopg2, pool, tdd, integration, sc6, sc9]
type: tdd
duration_min: 7
completed: 2026-04-27
status: complete
requires:
  - phase 04 auth.py at the post-WR-03 closing()-wrapped state
  - psycopg2-binary >= 2.0 (project pin: 2.9.11; local venv: 2.9.12)
provides:
  - "app.db.get_connection: @contextmanager that borrows from a ThreadedConnectionPool and putconn-on-exit (try/finally) — leak-safe on every exit path"
  - "app.db._get_pool: lazy module-level pool getter (singleton; created on first use, never recreated; tests can reset via close_pool())"
  - "app.db._connection_pool: module-level cache slot (None until _get_pool() runs the first time)"
  - "app.db.close_pool: optional teardown helper (closeall + clear cache)"
  - "app.db.DATABASE_URL: unchanged — env-driven, default rq:rqpass@localhost"
affects:
  - "backend/app/routes/auth.py register/login/login-rehash flows: the contextlib.closing() wrappers were dropped because get_connection() now returns a context manager (closing() expects a .close()-able object)"
  - "backend/app/routes/routing.py and backend/app/routes/segments.py: source unchanged but their `with get_connection() as conn:` blocks are now automatically leak-safe via the wrapper's try/finally putconn"
tech-stack:
  added: []
  patterns:
    - "ThreadedConnectionPool wrapper preserving the @contextmanager API (RESEARCH §3 Pattern 1; minimal-diff migration — every call site keeps its `with get_connection() as conn:` syntax)"
    - "Lazy singleton pool init (defer pool creation until first use so test fixtures that override DATABASE_URL run BEFORE the pool opens its first socket)"
    - "try/finally putconn — the same shape that fixed Phase 3 plan 03's WR-04 and Phase 4 plan 03's WR-03, generalized one layer up so the call sites need no edit"
key-files:
  created:
    - "backend/tests/test_db_pool.py: 4 unit tests (95 LOC) — getconn/putconn lifecycle on success path, on exception path, lazy init invariant, RealDictCursor cursor_factory passthrough"
    - "backend/tests/test_routing_pool_release.py: 1 integration test (97 LOC) — injects invalid SQL into routing.py's SNAP_NODE_SQL constant, asserts pool._used returns to baseline after the failed POST /route (SC #9 regression gate)"
    - ".planning/phases/05-cloud-deployment/deferred-items.md: 6 pre-existing test failures (unseeded DB) logged for Plan 05-04 territory"
  modified:
    - "backend/app/db.py: full rewrite — 11 LOC single-connection factory replaced with 102 LOC ThreadedConnectionPool wrapper (cursor_factory=RealDictCursor preserved)"
    - "backend/app/routes/auth.py: 4 line-level changes — drop `from contextlib import closing` import; unwrap 3x `closing(get_connection())` to `get_connection()` at lines 63 (register), 92 (login), 118 (login rehash)"
decisions:
  - "ThreadedConnectionPool, not the single-thread variant — psycopg2 documents the single-thread class as not shareable across threads; FastAPI's anyio threadpool (40 workers default) calls getconn from multiple threads concurrently. Corrects CONTEXT D-07's incorrect default per RESEARCH Correction A."
  - "Pool sizing minconn=2 / maxconn=12 — bumped from CONTEXT D-07's maxconn=10 for headroom against the 40-thread anyio pool while staying well under PG's default max_connections=100 (RESEARCH Pattern 1)."
  - "Pool wrapper IS the SC #9 leak fix — routing.py source is intentionally NOT edited because the @contextmanager's try/finally putconn runs on every exit including exceptions. CONTEXT line 174's 'wrap routing.py in contextlib.closing' suggestion was correct only for the pre-pool world (RESEARCH Pattern 4 + Correction D)."
  - "Lazy _get_pool() initializer instead of eager module-import — tests may set DATABASE_URL via fixture before the pool opens its first socket. Eager init at module scope would race the fixture."
  - "auth.py drops closing() — the new get_connection() returns a context manager, not a connection. Calling .close() on a context manager would raise TypeError (RESEARCH Correction E)."
metrics:
  tasks_completed: 3
  tasks_total: 3
  commits: 4
  duration_sec: 439
  duration_min: 7
  files_created: 3
  files_modified: 2
  loc_added: 336
  loc_removed: 12
  tests_added: 5
  tests_added_unit: 4
  tests_added_integration: 1
  test_regressions: 0
---

# Phase 05 Plan 01: ThreadedConnectionPool Migration Summary

**One-liner:** Replaced `backend/app/db.py`'s per-request `psycopg2.connect()` factory with a thread-safe `ThreadedConnectionPool` wrapped in a `@contextmanager` — single rewrite that simultaneously satisfies SC #6 (connections pooled) AND SC #9 (`/route` releases connection on exception path) per RESEARCH Pattern 4.

## What landed

### Core: db.py rewrite (Task 2)

`backend/app/db.py` went from 11 LOC (single-connection factory) to 102 LOC (pool wrapper):

```
Public API (preserved + extended):
  DATABASE_URL                          # unchanged, env-driven
  get_connection() -> @contextmanager   # SAME API SURFACE — every existing
                                        # `with get_connection() as conn:`
                                        # call site keeps working unchanged
Private helpers (new):
  _connection_pool: ThreadedConnectionPool | None   # cache slot
  _get_pool() -> ThreadedConnectionPool             # lazy singleton init
  close_pool() -> None                              # test/shutdown teardown
```

Pool config: `ThreadedConnectionPool(minconn=2, maxconn=12, dsn=DATABASE_URL, cursor_factory=RealDictCursor)`. The `@contextmanager` shape: `try: yield conn finally: pool.putconn(conn)` — the try/finally is the SC #9 fix; it runs on every exit path.

### Surgical edits to auth.py (Task 3)

4 line-level changes:

| Line (was) | Old | New |
|-----------|-----|-----|
| 10 | `from contextlib import closing` | (deleted) |
| 63 | `with closing(get_connection()) as conn, conn:` | `with get_connection() as conn, conn:` |
| 92 | `with closing(get_connection()) as conn, conn:` | `with get_connection() as conn, conn:` |
| 118 | `with closing(get_connection()) as conn, conn:` | `with get_connection() as conn, conn:` |

Why drop `closing()`: the new `get_connection()` returns a context manager (not a connection); calling `.close()` on a context manager is a `TypeError`. The pool wrapper's `try/finally putconn` replaces what `closing()` previously handled.

### Tests (Task 1 RED, validated GREEN by Tasks 2-3)

**`backend/tests/test_db_pool.py` — 4 unit tests (no DB, sub-millisecond):**

- `test_get_connection_calls_putconn_on_success`: pool.getconn on enter, pool.putconn on exit
- `test_get_connection_calls_putconn_on_exception`: SC #9 invariant at unit level — slot releases even when caller raises
- `test_get_connection_lazy_pool_init`: _get_pool() singleton — constructor runs once across N calls
- `test_pool_uses_real_dict_cursor`: kwargs forwarded include `cursor_factory=RealDictCursor` + `minconn=2` + `maxconn=12`

**`backend/tests/test_routing_pool_release.py` — 1 integration test (DB-required; @pytest.mark.integration):**

- `test_route_handler_releases_pool_slot_on_exception`: monkeypatches `routing.SNAP_NODE_SQL` to invalid SQL, POSTs to `/route`, asserts the response is 5xx AND `pool._used` returned to baseline. This IS the SC #9 regression gate at integration level.

## What was NOT touched (intentionally — anti-churn)

| File | Reason |
|------|--------|
| `backend/app/routes/routing.py` | Pool wrapper makes existing `with get_connection() as conn:` automatically leak-safe. Editing here would be unnecessary churn (RESEARCH Pattern 4). Source identical to base. |
| `backend/app/routes/segments.py` | Same as routing — pool wrapper is the leak fix. Source identical to base. |
| `backend/requirements.txt` | psycopg2-binary 2.9.11 already supports ThreadedConnectionPool (class exists since psycopg2 2.0). Bumping version is unrelated scope. |
| `backend/tests/conftest.py` | `db_conn` fixture continues to open its own connection bypassing the pool — this is correct for tests that exercise the DB outside the FastAPI request flow. |
| `.planning/STATE.md`, `.planning/ROADMAP.md` | Per parallel-execution constraint — orchestrator owns these. |

## Pool sizing rationale

`minconn=2, maxconn=12`:
- **minconn=2**: warm slots for `/health`, demo traffic, and the test fixture's session-scoped `db_conn`.
- **maxconn=12**: bounded against FastAPI's anyio threadpool (40 workers) AND PG's default `max_connections=100` — leaves headroom for psql sessions, the seed script, and in-machine tooling. Burst above 12 will block on getconn — this IS the intended graceful backpressure (not a 500). RESEARCH §3 Pattern 1 bumped from CONTEXT D-07's maxconn=10 for safety margin.

## SC contribution map

| Success Criterion | Owner Plan | This plan's contribution |
|-------------------|-----------|--------------------------|
| SC #6 (connections pooled) | **05-01 (this plan)** | ThreadedConnectionPool with minconn=2/maxconn=12 in db.py |
| SC #9 (routing.py releases connection on exception) | **05-01 (this plan)** | Pool wrapper's `try/finally putconn` — the wrapper IS the leak fix at every call site (RESEARCH Pattern 4) |
| SC #2 (CORS restricted) | 05-02 | n/a |
| SC #5 (/health DB reachability) | 05-02 | n/a |
| SC #1 (deploy artifacts) | 05-03 / 05-04 | n/a |
| SC #7 (pgr_createTopology in seed) | 05-04 | n/a |
| SC #3, #7, #8 (CI gates) | 05-05 | n/a |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] db.py docstring tripped the plan's verify gate**

- **Found during:** Task 2 verification.
- **Issue:** The plan's verify command included `! grep -q "SimpleConnectionPool" backend/app/db.py` (success_criteria line: "Correction A guard"). The plan's verbatim §3 Pattern 1 docstring explained the rationale by writing the word "SimpleConnectionPool" 4 times in the module header. This made the grep gate fail.
- **Fix:** Rephrased the docstring to convey the same rationale without using the literal class name — "the single-thread variant" instead. The technical content (psycopg2 source documentation, anyio 40-thread context, threading.Lock difference) is preserved verbatim.
- **Files modified:** `backend/app/db.py` (docstring lines 10-19)
- **Commit:** Folded into `789ec07` (Task 2 GREEN commit)

**2. [Rule 1 - Bug] test_routing_pool_release.py: Starlette TestClient default re-raises**

- **Found during:** Task 3 verification (running the integration test against the live DB).
- **Issue:** The test as written in Task 1 (per the plan's verbatim block) calls `authed_client.post("/route", json=body)` and then asserts `response.status_code >= 500`. But Starlette's `TestClient` defaults to `raise_server_exceptions=True` — when the route handler raises, the exception is re-raised in the test rather than converted to a 500 response. The status_code assertion never ran; the test failed with the raw `psycopg2.errors.UndefinedTable` exception.
- **Fix:** Switch the test from the session-scoped `authed_client` fixture to a per-test setup that constructs `TestClient(app, raise_server_exceptions=False)` and applies `app.dependency_overrides[get_current_user_id] = lambda: 42` in a try/finally. This preserves the assertion shape the plan intended.
- **Files modified:** `backend/tests/test_routing_pool_release.py`
- **Commit:** `1c3a93d`

**3. [Rule 1 - Bug] test_routing_pool_release.py: in-memory route_cache bypasses the SQL injection**

- **Found during:** Task 3 full-suite run.
- **Issue:** `routing.py` checks `app.cache.route_cache` (a TTLCache, in-memory module-level) BEFORE running `SNAP_NODE_SQL`. `tests/test_route.py` populates the cache with a request body that overlaps ours; when our test runs after test_route.py, the cached 200 response is served and our injected invalid SQL never executes. The test passes in isolation but fails in the full suite under that ordering.
- **Fix:** Call `route_cache.clear()` at the start of the test. Pre-existing in-memory caches with no fixture-level isolation are a broader hygiene issue, but a one-line clear is the minimal, scope-appropriate fix here.
- **Files modified:** `backend/tests/test_routing_pool_release.py`
- **Commit:** `1c3a93d` (combined with fix #2)

### Out-of-Scope Discoveries (logged, not fixed)

6 pre-existing test failures discovered during the full-suite run — all caused by the local Docker DB having no seed data (`road_segments_vertices_pgr` doesn't exist or is empty). Verified pre-existing via `git stash → run → git stash pop`. Logged to `.planning/phases/05-cloud-deployment/deferred-items.md` for Plan 05-04 (the SC #7 `pgr_createTopology` plan) to address.

## Verification (executed, all green)

```bash
# Per-task verify commands (all PASS):
! grep -q "SimpleConnectionPool" backend/app/db.py                                  # OK
grep -c "ThreadedConnectionPool" backend/app/db.py                                   # 4 (header + type ann + ctor + return type)
grep -q "minconn=2" backend/app/db.py && grep -q "maxconn=12" backend/app/db.py     # OK
grep -q "cursor_factory=RealDictCursor" backend/app/db.py                            # OK
grep -q "@contextmanager" backend/app/db.py                                          # OK
grep -q "p.putconn(conn)" backend/app/db.py                                          # OK

! grep -q "from contextlib import closing" backend/app/routes/auth.py               # OK
! grep -q "closing(get_connection())" backend/app/routes/auth.py                    # OK
[ $(grep -c "with get_connection() as conn, conn:" backend/app/routes/auth.py) -eq 3 ]  # OK

# routing.py + segments.py untouched vs. base ffd8603:
git diff ffd8603 -- backend/app/routes/routing.py backend/app/routes/segments.py     # empty

# Full pytest results (DB up):
pytest backend/tests/test_db_pool.py                                                  # 4 passed
pytest backend/tests/test_routing_pool_release.py                                     # 1 passed
pytest backend/tests/test_auth_routes.py                                              # 17 passed, 1 fail (pre-existing, deferred)
pytest backend/tests/                                                                 # 227 passed, 6 pre-existing fail (deferred), 11 skipped
```

Net new tests: +5 (4 unit + 1 integration). Net regressions caused by this plan: 0.

## Anti-pattern guard for future maintainers

If a future refactor hits the temptation to switch from `ThreadedConnectionPool` to its single-thread sibling (smaller LOC, slightly faster getconn under no contention) — **do not.** psycopg2 documents the single-thread variant as not shareable across threads. FastAPI's anyio threadpool (40 workers default) calls getconn from multiple threads concurrently. The single-thread pool's `_pool` list and `_used` dict are mutated without a lock — race conditions, deadlocks, and double-handed connections will result. The plan's verify gate explicitly bans the single-thread class name from db.py via grep; CI will fail on a regression.

This is RESEARCH Correction A, locked. The CONTEXT D-07 default that suggested the single-thread variant was incorrect — Correction A overrides it.

## Self-Check: PASSED

Files created (verified existence):
- backend/tests/test_db_pool.py — FOUND
- backend/tests/test_routing_pool_release.py — FOUND
- .planning/phases/05-cloud-deployment/deferred-items.md — FOUND

Commits (verified in `git log --oneline`):
- 0725666 (test 05-01: failing tests RED) — FOUND
- 789ec07 (feat 05-01: db.py pool wrapper) — FOUND
- 303b00c (refactor 05-01: drop closing wrappers) — FOUND
- 1c3a93d (fix 05-01: test robustness + deferred-items log) — FOUND

Files NOT modified (verified zero diff vs. ffd8603):
- backend/app/routes/routing.py — UNCHANGED
- backend/app/routes/segments.py — UNCHANGED
- backend/requirements.txt — UNCHANGED
- backend/tests/conftest.py — UNCHANGED

## TDD Gate Compliance

- RED gate: `0725666 test(05-01): add failing tests for ThreadedConnectionPool wrapper + SC #9 regression gate` — confirmed failing tests landed before any implementation.
- GREEN gate: `789ec07 feat(05-01): rewrite db.py as ThreadedConnectionPool wrapper (SC #6 + SC #9 fix)` — implementation made the 4 unit tests pass.
- REFACTOR / FOLLOW-ON: `303b00c refactor(05-01): drop redundant closing() wrappers in auth.py` — Task 3 (call-site adjustment).
- BUG-FIX (deviations): `1c3a93d fix(05-01): make SC #9 regression test robust...` — three Rule 1 deviations folded into one commit.
