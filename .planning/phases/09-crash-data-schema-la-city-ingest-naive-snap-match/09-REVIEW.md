---
phase: 09-crash-data-schema-la-city-ingest-naive-snap-match
reviewed: 2026-05-07T00:00:00Z
depth: standard
files_reviewed: 12
files_reviewed_list:
  - db/migrations/004_crash_records.sql
  - data_pipeline/lacity_mocodes.py
  - data_pipeline/snap.py
  - data_pipeline/lacity_socrata.py
  - scripts/ingest_crashes.py
  - backend/tests/test_migration_004.py
  - backend/tests/test_lacity_mocodes.py
  - backend/tests/test_snap.py
  - backend/tests/test_lacity_socrata.py
  - backend/tests/test_ingest_crashes.py
  - .env.example
  - data/crashes_la/lacity_fixture.csv
findings:
  critical: 0
  warning: 4
  info: 5
  total: 9
status: issues_found
---

# Phase 9: Code Review Report

**Reviewed:** 2026-05-07T00:00:00Z
**Depth:** standard
**Files Reviewed:** 12
**Status:** issues_found

## Summary

Phase 9 introduces the LA City Socrata crash-ingest pipeline (mocode parser,
SoQL paged client, shared snap-match SQL primitive, idempotent migration, CLI
driver) plus a thorough integration test suite using a 206-row CSV fixture.

The submission is in solid shape against the focus-area checklist:

- **SQL injection / parameter binding (`scripts/ingest_crashes.py`,
  `data_pipeline/snap.py`):** The snap primitive uses parameterized `%s`
  placeholders correctly, including the dual `::geography` cast required for
  meter-scale `ST_DWithin`. The `execute_values` ON CONFLICT INSERT in the
  driver also binds all values; the fixed template is the only string-built
  fragment and contains no user data. **Pass.**
- **Migration idempotency (`db/migrations/004_crash_records.sql`):** Faithful
  mirror of `002_mapillary_provenance.sql` — `CREATE TABLE IF NOT EXISTS`,
  separate `CREATE UNIQUE INDEX IF NOT EXISTS`, DROP-then-ADD for both CHECK
  constraints, `ADD COLUMN IF NOT EXISTS` for `crash_norm`. The `INTEGER`
  (not `BIGINT`) FK type matches `road_segments.id SERIAL` per Pitfall D.
  **Pass.**
- **Token leakage (`data_pipeline/lacity_socrata.py`,
  `scripts/ingest_crashes.py`):** Token never appears in log calls or `print`
  statements. `requests.HTTPError` does not include header values in its
  message. The static-analysis test in `test_lacity_socrata.py` enforces this
  contract. **Pass.**
- **Charitable mocode parsing (`data_pipeline/lacity_mocodes.py`):**
  `ValueError` is correctly raised only when **zero** severity codes are
  present in the input — non-KABCO codes are silently ignored, matching D-09-13
  REVISED and Pitfall 2 / KEY LESSON 2. **Pass.**
- **Snap primitive correctness (`data_pipeline/snap.py`):** `ST_DWithin` and
  `ST_Distance` both cast to `::geography` for meter semantics. KNN
  `ORDER BY geom <-> point` intentionally uses geometry (KNN GIST works on
  geometry). All 7 placeholders bound. **Pass.**
- **CLI exit codes (`scripts/ingest_crashes.py`):** EXIT_OK=0, EXIT_OTHER=1,
  EXIT_VALIDATION=2, EXIT_MISSING_RESOURCE=3 mirror `ingest_mapillary.py`.
  Error paths route to the correct code. **Pass.**
- **Test isolation:** The only test that mutates `road_segments`
  (`test_fk_set_null_on_segment_delete`) correctly wraps its DELETE in
  `SAVEPOINT before_seg_delete` … `ROLLBACK TO SAVEPOINT` and additionally
  pre-deletes the dependent `segment_defects` / `segment_scores` cascade
  rows so the rollback restores the topology cleanly. The
  `_wipe_lacity_crash_records` fixture deletes only `crash_records` rows
  the test owns. **Pass.**
- **Run-summary JSON shape (D-09-08):** Exactly 10 top-level keys
  (`source`, `fetched`, `inserted`, `skipped_duplicate`,
  `dropped_outside_snap`, `errors`, `snap_distance_m`, `by_severity`,
  `started_at`, `duration_s`), with the required `{p50, p95, max}` and
  `{fatal, injury, pdo}` nested sub-keys. The integration test pins the
  exact key set. **Pass.**

The findings below are **defense-in-depth** improvements (not bugs that will
fail the acceptance criteria). The single Warning worth fixing before merge
is **WR-01** (SoQL date interpolation hardening).

## Warnings

### WR-01: SoQL date interpolation in `iter_crashes` is not validated at the boundary

**File:** `data_pipeline/lacity_socrata.py:80-82`

