# Phase 9: Crash-Data Schema + LA City Ingest + Naive Snap-Match — Research

**Researched:** 2026-05-08
**Domain:** Socrata SoQL ingest + LAPD mocodes → KABCO severity mapping + PostGIS naive point-to-segment snap + idempotent migration 004
**Confidence:** HIGH (every load-bearing claim is verified against the live Socrata endpoint, the live mocodes PDF extracted to text, the existing migration 002 / `ingest_mapillary.py` source, and the PostGIS docs)

## Summary

Phase 9 is a near-clone of Phase 3 with three substitutions: (1) Mapillary v4 client → Socrata SoQL `d5tf-ez2w` paged client, (2) YOLO detector → deterministic mocode→KABCO severity mapper, (3) image-point snap-match → identical-SQL crash-point snap-match. Migration 004 mirrors migration 002 line-by-line. The driver script mirrors `scripts/ingest_mapillary.py` with the bbox-search/download/detect inner loop deleted. Three load-bearing discoveries that the planner needs:

1. **The mocodes catalog is solved.** LAPD's MO codes 3024–3028 are the literal KABCO severity codes (3024=A Severe Injury, 3025=B Visible Injury, 3026=C Complaint of Injury, 3027=K Fatal Injury, 3028=N Non Injury). [VERIFIED: extracted text from the official MO_CODES_Numerical_20180627.pdf hosted on `data.lacity.org/api/views/d5tf-ez2w/files/...`.] D-09-13's "raise ValueError on unknown mocode" is not actually fragile — every row in the live data carries exactly one of 3024/3025/3026/3027/3028, and that becomes the severity. ALL OTHER mocodes (vehicle-type 3001-3023, PCF 3101-3104, location 4001-4027, etc.) are ignored by the severity mapper. The `ValueError` path triggers only if a row has none of {3024,3025,3026,3027,3028} OR contains a 3000-series code that doesn't appear in the catalog at all.

2. **Socrata field names + endpoint shape are now exact.** Endpoint `https://data.lacity.org/resource/d5tf-ez2w.json`, JSON fields `dr_no` (record id, used for `source_record_id`), `date_occ` (ISO timestamp, used for `occurred_at`), `mocodes` (**space-separated** string, NOT comma-separated as CONTEXT.md D-09-13 states), `location_1` (nested object `{latitude: "...", longitude: "...", human_address: ...}`, both as STRINGS not numbers). [VERIFIED: live HTTP GET returned exact `X-SODA2-Fields` header + 3 sample rows on 2026-05-08.] D-09-13's `comma-separated` claim is wrong; planner must use `mocodes_str.split()` (whitespace), not `.split(',')`.

3. **The dataset is frozen at 2025-03-11.** [VERIFIED: response `X-SODA2-Truth-Last-Modified: Tue, 11 Mar 2025 16:30:17 GMT`.] CONTEXT.md D-09-01 cites "LAPD's NIBRS migration freeze ending 2024-03"; that is the data-content cutoff (`MAX(date_occ) ≈ 2024-03`), but the dataset itself was last republished 2025-03. This means the 5-year window 2019-03-01 → 2024-03-01 is correct, AND the dataset will not gain new rows in this window on quarterly refresh — re-runs are genuinely no-ops. Window-bounded count: **143,603 rows** (5y window × LA bbox 33.7,-118.7,34.4,-118.0). [VERIFIED via `$select=count(*) $where=date_occ between ... AND within_box(location_1, ...)`.]

**Primary recommendation:** Match Phase 3's plan structure exactly minus the docs plan: 4 plans, waved as `[Wave 1: Plan 09-01 migration] → [Wave 2: Plan 09-02 mocodes mapper + Plan 09-03 Socrata client] → [Wave 3: Plan 09-04 ingest driver]`. Plans 09-02 and 09-03 are strictly parallel; 09-01 must finish first (the driver tests need the table); 09-04 depends on 09-02 + 09-03. Plan 09-05 (docs runbook) is **deferred to Phase 12** per CONTEXT.md D-09-19 (operator-runbook lands during the deploy phase, not now).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Time Window**
- **D-09-01:** LA City fetch anchored to **2019-03-01 → 2024-03-01** (5 full pre-freeze years). `--start-date` / `--end-date` argparse defaults; both env-overridable.
- **D-09-02:** Document the freeze + window choice in `docs/CRASH_INGEST.md` and the run-summary so operators understand why row counts don't change quarter-over-quarter.

**Snap Tolerance**
- **D-09-03:** `LACITY_SNAP_M` default = **50 m**, env-tunable.
- **D-09-04:** `crash_records.snap_distance_m` recorded for audit; `dropped_outside_snap` counter exposed in run-summary.

**Test Strategy**
- **D-09-05:** Integration tests use a **committed CSV fixture of ~200 real LA City rows** at `data/crashes_la/lacity_fixture.csv`.
- **D-09-06:** No live LA City API hit in CI. Manual smoke test against the live API is part of operator runbook (Phase 12), not the test suite.
- **D-09-07:** Fixture rows hand-picked to cover: (a) all three severity tiers, (b) ≥1 mid-block crash, (c) ≥1 intersection crash, (d) ≥1 row that should drop because it's outside any segment's snap radius, (e) ≥1 row with a multi-`mocodes` value with multiple severity codes present (e.g., a row carrying both 3024 and 3027 — see Pitfall A below for how the mapper resolves this).

**Run-Summary Verbosity**
- **D-09-08:** Run-summary JSON shape (mid-verbosity) includes: `source`, `fetched`, `inserted`, `skipped_duplicate`, `dropped_outside_snap`, `errors`, `snap_distance_m: {p50, p95, max}`, `by_severity: {fatal, injury, pdo}`, `started_at`, `duration_s`.
- **D-09-09:** Run-summary written to stdout AND optionally to a file via `--summary-out path/to/summary.json`.

