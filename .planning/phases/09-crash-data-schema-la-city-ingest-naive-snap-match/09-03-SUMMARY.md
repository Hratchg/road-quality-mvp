---
phase: 09-crash-data-schema-la-city-ingest-naive-snap-match
plan: 03
subsystem: data-pipeline
tags: [python, socrata, http-client, test-fixture, security, paged-generator, requests, csv]

# Dependency graph
requires:
  - phase: 03-mapillary
    provides: data_pipeline/mapillary.py shape (framework-agnostic, env-var token,
      paged generator, requests-only) — mirrored line-by-line for the new Socrata client
  - phase: 09-01
    provides: crash_records table column shape (the fixture's flattened latitude/longitude
      pair maps to the geom column the driver in 09-04 will populate)
provides:
  - data_pipeline/lacity_socrata.py with iter_crashes(start_date, end_date, *, bbox,
    page_size, token, timeout_s) → Iterator[dict] (paged Socrata SoQL generator)
  - $where date_occ BETWEEN + within_box(location_1, ymin, xmin, ymax, xmax)
    composition (lat-first; verified at dev.socrata.com/docs/functions/within_box)
  - Two-condition pagination termination (empty response OR partial page)
  - Optional X-App-Token header iff LACITY_APP_TOKEN env or explicit token arg present
    (D-09-20: token is optional; anonymous works at lower rate limit)
  - data/crashes_la/lacity_fixture.csv (205 rows, D-09-07 a-e coverage verified)
  - 9-test pytest module pinning URL composition, pagination, token handling,
    and the T-9-03 token-never-logged static contract
affects: [09-04 ingest_crashes driver imports iter_crashes + reads CSV fixture,
  Phase 12 operator runbook documents LACITY_APP_TOKEN load via Python .env parser]

# Tech tracking
tech-stack:
  added: []  # No new third-party deps — uses requests already vendored for Mapillary
  patterns:
    - "Paged Socrata SoQL generator with $offset incrementing by page_size and
      two-condition termination (empty list OR len(rows) < page_size)"
    - "$order=:id REQUIRED for stable pagination across $offset windows
      (otherwise Socrata's natural order can shift between pages → duplicate
      or skipped rows; verified at dev.socrata.com/docs/paging)"
    - "within_box(location_1, ymin, xmin, ymax, xmax) for bbox spatial filter
      uses LAT-FIRST argument order (per Socrata docs); explicit float()
      coercion of caller-supplied bbox tuple to defang T-9-08 SoQL injection"
    - "Token-not-logged static contract: enforced by reading the module source
      and asserting forbidden substrings (logger.{debug,info,warning,error}
      of 'token' or 'headers'; print of 'token' or 'headers') are absent"
    - "Synthetic test fixture with SEED=42 reproducibility and dr_no marker
      prefixes (SYN-, MIDBLOCK-, INTERSECTION-, OUTSIDE-SNAP-, MULTI-SEV-)
      for downstream by-id targeting in integration tests"

key-files:
  created:
    - data_pipeline/lacity_socrata.py
    - backend/tests/test_lacity_socrata.py
    - data/crashes_la/lacity_fixture.csv
  modified: []  # No edits to existing files; all three artifacts are new

