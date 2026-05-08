# Phase 10 Deferred Items

Items discovered during plan execution that are out-of-scope for the current plan.

## test_ingest_crashes.py::test_idempotent_reingest timeout under parallel-agent load

**Discovered during:** Plan 10-02 execution (post-test verification, 2026-05-08).

**Issue:** `test_idempotent_reingest` invokes the `scripts/ingest_crashes.py` CLI driver twice via subprocess. A single ingest of the 205-row LA City fixture takes ~107s on the dev machine (snap-matching against 209k road_segments dominates wall clock). Two back-to-back runs require >214s in optimal conditions. Under parallel-agent load (multiple worktree executors hitting the same live PostGIS), pgr/PostGIS contention pushed this test past pytest-timeout's default 180s ceiling.

**Why deferred:** Out of scope for Plan 10-02 (this plan's `files_modified` is `scripts/compute_scores.py`, `backend/tests/test_compute_scores_source.py`, `backend/tests/conftest.py` — none of which are imported by `test_ingest_crashes.py`). The timeout is environmental, not a regression in this plan's code. Plan 10-02's full test gate (test_compute_scores_source.py + test_scoring.py) passes 9/10 with 1 expected skip.

**Verifiable resolution path (later phase or runbook):**
- Option A: bump `test_idempotent_reingest`'s pytest-timeout to 600s (it's an integration test, not a unit test).
- Option B: parameterize the fixture to use a smaller CSV (e.g., 20 rows) for the idempotency check — the contract is "second run inserts 0", not "second run handles 200 rows".
- Option C: serialize integration tests across worktrees via pytest-xdist's `--dist=loadgroup`.

**Confirmed not caused by Plan 10-02:** Plan 10-02's modifications do not touch `scripts/ingest_crashes.py` nor `backend/tests/test_ingest_crashes.py`. The first ingest test in the file (`test_run_summary_keys_and_types`) passed cleanly in the same pytest run. Only `test_idempotent_reingest` (the only test that runs the driver twice) hit the timeout.
