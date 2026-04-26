---
phase: 03-mapillary-ingestion-pipeline
fixed_at: 2026-04-25
fix_scope: critical_warning
findings_in_scope: 4
fixed: 4
skipped: 0
iteration: 1
status: all_fixed
review_source: 03-REVIEW.md
---

# Phase 03 — Code Review Fix Report

All four Warning-severity findings from `03-REVIEW.md` were resolved in iteration 1. The Critical bucket was empty (0 findings); Info bucket (8 findings) was deliberately out of scope.

## Fixes Applied

### WR-01 — `rows_skipped_idempotent` undercounts on multi-page inserts
**Commit:** `cbe0091` — `fix(03): WR-01 use RETURNING+fetch=True for accurate inserted count`
**File:** `scripts/ingest_mapillary.py`

`cur.rowcount` after `psycopg2.extras.execute_values(..., page_size=500)` reports only the count from the LAST page of the batch, not the cumulative count across all pages. On any run that crosses the 500-row page boundary, `rows_skipped_idempotent` in the manifest run-summary was wrong.

Switched to `execute_values(..., template, fetch=True)` with `RETURNING 1` and computed inserted count as `len(returned_rows)`. `rows_skipped_idempotent = len(detections) - inserted`.

### WR-02 — `test_unique_allows_multiple_null_synthetic_rows` leaks rows
**Commit:** `64373df` — `fix(03): WR-02 drop commit() in NULL-distinct UNIQUE test`
**File:** `backend/tests/test_migration_002.py`

The test called `conn.commit()` to persist two synthetic rows, then called `conn.rollback()` in a `finally` block. After commit, rollback is a no-op — the rows persisted to the DB and accumulated 2 rows per test run.

Removed the `commit()`. The transaction is now held open through the assertion and rolled back at teardown, leaving zero residue. Behavior preserved (both rows are visible inside the transaction during the assertion).

### WR-03 — `test_wipe_synthetic_preserves_mapillary` relies on pytest ordering
**Commit:** `d46dc5c` — `fix(03): WR-03 snapshot+restore synthetic rows around wipe test`
**File:** `backend/tests/test_integration.py`

The test ran a destructive `--wipe-synthetic` against the shared fixture DB, which destroyed all synthetic rows globally. Subsequent tests that depend on synthetic baseline data passed only because they happened to run *before* this one in the default lexical pytest order. Under `pytest-randomly`, `--lf`, or `pytest-xdist`, the suite became flaky.

Snapshot all synthetic rows to a temp table at test entry, run the wipe assertion, restore the snapshot at test exit (in a `finally`). Test is now order-independent.

### WR-04 — `compute_scores.py` leaks DB connection on SQL errors
**Commit:** *(applied this session, after fixer hit usage limit)* — `fix(03): WR-04 wrap compute_scores DB handles in context managers`
**File:** `scripts/compute_scores.py`

Bare `conn = psycopg2.connect(...)` + `cur = conn.cursor()` leaked the socket on any exception in `cur.execute()` (constraint violation, transient network error, statement timeout). The trailing `cur.close() / conn.close()` was unreachable on the exception path.

Wrapped the connection in `contextlib.closing(psycopg2.connect(DATABASE_URL))` and the cursor in a `with conn.cursor()` block. `psycopg2.connect()` as a context manager commits on clean exit and rolls back on exception, but does NOT close — `contextlib.closing()` provides the close guarantee. No behavior change to SQL, logging, or exit code.

## Out of Scope (Info — deferred)

The 8 Info findings from `03-REVIEW.md` were not addressed in this run (`fix_scope: critical_warning`). They remain advisory and can be re-surfaced later via `/gsd-code-review-fix 3 --all` or addressed opportunistically in future phases. Highlights for follow-up:

- `--where` predicate documentation (trust model is correct, docs could be more explicit)
- `with_retry` doesn't catch `requests.ConnectionError` / `requests.Timeout` (only generic `RequestException` — narrower retries possible)
- Missing `subprocess.run(..., timeout=...)` on auto-recompute hook (defaults to no timeout)
- `RealDictCursor` positional dict extraction is fragile (style nit, not a bug)
- `statement_timeout` is session-scoped, not per-statement
- Migration 002 DROP-then-ADD CHECK is not atomic (acceptable for init flow; risky for rolling production migration — Phase 5+ concern)
- Hardcoded `docker-compose.yml` credentials (acceptable for local dev only)
- `segment_scores` baseline isn't restored in `compute_scores` test teardown

## Resumption Note

The original `gsd-code-fixer` agent applied WR-01..WR-03 cleanly, then began WR-04 but hit a usage limit before committing the file edit or writing this report. The orchestrator (this session) inspected the staged diff for WR-04, confirmed it was the intended context-manager wrap with no unrelated changes, committed it manually with the fix message above, and wrote this `03-REVIEW-FIX.md` summarizing all four fixes.