key-decisions:
  - "Mirrored data_pipeline/mapillary.py module shape line-for-line (framework-agnostic,
    no argparse, no sys.exit, module-top env-var read, requests-only). Critical
    cross-pipeline consistency: the operator runbook treats Mapillary and LA City
    as one mental model and the same review checklist works for both."
  - "Used plain requests.get against the Socrata endpoint (NOT sodapy). Per
    09-RESEARCH.md §3 'Don't-Hand-Roll' table: sodapy is unmaintained since
    2022-08, Socrata's SoQL surface is small enough to wrap in <100 LOC of
    requests, and adding a transitive deprecated dep increases supply-chain risk."
  - "Two-condition pagination termination — STOP on empty response (rows == [])
    AND STOP on partial page (len(rows) < page_size). Either alone is enough
    in normal operation; pinning both makes the generator robust against the
    edge case where Socrata returns exactly page_size rows on the last page,
    which would loop forever otherwise."
  - "$order=:id (NOT a column name) is the documented stable-paging primitive.
    Without it the natural order can shift between $offset calls and rows can
    be duplicated or skipped. Pinned in test_where_clause_composition_with_bbox."
  - "Token-not-logged is enforced by static analysis (test_token_never_logged_or_printed)
    NOT just code review. Operator-style drift (someone adding logger.debug(headers)
    during a future debugging session) will fail this test loud. Mitigates T-9-03."
  - "Synthetic CSV fixture (Option B from the plan) chosen over live Socrata pull
    because (1) Socrata is rate-limited and the operator host doesn't have a
    LACITY_APP_TOKEN configured in this worktree; (2) CONVENTIONS.md SEED=42
    keeps the fixture reproducible across regenerations; (3) D-09-06 explicitly
    bans live API hits in CI so the fixture is the only data source the test
    suite ever sees. Marker rows (MIDBLOCK-001, INTERSECTION-001, OUTSIDE-SNAP-001,
    MULTI-SEV-001) make the criteria b-e cases targetable by id from 09-04."

patterns-established:
  - "Socrata SoQL paged generator template — one module-level function, $offset
    pagination, two-condition termination. Future Socrata datasets (SWITRS in
    v0.4.1) can clone this shape verbatim, swap the endpoint URL and field list."
  - "Token-not-logged static-analysis test pattern — codify as a security regression
    guard for any future module that reads a credential from env. Cheap to add
    (10 lines of test), catches an entire class of drift (debug-logging headers)."
  - "Marker-prefixed synthetic dr_no values for fixture rows (MIDBLOCK-001,
    OUTSIDE-SNAP-001, MULTI-SEV-001) — pattern for targetable rows in any future
    fixture where integration tests need to assert behavior on specific edge cases."

requirements-completed:
  - REQ-crash-ingest-lacity  # Plan 09-03 contributes the client + fixture pieces;
                             # Plan 09-04 will close out the requirement with the
                             # ingest driver. (REQUIREMENTS.md tracks the full set
                             # of plans contributing to each REQ.)

# Metrics
duration: ~5min
tasks: 2
files-created: 3
completed: 2026-05-08
---

# Phase 9 Plan 03: LA City Socrata Client + CSV Fixture Summary

**`data_pipeline/lacity_socrata.py` mirrors `data_pipeline/mapillary.py` exactly — paged Socrata SoQL generator with `$order=:id` stable pagination, `within_box(location_1, ...)` spatial filter, optional `X-App-Token` header, and a token-never-logged static contract. `data/crashes_la/lacity_fixture.csv` ships 205 hand-curated rows covering all five D-09-07 criteria (a-e). 9/9 mock-based unit tests pass in 0.05 s.**

## Performance

- **Duration:** ~5 min (292 s)
- **Started:** 2026-05-08T05:29:05Z
- **Completed:** 2026-05-08T05:33:57Z
- **Tasks:** 2 (Task 1 was `tdd="true"` → RED + GREEN commits; Task 2 was a single fixture commit)
- **Files created:** 3 (one module, one test file, one CSV fixture); zero existing files modified
- **Test latency:** 9 mock-based tests pass in **0.05 s** (no DB, no network)
- **Fixture size:** 16 KB (205 rows × 5 columns) — well under the 1 MB committable limit

## Accomplishments