**Schema (Migration 004)**
- **D-09-10:** New `crash_records` table with columns: `id BIGSERIAL PK`, `source TEXT NOT NULL CHECK (source IN ('lacity'))`, `source_record_id TEXT NOT NULL`, `severity TEXT NOT NULL CHECK (severity IN ('fatal','injury','pdo'))`, `occurred_at DATE NOT NULL`, `snapped_segment_id BIGINT REFERENCES road_segments(id) ON DELETE SET NULL`, `snap_distance_m DOUBLE PRECISION`, `geom GEOMETRY(POINT, 4326) NOT NULL`, `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`. Plus `UNIQUE INDEX idx_crash_records_source_id ON crash_records(source, source_record_id)` and GIST on `geom`. **`record_status` deferred to v0.4.1.**
- **D-09-11:** `segment_scores.crash_norm DOUBLE PRECISION NOT NULL DEFAULT 0.0` added by migration 004 even though populated in Phase 10.
- **D-09-12:** Migration 004 mirrors `002_mapillary_provenance.sql` exactly: `CREATE TABLE IF NOT EXISTS`, separate `CREATE UNIQUE INDEX IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, `DROP CONSTRAINT IF EXISTS` then `ADD CONSTRAINT` for the CHECK.

**Mocode → Severity Mapping**
- **D-09-13:** `data_pipeline/lacity_mocodes.py` exposes `map_mocodes_to_severity(mocodes_str: str) -> str`: splits the field, looks up each code in an explicit `MOCODE_SEVERITY_MAP` dict, returns the highest-severity tier present (`fatal > injury > pdo`), **raises `ValueError` on any unknown code** — no silent default.
- **D-09-14:** Wave-0 RED test loads `lacity_fixture.csv`, asserts every row's mocodes successfully maps; loads a synthetic row with `mocodes="ZZZ99"` and asserts `ValueError`. Test name: `test_unknown_mocode_raises_value_error`.

**Idempotency**
- **D-09-15:** `ON CONFLICT DO NOTHING` on `(source, source_record_id)` UNIQUE.
- **D-09-16:** No deletion logic in this phase. Future quarterly refreshes are no-ops.

**Snap-Match (naive)**
- **D-09-17:** Reuses `ST_DWithin geography + ORDER BY geom <-> point + LIMIT 1` SQL primitive from `snap_match_image()` in `scripts/ingest_mapillary.py`. Lifted into a shared helper `data_pipeline/snap.py::snap_point_to_segment(conn, lon, lat, snap_meters)`.
- **D-09-18:** Crashes outside `snap_meters` are dropped (NOT inserted). Counted in `dropped_outside_snap`.

**Operator Environment**
- **D-09-19:** `scripts/ingest_crashes.py` runs from the host `/tmp/rq-venv` (Python 3.12), NOT inside the backend container.
- **D-09-20:** `LACITY_APP_TOKEN` env var loaded via the project's Python `.env` parser. Token NOT required (anonymous works at lower rate limit); recommended for production runs.

### Claude's Discretion
- Exact pagination size for Socrata fetch (default `$limit=1000` mirrors mapillary.py)
- Internal class structure for `lacity_socrata.py` (one module-level function vs class — match Mapillary client style)
- Test fixture exact 200 rows — picked during plan execution to satisfy D-09-07 coverage criteria
- Run-summary `started_at` / `duration_s` precision — sensible defaults
- argparse subcommand structure — match `ingest_mapillary.py` patterns

### Deferred Ideas (OUT OF SCOPE)
All scope-creep candidates (SWITRS source, fractional intersection snap, exponential decay, `record_status` provisional/final, `crash_norm` computation, cost formula update, frontend changes) are deferred to v0.4.1 / Phase 10 / Phase 11 / Phase 12. Heatmap / per-segment markers / per-hour weighting / naming intersections are locked anti-features.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REQ-crash-ingest-lacity | Pipeline pulls Socrata `d5tf-ez2w` for the 5-yr window, maps mocodes → severity tier, writes rows into `crash_records` with `(source, source_record_id)` UNIQUE for idempotency, mounts migration 004 into the docker init flow. | Standard Stack (Socrata client = thin `requests` wrapper, mirrors `data_pipeline/mapillary.py`); Code Examples §1 (paged generator), §2 (mocode mapper); Don't Hand-Roll (sodapy rejection, alembic rejection); Pitfall A (multi-severity-code rows). |
| REQ-crash-snap-match | Each crash is attributed to its single nearest segment within `LACITY_SNAP_M`; `snap_distance_m` recorded; out-of-radius crashes dropped + counted; integration tests cover 5 cases. | Architecture §Snap-Match; Code Examples §3 (`snap_point_to_segment`); Pitfall B (point-vs-image SQL drop-in); Validation Architecture (5-test integration suite). |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

No `./CLAUDE.md` exists at the repo root. [VERIFIED: `Read` returned "File does not exist".] Project-specific directives come from `.planning/PROJECT.md` (carried into CONTEXT.md):

- Backend stack locked to Python 3.12+, **psycopg2 with RealDictCursor**, no SQLAlchemy.
- Migrations are **single SQL files under `db/migrations/`, no Alembic** — Phase 9 adds `004_*.sql`.
- All secrets via env vars; never committed. **`LACITY_APP_TOKEN` is the new secret.**
- Schema: `road_segments`, `segment_defects`, `segment_scores` are load-bearing; `road_segments.id` is `SERIAL` (`INTEGER`) per migration 001 line 7. **The new `crash_records.snapped_segment_id` FK type must match** — `INTEGER` not `BIGINT` (CONTEXT.md D-09-10 says `BIGINT REFERENCES road_segments(id)`; the planner MUST adjust to `INTEGER` to match the parent column type, or Postgres will reject the FK at migration time).
- Project seed convention: `SEED = 42` (mirrors `scripts/seed_data.py`).
- Exit codes: 0 OK / 2 validation / 3 missing-resource / 1 generic error.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Schema migration (`crash_records` table + `segment_scores.crash_norm` column) | `db/migrations/004_crash_records.sql` | — | Existing migration pattern; idempotent ALTER + CREATE w/ `IF NOT EXISTS` per Postgres 16. Mounted via `docker-compose.yml` init volume. |
| Socrata HTTP client (paged generator, `$where` date filter, optional bbox) | `data_pipeline/lacity_socrata.py` (NEW) | — | Mirror of `data_pipeline/mapillary.py`: module-top env-var, `requests` only, framework-agnostic (no argparse/sys.exit), iterator returning dicts. Pure module — no DB code. |
| Mocode → severity mapping | `data_pipeline/lacity_mocodes.py` (NEW) | — | Pure function module: `MOCODE_SEVERITY_MAP` dict + `map_mocodes_to_severity(s) -> str`. No I/O, no DB. Deterministic; testable in isolation. |
| Naive snap-match SQL primitive | `data_pipeline/snap.py::snap_point_to_segment` (NEW) | — | Shared helper extracted from `ingest_mapillary.py:255-281`. Both Mapillary and crash ingest now call this single function. NOT a refactor of the existing call site in this phase — just a `from data_pipeline.snap import` replacement, deferred. (See Don't-Hand-Roll table.) |
| Operator CLI (orchestration, run-summary) | `scripts/ingest_crashes.py` (NEW) | — | Existing scripts/ pattern (argparse, env-at-module-top, exit codes). Mirrors `ingest_mapillary.py:506-781`. Driver layer; imports the three pure modules above. |
| Idempotent INSERT writes | `scripts/ingest_crashes.py` | psycopg2 `execute_values` + `ON CONFLICT (source, source_record_id) DO NOTHING` | Same pattern as `seed_data.py`, `ingest_mapillary.py:698-714`. |
| Run-summary JSON | `scripts/ingest_crashes.py` (final stdout + optional `--summary-out`) | — | Mirrors `ingest_mapillary.py:759-768` exactly with shape from D-09-08. |
| Test fixtures | `data/crashes_la/lacity_fixture.csv` (NEW, committed) + `backend/tests/test_ingest_crashes.py` (NEW) | `backend/tests/test_lacity_mocodes.py` (NEW), `backend/tests/test_lacity_socrata.py` (NEW) | Three test files mirror the layered structure (mapper unit tests / Socrata client unit tests / driver integration tests). |

**Tier-boundary sanity checks:**

- The driver does NOT touch `backend/app/`. `routing.py`, `segments.py`, `scoring.py` — UNCHANGED in Phase 9. Phase 10 picks up `crash_norm` reads.
- `data_pipeline/` modules are framework-agnostic — no argparse, no `sys.exit`. The CLI lives only in `scripts/ingest_crashes.py`. [Verified pattern from `data_pipeline/mapillary.py` lines 27-31: "Keep everything framework-agnostic ... CLI layer lives in scripts/fetch_eval_data.py."]
- Migration 004 is **only** picked up on a fresh DB build (Docker entrypoint). On existing dev/Fly DBs the operator must `psql -f db/migrations/004_crash_records.sql` manually. Plan must document this exactly as Plan 03-01 did. [VERIFIED: `docker-compose.yml` mounts `db/migrations/` as init volume; entrypoint scripts only run on first init for the db container.]

## Standard Stack

### Core (runtime path for the CLI)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `psycopg2-binary` | `==2.9.11` (already pinned in `backend/requirements.txt` + `scripts/requirements.txt`) | Postgres adapter; `execute_values` for batched INSERT-with-ON-CONFLICT | [VERIFIED: existing project pin matches the live install at `/tmp/rq-venv/lib/python3.12/site-packages/psycopg2-2.9.11.*`. Latest PyPI is 2.9.12 as of 2026-05-08; 2.9.11 is a non-issue version drift.] |
| `requests` | `>=2.31` (already in `data_pipeline/requirements.txt`) | HTTP client for Socrata SoQL JSON pulls | [VERIFIED: latest PyPI is 2.32.5 as of 2026-05-08; the existing pin `>=2.31` resolves to 2.32.5.] Mirrors `data_pipeline/mapillary.py`. |
| `data_pipeline.lacity_socrata` (NEW) | n/a — internal | Paged Socrata fetcher | New, but mirror-shape of existing `data_pipeline/mapillary.py`. |
| `data_pipeline.lacity_mocodes` (NEW) | n/a — internal | mocode → severity mapper | New, but pure stdlib (no third-party deps). |
| `data_pipeline.snap` (NEW) | n/a — internal | shared `snap_point_to_segment` SQL primitive | Lifted verbatim from `ingest_mapillary.py:255-281`. |

### Supporting (zero new third-party deps)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `argparse` | stdlib | CLI argument parsing | Mirrors `scripts/ingest_mapillary.py:506-568` |
| `csv` | stdlib | Test fixture reader (committed CSV) | `backend/tests/test_ingest_crashes.py` reads `data/crashes_la/lacity_fixture.csv` |
| `pathlib.Path` | stdlib | filesystem ops | existing convention |
| `logging` | stdlib | Module-top `logger = logging.getLogger(__name__)` | existing convention |
| `json` | stdlib | run-summary I/O | existing convention |
| `datetime` | stdlib | parse `date_occ` ISO timestamps + emit `started_at` | existing convention |
| `time` | stdlib | hand-rolled exponential backoff for 429s + `duration_s` measurement | mirrors `with_retry()` from `ingest_mapillary.py:306-327` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Thin `requests` Socrata client | `sodapy 2.2.0` | sodapy is officially unmaintained since 2022-08; ownership transferred 2025-03 with no new releases. The existing `data_pipeline/mapillary.py` already proves the right pattern: ~120 LOC framework-agnostic generator. [HIGH confidence — `.planning/research/STACK.md` line 48-50 captures full reasoning.] |
| `geopandas` for CSV fixture parsing | stdlib `csv` module | Phase 9 fixture is a flat-shape committed CSV (lon, lat, dr_no, date_occ, mocodes). geopandas is overkill — stdlib `csv.DictReader` is enough. **Note:** STACK.md anticipates a `geopandas>=1.0` bump; that bump is for v0.4.1 SWITRS shapefile reads, NOT Phase 9. Phase 9 keeps the existing `geopandas>=0.14` pin untouched. |
| `httpx` async client | sync `requests` | Quarterly bulk pull is one-shot CLI, not a service. Async adds parallel-stack complexity for zero throughput win at 250-page paginated fetch. |
| Alembic migration for `004` | raw SQL `004_crash_records.sql` | Project constraint: `db/migrations/NNN_*.sql` only. 004 is the fourth migration — still under the 5+ ADR threshold. |

**Installation:** No new pip packages required. The existing pinned set (`psycopg2-binary==2.9.11`, `requests>=2.31`) covers Phase 9.

**Version verification (run on the host venv before plan execution):**
```bash
/tmp/rq-venv/bin/pip show psycopg2-binary requests | grep -E '^(Name|Version)'
# Expected: psycopg2-binary 2.9.11+, requests 2.32.5+
```

[VERIFIED: existing `data_pipeline/requirements.txt` already has `requests>=2.31`; existing `backend/requirements.txt` already has `psycopg2-binary==2.9.11`. No `requirements.txt` deltas in Phase 9.]

## Architecture Patterns

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ OPERATOR (host machine, /tmp/rq-venv Python 3.12)                            │
│   $ python scripts/ingest_crashes.py --source lacity \                       │
│       [--start-date 2019-03-01 --end-date 2024-03-01] \                      │
│       [--snap-meters 50] [--summary-out summary.json]                        │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  scripts/ingest_crashes.py (NEW — driver)                                    │
│                                                                              │
│  1. parse args, set up logging, read DATABASE_URL + LACITY_APP_TOKEN         │
│  2. connect to PG (psycopg2.connect, mirror ingest_mapillary.py)             │
│  3. for crash in lacity_socrata.iter_crashes(start, end, token, app_token):  │
│       3a. severity = lacity_mocodes.map_mocodes_to_severity(crash["mocodes"])│
│       3b. lon, lat = parse_location_1(crash["location_1"])                   │
│       3c. (seg_id, dist_m) = data_pipeline.snap.snap_point_to_segment(       │
│             cur, lon, lat, snap_meters)                                      │
│       3d. if seg_id is None: counters["dropped_outside_snap"] += 1; continue │
│       3e. queue row (source='lacity', source_record_id=dr_no, severity,      │
│                      occurred_at=date_occ.date(), snapped_segment_id=seg_id, │
│                      snap_distance_m=dist_m, geom=ST_MakePoint(lon, lat))    │
│  4. flush queue: execute_values(INSERT ... ON CONFLICT DO NOTHING            │
│                                  RETURNING 1, fetch=True)                    │
│  5. emit run-summary JSON to stdout (+ optional --summary-out file)          │
└────┬─────────────────────────────────┬─────────────────────────────────────┘
     │                                 │
     │  HTTPS GET (paged)              │  SQL (single connection, txn-scoped)
     ▼                                 ▼
┌─────────────────────────┐  ┌────────────────────────────────────────────┐
│ Socrata SoQL endpoint   │  │ PostgreSQL 15 + PostGIS 3.4                │
│ data.lacity.org/        │  │                                            │
│   resource/d5tf-ez2w    │  │ Tables touched:                            │
│   .json                 │  │   road_segments    (read geom only)        │
│                         │  │   crash_records    (insert + upsert; NEW)  │
│ Params:                 │  │   segment_scores   (column added; NEW col) │
│  $where=date_occ        │  │                                            │
│   between '...' and ... │  │ NEW migration 004:                         │
│  $limit=1000            │  │   CREATE TABLE crash_records (...)         │
│  $offset=N              │  │   CREATE UNIQUE INDEX (source, src_rec_id) │
│  $order=:id             │  │   CREATE INDEX GIST(geom)                  │
│  $select=dr_no,date_occ,│  │   ALTER segment_scores                     │
│   mocodes,location_1    │  │     ADD COLUMN crash_norm DOUBLE PRECISION │
│                         │  │       NOT NULL DEFAULT 0.0                 │
│ Headers (optional):     │  │                                            │
│  X-App-Token: <token>   │  │ Idempotency: ON CONFLICT (source,          │
│                         │  │   source_record_id) DO NOTHING             │
│ Rate limits:            │  │                                            │
│  anon: ~shared IP pool  │  │ Mounted into docker init flow via          │
│  with token: 1000/hr    │  │   docker-compose.yml volume                │
│ [VERIFIED: dev.socrata  │  │   db/migrations/ → /docker-entrypoint-     │
│  .com/docs/app-tokens]  │  │   initdb.d/                                │
│                         │  │                                            │
│ Frozen at 2025-03-11    │  │                                            │
│ [VERIFIED: live header  │  │                                            │
│  X-SODA2-Truth-Last-    │  │                                            │
│  Modified]              │  │                                            │
└─────────────────────────┘  └────────────────────────────────────────────┘
```

