---
phase: 03-mapillary-ingestion-pipeline
reviewed: 2026-04-25T00:00:00Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - scripts/ingest_mapillary.py
  - scripts/compute_scores.py
  - db/migrations/002_mapillary_provenance.sql
  - backend/tests/test_ingest_mapillary.py
  - backend/tests/test_integration.py
  - backend/tests/test_migration_002.py
  - backend/tests/test_compute_scores_source.py
  - docker-compose.yml
findings:
  critical: 0
  warning: 4
  info: 8
  total: 12
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-04-25
**Depth:** standard
**Files Reviewed:** 8
**Status:** issues_found

## Summary

Phase 3 ships a Mapillary -> YOLO -> `segment_defects` ingestion pipeline with
strong defensive posture: psycopg2.sql composition + a forbidden-token regex on
`--where`, a hard-coded literal WHERE for `--wipe-synthetic`, `sys.executable`
for the recompute subprocess (no `shell=True`, no `$PATH` resolution), and a
NULL-distinct UNIQUE index that lets pre-existing synthetic rows coexist while
deduping new mapillary rows on `(segment_id, source_mapillary_id, severity)`.
The MAPILLARY token is read once at module top, never logged, and never
serialized into manifests, summaries, or error messages.

The bulk of the review is positive: parameterization, idempotency invariants,
path-traversal defense, and the migration's DROP-then-ADD pattern all hold up.
Findings below are concentrated in two areas:

1. A correctness bug in the post-INSERT bookkeeping (`cur.rowcount` after
   `execute_values` reports the LAST page only, so `rows_skipped_idempotent`
   under-counts when `len(all_rows) > page_size=500`).
2. Test isolation gaps where two integration tests commit rows or trigger
   global `--wipe-synthetic` without restoring state, which can pollute
   downstream tests when pytest order changes.

No Critical findings; the `--where` injection surface, token handling, and
`subprocess.run` invocation are all properly hardened.

## Warnings

### WR-01: `cur.rowcount` after `execute_values` reports last page only — `rows_skipped_idempotent` is wrong for batches > 500 rows

**File:** `scripts/ingest_mapillary.py:644-663`
**Issue:** After `execute_values(..., all_rows, page_size=500)`, `cur.rowcount`
reflects only the rows affected by the FINAL internal page, not the cumulative
count across pages. The summary computes
`rows_skipped_idempotent = rows_attempted - inserted` from this value (line
663), so when `len(all_rows) > 500`, `inserted` is a fraction of the real
total and `rows_skipped_idempotent` becomes inflated (and may go negative if
the last page was small). This breaks the operator-facing run summary on any
multi-page run.

The idempotency invariant itself (ON CONFLICT DO NOTHING) is correct; only
the reporting is wrong.
**Fix:** Use `RETURNING segment_id` and count returned rows, or fall back to
fetching `cur.rowcount` after each page by passing `page_size` explicitly via
a manual loop. Cleanest:
```python
result = execute_values(
    cur,
    """
    INSERT INTO segment_defects (...)
    VALUES %s
    ON CONFLICT (segment_id, source_mapillary_id, severity) DO NOTHING
    RETURNING 1
    """,
    all_rows,
    page_size=500,
    fetch=True,
)
inserted = len(result)
```
`fetch=True` aggregates RETURNING rows across all internal pages.

### WR-02: `test_unique_allows_multiple_null_synthetic_rows` commits rows then rollbacks — DB pollution