- `data_pipeline/lacity_socrata.py` published — 119 LOC paged generator, framework-agnostic
- `iter_crashes(start_date, end_date, *, bbox, page_size, token, timeout_s)` yields one dict per Socrata row
- $where composition handles both bbox-present (`AND within_box(location_1, ymin, xmin, ymax, xmax)`) and bbox-absent paths
- $order=:id, $select=`dr_no,date_occ,mocodes,location_1`, $limit, $offset all pinned by tests
- Two-condition pagination termination: stops on empty response AND on partial page (len < page_size); pinned by `test_iter_crashes_stops_on_partial_page` and `test_iter_crashes_stops_on_empty_response`
- Optional X-App-Token header (D-09-20): present iff explicit token arg or LACITY_APP_TOKEN env is set; pinned by `test_token_header_added_when_set` + `test_token_header_absent_when_unset`
- T-9-03 mitigation: static-analysis test (`test_token_never_logged_or_printed`) reads the module source and rejects any `logger.{debug,info,warning,error}(token` or `print(token` or `logger.{debug,info}(headers` substrings — fails loud if a future debug session inadvertently logs the credential
- `data/crashes_la/lacity_fixture.csv` committed — 205 rows, header `dr_no,date_occ,mocodes,latitude,longitude`
- All five D-09-07 coverage criteria verified at fixture-write time with hard-fail assertions (criteria a–e):
  - **(a)** all three severity tiers represented: 10 fatal (3027), 101 injury (3024/3025/3026), 95 pdo (3028) — exceed minimums of 5/30/30
  - **(b)** `MIDBLOCK-001` row at Wilshire @ Hope (34.0535, −118.2434)
  - **(c)** `INTERSECTION-001` row at Wilshire & Vermont (34.0617, −118.2916)
  - **(d)** `OUTSIDE-SNAP-001` row at LAX runway interior (33.9416, −118.4085) — exercises Plan 09-04's `dropped_outside_snap` counter
  - **(e)** `MULTI-SEV-001` row carrying both `3024` and `3027` mocodes — Pitfall A multi-victim case; the mapper from Plan 09-02 resolves this to `fatal`

## Task Commits

Each task was committed atomically (no `git add -A`; only the specific files; all commits made with `--no-verify` per parallel-executor protocol):

1. **Task 1 RED — failing tests for `iter_crashes`** — `bbf0120` (test): 156 lines, 9 test functions; ImportError on collection (module not yet authored)
2. **Task 1 GREEN — `data_pipeline/lacity_socrata.py`** — `87ccfad` (feat): 119 LOC paged generator; all 9 tests now pass in 0.05 s
3. **Task 2 — `data/crashes_la/lacity_fixture.csv`** — `467ec4a` (feat): 205 rows; D-09-07 a-e coverage verified at write time

_Note: Plan 09-03 Task 1 is `tdd="true"`, which mandates the RED/GREEN cycle. No REFACTOR commit was needed — the GREEN module is the verbatim plan content and 9/9 tests pass on first run._

## TDD Gate Compliance

The Task-1 RED→GREEN sequence is visible in `git log --oneline`:

```text
467ec4a feat(09-03): add LA City crash CSV fixture (205 rows; D-09-07 a-e covered)
87ccfad feat(09-03): add data_pipeline/lacity_socrata.py paged Socrata client    ← GREEN gate
bbf0120 test(09-03): add failing tests for lacity_socrata.iter_crashes           ← RED gate
```

- **RED gate:** ✅ `bbf0120` (test commit before any implementation; ImportError verified)
- **GREEN gate:** ✅ `87ccfad` (implementation commit; 9/9 tests pass)
- **REFACTOR gate:** N/A (no behavior-preserving cleanup needed)

## Files Created/Modified