**Issue:** The `$where` clause is built via f-string interpolation of
`start_date` and `end_date`:

```python
where_parts = [
    f"date_occ between '{start_date}T00:00:00' and '{end_date}T00:00:00'"
]
```

Numeric `bbox` values on line 84 are explicitly cast through `float(c)` (which
neutralises injection by raising `ValueError` on non-numeric input). The two
date strings receive no equivalent validation inside the module — the function
trusts the caller to have already run `datetime.fromisoformat()`. Today, only
`scripts/ingest_crashes.py:228-229` provides that validation; a future second
caller (a notebook, a Phase 12 cron wrapper, a future re-pull script) could
forget it and pass a string carrying `'` or whitespace, producing either a
404 from Socrata or a query that silently returns the wrong window.

This is not exploitable as classical SQL injection (SoQL is a sandboxed query
language, and the dataset is read-only and public), but it is a correctness
foot-gun and a deviation from the rest of the codebase's "validate at the
boundary" pattern.

**Fix:**
```python
def iter_crashes(start_date: str, end_date: str, ...) -> Iterator[dict]:
    # Defense-in-depth: validate ISO format here too. The driver also
    # validates, but a future caller that forgets to would emit a malformed
    # SoQL where-clause to the network.
    from datetime import datetime
    try:
        datetime.fromisoformat(start_date)
        datetime.fromisoformat(end_date)
    except ValueError as e:
        raise ValueError(
            f"start_date and end_date must be ISO format; got "
            f"start_date={start_date!r}, end_date={end_date!r}: {e}"
        ) from e
    where_parts = [
        f"date_occ between '{start_date}T00:00:00' and '{end_date}T00:00:00'"
    ]
    ...
```

---

### WR-02: `LACITY_SNAP_M` parsed at import time with no fallback on malformed input

**File:** `scripts/ingest_crashes.py:79`

**Issue:**
```python
DEFAULT_SNAP_METERS = float(os.environ.get("LACITY_SNAP_M", "50.0"))
```

If an operator sets `LACITY_SNAP_M=auto` or `LACITY_SNAP_M=50m` in `.env`, this
raises `ValueError` at module import — **before** argparse runs and before any
nice user-facing error message. The driver process exits with a Python
traceback, not the documented EXIT_VALIDATION=2.

This is the same shape as `LACITY_APP_TOKEN` (which is a string and so cannot
fail at parse time) but breaks the convention.

**Fix:**
```python
def _parse_snap_meters_env() -> float:
    raw = os.environ.get("LACITY_SNAP_M", "50.0")
    try:
        return float(raw)
    except ValueError:
        # Fail soft at import; argparse default falls through and the
        # operator can override on the CLI. The bad value will be surfaced
        # by the WARN log below, not a traceback.
        logging.getLogger(__name__).warning(
            "LACITY_SNAP_M=%r is not a number; falling back to 50.0", raw,
        )
        return 50.0

DEFAULT_SNAP_METERS = _parse_snap_meters_env()
```

Alternatively: validate inside `main()` after argparse and exit
EXIT_VALIDATION on bad input. Either is fine; the current shape's import-time
crash is the issue.

---

### WR-03: `--limit` over-fetches one row from the source iterator

**File:** `scripts/ingest_crashes.py:270-274`

**Issue:**
```python
for crash in row_iter:
    counters["fetched"] += 1
    if args.limit is not None and counters["fetched"] > args.limit:
        counters["fetched"] -= 1  # don't count the row we didn't process
        break
```

The off-by-one in the counter is correctly compensated, but the iterator was
already advanced one row past `--limit`. For the live Socrata path, that
means the (limit-th + 1) row was fetched over HTTP and discarded; for an
operator running `--limit 1` against the live API to smoke-test connectivity,
this still pulls a full 1000-row page. Not a bug per se — the post-decrement
keeps the run-summary correct — but the comment is slightly misleading
("don't count the row we didn't process" — we did fetch it, just didn't
insert it).

**Fix:** Use a counter-first guard:
```python
for crash in row_iter:
    if args.limit is not None and counters["fetched"] >= args.limit:
        break
    counters["fetched"] += 1
    ...
```
This avoids the decrement dance and matches the obvious read of
"`--limit N` processes at most N rows."

---

### WR-04: `_run_driver` PYTHONPATH inheritance can mask local-environment hazards

**File:** `backend/tests/test_ingest_crashes.py:65-71`

**Issue:** The integration test propagates `os.environ` wholesale into the
subprocess and additionally prepends `REPO_ROOT` to `PYTHONPATH`. Two
side-effects:

1. If the developer has an unrelated `LACITY_APP_TOKEN` exported in their
   shell, the driver subprocess will use it and hit the live Socrata API
   for token-validation (Socrata returns 403 on bad tokens). On CI, this is
   moot because the env is clean; locally it can produce confusing failures.