**File:** `backend/tests/test_migration_002.py:74-90`
**Issue:** The test executes the INSERT, then `applied_migration.commit()`
inside the `try` block (line 88) before the `finally: rollback()` (line 90).
Once committed, the rollback at line 90 is a no-op, so the two NULL-source
synthetic rows remain in `segment_defects` after the test. The test makes no
assertion on the result either — its purpose is "INSERT did not raise" — so
behavior is correct, but every run leaks two rows. Subsequent runs of
`test_existing_synthetic_rows_backfill_source` see those leaked rows tagged
`synthetic` (still passes by accident), and operators inspecting the DB will
find unexplained orphaned defect rows on their seed segment.
**Fix:** Either drop the `commit()` (the assertion that the multi-row INSERT
does not raise the UNIQUE violation only needs the statement to execute, not
persist), or add explicit cleanup:
```python
try:
    cur.execute(
        "INSERT INTO segment_defects (...) VALUES (%s, %s, %s, %s, NULL, 'synthetic'), "
        "(%s, %s, %s, %s, NULL, 'synthetic')",
        (a_segment_id, "moderate", 1, 0.5, a_segment_id, "moderate", 1, 0.6),
    )
    # Statement succeeded -> NULL-distinct UNIQUE works. No commit needed.
finally:
    applied_migration.rollback()
```

### WR-03: `test_wipe_synthetic_preserves_mapillary` relies on lexical test order to avoid corrupting downstream state

**File:** `backend/tests/test_integration.py:490-556`
**Issue:** The test calls the CLI with `--wipe-synthetic --force-wipe`, which
DELETEs every `source='synthetic'` row in `segment_defects`. The docstring
(lines 502-504) acknowledges the destruction and asks readers to keep this
test last. pytest does not guarantee lexical execution order across plugin
configurations (`-p no:randomly` vs `pytest-randomly`, `--lf`,
`pytest-xdist`), so the "place it last" contract is unenforceable in CI.
Once the wipe runs, every other integration test that assumes synthetic rows
exist (e.g. `test_segments_returns_geojson` checking
`pothole_score_total` > 0 indirectly via real seed data) is at risk.
**Fix:** Either snapshot+restore synthetic rows around the wipe, or scope the
test to a synthetic row it inserts itself:
```python
# Setup: insert ONE synthetic test row with a known marker.
# Run --wipe-synthetic.
# Assert the test marker is gone, the mapillary marker survived.
# Reseed via subprocess.run([sys.executable, "scripts/seed_data.py", "--synthetic-only"])
#   in a teardown fixture so subsequent tests see a stable baseline.
```
Alternatively, mark the test with `@pytest.mark.destructive` and document a
required `pytest -m "integration and not destructive"` for normal CI runs.

### WR-04: `compute_scores.py` does not use a `with conn.cursor()` context — leaked connections on SQL errors

**File:** `scripts/compute_scores.py:47-104`
**Issue:** `cur = conn.cursor()` (line 48) and `conn = psycopg2.connect(...)`
(line 47) are bare resource acquisitions. If `cur.execute(sql, params)` at
line 93 raises (e.g., a constraint violation or transient error), the
`cur.close()` and `conn.close()` calls at lines 103-104 never run, leaking
the connection. This is a recompute hot path invoked by the ingest CLI as a
subprocess; a leaked connection per run accumulates over a long demo session
or CI sweep.
**Fix:** Use context managers:
```python
with psycopg2.connect(DATABASE_URL) as conn:
    with conn.cursor() as cur:
        # ... existing logic ...
        cur.execute(sql, params)
        conn.commit()
        cur.execute("SELECT COUNT(*) FROM segment_scores WHERE pothole_score_total > 0")
        count = cur.fetchone()[0]
        print(f"Scores recomputed (--source {args.source}). {count} segments have pothole data.")
```
Note: `psycopg2.connect` as a context manager commits on clean exit and
rolls back on exception, but does NOT close the connection — pair with
`contextlib.closing(...)` or an explicit `conn.close()` in `finally`.

## Info

### IN-01: `--where` regex defense allows `UNION` and subquery exfiltration within the same DB role