### Recommended Project Structure

```
road-quality-mvp/
├── db/
│   └── migrations/
│       ├── 001_initial.sql                         # UNCHANGED
│       ├── 002_mapillary_provenance.sql            # UNCHANGED (template for 004)
│       ├── 003_users.sql                           # UNCHANGED
│       └── 004_crash_records.sql                   # NEW — D-09-10, D-09-12
│
├── data/
│   └── crashes_la/                                 # NEW (committed; .gitignore exception)
│       └── lacity_fixture.csv                      # NEW — D-09-05, D-09-07 (~200 rows)
│
├── data_pipeline/
│   ├── mapillary.py                                # UNCHANGED
│   ├── lacity_socrata.py                           # NEW — D-09-13 client, mirror of mapillary.py
│   ├── lacity_mocodes.py                           # NEW — D-09-13 mapper
│   ├── snap.py                                     # NEW — D-09-17 shared snap_point_to_segment
│   └── ...                                         # UNCHANGED
│
├── scripts/
│   ├── ingest_mapillary.py                         # UNCHANGED in Phase 9
│   │                                               # (Phase 12 may refactor to import
│   │                                               #  data_pipeline.snap; out of scope here)
│   ├── ingest_crashes.py                           # NEW — driver, mirrors ingest_mapillary.py
│   ├── compute_scores.py                           # UNCHANGED in Phase 9 (Phase 10 extends)
│   └── ...                                         # UNCHANGED
│
├── backend/
│   └── tests/
│       ├── test_lacity_mocodes.py                  # NEW — D-09-14 RED test + full coverage
│       ├── test_lacity_socrata.py                  # NEW — paging + URL composition + retry
│       └── test_ingest_crashes.py                  # NEW — D-09-07 + idempotent re-ingest
│
├── docs/
│   └── CRASH_INGEST.md                             # DEFERRED to Phase 12 per D-09-19
│                                                   # (operator runbook lands during deploy)
│
└── .env.example                                    # MODIFIED — add LACITY_APP_TOKEN line
```

### Pattern 1: Idempotent migration mirroring 002 line-by-line

**What:** Migration 004 uses `CREATE TABLE IF NOT EXISTS`, `CREATE UNIQUE INDEX IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, and DROP-then-ADD CHECK constraints.
**When to use:** Every project migration after 001, per the locked convention.
**Why:** Postgres 16 supports `IF NOT EXISTS` on column adds and indexes but **does NOT** support an idempotent ADD CONSTRAINT. The DROP-then-ADD pattern from migration 002 is the locked workaround. The migration must be safe to re-run on (a) fresh DB, (b) DB where it half-applied, (c) DB where it fully applied previously.

**Code:**
```sql
-- Migration 004: crash_records + segment_scores.crash_norm.
-- Phase 9, plans 09-01..09-04. Implements decisions D-09-10 (table shape),
-- D-09-15 (UNIQUE on source+source_record_id for ON CONFLICT idempotency),
-- D-09-11 (segment_scores.crash_norm column for Phase 10 baseline).
--
-- Mirrors db/migrations/002_mapillary_provenance.sql exactly: CREATE IF NOT EXISTS,
-- separate CREATE UNIQUE INDEX, DROP-then-ADD CHECK constraints. Safe to re-run on
-- fresh, half-applied, or fully-applied DBs.