- **`data_pipeline/lacity_socrata.py`** (NEW, 119 LOC) — Socrata SoQL paged generator. Mirrors `data_pipeline/mapillary.py` shape exactly: framework-agnostic, module-top env-var read for `LACITY_APP_TOKEN`, `requests`-only HTTP, `iter_crashes` generator. Embeds Pitfall E mitigation in module docstring (token-loaded-as-pipe via Python `.env` parser, never `source .env`).
- **`backend/tests/test_lacity_socrata.py`** (NEW, 156 LOC) — Nine mock-based unit tests. Mocks `requests.get` via `unittest.mock.patch.object(lacity_socrata.requests, "get")`. No DB, no network, no pytest fixtures from `conftest.py` (the test file imports `data_pipeline.lacity_socrata` only — `conftest.py`'s app/db imports happen at session level but are not exercised because none of these tests touch the FastAPI surface).
- **`data/crashes_la/lacity_fixture.csv`** (NEW, 205 rows + header) — Synthetic LA City Socrata-shape rows. Coverage breakdown:
  - 4 special-marker rows (MIDBLOCK-001, INTERSECTION-001, OUTSIDE-SNAP-001, MULTI-SEV-001)
  - 6 SYN-FATAL rows (criterion a fatal cushion)
  - 60 SYN-INJURY rows (criterion a injury cushion)
  - 60 SYN-PDO rows (criterion a pdo cushion)
  - 75 SYN-MIX rows (realistic distribution; weighted 5:35:35 fatal:injury:pdo)

## Decisions Made

- **Plain `requests` over `sodapy`** — sodapy is unmaintained since 2022-08 (per 09-RESEARCH.md §3). The Socrata SoQL surface we need is `$where + $select + $order + $limit + $offset`, all expressible as a single `requests.get(_API_URL, params={...})` call. Adding a deprecated transitive dep is supply-chain debt with no benefit.
- **Two-condition pagination termination** — stop on empty response AND on partial page. The empty-response path catches the natural end (Socrata returns `[]` past the last record); the partial-page path catches the edge case where Socrata returns exactly `page_size` rows on the last call and the next call would also return `[]`. Either alone is correct in normal operation but pinning both makes the generator robust against off-by-one edge cases.
- **Token-not-logged enforced by static-analysis test** — the test reads the module source and asserts forbidden substrings are absent. Catches `logger.debug(headers, ...)` (which would dump the X-App-Token), not just `logger.debug(token)`. Codifies the T-9-03 mitigation as a regression guard.
- **Synthetic fixture (Option B) over live pull (Option A)** — D-09-06 bans live API hits in CI, and the worktree doesn't have a configured LACITY_APP_TOKEN. Synthesis with SEED=42 is reproducible (a future regeneration produces the same rows) and lets us hit all five D-09-07 criteria deterministically. The `dr_no` prefix scheme (SYN-, MIDBLOCK-, OUTSIDE-SNAP-, MULTI-SEV-, INTERSECTION-) makes the rows identifiable as synthetic AND targetable by 09-04 integration tests.

## Deviations from Plan

**None.** Plan 09-03 was executed exactly as written.

### Acceptance-Criteria Notes (informational, not deviations)

The plan's Task-1 acceptance criteria include two literal `grep -c` checks that overshoot by one due to docstring overlap (the same harmless artifact 09-01-SUMMARY documented):

- `grep -c "data.lacity.org/resource/d5tf-ez2w" data_pipeline/lacity_socrata.py` returns **2** (plan said 1). The URL appears once in the module docstring (`Dataset: https://data.lacity.org/resource/d5tf-ez2w.json`) and once as the `_API_URL` constant. The plan's `<action>` block explicitly required copying the SQL/Python "verbatim" including the docstring. The substantive endpoint constant exists exactly once; both occurrences are necessary.
- `grep -c "within_box(location_1" data_pipeline/lacity_socrata.py` returns **2** (plan said 1). Identical situation: docstring documents `bbox: ... uses Socrata within_box(location_1, ymin, xmin, ymax, xmax)` and the implementation uses `f"within_box(location_1, {ymin}, ..."`. Both are necessary; the verbatim-copy directive supersedes the literal grep count.

These are documented (not silently corrected) for orchestrator visibility — same precedent as 09-01-SUMMARY's "ON DELETE SET NULL" note.

### Total deviations: 0
### Impact on plan: None — Tasks 1 and 2 implemented exactly as specified.

## Issues Encountered

- **None.** Tests pass on first run; fixture coverage criteria all met on first generation.

## Threat Surface (per plan threat_model)

All three STRIDE entries from the plan threat_model were addressed:

- **T-9-03 (Information Disclosure — token leak):** Mitigated. Token is loaded via `os.environ.get` at module top (matches the project's Python `.env` parser pattern per memory pin); the module never logs the token (no `logger.{debug,info,warning,error}(token`, no `print(token`, no `logger.{debug,info}(headers`). Verified by `test_token_never_logged_or_printed` static-analysis test (regression guard).
- **T-9-04 (DoS — hammering Socrata):** Mitigated by design. `$limit=1000` page size matches the Mapillary precedent; the quarterly one-shot run is operator-driven (not cron in v0.4.0) so blast radius is bounded. With `LACITY_APP_TOKEN` set, the rate is 1000 req/hr per registered app — 144 reqs for the full ~144k-row dataset is well under the limit.
- **T-9-08 (Tampering — operator bbox injection):** Mitigated. `bbox` is typed `tuple[float, float, float, float] | None`; the implementation explicitly coerces each coordinate via `float(c)` before substitution into the f-string. No string concatenation of operator-controlled strings — only the literal `within_box(location_1, %f, %f, %f, %f)` template with type-validated numeric values.

No additional threat flags surfaced during execution.

## Self-Check: PASSED

- `data_pipeline/lacity_socrata.py` — FOUND
- `backend/tests/test_lacity_socrata.py` — FOUND
- `data/crashes_la/lacity_fixture.csv` — FOUND (205 rows, 16 KB)
- Commit `bbf0120` (Task 1 RED) — FOUND in `git log --oneline -10`
- Commit `87ccfad` (Task 1 GREEN feat) — FOUND in `git log --oneline -10`
- Commit `467ec4a` (Task 2 fixture feat) — FOUND in `git log --oneline -10`

```bash
$ test -f data_pipeline/lacity_socrata.py && echo FOUND
FOUND
$ test -f backend/tests/test_lacity_socrata.py && echo FOUND
FOUND
$ test -f data/crashes_la/lacity_fixture.csv && echo FOUND
FOUND
$ git log --oneline | grep -E "bbf0120|87ccfad|467ec4a"
467ec4a feat(09-03): add LA City crash CSV fixture (205 rows; D-09-07 a-e covered)
87ccfad feat(09-03): add data_pipeline/lacity_socrata.py paged Socrata client
bbf0120 test(09-03): add failing tests for lacity_socrata.iter_crashes
$ cd backend && pytest tests/test_lacity_socrata.py -x -q
.........                                                                [100%]
9 passed in 0.05s
```

## Next Phase Readiness

- **Plan 09-04 (`scripts/ingest_crashes.py` driver)** can now:
  - `from data_pipeline.lacity_socrata import iter_crashes` and call it with the locked D-09-01 window `iter_crashes("2019-03-01", "2024-03-01")` to drive live ingest
  - `csv.DictReader(open("data/crashes_la/lacity_fixture.csv"))` to drive integration tests against the committed fixture; rows have keys `{dr_no, date_occ, mocodes, latitude, longitude}` (latitude/longitude already flattened from Socrata's nested `location_1` for stdlib-only parsing)
  - Target marker rows by `dr_no` for criterion-specific assertions:
    - `MIDBLOCK-001` for "snap-to-midblock works"
    - `INTERSECTION-001` for "naive snap-match picks one of N approaches arbitrarily" (documented limitation)
    - `OUTSIDE-SNAP-001` for "outside-snap-radius row increments `dropped_outside_snap` counter"
    - `MULTI-SEV-001` for "multi-severity row resolves to `fatal` via Plan 09-02's mapper"
  - Rely on the `(source, source_record_id)` UNIQUE from migration 004 (Plan 09-01) for ON CONFLICT idempotency; `dr_no` IS the `source_record_id`
- **Phase 12 operator runbook** should document:
  - `LACITY_APP_TOKEN` is loaded via the project's Python `.env` parser (per memory pin: tokens contain pipes, never `source .env`)
  - The token is OPTIONAL (anonymous works at lower rate limit per D-09-20) but RECOMMENDED for production runs
  - The token is NEVER logged or echoed by `data_pipeline/lacity_socrata.py` (T-9-03 mitigation verified by static-analysis test)
- **Plan 09-02** (parallel wave-2 plan, snap helper + mocode mapper) is unaffected by 09-03 — neither plan touches the other's files; both depend only on 09-01.

---
*Phase: 09-crash-data-schema-la-city-ingest-naive-snap-match*
*Plan: 03*
*Completed: 2026-05-08*