2. `--csv` is the chosen mode, so the token is never actually consulted —
   but the subprocess still inherits `DATABASE_URL`, which is correct.

Per the per-CONTEXT memory pin (tokens contain pipes; never `source .env`),
the safer pattern is to scrub `LACITY_APP_TOKEN` from the subprocess env in
the CSV-mode test path so the test cannot accidentally reach out to the live
network even if the live code path were ever exercised.

**Fix:**
```python
env = {**os.environ}
# Test path is --csv; ensure no live-API contact even by accident.
env.pop("LACITY_APP_TOKEN", None)
```

## Info

### IN-01: KNN ORDER BY uses geometry, not geography (intentional, document the asymmetry)

**File:** `data_pipeline/snap.py:62`

**Issue:** `ORDER BY geom <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326)` does not
include `::geography`. This is **correct PostGIS practice** — KNN GIST
operators work on `geometry`, not `geography` — but at LA's latitude (~34°)
1° longitude ≈ 92 km versus 1° latitude ≈ 111 km, so degree-distance ranking
differs slightly from great-circle ranking. For the 50 m default radius the
ordering error is sub-meter and irrelevant; for any future widened radius
(>1 km) it is worth a comment so the next reader does not "fix" it by adding
a cast that defeats the GIST index.

**Fix:** Add a short comment near the ORDER BY:
```python
# NOTE: ORDER BY uses GEOMETRY (no ::geography) so the KNN GIST index is
# usable. At LA latitude this differs from great-circle by <1% within the
# ST_DWithin radius — the radius filter (above, geography) bounds candidates
# in METERS, the KNN ordering picks the nearest in degree-space among them.
```

---

### IN-02: Pagination log line is emitted for the *next* offset, not the one just fetched

**File:** `data_pipeline/lacity_socrata.py:118-119`

**Issue:**
```python
offset += page_size
logger.info("lacity_socrata: paged offset=%d page_size=%d", offset, page_size)
```

The log fires AFTER the increment, so the value it reports is the offset of
the page about to be fetched, not the page just returned. Reading the log
during a long pull, an operator sees `offset=1000` after the first 1000 rows
have already been delivered — slightly counter-intuitive.

**Fix:** Either log before incrementing, or rephrase the message:
```python
logger.info("lacity_socrata: page complete, next offset=%d", offset)
offset += page_size
```

---

### IN-03: `crash_records_source_check` uses single-element IN clause

**File:** `db/migrations/004_crash_records.sql:35-36`

**Issue:** `CHECK (source IN ('lacity'))` is functionally equivalent to
`CHECK (source = 'lacity')`. The inline comment explains v0.4.1 will widen
to `('lacity','switrs')`, so the IN form is forward-looking and intentional.
No change required; flagged only because static analysers may warn.

**Fix:** None — keep the IN form to minimise the v0.4.1 diff.

---

### IN-04: `test_snap_within_radius` does not assert the matched id equals the picked segment

**File:** `backend/tests/test_snap.py:56-66`

**Issue:** The fixture returns `(seg_id, clon, clat)` where `clon, clat` is
the midpoint of segment `seg_id`. The test asserts `dist_m < 1.0` but does
not assert `matched_id == seg_id`. The KNN ordering test
(`test_snap_picks_nearest_when_multiple_in_radius`) does cover that
assertion, so coverage exists in aggregate, but the simpler test would be
strictly stronger if it included the id check.

**Fix:**
```python
matched_id, dist_m = result
assert matched_id == seg_id, f"matched id {matched_id} != picked id {seg_id}"
assert dist_m < 1.0, ...
```

---

### IN-05: `test_token_never_logged_or_printed` static checks are case-folded but skip `f"…{token}…"`

**File:** `backend/tests/test_lacity_socrata.py:124-142`

**Issue:** The forbidden-substring list catches `logger.info(token`,
`print(token`, `print(headers`, etc. It does not catch the more dangerous
modern Python form `f"...{token}..."` (e.g.,
`logger.info(f"using token {tok}")`) because the substring `token` appears
inside `{}`, not as a positional argument.

This is a low-impact omission — current code has no such pattern, and a
reviewer would catch it — but the test name promises a stronger guarantee
than it delivers.

**Fix:** Add a regex-based check in addition to the substring list:
```python
import re
# Catch f-string interpolation of token / headers in any logger or print call.
forbidden_patterns = [
    re.compile(r"(logger\.\w+|print)\(\s*f[\"'].*\{[^}]*token[^}]*\}", re.IGNORECASE),
    re.compile(r"(logger\.\w+|print)\(\s*f[\"'].*\{[^}]*headers[^}]*\}", re.IGNORECASE),
]
for pat in forbidden_patterns:
    assert not pat.search(src), f"forbidden f-string token leak: {pat.pattern}"
```

---

_Reviewed: 2026-05-07T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