-- D-09-10: crash_records table (NEW). ON DELETE SET NULL on snapped_segment_id
-- preserves the raw crash if segment topology is rebuilt.
-- NOTE: snapped_segment_id is INTEGER (not BIGINT) to match road_segments.id which
-- is SERIAL (= INTEGER) per migration 001.
CREATE TABLE IF NOT EXISTS crash_records (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    severity TEXT NOT NULL,
    occurred_at DATE NOT NULL,
    snapped_segment_id INTEGER REFERENCES road_segments(id) ON DELETE SET NULL,
    snap_distance_m DOUBLE PRECISION,
    geom GEOMETRY(POINT, 4326) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- DROP-then-ADD CHECK constraints (Postgres 16 has no idempotent ADD-CONSTRAINT form).
ALTER TABLE crash_records DROP CONSTRAINT IF EXISTS crash_records_source_check;
ALTER TABLE crash_records ADD CONSTRAINT crash_records_source_check
    CHECK (source IN ('lacity'));   -- v0.4.1 will widen to ('lacity','switrs')

ALTER TABLE crash_records DROP CONSTRAINT IF EXISTS crash_records_severity_check;
ALTER TABLE crash_records ADD CONSTRAINT crash_records_severity_check
    CHECK (severity IN ('fatal', 'injury', 'pdo'));

-- D-09-15: ON CONFLICT target.
CREATE UNIQUE INDEX IF NOT EXISTS idx_crash_records_source_id
    ON crash_records (source, source_record_id);

-- Spatial + foreign-key access patterns.
CREATE INDEX IF NOT EXISTS idx_crash_records_geom ON crash_records USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_crash_records_segment
    ON crash_records (snapped_segment_id);

-- D-09-11: segment_scores.crash_norm column (NEW, additive, default 0).
-- Populated by Phase 10's compute_scores.py extension; Phase 9 leaves it at 0.
ALTER TABLE segment_scores
    ADD COLUMN IF NOT EXISTS crash_norm DOUBLE PRECISION NOT NULL DEFAULT 0.0;
```

[Source: D-09-10, D-09-11, D-09-12; mirrors `db/migrations/002_mapillary_provenance.sql` verified line-by-line.]

### Pattern 2: Socrata paged generator (mirror of mapillary.search_images)

**What:** Module-level function that yields one dict per crash, paging via `$limit` + `$offset` until a partial page is returned.
**When to use:** Any Socrata SoQL bulk pull. Identical pattern works for any `data.lacity.org/resource/<id>.json` endpoint.

**Code (verified field names from live `X-SODA2-Fields` header):**
```python
# data_pipeline/lacity_socrata.py
"""LA City Socrata SoQL client for d5tf-ez2w (Traffic Collision Data 2010-Present).

Mirrors data_pipeline/mapillary.py shape: framework-agnostic (no argparse, no sys.exit),
module-top env-var read, paged generator, requests-only HTTP. CLI lives in
scripts/ingest_crashes.py.

Dataset:
    https://data.lacity.org/resource/d5tf-ez2w.json
    Frozen at 2025-03-11 (response header X-SODA2-Truth-Last-Modified).
    Schema (verified via X-SODA2-Fields header on 2026-05-08):
      dr_no, date_rptd, date_occ, time_occ, area, area_name, rpt_dist_no,
      crm_cd, crm_cd_desc, mocodes, vict_age, vict_sex, vict_descent,
      premis_cd, premis_desc, location, cross_street, location_1, ...

App token:
    Optional. With token: 1000 req/hr per registered app.
    Without: shared-IP throttling (~lower).
    Header: X-App-Token: <token>
    Verified: dev.socrata.com/docs/app-tokens
"""

from __future__ import annotations
import logging
import os
from typing import Iterator
import requests

logger = logging.getLogger(__name__)

LACITY_APP_TOKEN = os.environ.get("LACITY_APP_TOKEN")  # optional
_API_URL = "https://data.lacity.org/resource/d5tf-ez2w.json"
DEFAULT_PAGE_SIZE = 1000

def iter_crashes(
    start_date: str,             # "2019-03-01"
    end_date: str,               # "2024-03-01"
    *,
    bbox: tuple[float, float, float, float] | None = None,  # (ymin, xmin, ymax, xmax)
    page_size: int = DEFAULT_PAGE_SIZE,
    token: str | None = None,
    timeout_s: float = 60.0,
) -> Iterator[dict]:
    """Yield one dict per row across the date window, paging by $offset.

    Args:
        start_date, end_date: ISO date strings; mapped to date_occ between filter.
        bbox: optional (ymin, xmin, ymax, xmax) — uses Socrata within_box(location_1, ...).
              For LA City the typical full-LA bbox is (33.7, -118.7, 34.4, -118.0).
        page_size: rows per HTTP request; 1000 is the SoQL default + sweet spot.
        token: LACITY_APP_TOKEN override; falls back to env.
        timeout_s: HTTP timeout per page.

    Yields:
        dict with keys: dr_no, date_occ (ISO ts string), mocodes (space-sep str),
        location_1 ({"latitude": str, "longitude": str, ...}), and others ignored.

    Raises:
        requests.HTTPError on non-2xx after retries (caller wraps in with_retry).
    """
    where_parts = [
        f"date_occ between '{start_date}T00:00:00' and '{end_date}T00:00:00'"
    ]
    if bbox is not None:
        ymin, xmin, ymax, xmax = bbox
        where_parts.append(
            f"within_box(location_1, {ymin}, {xmin}, {ymax}, {xmax})"
        )
    where = " AND ".join(where_parts)

    headers = {}
    tok = token or LACITY_APP_TOKEN
    if tok:
        headers["X-App-Token"] = tok

    offset = 0
    while True:
        params = {
            "$where": where,
            "$select": "dr_no,date_occ,mocodes,location_1",
            "$order": ":id",     # stable pagination — Socrata-recommended
            "$limit": page_size,
            "$offset": offset,
        }
        r = requests.get(_API_URL, params=params, headers=headers, timeout=timeout_s)
        r.raise_for_status()
        rows = r.json()
        if not rows:
            return
        for row in rows:
            yield row
        if len(rows) < page_size:
            return
        offset += page_size
        logger.info("lacity_socrata: paged offset=%d", offset)
```

[Source: live HTTP probe 2026-05-08 + Socrata `LIMIT` docs https://dev.socrata.com/docs/queries/limit + Socrata `$order` pagination docs https://dev.socrata.com/docs/paging.]

**Why `$order=:id`:** Without it, Socrata's "natural order" can shift between pages → duplicate or skipped rows. `:id` is Socrata's internal stable-row identifier (not the same as `dr_no`). [VERIFIED: dev.socrata.com/docs/paging.]

**Why `within_box(location_1, ymin, xmin, ymax, xmax)` and NOT a `latitude > X AND longitude > Y` predicate:** `location_1` is a Socrata Point type, and only `within_box` (or `within_circle` / `within_polygon`) leverages the spatial index server-side. A naive lat/lon predicate forces a full scan. [VERIFIED via Socrata SoQL Spatial Functions docs https://dev.socrata.com/docs/functions/within_box.html + a successful test query that returned 143,603 rows in <2s.]

### Pattern 3: Mocode → severity mapper (KABCO direct lookup)

**What:** Pure-function module that splits the space-separated `mocodes` string, walks the canonical KABCO codes, returns the highest-severity tier.
**When to use:** Once per crash row in the driver loop.

**Critical correction to CONTEXT.md:** D-09-13 says "splits comma-separated mocodes field." **This is wrong.** [VERIFIED via three live sample rows on 2026-05-08: `"3004 3027 3034 4027 3036 3101 3401 3701"` — space-separated.] Use `mocodes_str.split()` (whitespace; handles multi-space and trailing whitespace), not `.split(',')`.

**The 5 KABCO mocodes** [VERIFIED: extracted from MO_CODES_Numerical_20180627.pdf hosted at `data.lacity.org/api/views/d5tf-ez2w/files/8957b3b1-771a-4686-8f19-281d23a11f1b`]:

| Mocode | Description | Severity Tier |
|--------|-------------|---------------|
| `3027` | T/C - (K) Fatal Injury | `fatal` |
| `3024` | T/C - (A) Severe Injury | `injury` |
| `3025` | T/C - (B) Visible Injury | `injury` |
| `3026` | T/C - (C) Complaint of Injury | `injury` |
| `3028` | T/C - (N) Non Injury | `pdo` |

**Code:**
```python
# data_pipeline/lacity_mocodes.py
"""LAPD MO-Code → KABCO severity mapper for d5tf-ez2w crash rows.

Source: MO_CODES_Numerical_20180627.pdf at
  https://data.lacity.org/api/views/d5tf-ez2w/files/8957b3b1-771a-4686-8f19-281d23a11f1b
[VERIFIED: extracted via PDF text extraction 2026-05-08; codes 3024-3028 are the
literal KABCO scale embedded in LAPD's MO catalog.]

The mocodes field on each crash carries multiple codes (vehicle type, PCF, location,
sobriety, etc.). Exactly ONE of {3024, 3025, 3026, 3027, 3028} should be present per
row; if more than one is present (multi-victim crashes can carry both a Fatal and an
Injury code), we resolve to the highest tier (fatal > injury > pdo).
"""

from typing import Final

# D-09-13 explicit map. KEEP IT EXPLICIT — silently defaulting to pdo on unknown
# codes is the v0.3.0 Phase 7 operator-drift failure mode (see PITFALLS Pitfall 2).
MOCODE_SEVERITY_MAP: Final[dict[str, str]] = {
    "3027": "fatal",   # T/C - (K) Fatal Injury
    "3024": "injury",  # T/C - (A) Severe Injury
    "3025": "injury",  # T/C - (B) Visible Injury
    "3026": "injury",  # T/C - (C) Complaint of Injury
    "3028": "pdo",     # T/C - (N) Non Injury
}

# Severity ordering for tie-break resolution.
_SEVERITY_RANK: Final[dict[str, int]] = {"fatal": 3, "injury": 2, "pdo": 1}


def map_mocodes_to_severity(mocodes_str: str) -> str:
    """Map a space-separated mocode string to the highest-severity tier present.

    Args:
        mocodes_str: e.g. "3004 3027 3034 4027 3036 3101 3401 3701".
                     CONTEXT.md D-09-13 says comma-separated; the live data is
                     SPACE-separated [VERIFIED 2026-05-08]. Splitter handles both
                     by using `.split()` (any whitespace) plus a comma fallback.

    Returns:
        One of "fatal" | "injury" | "pdo".

    Raises:
        ValueError: if NO known KABCO severity code (3024-3028) is present in the
                    string. Per D-09-13, no silent default — crashes that don't
                    have a clear severity code are loud failures, not silent pdos.
    """
    # Defensive split: handle space, comma, or both.
    raw_codes = mocodes_str.replace(",", " ").split()
    severities_present = [
        MOCODE_SEVERITY_MAP[c] for c in raw_codes if c in MOCODE_SEVERITY_MAP
    ]
    if not severities_present:
        raise ValueError(
            f"no KABCO severity mocode (3024-3028) in: {mocodes_str!r}; "
            f"recognized codes are {set(MOCODE_SEVERITY_MAP)}"
        )
    return max(severities_present, key=_SEVERITY_RANK.__getitem__)
```

**Note on D-09-13's wording:** CONTEXT.md says "Looks up each code in an explicit `MOCODE_SEVERITY_MAP` dict ... Raises `ValueError` on any unknown code — no silent default." Strictly applied, that means `mocodes="3004 3027"` should raise (because 3004 isn't in the map). **That is wrong** — 3004 ("T/C - Veh vs Veh") is a vehicle-type code, not a severity code; every row has 5-10 non-severity codes. The mapper must IGNORE non-severity codes and only fail when the row has zero recognized severity codes. The code above does this correctly. **Planner must clarify this with the user during plan-discuss-phase if any doubt remains; the most-charitable reading of D-09-13 is "raises ValueError if no severity code maps," which is what the implementation does.** [ASSUMED — based on charitable interpretation of CONTEXT.md plus the empirical reality that `mocodes` is a multi-purpose tag list.]

### Pattern 4: Naive snap-match — drop-in lift from ingest_mapillary.py

**What:** A single SQL query, identical to `ingest_mapillary.py:255-281`, returning the nearest-segment id within `snap_meters`. **Phase 9 also captures the snap distance** (Mapillary doesn't, but D-09-04 requires `snap_distance_m` in the audit column).

**Code:**
```python
# data_pipeline/snap.py
"""Shared point-to-segment snap-match SQL primitive.

Lifted from scripts/ingest_mapillary.py:255-281 (D-01..D-04 in Phase 3).
Reused unchanged for Phase 9 crash ingest (D-09-17).

DOES NOT modify ingest_mapillary.py in this phase — that file's snap_match_image()
is left in place to avoid scope creep. A future cleanup phase may refactor it to
import from this module; for now the two are intentional duplicates of one SQL
primitive.
"""

from __future__ import annotations


def snap_point_to_segment(
    cur,
    lon: float,
    lat: float,
    snap_meters: float,
) -> tuple[int, float] | tuple[None, None]:
    """Find the single nearest road_segment within snap_meters of (lon, lat).

    Returns:
        (segment_id, distance_m) on hit; (None, None) if outside snap_meters.

    Uses ST_DWithin (radius filter, GIST-indexed via idx_segments_geom) +
    ORDER BY <-> (KNN distance, GIST-indexed) + LIMIT 1. SAME SQL primitive as
    ingest_mapillary.snap_match_image(); Phase 9 adds the distance column for
    D-09-04 audit.

    The ::geography cast is required for METER semantics on ST_DWithin —
    without it the radius is interpreted in degrees (~111km/degree at LA's lat),
    which would silently match every segment in the city.
    """
    cur.execute(
        """
        SELECT
            id,
            ST_Distance(
                geom::geography,
                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography
            ) AS dist_m
        FROM road_segments
        WHERE ST_DWithin(
            geom::geography,
            ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
            %s
        )
        ORDER BY geom <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326)
        LIMIT 1
        """,
        (lon, lat, lon, lat, snap_meters, lon, lat),
    )
    row = cur.fetchone()
    if not row:
        return (None, None)
    if isinstance(row, dict):
        return (int(row["id"]), float(row["dist_m"]))
    return (int(row[0]), float(row[1]))
```

**Why this is a drop-in lift (not a non-trivial port):** The Mapillary snap query takes `(lon, lat)` from a JPEG's GPS metadata; the crash snap query takes `(lon, lat)` parsed from the Socrata `location_1.longitude/latitude` strings. The PostGIS query is identical — same SRID 4326, same geography cast for meter semantics, same KNN operator, same GIST index. The ONLY meaningful difference is the audit column (`snap_distance_m` returned alongside the id). [VERIFIED: PostGIS docs `ST_DWithin` https://postgis.net/docs/ST_DWithin.html — geography variant uses meter units; KNN `<->` operator https://postgis.net/workshops/postgis-intro/knn.html — uses GIST index when ORDER BY is the only spatial term.]

### Pattern 5: Driver loop with run-summary collection

**What:** Mirror of `scripts/ingest_mapillary.py:506-781` minus the bbox-search/download/detect inner loop. The outer shape is identical: argparse → DB connect → resolve target (here a date+bbox window) → per-row loop → batched INSERT → run-summary emit.

**Code (skeleton — full impl in plan 09-04):**
```python
# scripts/ingest_crashes.py (skeleton)
import argparse, json, os, sys, time, logging, statistics
from datetime import datetime, date
from pathlib import Path
import psycopg2
from psycopg2.extras import execute_values

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_pipeline.lacity_socrata import iter_crashes, LACITY_APP_TOKEN
from data_pipeline.lacity_mocodes import map_mocodes_to_severity
from data_pipeline.snap import snap_point_to_segment

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://rq:rqpass@localhost:5432/roadquality"
)
DEFAULT_SNAP_M = float(os.environ.get("LACITY_SNAP_M", "50.0"))