**File:** `scripts/ingest_mapillary.py:96-100, 143-162, 165-190`
**Issue:** `_FORBIDDEN_RE` blocks DDL/DML and `pg_*`/`information_schema`,
but does not block `UNION`, `WITH`, or subqueries. An operator who can pass
`--where` can write
`id IN (SELECT segment_id FROM segment_defects)` to enumerate any data the
`rq` DB role can read. The CLI is operator-facing and the trust model is
explicitly "only run-bookers may pass --where" (per the docs reference at
README.md:154 and `docs/MAPILLARY_INGEST.md`), so this is by design.
The 30s `statement_timeout` (line 178) and the 1000-segment cap (line 91 +
185-189) bound the blast radius. Worth documenting that `--where` is a
trusted-input surface, not an untrusted-input surface.
**Fix:** Add a sentence to the `--where` `argparse` help text:
`"Trusted operator input only -- runs as the rq DB role; do not expose to
end users."` and consider blocking `UNION`/`WITH` keywords too if the trust
model tightens.

### IN-02: `with_retry` only retries `requests.HTTPError` — connection/timeout errors fail fast

**File:** `scripts/ingest_mapillary.py:306-327`
**Issue:** The retry loop only catches `requests.HTTPError` (which requires
the request to have completed with a 4xx/5xx status). Transient
`requests.ConnectionError` and `requests.Timeout` exceptions — common with
flaky residential ISPs and Mapillary's CDN — bypass the retry and bubble up
as a `search_failed` / `download_failed` counter increment, dropping the
sub-bbox or image entirely. For a long ingest of hundreds of segments this
silently shrinks coverage.
**Fix:**
```python
except (requests.HTTPError, requests.ConnectionError, requests.Timeout) as e:
    last_exc = e
    status = ...  # only meaningful for HTTPError
    is_retryable = (
        isinstance(e, (requests.ConnectionError, requests.Timeout))
        or status == 429
        or 500 <= status < 600
    )
    if is_retryable and attempt < max_attempts - 1:
        ...
```

### IN-03: `subprocess.run` recompute call has no timeout — a hung `compute_scores.py` hangs ingest forever

**File:** `scripts/ingest_mapillary.py:362-364`
**Issue:** No `timeout=` kwarg. If the recompute SQL stalls (e.g., a stuck
autovacuum on `segment_defects`, an exclusive lock from another session),
`subprocess.run` blocks indefinitely. The parent ingest CLI has already
written its rows and committed; there's no recovery path other than Ctrl-C.
**Fix:** Add a generous timeout and convert to a warning on expiry:
```python
try:
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(repo_root),
        timeout=300,  # 5 minutes; recompute on 62k segments runs in ~5s
    )
except subprocess.TimeoutExpired:
    logger.error("compute_scores.py timed out after 300s; segment_scores stale")
    return -1
```

### IN-04: `compute_padded_bbox` dict-extraction is positional but un-asserted

**File:** `scripts/ingest_mapillary.py:226-234`
**Issue:** When the cursor is a `RealDictCursor`, the code does
`vals = [row[k] for k in list(row.keys())]` — assuming dict insertion order
matches the SELECT column order. This is true for psycopg2's
`RealDictCursor` (it iterates `cursor.description` which preserves SELECT
order), but the code does not assert it. A future refactor that swaps in a
sorted-dict cursor or changes the SELECT column order would silently scramble
`(min_lon, min_lat, max_lon, max_lat)` into a malformed bbox. The script's
own connection at line 557 uses the default tuple cursor, so the dict branch
runs only when callers pass a custom cursor (e.g., tests using `db_conn`).
**Fix:** Either alias the columns and select by alias name, or skip the dict
branch:
```python
SELECT
    ST_XMin(env) AS min_lon, ST_YMin(env) AS min_lat,
    ST_XMax(env) AS max_lon, ST_YMax(env) AS max_lat
FROM (...) e
```
Then `row["min_lon"]` etc. on dict cursors, `row[0..3]` on tuple cursors.

### IN-05: `SET statement_timeout = '30s'` persists for the rest of the connection