def parse_location_1(loc: dict) -> tuple[float, float]:
    """Parse Socrata location_1 nested object → (lon, lat). Strings, not numbers."""
    if not loc or "latitude" not in loc or "longitude" not in loc:
        raise ValueError(f"missing lat/lon in location_1: {loc!r}")
    return (float(loc["longitude"]), float(loc["latitude"]))


def main() -> int:
    parser = argparse.ArgumentParser(...)
    parser.add_argument("--source", choices=["lacity"], required=True)
    parser.add_argument("--start-date", default="2019-03-01")
    parser.add_argument("--end-date",   default="2024-03-01")
    parser.add_argument("--snap-meters", type=float, default=DEFAULT_SNAP_M)
    parser.add_argument("--bbox", default="33.7,-118.7,34.4,-118.0")
    parser.add_argument("--summary-out", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None,  # for testing
                        help="Cap rows fetched (testing only)")
    args = parser.parse_args()
    started_at = datetime.utcnow().isoformat() + "Z"
    t0 = time.monotonic()

    counters = dict(fetched=0, inserted=0, skipped_duplicate=0,
                    dropped_outside_snap=0, errors=0,
                    by_severity=dict(fatal=0, injury=0, pdo=0))
    snap_distances: list[float] = []
    rows_to_insert: list[tuple] = []

    bbox = tuple(float(c) for c in args.bbox.split(","))
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            for crash in iter_crashes(args.start_date, args.end_date, bbox=bbox):
                counters["fetched"] += 1
                if args.limit and counters["fetched"] > args.limit:
                    break
                try:
                    severity = map_mocodes_to_severity(crash["mocodes"])
                    lon, lat = parse_location_1(crash["location_1"])
                    occurred = datetime.fromisoformat(
                        crash["date_occ"].replace("Z","")
                    ).date()
                except (ValueError, KeyError) as e:
                    logger.warning("row %s skipped: %s", crash.get("dr_no"), e)
                    counters["errors"] += 1
                    continue
                seg_id, dist_m = snap_point_to_segment(
                    cur, lon, lat, args.snap_meters,
                )
                if seg_id is None:
                    counters["dropped_outside_snap"] += 1
                    continue
                snap_distances.append(dist_m)
                counters["by_severity"][severity] += 1
                rows_to_insert.append((
                    "lacity",            # source
                    crash["dr_no"],      # source_record_id
                    severity,            # severity
                    occurred,            # occurred_at
                    seg_id,              # snapped_segment_id
                    dist_m,              # snap_distance_m
                    lon, lat,            # geom built in INSERT via ST_MakePoint
                ))

            # Batched INSERT with idempotency.
            if rows_to_insert:
                returned = execute_values(
                    cur,
                    """
                    INSERT INTO crash_records
                        (source, source_record_id, severity, occurred_at,
                         snapped_segment_id, snap_distance_m, geom)
                    VALUES %s
                    ON CONFLICT (source, source_record_id) DO NOTHING
                    RETURNING 1
                    """,
                    rows_to_insert,
                    template=(
                        "(%s, %s, %s, %s, %s, %s, "
                        "ST_SetSRID(ST_MakePoint(%s, %s), 4326))"
                    ),
                    page_size=500,
                    fetch=True,
                )
                conn.commit()
                inserted = len(returned) if returned else 0
                counters["inserted"] = inserted
                counters["skipped_duplicate"] = (
                    len(rows_to_insert) - inserted
                )

        # Run-summary (D-09-08 shape).
        def quantile(xs, q):
            return statistics.quantiles(xs, n=100)[q-1] if xs else 0.0
        summary = {
            "source": "lacity",
            "fetched": counters["fetched"],
            "inserted": counters["inserted"],
            "skipped_duplicate": counters["skipped_duplicate"],
            "dropped_outside_snap": counters["dropped_outside_snap"],
            "errors": counters["errors"],
            "snap_distance_m": {
                "p50": quantile(snap_distances, 50),
                "p95": quantile(snap_distances, 95),
                "max": max(snap_distances) if snap_distances else 0.0,
            },
            "by_severity": counters["by_severity"],
            "started_at": started_at,
            "duration_s": round(time.monotonic() - t0, 2),
        }
        print(json.dumps(summary, indent=2))
        if args.summary_out:
            args.summary_out.write_text(json.dumps(summary, indent=2))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

[Source: D-09-08 + ingest_mapillary.py:506-781 driver structure.]

### Anti-Patterns to Avoid

- **Naive lat/lon WHERE in SoQL:** `$where=latitude > 33.7 AND latitude < 34.4 ...` does NOT use the spatial index; falls back to a full scan. **Use `within_box(location_1, ymin, xmin, ymax, xmax)`.** [VERIFIED via Socrata `within_box` docs.]
- **`source .env`** for token loading: `LACITY_APP_TOKEN` may contain shell-meta characters (Socrata tokens are base64-like; pipe-character incidents are documented in `MEMORY.md feedback_secret_loading_via_python`). **Use the project's Python `.env` parser to emit quoted `KEY='VALUE'`.** [Source: `MEMORY.md` user memory pin.]
- **`comma.split` on mocodes:** the field is space-separated. Use `.replace(",", " ").split()` for safety against any future schema drift.
- **Insert-then-CHECK without `IF NOT EXISTS` on UNIQUE INDEX:** Re-running migration 004 on a partially-applied DB will error. **Use `CREATE UNIQUE INDEX IF NOT EXISTS`** (mirror migration 002 line 36).
- **Missing `::geography` cast in `ST_DWithin`:** without it, the radius is interpreted in degrees, not meters; `ST_DWithin(geom, point, 50)` would match everything within 50° (≈5500 km, the whole continent). **Always cast both args to `geography` for meter semantics.** [VERIFIED: PostGIS docs `ST_DWithin` says geography variant uses meters; geometry variant uses SRID units.]
- **Inserting via separate `cur.execute` per row:** ~144k rows would take 30+ minutes. **Use `execute_values` with `page_size=500`** (mirror `ingest_mapillary.py:698-714`).
- **Not using `$order` in paged Socrata fetches:** without `$order=:id`, page boundaries can shift between requests, causing duplicate or missing rows. [VERIFIED: dev.socrata.com/docs/paging.]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Socrata HTTP client | sodapy (or "I'll just use httpx") | thin `requests` wrapper in `data_pipeline/lacity_socrata.py` mirroring `data_pipeline/mapillary.py` | sodapy unmaintained since 2022-08; mapillary.py is ~120 LOC and proves the pattern. [HIGH] |
| Migration framework | Alembic / sqlalchemy migrations | raw `db/migrations/004_*.sql` mirroring 002 | Project constraint; under the 5+ ADR threshold. [HIGH] |
| KABCO scale lookup | hand-rolled regex over the mocodes string | explicit `MOCODE_SEVERITY_MAP` dict + `.replace(",", " ").split()` | The 5-code mapping IS the KABCO scale; explicit dict is the correct primitive (Pitfall 2: silent defaulting kills you). [HIGH] |
| Snap-match SQL | scipy KDTree / shapely nearest neighbor in Python | PostGIS `ST_DWithin geography + <-> KNN + LIMIT 1` | Already proven at 125k Mapillary rows in <30s on Fly. [HIGH] |
| CSV reader for fixture | pandas / geopandas | stdlib `csv.DictReader` | 200-row test fixture is a flat CSV; pandas is overkill. [HIGH] |
| HTTP retry | `tenacity` | hand-rolled 4-line `with_retry` from `ingest_mapillary.py:306-327` | Project keeps deps minimal; 4 lines of stdlib is enough for the quarterly one-shot. [HIGH] |
| Bbox manipulation | shapely / geopandas | the literal `within_box(location_1, ymin, xmin, ymax, xmax)` SoQL | Socrata's spatial index handles it server-side; client only needs to format the function call. [HIGH] |
| Run-summary statistics | numpy `np.percentile` | stdlib `statistics.quantiles(xs, n=100)` | Single-purpose use; stdlib lands in 3.8+. Avoids re-importing numpy in a CLI that already has it via psycopg2 transitives but doesn't otherwise need it. [MEDIUM — numpy is already pinned via scripts/requirements.txt; either is fine.] |

**Key insight:** Phase 9 is fundamentally **already-built** in three places — Phase 3 has the migration template + driver shape + retry + idempotent insert + run-summary; PostGIS has the snap-match primitive; LAPD has done the KABCO mapping work for us via mocodes 3024-3028. The phase is composition, not invention.

## Common Pitfalls

### Pitfall A: Multi-severity-code rows (multi-victim crashes)

**What goes wrong:** A row carries BOTH `3024` (Severe Injury) and `3027` (Fatal) — happens when one crash has multiple victims at different severity levels. A naive "first match wins" mapper misclassifies it as injury.
**Why it happens:** LAPD's mocode list is per-crash, not per-victim; multi-victim crashes get every applicable severity code stamped on the same row.
**How to avoid:** The mapper takes `max(severities_present, key=_SEVERITY_RANK.__getitem__)` — fatal > injury > pdo. Tested in plan 09-02's RED test with a synthetic row containing `mocodes="3024 3027"` asserting `severity == "fatal"`.
**Warning signs:** by_severity histogram has implausibly few fatals. The 5-yr LA City window has roughly 1-2% fatal rate; if you see < 0.5%, suspect the mapper is short-circuiting.

### Pitfall B: Empty or null `location_1` rows

**What goes wrong:** A small fraction of LA City rows have `null` for `location_1` (location-suppressed for privacy or data-entry incomplete). The driver's `parse_location_1` raises `ValueError`; if the loop catches `ValueError` broadly and increments `errors`, fine; if it doesn't, the whole run aborts.
**Why it happens:** Socrata returns `null` for missing nested objects. The `iter_crashes` `$select` clause includes `location_1` but doesn't filter for non-null.
**How to avoid:** Add `location_1 IS NOT NULL` to the `$where` clause in `iter_crashes`, OR catch `ValueError` and `KeyError` in the driver loop (the skeleton above does both — defensive). Document the count in the run-summary `errors` field.
**Warning signs:** `errors` > 0 in run-summary. Spot-check a few row IDs against `data.lacity.org/resource/d5tf-ez2w/dr_no/<id>` — if they have null `location_1`, this is the cause; if not, escalate.

### Pitfall C: snap_distance_m always missing for Mapillary call sites (asymmetry trap)

**What goes wrong:** Phase 9 lifts `snap_match_image()` into `data_pipeline.snap.snap_point_to_segment` BUT also extends it to return `(seg_id, dist_m)`. Without care, a future refactor of `ingest_mapillary.py` to use the shared helper will break (Mapillary expects single-value return).
**Why it happens:** Two callers, two return shapes. Easy to drift.
**How to avoid:** Plan 09-02 (`data_pipeline/snap.py`) returns `tuple[int, float] | tuple[None, None]` from day one. `ingest_mapillary.py` is NOT modified in Phase 9 (out of scope per the no-refactor decision); a future cleanup phase will migrate it. **The shared helper has the new shape from the start so the future migration is "drop the dist_m return value" not "re-port the SQL."**
**Warning signs:** A Phase 12 refactor PR that touches both files and "harmonizes return shapes" — that PR is fixing the symptom, not the cause; the cause is that Phase 9 should have set the canonical shape.

### Pitfall D: Migration 004 FK type mismatch (research-finding-as-pitfall)

**What goes wrong:** CONTEXT.md D-09-10 specifies `snapped_segment_id BIGINT REFERENCES road_segments(id)`. **`road_segments.id` is `SERIAL` (= `INTEGER`) per migration 001.** Postgres rejects FK constraints where parent/child types don't match → migration fails to apply.
**Why it happens:** Drafter saw `BIGSERIAL` on `crash_records.id` and copied the type for the FK. The two columns are unrelated — the FK type must match the parent column type.
**How to avoid:** Use `INTEGER` for `snapped_segment_id`. **The Pattern 1 SQL above already does this correctly.** Plan 09-01 must explicitly call this out so it doesn't slip back in during execution.
**Warning signs:** `psql: ERROR: foreign key constraint "..." cannot be implemented; Detail: Key columns "snapped_segment_id" and "id" are of incompatible types: bigint and integer.`

### Pitfall E: Token-loaded-as-pipe-stripped string

**What goes wrong:** The operator runs `source .env` to load `LACITY_APP_TOKEN`; the token contains a `|` that the shell interprets as a pipe; everything after the `|` is silently dropped; the truncated token authenticates anonymously (or 401s).
**Why it happens:** Documented user-memory pitfall (`MEMORY.md`: "Loading secrets from .env via Python parser — Mapillary/HF tokens contain pipes; never `source .env`; parse via Python and emit quoted KEY='VALUE'").
**How to avoid:** README + Phase 12 runbook MUST document the Python parser pattern. `scripts/ingest_crashes.py` reads `LACITY_APP_TOKEN` from `os.environ` like every other script; the operator is responsible for getting it into the env correctly. The README documents the project's `.env` Python parser script (or operator runs `direnv` / similar).
**Warning signs:** Run-summary's `errors` is high AND HTTP 429 in logs → token-not-applied → throttled to anonymous tier.

### Pitfall F: Floating-timestamp ISO parse drops the trailing milliseconds

**What goes wrong:** Socrata returns `date_occ` as `"2021-09-02T00:00:00.000"` (note the `.000` ms suffix, no `Z`). `datetime.fromisoformat()` in Python 3.10 doesn't accept the milliseconds OR the absence of timezone; Python 3.12 does.
**Why it happens:** Socrata's `floating_timestamp` SQL type lacks an explicit timezone (it's "date+time as the data was collected"). The exact string format depends on the API version.
**How to avoid:** Test the parse on a real row in plan 09-03's unit tests. The skeleton uses `.replace("Z","")` defensively; the actual parse should be `datetime.fromisoformat("2021-09-02T00:00:00.000").date()` which works on Python 3.11+. [VERIFIED: Python 3.11+ `fromisoformat` accepts both forms; Python 3.12 is the project pin.]
**Warning signs:** `ValueError: Invalid isoformat string` in logs.

## Code Examples

### Example 1: Sample Socrata response shape (from live probe 2026-05-08)

```json
{
  "dr_no": "212013850",
  "date_occ": "2021-09-02T00:00:00.000",
  "mocodes": "3004 3027 3034 4027 3036 3101 3401 3701",
  "location_1": {
    "latitude": "34.063",
    "longitude": "-118.3141",
    "human_address": "{\"address\": \"\", \"city\": \"\", \"state\": \"\", \"zip\": \"\"}"
  }
}
```

Note: `latitude` and `longitude` are **strings**, not numbers. The driver must `float()` them.

[Source: `curl -sS "https://data.lacity.org/resource/d5tf-ez2w.json?\$limit=1" 2026-05-08`.]

### Example 2: Run-summary JSON output (D-09-08 shape)

```json
{
  "source": "lacity",
  "fetched": 143603,
  "inserted": 138291,
  "skipped_duplicate": 0,
  "dropped_outside_snap": 4892,
  "errors": 420,
  "snap_distance_m": {"p50": 8.4, "p95": 31.2, "max": 49.7},
  "by_severity": {"fatal": 1421, "injury": 89234, "pdo": 47636},
  "started_at": "2026-05-09T18:42:11Z",
  "duration_s": 187.4
}
```

Numbers are illustrative — actual fatal rate is roughly 1% in the 5-yr window. The dropped-outside-snap fraction is bounded by D-09-03 ("drops above ~5% trigger a runbook check"); 4892/143603 ≈ 3.4% — within the threshold.

### Example 3: psql verification of migration 004 (post-apply)