**File:** `scripts/ingest_mapillary.py:178`
**Issue:** `SET` (without `LOCAL`) applies for the remainder of the session.
After `resolve_where_targets` returns, every subsequent query on the same
connection (the per-segment loop, the wipe DELETE, the batch INSERT, the
final commit) inherits the 30s timeout. A large `execute_values` INSERT on a
slow disk could trip the timeout and abort the run. Probably fine in
practice (the INSERT is bounded by the 1000-segment cap × ~20 images ×
2 severities = ~40k rows), but the implicit scope is fragile.
**Fix:** Use `SET LOCAL` inside an explicit transaction, or `RESET
statement_timeout` immediately after the `SELECT id` query completes:
```python
cur.execute("SET LOCAL statement_timeout = '30s'")  # only valid inside BEGIN
# ... or ...
try:
    cur.execute("SET statement_timeout = '30s'")
    cur.execute(query)
    rows = cur.fetchmany(max_segments + 1)
finally:
    cur.execute("RESET statement_timeout")
```

### IN-06: Migration 002 DROP-then-ADD CHECK is non-atomic — racy under concurrent writes

**File:** `db/migrations/002_mapillary_provenance.sql:26-30`
**Issue:** Between the `DROP CONSTRAINT IF EXISTS` and `ADD CONSTRAINT`
statements, the table has no `source` CHECK. A concurrent transaction
inserting `source='garbage'` would succeed mid-migration and then cause the
subsequent `ADD CONSTRAINT` to fail with a "violates check constraint" error
on existing data. The migration is intended for offline application (single
operator, no traffic), so this is a documentation/operability issue, not a
production race. Accept as-is for v1, document the offline-only requirement.
**Fix:** Wrap both statements in `BEGIN; ... COMMIT;` or document explicitly
that migrations require zero concurrent writers. Postgres 16 still has no
idempotent `ADD CONSTRAINT IF NOT EXISTS`, so the DROP-then-ADD pattern is
unavoidable; the transaction wrapper is the only mitigation.

### IN-07: docker-compose.yml hardcodes default DB credentials in source

**File:** `docker-compose.yml:5-7`
**Issue:** `POSTGRES_PASSWORD: rqpass` is committed alongside the matching
`DATABASE_URL` connection string. README.md publishes the same credentials
publicly. Acceptable for local-dev demo, but a future operator deploying
this compose file to a public host without changing the password would
expose the DB. The repo lacks a `.env.example` / template indicating the
override path.
**Fix:** Add an `.env.example`, switch to `${POSTGRES_PASSWORD:-rqpass}`
interpolation, and add a one-line README warning. Example:
```yaml
environment:
  POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-rqpass}  # local-dev default; override via .env in prod
```

### IN-08: `test_compute_scores_source.py:test_source_synthetic_excludes_mapillary` leaves segment_scores reflecting `--source mapillary` final state

**File:** `backend/tests/test_compute_scores_source.py:124-155`
**Issue:** The test runs `compute_scores.py --source synthetic` then
`compute_scores.py --source mapillary` and asserts the snapshots differ. The
`cleanup_test_rows` fixture removes the inserted defect row, but does NOT
re-run `compute_scores.py --source all` to restore default
`segment_scores`. Subsequent integration tests that inspect
`segment_scores` (e.g., the route endpoint computing per-segment cost) see
mapillary-only scores rather than the all-source baseline. Not catastrophic
— other tests trigger their own recomputes — but a hidden ordering coupling.
**Fix:** Add the restoration step to the cleanup fixture:
```python
@pytest.fixture
def cleanup_test_rows(db_conn):
    marker = "test_03_02_999"
    # ... existing setup ...
    yield marker
    # ... existing teardown DELETE ...
    # NEW: restore baseline scores
    subprocess.run(
        [sys.executable, str(SCRIPT), "--source", "all"],
        check=True, capture_output=True, cwd=REPO_ROOT,
    )
```

---

_Reviewed: 2026-04-25_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