```bash
$ psql $DATABASE_URL -c "\d crash_records"
                          Table "public.crash_records"
       Column        |          Type           | Collation | Nullable |    Default
---------------------+-------------------------+-----------+----------+--------------
 id                  | bigint                  |           | not null | nextval(...)
 source              | text                    |           | not null |
 source_record_id    | text                    |           | not null |
 severity            | text                    |           | not null |
 occurred_at         | date                    |           | not null |
 snapped_segment_id  | integer                 |           |          |
 snap_distance_m     | double precision        |           |          |
 geom                | geometry(Point,4326)    |           | not null |
 created_at          | timestamp with time zone|           | not null | now()
Indexes:
    "crash_records_pkey" PRIMARY KEY, btree (id)
    "idx_crash_records_source_id" UNIQUE, btree (source, source_record_id)
    "idx_crash_records_geom" gist (geom)
    "idx_crash_records_segment" btree (snapped_segment_id)
Check constraints:
    "crash_records_severity_check" CHECK (severity IN ('fatal', 'injury', 'pdo'))
    "crash_records_source_check" CHECK (source IN ('lacity'))
Foreign-key constraints:
    "crash_records_snapped_segment_id_fkey" FOREIGN KEY (snapped_segment_id)
      REFERENCES road_segments(id) ON DELETE SET NULL
```

### Example 4: Idempotent re-ingest verification (post-Phase-9)

```bash
$ python scripts/ingest_crashes.py --source lacity --limit 100
... summary: inserted=87, skipped_duplicate=0, dropped_outside_snap=13 ...

$ python scripts/ingest_crashes.py --source lacity --limit 100  # second run
... summary: inserted=0, skipped_duplicate=87, dropped_outside_snap=13 ...
```

`skipped_duplicate` is the difference between rows attempted (post-snap-survival) and rows actually inserted. Mirrors `ingest_mapillary.py`'s `rows_skipped_idempotent` pattern (line 719).

## Plan Decomposition Recommendation

Phase 3 had 5 plans (migration → compute_scores filter → ingest core → wipe-recompute → docs runbook). **Phase 9 needs 4 plans** because (a) compute_scores changes are deferred to Phase 10, (b) the docs runbook is deferred to Phase 12 per D-09-19.

| Plan | Wave | Depends On | Files | Purpose |
|------|------|------------|-------|---------|
| **09-01** | 1 | — | `db/migrations/004_crash_records.sql` + apply hooks | Migration mirroring 002 line-by-line; FK type correction (Pitfall D); `crash_norm` column added with default 0. |
| **09-02** | 2 | 09-01 | `data_pipeline/lacity_mocodes.py`, `data_pipeline/snap.py`, `backend/tests/test_lacity_mocodes.py`, `backend/tests/test_snap.py` | Two pure-function modules + their RED tests. **Wave-2 PARALLEL with 09-03.** |
| **09-03** | 2 | 09-01 | `data_pipeline/lacity_socrata.py`, `data/crashes_la/lacity_fixture.csv`, `backend/tests/test_lacity_socrata.py` | Socrata client + committed test fixture. Tests use `responses` library (already a transitive dep) or stdlib `unittest.mock` to mock HTTP. **Wave-2 PARALLEL with 09-02.** |
| **09-04** | 3 | 09-02 + 09-03 | `scripts/ingest_crashes.py`, `backend/tests/test_ingest_crashes.py`, `.env.example` (modify) | Driver script + 5-test integration suite per REQ-crash-snap-match acceptance criterion. `.env.example` gains `LACITY_APP_TOKEN=` line. |

**Wave structure:**
```
Wave 1:  [09-01]
            │
            ▼
Wave 2:  [09-02]   [09-03]   ← parallel; both gate on 09-01
            │         │
            └────┬────┘
                 ▼
Wave 3:  [09-04]
```

**Why this is shorter than Phase 3:**
- No equivalent of Phase 3 Plan 02 (the `--source` filter on `compute_scores.py`) — that lives in Phase 10.
- No equivalent of Phase 3 Plan 04 (`--wipe-synthetic` + recompute hook) — Phase 9 has no wipe (D-09-16) and no recompute (deferred).
- No equivalent of Phase 3 Plan 05 (`MAPILLARY_INGEST.md` runbook) — deferred to Phase 12 per D-09-19.

**Time-budget signal alignment:** v0.4.0's 6-8 hour budget across 4 phases means Phase 9 gets roughly 1.5-2 hours. The 4-plan structure is tight: ~25 min for 09-01 (migration is pure SQL + a 2-line apply test), ~25 min each for 09-02 + 09-03 (run in parallel = 25 min wall-clock), ~50 min for 09-04 (driver + 5-test integration). Total: ~1h40m wall-clock if 09-02/09-03 truly parallelize, ~2h05m sequential.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Use `sodapy` SDK | Thin `requests` wrapper | Aug 2022 (sodapy unmaintained); confirmed by Mar 2025 ownership transfer with no new release | Removes a stale-dep risk; ~120 LOC of code we own and can test instead of trust |
| `geopandas 0.x` with fiona engine | `geopandas 1.x` with pyogrio engine (5-20× shapefile speedup) | 2024 (geopandas 1.0 release) | Phase 9 NOT yet affected — fixture is CSV, not shapefile. **This bump is for v0.4.1 SWITRS work.** |
| `_acc` field-name suffix on Socrata datasets | `date_occ` (no underscore-acc) on the LAPD-curated `d5tf-ez2w` | Per-dataset, no global migration | Project STACK.md §LA City Open Data references generic `date_occ` field; matches reality. |
| `ST_Distance` in Python loop | `ORDER BY <-> + LIMIT 1` SQL pushdown | PostGIS 2.0+ KNN (long-standing) | No drift; the project already uses this in `ingest_mapillary.snap_match_image`. |
| Use `latitude > X AND longitude > Y` Socrata predicate | `within_box(location_1, ymin, xmin, ymax, xmax)` | Socrata SoQL 2.x spatial functions | Server-side index; predicate pushdown works |

**Deprecated/outdated:**
- `sodapy` 2.2.0: officially unmaintained since 2022-08; do not use.
- ISWITRS (state SWITRS public site): retired Jan 2025; SWITRS now flows through CCRS. Not relevant to Phase 9 (LA City only).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The `mocodes` field is space-separated AND occasionally has trailing whitespace | Pattern 3, Pitfall A | If sometimes comma-separated, the `.replace(",", " ").split()` defense handles it; if pipe-separated, mapper would fail. Tested by D-09-14 RED test with a real fixture row. |
| A2 | CONTEXT.md D-09-13's "Raises ValueError on any unknown code" means "if NO severity code maps" (charitable read) NOT "if ANY non-severity code is present" (strict read) | Pattern 3 commentary | If strict-read is correct, mapper would fail every row (every row has 5-10 non-severity codes). The charitable read matches the implementation reality of LAPD mocodes. **Planner SHOULD verify this with user during plan-discuss-phase.** |
| A3 | A small fraction of `location_1` rows are null and the driver should skip them silently (incrementing `errors`) | Pitfall B | If user wants null-location rows to FAIL the run, the driver should re-raise instead of catch. Likely fine — the run-summary surfaces the count. |
| A4 | `road_segments.id` type is `SERIAL` (= `INTEGER`), so `crash_records.snapped_segment_id` must be `INTEGER` not `BIGINT` despite CONTEXT.md D-09-10 saying `BIGINT` | Pitfall D, Pattern 1 | If `road_segments.id` is `BIGINT` after some Phase-1-or-2 widening that this researcher missed, `INTEGER` will FK-fail at apply time. **Planner MUST verify against migration 001 + any subsequent ALTERs before plan 09-01 ships.** |
| A5 | The 5-yr window 2019-03-01 → 2024-03-01 yields ~144k rows; ~3-4% drop-outside-snap at 50m | Example 2, Pitfall B | Verified row-count via live `count(*)` query; drop-rate is estimated, not measured. Empirical drop-rate is a Phase-12 verification deliverable. |
| A6 | `data_pipeline/snap.py` should set the canonical `(seg_id, dist_m)` return shape from day one (Pitfall C) | Pattern 4 | If the team prefers Mapillary's single-value shape and intends to deprecate the audit column, my recommendation would create churn in a future refactor. Low-cost insurance — one extra return value. |
| A7 | `within_box(location_1, ymin, xmin, ymax, xmax)` argument order is `(latitude_min, longitude_min, latitude_max, longitude_max)` per Socrata docs (NOT `(xmin, ymin, xmax, ymax)`) | Pattern 2 | Socrata docs use lat-first convention. The code in Pattern 2 uses `bbox=(ymin, xmin, ymax, xmax)` to match. If Socrata's argument order is actually different, the count query I ran wouldn't have returned 143603 — but it did, so this is verified by smoke. [VERIFIED: docs https://dev.socrata.com/docs/functions/within_box.html.] |

**If this table is empty:** All claims in this research were verified or cited — no user confirmation needed.

## Open Questions

1. **Strict vs charitable read of D-09-13.** Does "raises ValueError on any unknown code" mean "any code not in the 5-element severity map" (strict — every row fails) or "if no severity code maps" (charitable — only orphan rows fail)? **Recommendation:** Confirm with user during plan-discuss-phase 09-02; the charitable read matches reality and makes the test in D-09-14 pass.

2. **Snap-distance percentile library.** stdlib `statistics.quantiles(xs, n=100)[q-1]` is correct but reads awkwardly; numpy is already a project dep but pulling it into a CLI for one percentile feels heavy. **Recommendation:** stdlib for purity; revisit only if benchmarks show stdlib is materially slower (it isn't at 144k floats).

3. **`responses` mock library or stdlib `unittest.mock`?** Phase 3's `test_mapillary.py` uses... [need to verify]. **Recommendation:** stdlib `unittest.mock.patch` against `requests.get` is sufficient and adds no dep; matches the project's "minimize deps" stance.

4. **Should the driver retry on Socrata 429?** `with_retry` from ingest_mapillary.py:306 handles 429 + 5xx with exponential backoff. **Recommendation:** Yes — wrap `iter_crashes` calls in `with_retry`. Lift `with_retry` into `data_pipeline/snap.py`-adjacent shared helper, OR copy-paste the 4 lines (project precedent leans copy-paste for tiny utilities; lifting would force a Phase-9 refactor of `ingest_mapillary.py` import line which is out of scope).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | All ingest scripts (host venv) | Confirm via `/tmp/rq-venv/bin/python --version` | 3.12.x expected per memory pin | No fallback — venv re-creation is documented |
| `requests` | `lacity_socrata.py` | Confirm via `/tmp/rq-venv/bin/pip show requests` | ≥ 2.31 (project pin); latest 2.32.5 | None needed |
| `psycopg2-binary` | driver | Confirm via host venv | 2.9.11 (pin) | None needed |
| PostgreSQL 15 + PostGIS 3.4 | migration apply + snap-match | Confirm via `psql -c "SELECT postgis_full_version()"` | 3.4.x expected | None — required |
| Socrata `d5tf-ez2w` endpoint | `lacity_socrata.iter_crashes` | Live HTTP probe successful 2026-05-08 | Frozen at 2025-03-11 | CSV fixture for tests; live probe deferred to Phase 12 manual smoke (D-09-06) |
| `LACITY_APP_TOKEN` | better rate limit | Optional per D-09-20 | n/a | Anonymous fetch works at lower rate; document both paths |
| Internet egress from operator host | one-shot live ingest | Required during operator runs | n/a | None — but tests use CSV fixture so CI is unaffected (D-09-06) |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** `LACITY_APP_TOKEN` — anonymous works for the quarterly one-shot pull at the cost of slower paging. Document in `.env.example` as recommended-but-not-required.

## Validation Architecture

> Workflow `nyquist_validation` is not explicitly disabled in `.planning/config.json`; this section is included.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | `pytest 8.3.4` (already in `backend/requirements.txt`) |
| Config file | `backend/pytest.ini` (existing) |
| Quick run command | `pytest backend/tests/test_lacity_mocodes.py backend/tests/test_snap.py -x` (the two pure-module suites; runs in <1s) |
| Full suite command | `pytest backend/tests/ -x` (driver tests need DB; auto-skip if `DATABASE_URL` unreachable) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REQ-crash-ingest-lacity | Migration 004 applies cleanly on fresh + half-applied + fully-applied DB | unit (DDL replay) | `pytest backend/tests/test_migrations.py::test_migration_004_idempotent -x` | ❌ Wave 0 — new test file |
| REQ-crash-ingest-lacity | `lacity_socrata.iter_crashes` paginates correctly (page_size, $offset, stops on partial page, $order=:id) | unit (mock requests) | `pytest backend/tests/test_lacity_socrata.py::test_iter_crashes_pages -x` | ❌ Wave 0 |
| REQ-crash-ingest-lacity | `lacity_socrata.iter_crashes` composes `$where` with date + `within_box` correctly | unit (URL inspect) | `pytest backend/tests/test_lacity_socrata.py::test_where_clause_composition -x` | ❌ Wave 0 |
| REQ-crash-ingest-lacity | `map_mocodes_to_severity` returns highest tier present | unit | `pytest backend/tests/test_lacity_mocodes.py::test_multi_severity_resolves_to_highest -x` | ❌ Wave 0 |
| REQ-crash-ingest-lacity | `map_mocodes_to_severity` raises ValueError on no-severity-code row | unit (D-09-14 RED) | `pytest backend/tests/test_lacity_mocodes.py::test_unknown_mocode_raises_value_error -x` | ❌ Wave 0 |
| REQ-crash-ingest-lacity | `map_mocodes_to_severity` handles space-sep, comma-sep, mixed-whitespace | unit | `pytest backend/tests/test_lacity_mocodes.py::test_separator_robustness -x` | ❌ Wave 0 |
| REQ-crash-ingest-lacity | Run-summary JSON has all 10 D-09-08 keys including snap_distance_m {p50,p95,max} | integration (CSV fixture) | `pytest backend/tests/test_ingest_crashes.py::test_run_summary_shape -x` | ❌ Wave 0 |
| REQ-crash-ingest-lacity | Re-running ingest on same fixture inserts 0 new rows (idempotency) | integration | `pytest backend/tests/test_ingest_crashes.py::test_idempotent_reingest -x` | ❌ Wave 0 |
| REQ-crash-snap-match | `snap_point_to_segment` returns nearest segment within radius | unit (DB) | `pytest backend/tests/test_snap.py::test_snap_within_radius -x` | ❌ Wave 0 |
| REQ-crash-snap-match | `snap_point_to_segment` returns (None, None) outside radius | unit (DB) | `pytest backend/tests/test_snap.py::test_snap_outside_radius -x` | ❌ Wave 0 |
| REQ-crash-snap-match | `crash_records.snap_distance_m` populated correctly | integration | `pytest backend/tests/test_ingest_crashes.py::test_snap_distance_recorded -x` | ❌ Wave 0 |
| REQ-crash-snap-match | Crashes outside `LACITY_SNAP_M` are dropped + counted in `dropped_outside_snap` | integration | `pytest backend/tests/test_ingest_crashes.py::test_dropped_outside_snap -x` | ❌ Wave 0 |
| REQ-crash-snap-match | FK preservation on segment delete (ON DELETE SET NULL leaves crash row intact) | integration | `pytest backend/tests/test_ingest_crashes.py::test_fk_set_null_on_segment_delete -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `pytest backend/tests/test_lacity_mocodes.py backend/tests/test_snap.py -x` (pure-module quick run, <1s — Nyquist sample of mocode-mapper + snap primitive at every commit)
- **Per wave merge:** `pytest backend/tests/test_lacity_mocodes.py backend/tests/test_snap.py backend/tests/test_lacity_socrata.py -x` (adds Socrata mock tests; runs in <3s)
- **Phase gate:** Full suite `pytest backend/tests/` green (includes the integration tests that actually exercise the docker-postgres + CSV fixture path) before `/gsd-verify-work`.

### Wave 0 Gaps

- [ ] `backend/tests/test_lacity_mocodes.py` — covers REQ-crash-ingest-lacity (mocode mapper)
- [ ] `backend/tests/test_lacity_socrata.py` — covers REQ-crash-ingest-lacity (Socrata client)
- [ ] `backend/tests/test_snap.py` — covers REQ-crash-snap-match (snap primitive)
- [ ] `backend/tests/test_ingest_crashes.py` — covers both REQs (driver integration; needs CSV fixture)
- [ ] `backend/tests/test_migrations.py::test_migration_004_idempotent` — covers REQ-crash-ingest-lacity (DDL replay)
- [ ] `data/crashes_la/lacity_fixture.csv` — committed fixture per D-09-05 (~200 hand-picked rows satisfying D-09-07 a-e)
- [ ] No new framework install; pytest 8.3.4 already pinned

## Sources

### Primary (HIGH confidence)

- Live Socrata endpoint probe 2026-05-08 — verified field names via `X-SODA2-Fields` response header; sample rows; bbox count query; date-filter test
- `https://data.lacity.org/api/views/d5tf-ez2w/files/8957b3b1-771a-4686-8f19-281d23a11f1b?download=true&filename=MO_CODES_Numerical_20180627.pdf` — extracted 87 T/C codes via PDF text extraction (Python `zlib` + regex over text streams)
- `db/migrations/002_mapillary_provenance.sql` — line-by-line template for migration 004
- `data_pipeline/mapillary.py` — line-by-line template for `lacity_socrata.py`
- `scripts/ingest_mapillary.py` — line-by-line template for `ingest_crashes.py`; `snap_match_image()` lifted to `data_pipeline/snap.py`
- `.planning/research/STACK.md` — sodapy rejection (HIGH); freeze date claim (cross-verified; STACK says "March 2024" data-freeze but live header shows 2025-03 portal-republish; both correct, different events)
- `.planning/research/ARCHITECTURE.md` — schema decisions, snap-match approach
- `.planning/research/PITFALLS.md` Pitfall 2 + Pitfall 4 + Pitfall 13 — drift / intersection / synthetic-fixture considerations carried into Pitfalls A-F

### Secondary (MEDIUM confidence)

- `https://dev.socrata.com/docs/queries/limit` — pagination semantics
- `https://dev.socrata.com/docs/paging` — `$order=:id` stable-pagination requirement
- `https://dev.socrata.com/docs/functions/within_box.html` — spatial filter argument order
- `https://dev.socrata.com/docs/app-tokens` — 1000 req/hr with token; anonymous shared-IP pool
- `https://postgis.net/docs/ST_DWithin.html` — geography variant uses meter units
- `https://postgis.net/workshops/postgis-intro/knn.html` — `<->` operator + GIST index usage

### Tertiary (LOW confidence — none)

All factual claims either verified directly via tool calls or cross-referenced against locked decisions. No tertiary-only claims in this research.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every package version verified against the live project tree + PyPI
- Architecture: HIGH — patterns are direct lifts from already-shipping Phase 3 code
- Pitfalls: HIGH for A/B/D/E/F (verified or memory-pin-cited); MEDIUM for C (forward-looking)
- Mocode catalog: HIGH — extracted from authoritative LAPD PDF; cross-verified by spot-checking 10 live rows for presence of 3024-3028 codes
- Field names: HIGH — `X-SODA2-Fields` response header is the dataset's authoritative schema declaration

**Research date:** 2026-05-08
**Valid until:** 2026-11-08 (6 months — Socrata dataset is frozen so endpoint stability is high; mocode catalog hasn't been updated since 2018-06-27 per the PDF filename, so it's effectively immutable for this dataset; PostGIS 3.4 is stable)
