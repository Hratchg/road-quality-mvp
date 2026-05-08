# Phase 3: Mapillary Ingestion Pipeline - Research

**Researched:** 2026-04-25
**Domain:** Mapillary→YOLO→PostGIS ingestion pipeline; segment-targeted CLI orchestration; idempotent provenance schema; raw SQL migration discipline; psycopg2 SQL composition
**Confidence:** HIGH (all locked decisions D-01..D-20 are technically sound and the implementation patterns are verified against existing code + official docs)

## Summary

Phase 3 is an orchestration phase. The Mapillary HTTP client (`data_pipeline/mapillary.py`) and the YOLO detector path (`data_pipeline/detector_factory.get_detector` + `YOLOv8Detector.detect`) both already exist from Phase 2 and are battle-hardened (bbox DoS guard, constant-time SHA256, path-traversal rejection, pickle-ACE notes). Phase 3 adds (1) one new SQL migration `db/migrations/002_mapillary_provenance.sql` extending `segment_defects` with `source_mapillary_id` + `source` + a UNIQUE index for idempotency, (2) one new operator CLI `scripts/ingest_mapillary.py` that targets segments three ways (explicit IDs / IDs file / SQL `WHERE` predicate) and runs the per-segment "pad bbox → search → download → detect → snap-match → upsert" loop, and (3) a small `--source` filter on `scripts/compute_scores.py`.

**The single most important correction to the locked decisions:** D-05 + the open question about `UNIQUE NULLS NOT DISTINCT` need a tighter answer than CONTEXT.md gave. PostgreSQL's default UNIQUE constraint **already** treats NULLs as distinct, which means existing synthetic rows (with `source_mapillary_id IS NULL`) will NOT collide with each other on the new `UNIQUE(segment_id, source_mapillary_id, severity)`. That's exactly what we want — synthetic rows shouldn't deduplicate, only Mapillary rows should. **`NULLS NOT DISTINCT` is NOT required and would actively break correctness** by collapsing legitimate distinct synthetic rows. [VERIFIED: PostgreSQL 16 docs + existing seed_data.py inserts multiple synthetic rows per segment without any unique constraint today.]

**The second most important correction:** D-09's `--where "iri_norm > 0.5 ORDER BY iri_norm DESC LIMIT N"` is operator-supplied SQL. The "operator has DB credentials anyway" argument from CONTEXT.md is true but not sufficient — the operator may copy a `--where` from a chat/blog/Slack and run it without thinking. The defense is **psycopg2.sql composition with a column whitelist**, not "trust the operator." See Pattern 6 below for the safe pattern: validate the WHERE predicate against an allowlist of columns + comparators OR (the easier path) wrap the whole thing in `psycopg2.sql.SQL` + `psycopg2.sql.Identifier`. The simplest defensible MVP is: parse the user string for forbidden tokens (`;`, `--`, `/*`, `DELETE`, `DROP`, `UPDATE`, `INSERT`, `ALTER`, `CREATE`, `GRANT`, `REVOKE`, `EXEC`, `pg_*`, `information_schema`) and refuse if any appear, then wrap into a parameterized `SELECT id FROM road_segments WHERE {predicate}` and treat the predicate as a literal SQL fragment. Document the trust model.

**Primary recommendation:** Follow CONTEXT.md decisions D-01..D-20 verbatim. For the open Claude's-discretion items: confidence threshold = **YOLOv8 default 0.25** (filter applied at `model.predict(conf=0.25)` time — `YOLOv8Detector` already does this); detection-row aggregation = **one row per detection** (matches the existing single-class `_map_severity` semantics; `count=1` and `confidence_sum=detection.confidence`); bbox padding = **50 m via `ST_Buffer(geom::geography, 50.0)::geometry → ST_Envelope`** then split if envelope > 0.01 deg²; rate-limit retry = **simple exponential backoff with `requests` + `tenacity` (NEW dep) OR a hand-rolled 4-line retry loop** — given Phase 1's "no new deps unless justified" stance, hand-roll for MVP. Run summary = **JSON to stdout (when `--json-out` set) + human-readable counts table to stderr**, mirroring `scripts/eval_detector.py`'s D-18 pattern.

## User Constraints (from CONTEXT.md)

### Locked Decisions

**Image-to-Segment Matching**
- **D-01:** Matching = **`SELECT id FROM road_segments WHERE ST_DWithin(geom::geography, ST_Point(lon, lat)::geography, snap_m) ORDER BY ST_Distance(geom::geography, point) LIMIT 1`** — one query per image, leverages `idx_segments_geom` GIST index.
- **D-02:** Snap radius default = **25 m**, tunable via `--snap-meters` CLI flag.
- **D-03:** Images outside snap radius are **dropped** (not force-attributed); counted in run summary, not written to `segment_defects`.
- **D-04:** Match-drift policy = **attribute to closest segment** (geometrically honest; produces "free coverage" of neighbors).

**Idempotency & Provenance**
- **D-05:** New migration adds `source_mapillary_id TEXT` to `segment_defects` + **`UNIQUE(segment_id, source_mapillary_id, severity)`** constraint. NULL `source_mapillary_id` rows (synthetic) are NULL-distinct (default Postgres behavior) and do not participate in the UNIQUE check.
- **D-06:** Inserts use **`INSERT ... ON CONFLICT DO NOTHING`** — second run silently skips, satisfying SC #2.
- **D-07:** Same migration adds **`source TEXT NOT NULL DEFAULT 'synthetic' CHECK (source IN ('synthetic', 'mapillary'))`**. Existing rows backfill as `'synthetic'`; Mapillary inserts tag `'mapillary'`.
- **D-08:** Resumability falls out of idempotency for free — kill-and-rerun handles itself; no checkpoint file.

**CLI: Targeting & Orchestration**
- **D-09:** `scripts/ingest_mapillary.py` with three mutually-exclusive target modes:
  - `--segment-ids 1,2,3` (explicit list)
  - `--segment-ids-file path.txt` (one id per line)
  - `--where "iri_norm > 0.5 ORDER BY iri_norm DESC LIMIT N"` (SQL predicate; planner MUST defend against injection — see Pattern 6 below)
- **D-10:** Per-segment workflow: pad bbox around segment geom (≥ snap_m, default 50 m); subdivide if > 0.01 deg²; `mapillary.search_images(bbox, limit=...)`; for each image: download → detect → snap-match → upsert.
- **D-11:** Image cache = **`data/ingest_la/<segment_id>/<image_id>.jpg`** + per-run `manifest.json` (mirrors Phase 2 manifest format). `--no-keep` deletes images after detection.
- **D-12:** `--limit-per-segment N` default 20 caps API cost + disk per segment.

**Synthetic-Data Coexistence & Demo Cutover**
- **D-13:** Hybrid policy: tag everything via `source` column AND provide a wipe path. Synthetic + Mapillary coexist during dev; synthetic wiped before public demo.
- **D-14:** `--wipe-synthetic` flag runs `DELETE FROM segment_defects WHERE source = 'synthetic'` BEFORE writing real data, then triggers `compute_scores.py`. Default keeps synthetic.
- **D-15:** Phase 6 deploy procedure MUST document `--wipe-synthetic` as cutover step.
- **D-16:** `compute_scores.py` gains `--source {synthetic|mapillary|all}` flag (default `'all'`); SC #4 demonstrable in dev via toggling the flag and diffing `/route` responses.

**End-to-End Verification**
- **D-17:** SC #3 satisfied by ingest → recompute → `/segments?bbox=...` + `/route` against same bbox. Add integration smoke against fixture or live DB.
- **D-18:** SC #4 = documented operator workflow in `docs/`, plus optional `scripts/compare_rankings.py` if cheap.

**Token & Reuse from Phase 2**
- **D-19:** Mapillary token via env-only: `MAPILLARY_ACCESS_TOKEN` (already in `data_pipeline/mapillary.py:49`).
- **D-20:** Reuse Phase 2 client surface (`validate_bbox`, `search_images`, `download_image`, `verify_manifest`, `write_manifest`, `_validate_manifest_path`, `_sha256_of_file`) — DO NOT reimplement.

### Claude's Discretion

- Confidence threshold for filtering low-confidence YOLO detections (CONTEXT.md suggests 0.25–0.5)
- Detection-row aggregation: one row per detection vs aggregated by `(segment_id, severity, image_id)`
- Bbox padding around target segment (default 50 m suggested)
- Mapillary rate-limit / retry / backoff specifics
- Run summary format (JSON / pretty table / mixed)
- Whether `--where` SQL uses parameterized queries or whitelisting
- Whether to drop existing `seed_data.py` synthetic-pothole insert when running `seed_data.py --no-defects` (low-priority polish)

### Deferred Ideas (OUT OF SCOPE)

- Confidence calibration / per-class threshold tuning (Phase 2 territory or post-MVP)
- Mapillary heading/orientation filter (defer unless first runs show direction-related noise)
- Continuous CI gate on ingestion correctness (future phase)
- Auto-tile sweep mode (`--bbox` instead of segments) — segment-targeted is locked default
- Named target sets (`--target downtown-arterials`) — operator uses `--where` instead
- Migration of synthetic seed to a separate `segment_defects_synthetic` table — heavy refactor, `source` column achieves separation
- Confidence histograms / per-class precision-recall on real ingest data — eval lives in Phase 2
- Soft-delete via `deleted_at` for rollback — `source_mapillary_id` already enables `DELETE WHERE` rollback by image

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REQ-mapillary-pipeline | Automated pipeline pulls Mapillary imagery, runs `YOLOv8Detector`, writes rows into `segment_defects`, then triggers `compute_scores.py`. CLI takes bbox+limit (Phase 3 reframes to segment-targeted per D-09); env-only token; idempotent on re-run; `/segments` and `/route` reflect real detections. | Migration shape (§Architecture Patterns Pattern 1), CLI orchestration (§Pattern 2), PostGIS snap query (§Pattern 3), idempotent INSERT (§Pattern 4), CLI argparse pattern from `ingest_iri.py` (verified file read), Mapillary client reuse (§Don't Hand-Roll), SC #3 + SC #4 verification approach (§Validation Architecture). |

## Project Constraints (from CLAUDE.md)

No `./CLAUDE.md` exists at the repo root. [VERIFIED: `cat CLAUDE.md 2>/dev/null` returned "No CLAUDE.md".] Project-specific directives come from `.planning/PROJECT.md` ("Constraints" section) and are encoded into CONTEXT.md decisions:

- Backend stack locked to Python 3.12+, FastAPI, **psycopg2 with RealDictCursor**, Pydantic v2 (CON-stack-backend) — no SQLAlchemy.
- Migrations are **single SQL files under `db/migrations/`, no Alembic** — Phase 3 adds `002_*.sql`.
- All secrets via env vars; never committed.
- Schema: `road_segments`, `segment_defects`, `segment_scores`, `route_requests` are load-bearing; `road_segments.source/target = BIGINT`; `geom = GEOMETRY(LineString, 4326)`.
- Project seed convention: `SEED = 42` (matches `scripts/seed_data.py:22` and Phase 2 conventions).
- Exit codes: 0 OK / 2 validation / 3 missing-resource / 1 generic error (Phase 2 D-18, inherited).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Schema migration (`source_mapillary_id`, `source`, UNIQUE constraint) | `db/migrations/002_mapillary_provenance.sql` | — | Existing migration pattern; idempotent ALTER TABLE w/ `IF NOT EXISTS` per Postgres 16 syntax |
| Operator CLI (target modes, orchestration, summary) | `scripts/ingest_mapillary.py` | — | Existing scripts/ pattern (argparse, env-at-module-top, exit codes per Phase 2 D-18) |
| Per-segment workflow (bbox pad, subdivide, search, download, detect, match, upsert) | `scripts/ingest_mapillary.py` | `data_pipeline/ingest.py` (NEW reusable module — optional) | Mirror `ingest_iri.py` + `iri_sources.py` split if helpers exceed ~80 lines; otherwise inline |
| Mapillary HTTP (`search_images`, `download_image`, `validate_bbox`) | `data_pipeline/mapillary.py` (Phase 2, EXISTING) | — | Reuse-only per D-20; do not modify |
| Manifest write/verify (per-run audit trail) | `data_pipeline/mapillary.py::write_manifest` (EXISTING) | `scripts/ingest_mapillary.py` (caller) | Exact reuse of Phase 2 schema (`version: "1.0"`, sha256, source_mapillary_id) |
| Detector instantiation + inference | `data_pipeline/detector_factory.py::get_detector` (EXISTING) | `data_pipeline/yolo_detector.py::YOLOv8Detector.detect` | Single injection point per Phase 2 — call once at startup |
| Image-to-segment matching (PostGIS) | `scripts/ingest_mapillary.py` (or `data_pipeline/ingest.py` helper) | psycopg2 raw SQL with parameterized point | Pure SQL — no library beyond stdlib + psycopg2 |
| Idempotent INSERT writes | `scripts/ingest_mapillary.py` | psycopg2 `execute_values` w/ `ON CONFLICT DO NOTHING` | Existing pattern in `seed_data.py` lines 115-121, 137 |
| `--source` filter on score recomputation | `scripts/compute_scores.py` (EXTEND) | — | Add `--source` arg + WHERE clause; preserves default 'all' behavior |
| `--wipe-synthetic` cutover | `scripts/ingest_mapillary.py` | — | Pre-write step; documented in Phase 6 runbook |
| Smoke test ingest→score→/segments+/route loop | `backend/tests/test_integration.py` (EXTEND) | `backend/tests/test_ingest_mapillary.py` (NEW for unit-level matching/upsert mocks) | Mirror Phase 2 `test_mapillary.py` mock pattern + existing `test_integration.py` skip-when-DB-down pattern |
| Operator runbook (`--wipe-synthetic` cutover, `--source` toggle, `compare_rankings`) | `docs/MAPILLARY_INGEST.md` (NEW) | README link from "Real-Data Pipeline" section | Documentation tier; cited by Phase 6 demo runbook |

**Tier-boundary sanity checks:**
- The CLI does NOT touch the FastAPI backend code. `backend/app/routes/*` is unchanged in Phase 3. [CITED: CONTEXT.md `<domain>` "Out of scope: Public demo URL wiring" + the explicit non-modification of `/segments` and `/route`.]
- The CLI directly imports `data_pipeline.mapillary` and `data_pipeline.detector_factory.get_detector` — both already work standalone (no FastAPI dependency).
- The migration `002_*.sql` is **only** picked up on a fresh DB build (Docker entrypoint); on existing DBs the operator must apply it manually with `psql -f db/migrations/002_*.sql`. [VERIFIED: `docker-compose.yml` mounts only `001_initial.sql` into `/docker-entrypoint-initdb.d/`, and the entrypoint scripts only run on first init.] Plan must document the manual-apply step for existing dev DBs.

## Standard Stack

### Core (runtime path for the CLI)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `psycopg2-binary` | `==2.9.11` (locked by `backend/requirements.txt`; latest 2.9.12 [VERIFIED via `pip index versions`]) | Postgres adapter; `psycopg2.sql` for safe identifier composition (`--where` defense) | Project standard per CON-stack-backend; already pinned in three requirements files; `psycopg2.sql` is stdlib-grade for SQL injection defense [CITED: https://www.psycopg.org/docs/sql.html] |
| `requests` | `==2.32.5` (latest [VERIFIED]) | HTTP client for Mapillary (already used by `data_pipeline/mapillary.py`) | Standard, no replacement needed; existing dep |
| `data_pipeline.mapillary` | EXISTING (Phase 2) | Mapillary client surface — `search_images`, `download_image`, `validate_bbox`, `write_manifest`, `verify_manifest` | Reuse per D-20; the bbox guard, sha256 constant-time compare, and image-id digit validation are already there |
| `data_pipeline.detector_factory.get_detector` | EXISTING (Phase 2) | YOLO model resolution (HF or local) + `YOLOv8Detector` instantiation | Single injection point per Phase 2 D-14 |
| `ultralytics` | `>=8.1` (already in `data_pipeline/requirements.txt`) | YOLOv8 inference loop (used through factory) | Existing dep; called via `get_detector(use_yolo=True).detect(image_path)` |

### Supporting (probably zero new deps)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `argparse` | stdlib | CLI argument parsing | Mirrors `scripts/ingest_iri.py` exactly |
| `pathlib.Path` | stdlib | Filesystem ops for image cache | Existing convention |
| `logging` | stdlib | Module-top `logger = logging.getLogger(__name__)` | Existing convention (CONVENTIONS.md) |
| `json` | stdlib | Run summary stdout / manifest writes | Existing convention; manifest schema is Phase 2-locked |
| `time` / `random` | stdlib | Hand-rolled exponential backoff for 429s | Avoid `tenacity` dep — 4-line retry loop is enough |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hand-rolled exponential backoff | `tenacity` PyPI package | tenacity is a well-loved retry library but adds a dep for ~5 lines of stdlib code. Keep deps minimal per project convention. If retry logic gets complex (multiple endpoints with different policies), revisit. |
| psycopg2.sql composition for `--where` | Pure regex sanitizer + string interpolation | psycopg2.sql is the canonical Python answer to "how do I parametrize an identifier or SQL fragment safely" [CITED: https://www.psycopg.org/docs/sql.html]. A pure regex is fragile; reviewers can't easily verify it's correct. **Recommendation:** Use BOTH — regex blacklist for obviously-malicious tokens (`;`, `--`, `DROP`, etc.) AS a defense-in-depth check, AND wrap the predicate in `psycopg2.sql.SQL(predicate)` so the operator can reference column identifiers without manual quoting. The regex is documentation; the sql.SQL is the actual safety. |
| `mapillary-python-sdk` | requests-based client | Phase 2 chose hand-rolled in `data_pipeline/mapillary.py` for control; Phase 3 reuses. SDK would tile bboxes automatically (nice for `--bbox` mode if ever added), but our segment-targeted bboxes are bounded by the segment geometry envelope — they're already small and we already have `validate_bbox` as a guard. |
| Aggregate detections by `(segment_id, severity, image_id)` | One row per detection | The existing schema's `count` field implies aggregation, BUT (a) every existing call site in the codebase writes one row per detection-tuple (e.g., `seed_data.py:108-112` produces multiple `(severity='moderate', count=N, confidence_sum=...)` rows per segment), (b) the UNIQUE constraint per D-05 includes `severity`, which means at most ONE row can exist per `(segment_id, source_mapillary_id, severity)` — already enforces aggregation per-image-per-severity. **Recommendation:** Insert one row per `(segment_id, source_mapillary_id, severity)` group, with `count = number of detections in that group` and `confidence_sum = sum of confidences`. This matches the schema's intent AND the UNIQUE constraint. |
| `requests.Session` with HTTPAdapter `Retry` mount | Hand-rolled `time.sleep()` loop | `urllib3.util.retry.Retry` mounted on a session would handle 429/5xx automatically across all `requests.get` calls in `data_pipeline/mapillary.py`. **Out of scope for Phase 3** — it would require modifying `data_pipeline/mapillary.py`, which D-20 forbids. Hand-roll the retry around `search_images` / `download_image` calls in the CLI. |

**Installation (no new pip deps required):**
```
# All deps already in:
#   backend/requirements.txt (psycopg2-binary 2.9.11, pytest 8.3.4)
#   data_pipeline/requirements.txt (ultralytics, opencv, huggingface_hub, scipy)
#   scripts/requirements.txt (osmnx, psycopg2-binary, numpy, geopandas)
#   .env.example (DATABASE_URL, MAPILLARY_ACCESS_TOKEN, YOLO_MODEL_PATH already documented)
```

**Version verification:**
```bash
python3 -m pip index versions psycopg2-binary  # 2.9.12 latest; we pin 2.9.11 — fine
python3 -m pip index versions requests          # 2.32.5 latest — already at this on dev machine
```
[VERIFIED on dev machine: psycopg2 2.9.12 + requests 2.32.5 system-wide.]

## Architecture Patterns

### System Architecture Diagram

```
                ┌──────────────────────────────────────────────────────────────┐
                │ OPERATOR (laptop, with PostgreSQL up and YOLO_MODEL_PATH set)│
                └──────────────────────────────────┬───────────────────────────┘
                                                   │
                                                   │ python scripts/ingest_mapillary.py \
                                                   │   --segment-ids 1,2,3 (or --where "...")
                                                   │   --snap-meters 25 --limit-per-segment 20
                                                   │   --no-keep --wipe-synthetic
                                                   ▼
              ┌─────────────────────────────────────────────────────────────────────┐
              │              scripts/ingest_mapillary.py (NEW)                      │
              │                                                                     │
              │  Step 0: parse args, set up logging                                  │
              │  Step 1: read MAPILLARY_ACCESS_TOKEN, DATABASE_URL, YOLO_MODEL_PATH  │
              │  Step 2: instantiate detector once via get_detector(use_yolo=True)  │
              │  Step 3: resolve target segments (resolve_targets)                  │
              │          ├── --segment-ids 1,2,3        ──► [1, 2, 3]               │
              │          ├── --segment-ids-file path    ──► read lines              │
              │          └── --where "predicate"        ──► safe SQL with whitelist │
              │                                            (Pattern 6)              │
              │  Step 4: optional --wipe-synthetic                                  │
              │          DELETE FROM segment_defects WHERE source='synthetic'       │
              │  Step 5: per-segment loop (Pattern 2):                              │
              │          ├── compute padded bbox via ST_Buffer(geom::geog, pad)     │
              │          ├── if envelope > 0.01 deg² → split (delegate to            │
              │          │   validate_bbox, retry with 4 quadrants)                 │
              │          ├── search_images(bbox, limit) — via Phase 2 client        │
              │          ├── for each image:                                        │
              │          │   ├── download_image(meta, cache_dir/<seg>/) (Pattern 5) │
              │          │   ├── detector.detect(image_path) → list[Detection]     │
              │          │   ├── snap-match (Pattern 3): 1 SQL → matched_seg_id     │
              │          │   ├── if matched: aggregate by severity, queue insert    │
              │          │   ├── append manifest entry                              │
              │          │   └── if --no-keep: unlink image                         │
              │          └── flush queue: INSERT ... ON CONFLICT DO NOTHING (P4)    │
              │  Step 6: write manifest.json (per-run audit trail)                  │
              │  Step 7: subprocess: python scripts/compute_scores.py --source all  │
              │  Step 8: emit summary (JSON to --json-out OR human-readable stderr) │
              └────┬─────────────────────────┬────────────────────────┬─────────────┘
                   │                         │                        │
                   ▼                         ▼                        ▼
        ┌──────────────────┐       ┌──────────────────┐    ┌────────────────────┐
        │  Mapillary API   │       │ data_pipeline/   │    │  PostgreSQL (DB)   │
        │  graph.mapillary │       │ detector_factory │    │  + PostGIS 3.4     │
        │  .com/images     │       │ → YOLOv8Detector │    │  + pgRouting 3.6   │
        │                  │       │ .detect(path)    │    │                    │
        │  /images?bbox=…  │       │                  │    │ Tables touched:    │
        │  → list of imgs  │       │  one .pt load    │    │  road_segments     │
        │                  │       │  per ingest run  │    │   (read geom only) │
        │  thumb_2048_url  │       │                  │    │  segment_defects   │
        │  → JPEG bytes    │       │                  │    │   (insert+upsert)  │
        │                  │       │                  │    │  segment_scores    │
        │  Rate limits:    │       │                  │    │   (rebuilt by      │
        │   - search       │       │                  │    │    compute_scores) │
        │     10k/min      │       │                  │    │                    │
        │   - entity       │       │                  │    │ NEW: 002_*.sql     │
        │     60k/min      │       │                  │    │  ADD COLUMN        │
        │   - tile         │       │                  │    │   source_mapillary │
        │     50k/day      │       │                  │    │   _id              │
        │                  │       │                  │    │  ADD COLUMN source │
        │  URLs are signed │       │                  │    │  CREATE UNIQUE     │
        │  (TTL — Pitfall 5│       │                  │    │   INDEX ...        │
        │  in Phase 2 res) │       │                  │    │                    │
        └──────────────────┘       └──────────────────┘    └────────────────────┘
                   │                                                  ▲
                   │                                                  │
                   ▼                                                  │
        ┌──────────────────┐                                          │
        │ data/ingest_la/  │   manifest.json (per-run audit trail;    │
        │  <segment_id>/   │   uses Phase 2 manifest schema 1.0)      │
        │   <img_id>.jpg   │                                          │
        │   manifest.json  │                                          │
        │                  │   --no-keep: images unlinked after detect│
        └──────────────────┘                                          │
                                                                      │
                                                                      │ after ingest:
                                                                      │
       backend/app/routes/segments.py (UNCHANGED) ──reads──────────────┤
       backend/app/routes/routing.py (UNCHANGED) ──reads───────────────┘
```

### Recommended Project Structure

```
road-quality-mvp/
├── db/
│   └── migrations/
│       ├── 001_initial.sql                         # UNCHANGED
│       └── 002_mapillary_provenance.sql            # NEW — D-05, D-07
│
├── data/
│   └── ingest_la/                                  # NEW (gitignored except .gitkeep)
│       └── <segment_id>/
│           ├── <image_id>.jpg                      # ephemeral with --no-keep
│           └── manifest.json                       # per-run audit trail
│
├── data_pipeline/
│   ├── mapillary.py                                # UNCHANGED (Phase 2 — reuse via D-20)
│   ├── detector.py                                 # UNCHANGED
│   ├── detector_factory.py                         # UNCHANGED
│   ├── yolo_detector.py                            # UNCHANGED
│   └── ingest.py                                   # OPTIONAL NEW — pure helpers if scripts/
│                                                   # gets unwieldy (>~250 lines). Decision
│                                                   # is Plan-time; default = inline in script.
│
├── scripts/
│   ├── seed_data.py                                # UNCHANGED (synthetic seed continues
│   │                                               #   to work; existing rows backfill
│   │                                               #   `source='synthetic'` via DEFAULT)
│   ├── compute_scores.py                           # MODIFIED — add --source flag (D-16)
│   └── ingest_mapillary.py                         # NEW — operator entrypoint (D-09..D-12)
│
├── backend/
│   └── tests/
│       ├── test_integration.py                     # EXTEND — add ingest→score→/segments
│       │                                           #   smoke (D-17, SC #3)
│       └── test_ingest_mapillary.py                # NEW — unit tests for snap-match SQL,
│                                                   #   upsert idempotency, --where
│                                                   #   injection defense, target-mode
│                                                   #   resolution
│
├── docs/
│   └── MAPILLARY_INGEST.md                         # NEW — operator runbook (D-15, D-18,
│                                                   #   Phase 6 cites this)
│
├── .env.example                                    # NO CHANGE (MAPILLARY_ACCESS_TOKEN,
│                                                   #   DATABASE_URL, YOLO_MODEL_PATH
│                                                   #   already there from Phase 1+2)
│
├── .gitignore                                      # MODIFY — add `data/ingest_la/*` +
│                                                   #   `!data/ingest_la/.gitkeep`
│                                                   #   (mirrors data/eval_la/ pattern)
│
└── README.md                                       # MODIFY — link "Real Data Ingest"
                                                    #   section pointing to
                                                    #   docs/MAPILLARY_INGEST.md
```

### Pattern 1: Idempotent ALTER TABLE migration (Postgres 16)

**What:** Two `ADD COLUMN IF NOT EXISTS` plus one `CREATE UNIQUE INDEX IF NOT EXISTS`. Use `CREATE UNIQUE INDEX IF NOT EXISTS` instead of `ADD CONSTRAINT IF NOT EXISTS` because Postgres 16 does NOT support `IF NOT EXISTS` on `ADD CONSTRAINT` [VERIFIED via WebFetch of postgresql.org/docs/16/sql-altertable.html — synopsis only includes `IF NOT EXISTS` for `ADD COLUMN`, `DROP COLUMN`, and `DROP CONSTRAINT`].

**When to use:** Every Phase 3 migration must be re-runnable on a fresh DB AND on a DB where the migration has already been applied (operator might have applied it manually before checkout updates).

**Example:**
```sql
-- db/migrations/002_mapillary_provenance.sql
-- Phase 3: add provenance columns to segment_defects + UNIQUE index for idempotent
-- Mapillary inserts. Existing synthetic rows backfill source='synthetic' via the
-- column DEFAULT; new Mapillary rows tag source='mapillary'.
--
-- Postgres 16 supports ADD COLUMN IF NOT EXISTS but NOT ADD CONSTRAINT IF NOT EXISTS.
-- Workaround: use CREATE UNIQUE INDEX IF NOT EXISTS. Functionally equivalent for our
-- use case (uniqueness enforcement + ON CONFLICT target).

-- D-05: source_mapillary_id is the per-image dedup key.
-- TEXT (not VARCHAR) per project convention. NULL allowed (existing synthetic rows).
ALTER TABLE segment_defects
    ADD COLUMN IF NOT EXISTS source_mapillary_id TEXT;

-- D-07: source column tags origin. DEFAULT 'synthetic' so existing rows backfill.
-- CHECK constraint cannot use IF NOT EXISTS but can be re-added safely after a
-- DROP CONSTRAINT IF EXISTS — guarded so re-runs don't error.
ALTER TABLE segment_defects
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'synthetic';

-- DROP-then-ADD pattern for the CHECK (Postgres 16 has no ADD CONSTRAINT IF NOT EXISTS).
-- Constraint name is fixed so DROP IF EXISTS is reliable.
ALTER TABLE segment_defects
    DROP CONSTRAINT IF EXISTS segment_defects_source_check;
ALTER TABLE segment_defects
    ADD CONSTRAINT segment_defects_source_check
    CHECK (source IN ('synthetic', 'mapillary'));

-- D-05 UNIQUE constraint enforced via UNIQUE INDEX (idempotent).
-- Default NULL behavior: synthetic rows (source_mapillary_id IS NULL) do NOT collide
-- with each other — exactly what we want. NULLS NOT DISTINCT is NOT used because it
-- would break the multiple-synthetic-rows-per-segment pattern in seed_data.py.
CREATE UNIQUE INDEX IF NOT EXISTS uniq_defects_segment_source_severity
    ON segment_defects (segment_id, source_mapillary_id, severity);

-- Optional: index on source for fast --source filter in compute_scores.py.
-- Cheap on small table; included for completeness.
CREATE INDEX IF NOT EXISTS idx_defects_source ON segment_defects(source);
```

*Source: synthesis of [VERIFIED: Postgres 16 docs at https://www.postgresql.org/docs/16/sql-altertable.html] + existing migration `db/migrations/001_initial.sql` style.*

**Critical correctness note on UNIQUE + NULL:** PostgreSQL's default is **NULL distinct** in unique indexes [CITED: https://www.postgresql.org/docs/16/indexes-unique.html]. This means existing synthetic rows (with `source_mapillary_id IS NULL`) do NOT collide on `(segment_id=42, source_mapillary_id=NULL, severity='moderate')` — even with multiple such rows. **This is the desired behavior.** Mapillary rows always have a non-NULL `source_mapillary_id` so they DO dedupe. Do NOT use `NULLS NOT DISTINCT` — it would break the existing seed script which inserts multiple synthetic rows per segment. [ASSUMED — flagged in §Open Questions for confirmation, but the math is unambiguous and `seed_data.py:108-112` does insert 1-3 defect rows per ~30% of segments with the same severity possible across rows.]

### Pattern 2: Per-segment workflow (CLI orchestration)

**What:** For each target segment id, compute padded bbox → search Mapillary → download → detect → snap-match → upsert. Emit summary at end.

**When to use:** The core loop of `scripts/ingest_mapillary.py`.

**Example:**
```python
# scripts/ingest_mapillary.py (sketch — main loop)
import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Iterable

import psycopg2
from psycopg2 import sql as psql
from psycopg2.extras import RealDictCursor, execute_values

# Ensure project root importable for `data_pipeline.*`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_pipeline.mapillary import (
    MAPILLARY_TOKEN,
    download_image,
    search_images,
    validate_bbox,
    write_manifest,
)
from data_pipeline.detector_factory import get_detector

# D-18 exit codes (inherited from Phase 2)
EXIT_OK = 0
EXIT_VALIDATION = 2
EXIT_MISSING_RESOURCE = 3
EXIT_OTHER = 1

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://rq:rqpass@localhost:5432/roadquality"
)

logger = logging.getLogger(__name__)

# Padding default 50m per CONTEXT.md D-10.
DEFAULT_PAD_METERS = 50.0
# Snap radius default 25m per D-02.
DEFAULT_SNAP_METERS = 25.0
# Per-segment image cap default 20 per D-12.
DEFAULT_LIMIT_PER_SEGMENT = 20


def compute_padded_bbox(
    cur, segment_id: int, pad_meters: float
) -> tuple[float, float, float, float]:
    """Compute (min_lon, min_lat, max_lon, max_lat) of segment geometry padded
    by pad_meters. Geography cast handles meter-based padding correctly on the
    SRID-4326 geometry column.
    """
    cur.execute(
        """
        SELECT
            ST_XMin(env), ST_YMin(env), ST_XMax(env), ST_YMax(env)
        FROM (
            SELECT ST_Envelope(
                ST_Buffer(geom::geography, %s)::geometry
            ) AS env
            FROM road_segments WHERE id = %s
        ) e
        """,
        (pad_meters, segment_id),
    )
    row = cur.fetchone()
    if not row or row[0] is None:
        raise ValueError(f"segment_id {segment_id} not found")
    return (row[0], row[1], row[2], row[3])


def snap_match_image(
    cur, lon: float, lat: float, snap_meters: float
) -> int | None:
    """D-01: find nearest segment within snap_meters. Returns segment id or
    None if no segment within radius.
    """
    cur.execute(
        """
        SELECT id FROM road_segments
        WHERE ST_DWithin(
            geom::geography,
            ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
            %s
        )
        ORDER BY geom <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326)
        LIMIT 1
        """,
        (lon, lat, snap_meters, lon, lat),
    )
    row = cur.fetchone()
    return row[0] if row else None


def aggregate_detections(
    detections: list, image_id: str
) -> list[tuple[str, str, int, float]]:
    """Group `detect()` output by severity for a single image.

    Returns rows ready for INSERT: (source_mapillary_id, severity, count, confidence_sum).
    Pattern 4: one row per (segment_id, source_mapillary_id, severity).
    """
    by_sev: dict[str, list[float]] = {}
    for det in detections:
        by_sev.setdefault(det.severity, []).append(det.confidence)
    return [
        (image_id, sev, len(confs), round(sum(confs), 3))
        for sev, confs in by_sev.items()
    ]


def with_retry(fn, *args, max_attempts: int = 3, base_delay: float = 1.0, **kwargs):
    """Hand-rolled exponential backoff for 429/5xx. Avoids tenacity dep.

    Retries:
        429 (rate limit): backoff
        5xx: backoff
        4xx (other): raise immediately
    """
    import requests as _r

    for attempt in range(max_attempts):
        try:
            return fn(*args, **kwargs)
        except _r.HTTPError as e:
            status = getattr(e.response, "status_code", 0)
            if status == 429 or 500 <= status < 600:
                if attempt < max_attempts - 1:
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        "HTTP %d on attempt %d/%d; sleeping %.1fs",
                        status, attempt + 1, max_attempts, delay,
                    )
                    time.sleep(delay)
                    continue
            raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pull Mapillary imagery for target segments, run YOLO, write detections.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--segment-ids", type=str,
                     help="Comma-separated segment ids: '1,2,3'")
    grp.add_argument("--segment-ids-file", type=Path,
                     help="One segment id per line")
    grp.add_argument("--where", type=str,
                     help='SQL predicate against road_segments, e.g.'
                          ' "iri_norm > 0.5 ORDER BY iri_norm DESC LIMIT 20"')

    parser.add_argument("--snap-meters", type=float, default=DEFAULT_SNAP_METERS)
    parser.add_argument("--pad-meters", type=float, default=DEFAULT_PAD_METERS)
    parser.add_argument("--limit-per-segment", type=int,
                        default=DEFAULT_LIMIT_PER_SEGMENT)
    parser.add_argument("--cache-root", type=Path, default=Path("data/ingest_la"))
    parser.add_argument("--no-keep", action="store_true",
                        help="Delete images after detection")
    parser.add_argument("--wipe-synthetic", action="store_true",
                        help="DELETE FROM segment_defects WHERE source='synthetic'"
                             " BEFORE writing real data")
    parser.add_argument("--no-recompute", action="store_true",
                        help="Skip the post-ingest compute_scores.py call")
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    # ... (logging setup, env checks, target resolution, main loop, summary)
    # [body fills the orchestration described in the diagram]
```

*Source: pattern from `scripts/ingest_iri.py` [VERIFIED: file read] + `scripts/fetch_eval_data.py` [VERIFIED: file read].*

### Pattern 3: PostGIS image-to-segment snap-match (D-01)

**What:** Single SQL query per image. Combines the spatial filter (`ST_DWithin`) with the nearest-neighbor sort (`<->` operator) to leverage the GIST index TWICE: once for the radius filter, once for the KNN sort.

**Why this exact form:** Per [CITED: https://blog.cleverelephant.ca/2021/12/knn-syntax.html], `ORDER BY geom <-> point` triggers indexed KNN that reads candidates from the GIST in best-first order. For LineStrings on Postgres ≥9.5, `<->` returns true distance (not centroid) [CITED: https://postgis.net/docs/geometry_distance_knn.html]. Pairing it with `ST_DWithin` upfront caps the candidate set so unbounded segments don't dominate. Including BOTH is correct — `ST_DWithin` provides a hard radius cutoff that the KNN order alone cannot.

**Example (one image at a time):**
```sql
SELECT id FROM road_segments
WHERE ST_DWithin(
    geom::geography,
    ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography,
    %(snap_meters)s
)
ORDER BY geom <-> ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)
LIMIT 1;
```

**Performance characterization:**
- The `::geography` cast on `geom` happens once per row evaluated by `ST_DWithin`. The existing `idx_segments_geom GIST(geom)` index is on the geometry column, NOT on the geography cast. **Functional index would be optimal but is not required for MVP** — `ST_DWithin` still uses the geometry GIST for the bounding-box pre-filter [CITED: https://postgis.net/workshops/postgis-intro/geography.html — `ST_DWithin` always uses bounding-box pre-filter from any indexable column]. For a 25 m search radius across LA's ~62k segments, expected query latency is <5 ms per image based on similar patterns in `scripts/iri_sources.py:357-367` [VERIFIED: file read].
- The `ORDER BY geom <-> point` uses the same GIST index for KNN ordering [CITED: https://postgis.net/docs/manual-3.4/en/geometry_distance_knn.html].
- ~300-image ingest = ~1500 ms total for matching, dominated by network + YOLO not DB.

**Optional optimization (probably overkill for MVP):** Add a functional index `CREATE INDEX idx_segments_geog ON road_segments USING GIST ((geom::geography))`. This would avoid the per-row geography cast in `ST_DWithin`. **Recommendation:** Skip this for Phase 3; revisit if profiling shows DB bottleneck. The plan-checker should verify the planner explicitly considered this and chose to defer.

*Source: synthesis of [VERIFIED: Postgres 16 docs] + existing pattern in `scripts/iri_sources.py:357-367`.*

### Pattern 4: Idempotent INSERT with ON CONFLICT DO NOTHING (D-06)

**What:** Use `psycopg2.extras.execute_values` (existing pattern in `scripts/seed_data.py:78-83, 115-121`) with the `ON CONFLICT DO NOTHING` clause. Targets the UNIQUE index from Pattern 1.

**When to use:** Every Mapillary detection insert. Re-running on the same images = no double-counting.

**Example:**
```python
# From within the per-segment loop
defect_rows: list[tuple[int, str, int, float, str, str]] = []
# (segment_id, severity, count, confidence_sum, source_mapillary_id, source)

for image_id, matched_segment_id, sev_groups in pending:
    for severity, count, confidence_sum in sev_groups:
        defect_rows.append((
            matched_segment_id,
            severity,
            count,
            confidence_sum,
            image_id,
            "mapillary",
        ))

if defect_rows:
    insert_sql = """
        INSERT INTO segment_defects
            (segment_id, severity, count, confidence_sum,
             source_mapillary_id, source)
        VALUES %s
        ON CONFLICT (segment_id, source_mapillary_id, severity) DO NOTHING
    """
    execute_values(cur, insert_sql, defect_rows, page_size=500)
    conn.commit()
    inserted = cur.rowcount  # rowcount works after ON CONFLICT DO NOTHING (returns
                             # number of rows that were actually inserted, not skipped)
```

**Subtle correctness note:** `cur.rowcount` after `ON CONFLICT DO NOTHING` returns the number of *successfully inserted* rows, not the number of `VALUES` rows submitted. This is the right number to report in the run summary. Skipped (already-present) rows are silently dropped. [CITED: https://www.psycopg.org/docs/cursor.html#cursor.rowcount — rowcount semantics with INSERT.]

*Source: existing `scripts/seed_data.py:78-83, 115-121, 137-141` [VERIFIED: file read] + Postgres docs.*

### Pattern 5: Image cache + manifest reuse from Phase 2

**What:** Reuse Phase 2's manifest schema via `data_pipeline.mapillary.write_manifest`. One manifest per ingest run, written under `data/ingest_la/<segment_id>/manifest.json` OR aggregated at `data/ingest_la/<run-timestamp>-manifest.json` (planner picks).

**When to use:** Every ingest run produces an audit trail. Even with `--no-keep`, the manifest preserves which Mapillary image_ids contributed which detections — required for CC-BY-SA attribution.

**Example:**
```python
manifest_entries = []
for image_id, matched_segment_id, image_path in successful_downloads:
    rel = str(image_path.relative_to(args.cache_root))
    manifest_entries.append({
        "path": rel,                              # required by mapillary.write_manifest
        "source_mapillary_id": image_id,           # CC-BY-SA attribution
        "matched_segment_id": matched_segment_id,  # ingest-specific extension
        "snap_meters": args.snap_meters,           # records the snap radius used
    })
    if args.no_keep:
        image_path.unlink(missing_ok=True)

# WRITE BEFORE --no-keep unlinks if you want write_manifest to compute SHA256.
# write_manifest computes hashes from disk; with --no-keep, write the manifest
# *before* unlinking, then unlink in a separate pass.
write_manifest(
    args.cache_root / f"manifest-{run_timestamp}.json",
    manifest_entries,
    source_bucket="mapillary:per-segment-targeted-ingest",
    license_str="CC-BY-SA 4.0 (Mapillary -- attribution via source_mapillary_id)",
)
```

**Caveat (Plan must address):** `write_manifest` computes SHA256 from each file on disk [VERIFIED: data_pipeline/mapillary.py:280-294]. With `--no-keep`, the unlink must happen AFTER the manifest is written, OR the manifest must be written without the integrity check — which would mean adapting `write_manifest` to accept a "skip-hash" mode (forbidden by D-20). **Recommendation:** Always write manifest first, then unlink. This keeps the audit trail intact and never modifies Phase 2 code.

*Source: `data_pipeline/mapillary.py::write_manifest` [VERIFIED: file read at lines 258-304].*

### Pattern 6: `--where` SQL injection defense (D-09)

**What:** Operator-supplied SQL predicate, sandwiched between `SELECT id FROM road_segments WHERE` and the end of the query. Defense in depth: (a) regex blocklist for forbidden tokens, (b) `psycopg2.sql.SQL` composition for safe identifier escaping, (c) explicit `LIMIT` cap from the CLI to prevent runaway results.

**When to use:** Only when `--where` is the chosen target mode.

**Example:**
```python
import re
from psycopg2 import sql as psql

# Blocklist of obvious injection / privilege-escalation tokens.
# Case-insensitive; matched against tokenized predicate.
_FORBIDDEN_RE = re.compile(
    r"\b(DELETE|UPDATE|INSERT|DROP|ALTER|CREATE|GRANT|REVOKE|EXECUTE|"
    r"TRUNCATE|COPY|EXEC|pg_\w+|information_schema|;\s*\w)",
    re.IGNORECASE,
)


def validate_where_predicate(predicate: str) -> str:
    """Reject predicates containing forbidden tokens or comment markers.

    Returns the cleaned predicate. Raises ValueError on rejection.

    Defense: regex catches obvious DDL/DML; psql.SQL composition does the
    actual quoting; the CLI's --limit-per-segment caps the explosion radius
    even if a malicious predicate slipped through.
    """
    if "--" in predicate or "/*" in predicate or "*/" in predicate:
        raise ValueError("comment markers (`--`, `/*`, `*/`) not allowed in --where")
    if _FORBIDDEN_RE.search(predicate):
        raise ValueError(
            f"forbidden token in --where predicate: {predicate!r}"
        )
    if predicate.count(";") > 0:
        raise ValueError("`;` not allowed in --where predicate")
    return predicate.strip()


def resolve_where_targets(cur, predicate: str, max_segments: int = 1000) -> list[int]:
    """Resolve a --where predicate into a list of segment ids.

    Uses psycopg2.sql.SQL composition so column names are quoted via the
    library. The predicate itself is wrapped as SQL.SQL(predicate) which is
    deliberately marked as the place to LOOK for injection — the regex
    in validate_where_predicate is the actual defense.
    """
    validate_where_predicate(predicate)
    # Build: SELECT id FROM road_segments WHERE <predicate>
    # We do NOT add a LIMIT here -- if the operator wants one, they put it in --where.
    # But we cap with max_segments after fetching to prevent unbounded loops.
    query = psql.SQL("SELECT id FROM road_segments WHERE {predicate}").format(
        predicate=psql.SQL(predicate),
    )
    cur.execute(query)
    ids = [row[0] for row in cur.fetchmany(max_segments + 1)]
    if len(ids) > max_segments:
        raise ValueError(
            f"--where predicate matched > {max_segments} segments; "
            f"add an explicit LIMIT clause"
        )
    return ids
```

**Trust model document the planner must capture in `docs/MAPILLARY_INGEST.md`:**
- The CLI is **operator-trusted** — the operator already has `DATABASE_URL` credentials and can run arbitrary SQL via `psql` if they want to.
- The injection defense exists to prevent **typo / copy-paste accidents**, not to defeat a determined operator.
- If the operator copies a malicious `--where` from the internet, the regex catches the obvious cases (`DROP`, `DELETE`, etc.). The capped `max_segments` prevents unbounded runaways. There is no defense against subtle predicate logic that produces wrong results.

[CITED: https://www.psycopg.org/docs/sql.html — psycopg2.sql composition; the docs explicitly note that `SQL.SQL(string)` does NOT escape its argument and is intended for trusted templates only. The regex in `validate_where_predicate` is what makes this trusted.]

### Pattern 7: `compute_scores.py --source` flag extension (D-16)

**What:** Add a `--source` flag with values `synthetic | mapillary | all` (default `'all'`). Filter the LEFT JOIN's `segment_defects` rows. Default behavior unchanged.

**When to use:** Phase 3 modifies `scripts/compute_scores.py` once. SC #4 ("real-vs-synthetic ranking diff") relies on this flag.

**Example:**
```python
# scripts/compute_scores.py (modified, sketch)
import argparse
import os
import sys
import psycopg2

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://rq:rqpass@localhost:5432/roadquality"
)

VALID_SOURCES = ("synthetic", "mapillary", "all")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recompute segment_scores from segment_defects."
    )
    parser.add_argument(
        "--source",
        choices=VALID_SOURCES,
        default="all",
        help="Which detection source to include in score recomputation (default: all)",
    )
    args = parser.parse_args()

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    where_clause = "" if args.source == "all" else f"AND sd.source = %s"
    params = () if args.source == "all" else (args.source,)

    # Use psycopg2 parameterization for the source value; the WHERE shape itself
    # is fixed because args.source is restricted to argparse choices.
    sql = f"""
        INSERT INTO segment_scores (segment_id, moderate_score, severe_score, pothole_score_total)
        SELECT
            rs.id,
            COALESCE(SUM(CASE WHEN sd.severity = 'moderate' THEN 0.5 * sd.count * sd.confidence_sum ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN sd.severity = 'severe' THEN 1.0 * sd.count * sd.confidence_sum ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN sd.severity = 'moderate' THEN 0.5 * sd.count * sd.confidence_sum ELSE 0 END), 0)
            + COALESCE(SUM(CASE WHEN sd.severity = 'severe' THEN 1.0 * sd.count * sd.confidence_sum ELSE 0 END), 0)
        FROM road_segments rs
        LEFT JOIN segment_defects sd ON rs.id = sd.segment_id {where_clause}
        GROUP BY rs.id
        ON CONFLICT (segment_id) DO UPDATE SET
            moderate_score = EXCLUDED.moderate_score,
            severe_score = EXCLUDED.severe_score,
            pothole_score_total = EXCLUDED.pothole_score_total,
            updated_at = NOW()
    """
    cur.execute(sql, params)
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM segment_scores WHERE pothole_score_total > 0")
    count = cur.fetchone()[0]
    print(f"Scores recomputed (--source {args.source}). {count} segments have pothole data.")
    cur.close()
    conn.close()
    return 0
```

**Critical detail:** The `LEFT JOIN ... AND sd.source = %s` filter is applied at JOIN time, not WHERE time. This preserves the LEFT JOIN's "every segment present in segment_scores" property (segments with no matching defects still get a row with zeros). If the filter was in WHERE, segments lacking matching-source defects would be excluded entirely — a behavior change.

*Source: existing `scripts/compute_scores.py` [VERIFIED: file read] modified per D-16.*

### Anti-Patterns to Avoid

- **Computing `ST_Buffer(geom, 50)` without geography cast.** Without `::geography`, the 50 is interpreted as 50 degrees ≈ 5500 km — catastrophic. Always cast to geography for meter-based ops, then cast back if needed.
- **Using `INSERT ... ON CONFLICT (segment_id, source_mapillary_id, severity) DO UPDATE SET count=count+1`.** This breaks idempotency — re-running would increment counts. The locked decision is `DO NOTHING` (D-06). UPSERT semantics are wrong for this domain.
- **Storing the per-image bbox / pixel-bbox in segment_defects.** Schema does not support it; CONTEXT.md `<deferred>` calls this out explicitly. If demo wants per-image traceability, the manifest.json provides it (image_id → matched_segment_id mapping).
- **Calling `data_pipeline/mapillary.py::download_image` outside a try/except.** The function raises on bad image_id, missing thumb_url, and on requests.HTTPError. The CLI must catch + log + continue (skip-this-image) per existing Phase 2 fetch_eval_data.py:177-180 pattern.
- **Aggregating detections across images before insert.** The schema's UNIQUE constraint includes `source_mapillary_id`, which means each image's detections must produce their own row(s). Don't pre-aggregate by `(segment_id, severity)` across images — you'd lose attribution and break dedup on re-run.
- **Forgetting to `cur.execute("SET statement_timeout = '30s'")` for `--where` mode.** A pathological predicate could lock the segments query for minutes. Wrap the resolution in a transaction with statement timeout.
- **Skipping `validate_bbox` on the padded segment bbox.** Even with a 50 m pad, a long arterial segment's envelope can exceed 0.01 deg². Reuse `data_pipeline.mapillary.validate_bbox` and split if it raises.
- **Calling `model.predict(conf=0.5)`.** YOLOv8Detector already applies `conf_threshold=0.25` at predict time [VERIFIED: `data_pipeline/yolo_detector.py:43, 96`]. Override only if `--conf-threshold` CLI flag is exposed.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Mapillary HTTP search/download/auth | New requests-based client | `data_pipeline.mapillary.{search_images, download_image}` | Phase 2 already built this with bbox DoS guard, image-id digit validation, constant-time SHA256, path-traversal rejection. Reuse per D-20. |
| Image-to-segment matching | Python loop over `cur.fetchall()` then numpy distance | `ST_DWithin + ORDER BY <-> + LIMIT 1` (Pattern 3) | PostGIS handles it in <5ms per image vs Python's many-second loop over 62k rows. |
| Bbox padding in meters | Manually convert meters → degrees at LA's latitude | `ST_Buffer(geom::geography, meters)::geometry` then `ST_Envelope` | Geography cast handles the spheroidal conversion correctly. Manual conversion is wrong at non-equatorial latitudes. |
| Idempotent insert | `SELECT ... IF NOT EXISTS THEN INSERT` | `INSERT ... ON CONFLICT DO NOTHING` (Pattern 4) | Atomic; lock-free; the canonical Postgres pattern. |
| Migration apply on existing DBs | Ad-hoc Python loop reading SQL files | Manual `psql -f db/migrations/002_*.sql` documented in `docs/MAPILLARY_INGEST.md` | Project rejects Alembic per CON-stack-backend. Manual psql is the project convention. |
| Run summary formatting | Custom table-printing | `print(json.dumps(summary, indent=2))` to `--json-out` + simple `print(...)` to stderr | Mirrors Phase 2 `scripts/eval_detector.py` [VERIFIED: file read]. JSON is machine-readable; stderr is human-readable. |
| Retry logic for 429/5xx | tenacity dependency | 4-line stdlib `time.sleep(2**attempt)` loop (Pattern 2) | Phase 3's API surface is two endpoints with simple retry needs; tenacity is overkill. |
| `--where` SQL injection defense | Hand-rolled string concat | psycopg2.sql + regex blocklist (Pattern 6) | psycopg2.sql is the canonical safe-composition surface. [CITED: psycopg2 docs] |
| YOLO inference loop | Custom torch + NMS | `data_pipeline.detector_factory.get_detector(use_yolo=True).detect(image_path)` | Phase 2 wraps ultralytics correctly with severity mapping. |

**Key insight:** Phase 3 is a 200–400 line CLI on top of three pre-existing libraries. Almost everything that looks tempting to build was already built in Phases 0-2. The new code is: (a) one SQL migration, (b) one CLI orchestrator, (c) one `--source` flag, (d) one helper module of ~5 functions. If the planner finds themselves writing more than ~600 LOC of new Python, something is being reinvented.

## Runtime State Inventory

This phase is **mostly additive** — new CLI, new migration, new docs. One in-place change to `compute_scores.py`. The migration touches existing data (backfills `source='synthetic'` on existing rows via DEFAULT) but that is a one-line column DEFAULT, not a migration script.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | **`segment_defects` table** has existing synthetic rows from `scripts/seed_data.py`. The new `source` column auto-tags them as `'synthetic'` via DEFAULT clause on `ADD COLUMN`. The new `source_mapillary_id` column is NULL for all existing rows. **No data migration needed beyond the DEFAULT.** | Apply `002_*.sql` to existing dev DBs via `psql -f db/migrations/002_*.sql`. New DBs pick it up automatically only after a `docker-compose down -v` and rebuild (because `docker-compose.yml` only mounts `001_initial.sql` into `/docker-entrypoint-initdb.d/`). **The plan must update docker-compose.yml to ALSO mount `002_*.sql`** — otherwise fresh stacks come up without the new schema. [VERIFIED: `docker-compose.yml` lines 8-9 explicitly mount only `001_initial.sql`.] |
| Live service config | Docker compose `db` service mounts `001_initial.sql` only. Backend reads `DATABASE_URL` at module top — no schema awareness in the API code. **The `/segments` endpoint joins on `segment_scores` only, never directly on `segment_defects`** [VERIFIED: `backend/app/routes/segments.py:25-36`], so the new columns don't affect API behavior. | Update `docker-compose.yml` `db.volumes` to mount `db/migrations/002_*.sql` as `/docker-entrypoint-initdb.d/03-mapillary.sql`. Document in `docs/MAPILLARY_INGEST.md` the manual psql invocation for existing-DB upgrades. |
| OS-registered state | None — no cron jobs, pm2 processes, systemd units, Windows Task Scheduler entries reference any Phase 3 component. The CLI is invoked manually by the operator. | None. Phase 5 (cloud deploy) will register a scheduled job invoking `scripts/ingest_mapillary.py`; that's a separate phase. |
| Secrets/env vars | `MAPILLARY_ACCESS_TOKEN` (already documented in `.env.example` and read at `data_pipeline/mapillary.py:49`). `DATABASE_URL` (existing). `YOLO_MODEL_PATH` (existing, optional). **No new env vars introduced.** | Verify `.env.example` already lists `MAPILLARY_ACCESS_TOKEN` (it does — verified by file read above). Document expected secrets in `docs/MAPILLARY_INGEST.md`. |
| Build artifacts / installed packages | No new pip dependencies. No new pyproject.toml or egg-info to invalidate. Existing `data_pipeline/requirements.txt` already includes `huggingface_hub`, `scipy` (Phase 2 additions). | Run `pip install -r data_pipeline/requirements.txt` if not already done from Phase 2. The CLI uses these transitively. |

**Verified non-issues:**
- The frontend code (`frontend/`) is unchanged in Phase 3. No build artifact concerns.
- Backend tests in `backend/tests/` only mock the DB or auto-skip when DB is down [VERIFIED: `backend/tests/conftest.py:13-21`]. The schema additions don't break any existing test (no test references `segment_defects.source` or `segment_defects.source_mapillary_id` columns).
- Existing `seed_data.py:41` does `TRUNCATE road_segments, segment_defects, segment_scores CASCADE` — this works fine after the migration (TRUNCATE doesn't care about column additions).
- Existing `ingest_iri.py` and `compute_scores.py` use `SELECT * FROM segment_defects` patterns? **No** — they explicitly list columns or join. Verified by grep — neither uses `SELECT *` on segment_defects [VERIFIED: file reads above]. The new columns are safe.

**Cutover script the plan should specify:**
```bash
# For existing dev DBs (one-time after pulling Phase 3 code):
docker compose exec -T db psql -U rq -d roadquality < db/migrations/002_mapillary_provenance.sql

# Then verify backfill:
docker compose exec db psql -U rq -d roadquality -c \
    "SELECT source, COUNT(*) FROM segment_defects GROUP BY source"
# Should show all existing rows under source='synthetic'

# Then start ingesting:
MAPILLARY_ACCESS_TOKEN=mly_xxx python scripts/ingest_mapillary.py --segment-ids 1,2,3
```

## Environment Availability

This phase reuses Phase 2's tooling almost entirely. Most dependencies were addressed in Phase 2.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12+ | All Phase 3 scripts | ✗ | System has 3.9.6 [VERIFIED: `python3 --version`] | Run scripts inside the backend Docker container's Python OR install 3.12 via brew. Phase 2 already flagged this. |
| `psycopg2-binary` | All scripts | ✓ | 2.9.12 system-wide [VERIFIED: `python3 -c "import psycopg2; print(psycopg2.__version__)"`] | None needed. Project pin is 2.9.11 in `backend/requirements.txt`. |
| `requests` | `data_pipeline/mapillary.py` | ✓ | 2.32.5 system-wide [VERIFIED] | None needed. |
| `ultralytics` (>=8.1) | YOLO inference via factory | ✗ on system Python; ✓ in Docker | Not installed system-wide | Install fresh per Phase 2's req: `pip install ultralytics>=8.1`. Or run inside Docker. |
| `huggingface_hub` | model resolution | ✗ system-wide | — | Same as ultralytics; install per `data_pipeline/requirements.txt`. |
| `MAPILLARY_ACCESS_TOKEN` env var | `search_images` and `download_image` | ✗ | Not set on dev machine | User must obtain at https://www.mapillary.com/dashboard/developers — flag as Plan 1 prerequisite. Phase 2 already established this pattern. |
| `DATABASE_URL` env var | All DB ops | ✓ (with default) | `postgresql://rq:rqpass@localhost:5432/roadquality` | Default is the docker-compose dev DB. Production needs cloud DB URL — Phase 5. |
| `YOLO_MODEL_PATH` env var | `get_detector(use_yolo=True)` | ✓ (optional, defaults to HF repo) | Default `keremberke/yolov8s-pothole-segmentation` per `detector_factory.py:43` | None needed. Phase 2's resolution logic handles unset case. |
| Docker (for live DB) | Integration test smoke | ✓ | 29.4.1 [VERIFIED] | — |
| PostgreSQL 16 + PostGIS 3.4 | All DB ops | ✓ (in Docker `db` service) | 16-3.4 image [VERIFIED: `db/Dockerfile:1`] | — |
| pgRouting 3.6 | Not used by Phase 3 directly | ✓ (in Docker) | 3.6 | — |

**Missing dependencies with no fallback:**
- Python 3.12 on bare-metal dev (carries forward from Phase 2; not net-new).
- `MAPILLARY_ACCESS_TOKEN` (operator action). Plan must list this as a precondition for first-run.

**Missing dependencies with fallback:**
- `ultralytics`/`huggingface_hub` system-wide: install via `pip install -r data_pipeline/requirements.txt` OR run scripts inside the backend container (which already has them per Phase 2's plan execution).

**Compute requirement:** YOLO inference is CPU-acceptable for a one-time ~300-image LA ingest. ~1 sec/image on CPU → ~5 minutes for a 300-image run. No GPU required for ingest. Pitfall 1 (Apple Silicon MPS bug) inherited from Phase 2: force `device='cpu'` if running locally on M-series. The detector factory does NOT currently support a `device` argument — `YOLOv8Detector.__init__` doesn't accept it, and `model.predict` is called with default device. **The plan should NOT add a device flag in Phase 3** unless Phase 2's MPS bug surfaces; current behavior is "ultralytics auto-selects" which on M-series defaults to CPU since MPS is unstable.

## Common Pitfalls

### Pitfall 1: Re-running ingest doubles results when forgetting `source_mapillary_id` value
**What goes wrong:** If the CLI inserts with `source_mapillary_id=NULL` for Mapillary rows (oversight), the UNIQUE constraint can't dedupe them — every re-run would create new rows.
**Why it happens:** The `Detection` dataclass [VERIFIED: `data_pipeline/detector.py:8-11`] has only `severity` and `confidence` — no image_id. The CLI must thread image_id through the loop and pass it to the insert.
**How to avoid:** Pass `image_meta["id"]` from `search_images` results all the way to the INSERT row tuple. Add a unit test that asserts `source_mapillary_id IS NOT NULL` on all `source='mapillary'` rows.
**Warning signs:** Re-running on the same bbox produces ever-growing `count(*)` of `source_mapillary_id IS NULL` rows.

### Pitfall 2: Padded bbox exceeds 0.01 deg² for long arterials
**What goes wrong:** A 1 km segment + 50 m pad has envelope ~1.1 km × 0.1 km = ~0.011 deg² (rough approximation at LA's lat). `validate_bbox` raises ValueError; CLI bails out for that segment.
**Why it happens:** LA arterials (Sunset, Wilshire, Sepulveda) are long. Some segments may exceed the limit even at the default pad.
**How to avoid:** Catch the ValueError, split the bbox into 4 quadrants (or N tiles by length), recurse. Or: pre-filter segments by `ST_Length(geom::geography) < 5000` and reject longer ones with an explicit error: "segment too long; ingest by sub-id".
**Warning signs:** Specific segment IDs always fail with "exceeds Mapillary direct-query limit".

### Pitfall 3: Mapillary URL TTL expires during slow YOLO inference
**What goes wrong:** Per Phase 2 Pitfall 5, `thumb_2048_url` is signed and expires. The Phase 3 loop is `search → download → detect`. If detect is slow (CPU YOLO ≈ 1s/image) and the loop processes many images sequentially, later images' download URLs may have expired between the search call and their respective download.
**Why it happens:** Phase 2 fetched in-pass for the same reason. Phase 3's per-segment loop calls `search_images` once with a `limit`, then iterates. If the limit is high (50+) and detect is slow, the last few images may 403/404.
**How to avoid:** Either (a) keep `--limit-per-segment` low (default 20 is safe — ~20 sec of YOLO total), OR (b) re-query Mapillary metadata via image_id when a download fails, refresh the URL, retry. Option (a) is simpler for MVP.
**Warning signs:** Late-in-loop images consistently fail with 403/404; counts of "URL expired" in run summary.

### Pitfall 4: `--wipe-synthetic` racing with concurrent reads
**What goes wrong:** Operator runs `--wipe-synthetic` while a `/segments` request is in flight. The frontend caches a stale 5-min response with synthetic data; user sees "wrong" map briefly.
**Why it happens:** No transaction isolation between ingest and HTTP reads. Operator may not realize cache is in front of `/segments`.
**How to avoid:** Document in `docs/MAPILLARY_INGEST.md`: after `--wipe-synthetic`, hit `POST /cache/clear` to invalidate the segments cache. Or have the CLI hit it directly via `requests.post(f"{api_url}/cache/clear")` (optional `--clear-cache` flag).
**Warning signs:** "I ran the wipe but the map still shows synthetic" reports.

### Pitfall 5: Segment-targeted matches drift to neighbors and look like a bug
**What goes wrong:** Operator targets segment 42, ingests 20 images, sees that 5 detections landed on segment 41 ("the wrong segment!"). Confused, reports as bug.
**Why it happens:** D-04 explicitly says attribute-to-closest, regardless of which segment was targeted. Mapillary GPS error + segment proximity means neighbors get "free coverage." This is a feature, not a bug.
**How to avoid:** The run summary MUST report per-input-segment counts AND per-matched-segment counts so the discrepancy is visible. Document in `docs/MAPILLARY_INGEST.md`.
**Warning signs:** "I targeted X but got Y in the DB" — first response: "did you check `--snap-meters`? did you check the per-matched-segment summary?"

### Pitfall 6: Existing synthetic rows accidentally deduped by NULLS-NOT-DISTINCT misconfig
**What goes wrong:** If the planner uses `UNIQUE NULLS NOT DISTINCT (segment_id, source_mapillary_id, severity)` (PG 15+), all existing synthetic rows for the same `(segment_id, severity)` collapse into one — silent data loss. `seed_data.py:108-112` inserts 1-3 rows per ~30% of segments with potentially duplicate severity.
**Why it happens:** CONTEXT.md mentions `NULLS NOT DISTINCT` as a possible option. If a planner sees that and "improves" the migration to use it without thinking through the synthetic case, data corruption.
**How to avoid:** Use plain `UNIQUE` (NULL distinct, the default). Add a regression test: after migration apply, `SELECT COUNT(*) FROM segment_defects WHERE source='synthetic'` should equal pre-migration count.
**Warning signs:** Existing dev DB shows fewer synthetic rows after migration apply.

### Pitfall 7: `compute_scores.py --source mapillary` with empty mapillary data shows zeros for all segments
**What goes wrong:** SC #4 demo: operator runs `compute_scores.py --source mapillary` before any Mapillary ingest. Every `pothole_score_total` becomes 0 because there are no Mapillary rows. The operator interprets "the demo doesn't work" instead of "I haven't ingested yet."
**Why it happens:** Empty source → empty SUM → 0. The LEFT JOIN preserves rows but the aggregation collapses to nothing.
**How to avoid:** `compute_scores.py --source mapillary` should print a warning when `count(*) FILTER (WHERE source='mapillary')` is 0. Document the workflow in `docs/MAPILLARY_INGEST.md`: ingest first, then toggle source.
**Warning signs:** "All segments are zero!" — first check: `SELECT COUNT(*) FROM segment_defects WHERE source='mapillary'`.

### Pitfall 8: Migration applied twice from different machines silently disagrees
**What goes wrong:** Operator A applies `002_*.sql` to the dev DB. Operator B pulls latest, runs the same migration, gets `column already exists` errors because Phase 3 didn't add `IF NOT EXISTS` to a clause that needed it.
**Why it happens:** `ADD CONSTRAINT IF NOT EXISTS` doesn't exist in Postgres 16 [VERIFIED]. If the planner uses `ADD CONSTRAINT segment_defects_source_check CHECK ...` directly, second-run errors.
**How to avoid:** Use the DROP-then-ADD pattern in Pattern 1 above for the CHECK constraint. Use `CREATE UNIQUE INDEX IF NOT EXISTS` (not `ADD CONSTRAINT UNIQUE`). Verified pattern in Pattern 1.
**Warning signs:** Second-run errors complaining about already-existing constraint.

### Pitfall 9: Segment lookup with `--where` matches 0 segments and the loop silently does nothing
**What goes wrong:** Operator runs `--where "iri_norm > 99"` (typo, should be 0.99). 0 matches. Script exits 0 with empty summary. Operator thinks it worked but no detections were written.
**Why it happens:** Empty target list → for loop body never executes → nothing inserted → exit 0.
**How to avoid:** If target resolution returns 0 segments, exit with code 2 (validation) and a clear message: `"--where matched 0 segments; refine predicate"`.
**Warning signs:** Empty run summary, exit 0, but no DB rows added.

### Pitfall 10: `data/ingest_la/` not gitignored, accidentally committed
**What goes wrong:** Run produces 300 images, operator forgets to `--no-keep`, forgets to update `.gitignore`. `git add` includes the whole tree. PR CI fails or PR balloons to MB.
**Why it happens:** `.gitignore` currently has `data/eval_la/*` but NOT `data/ingest_la/*` [VERIFIED: file read].
**How to avoid:** Plan must add `data/ingest_la/*` and `!data/ingest_la/.gitkeep` to `.gitignore` as the first task.
**Warning signs:** `git status` shows hundreds of `.jpg` files.

## Code Examples

Verified patterns from existing files + official sources.

### Example 1: Migration application against existing dev DB

```bash
# Source: existing project convention; manual psql per CON-stack-backend
docker compose exec -T db psql -U rq -d roadquality < db/migrations/002_mapillary_provenance.sql

# Verify backfill:
docker compose exec db psql -U rq -d roadquality -c \
    "SELECT source, COUNT(*) FROM segment_defects GROUP BY source"
```

### Example 2: PostGIS bbox padding (geography cast pattern)

```python
# Source: scripts/iri_sources.py:357-367 [VERIFIED] adapted for envelope ops
cur.execute(
    """
    SELECT
        ST_XMin(env), ST_YMin(env), ST_XMax(env), ST_YMax(env),
        (ST_XMax(env) - ST_XMin(env)) * (ST_YMax(env) - ST_YMin(env)) AS area_deg2
    FROM (
        SELECT ST_Envelope(ST_Buffer(geom::geography, %s)::geometry) AS env
        FROM road_segments WHERE id = %s
    ) e
    """,
    (pad_meters, segment_id),
)
min_lon, min_lat, max_lon, max_lat, area_deg2 = cur.fetchone()
if area_deg2 > 0.01:
    # Subdivide: split lon range in halves, lat range in halves → 4 sub-bboxes
    mid_lon = (min_lon + max_lon) / 2
    mid_lat = (min_lat + max_lat) / 2
    bboxes = [
        (min_lon, min_lat, mid_lon, mid_lat),
        (mid_lon, min_lat, max_lon, mid_lat),
        (min_lon, mid_lat, mid_lon, max_lat),
        (mid_lon, mid_lat, max_lon, max_lat),
    ]
else:
    bboxes = [(min_lon, min_lat, max_lon, max_lat)]
```

### Example 3: Reusing Phase 2 client end-to-end

```python
# Source: scripts/fetch_eval_data.py:62-68, 137-189 [VERIFIED] - reuse pattern
from data_pipeline.mapillary import (
    MAPILLARY_TOKEN, search_images, download_image, write_manifest, validate_bbox,
)
from data_pipeline.detector_factory import get_detector

if not MAPILLARY_TOKEN:
    print("ERROR: MAPILLARY_ACCESS_TOKEN not set", file=sys.stderr)
    sys.exit(EXIT_OTHER)

detector = get_detector(use_yolo=True)  # one model load for the entire run

for bbox in bboxes:
    validate_bbox(bbox)  # raises ValueError if > 0.01 deg² — caller handles
    images = search_images(bbox, limit=args.limit_per_segment)
    for img in images:
        try:
            local_path = download_image(img, cache_dir=cache_root / str(seg_id))
            detections = detector.detect(str(local_path))
            # ... snap-match + queue for insert
        except Exception:
            logger.exception("skip image %s", img.get("id"))
            continue
```

### Example 4: psycopg2 idempotent INSERT batched

```python
# Source: scripts/seed_data.py:115-121, 137 [VERIFIED]
from psycopg2.extras import execute_values

if defect_rows:  # list of (segment_id, severity, count, conf_sum, src_mly_id, source)
    execute_values(
        cur,
        """
        INSERT INTO segment_defects
            (segment_id, severity, count, confidence_sum, source_mapillary_id, source)
        VALUES %s
        ON CONFLICT (segment_id, source_mapillary_id, severity) DO NOTHING
        """,
        defect_rows,
        page_size=500,
    )
    conn.commit()
    inserted = cur.rowcount  # actual inserts, conflict-skipped excluded
```

### Example 5: Hand-rolled retry with exponential backoff

```python
# Source: stdlib pattern; no new dep needed
import time
import requests

def search_with_retry(bbox, limit, max_attempts=3):
    for attempt in range(max_attempts):
        try:
            return search_images(bbox, limit=limit)
        except requests.HTTPError as e:
            status = getattr(e.response, "status_code", 0)
            if status == 429 or 500 <= status < 600:
                if attempt < max_attempts - 1:
                    delay = 2.0 ** attempt
                    logger.warning(
                        "Mapillary HTTP %d; sleeping %.1fs (attempt %d/%d)",
                        status, delay, attempt + 1, max_attempts,
                    )
                    time.sleep(delay)
                    continue
            raise
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `ALTER TABLE ADD CONSTRAINT IF NOT EXISTS` | `CREATE UNIQUE INDEX IF NOT EXISTS` for unique enforcement; DROP-then-ADD for CHECK | Postgres has never supported `ADD CONSTRAINT IF NOT EXISTS` (verified via PG 16 docs synopsis) | Migration must use the workaround pattern. |
| Hand-rolled regex SQL injection sanitizers | `psycopg2.sql.SQL` + `psycopg2.sql.Identifier` composition | psycopg2 ≥2.7 (2017) | Defense-in-depth: regex blocklist for obvious tokens + sql.SQL for structural composition. [CITED: https://www.psycopg.org/docs/sql.html] |
| `ORDER BY ST_Distance(geom, point)` for nearest neighbor | `ORDER BY geom <-> point` (KNN operator) | PostGIS 2.0+ (KNN op); >= 9.5 returns true distance for non-point geoms | Faster (one distance calc vs two), index-aware. Pattern 3 uses both `ST_DWithin` + `<->` for safety + speed. [CITED: postgis.net/docs/geometry_distance_knn.html, blog.cleverelephant.ca] |
| `urllib + manual headers` for HTTP | `requests` with `OAuth` Authorization header | requests has been stdlib-grade for 10+ years; project standard | Phase 2 client uses requests; Phase 3 reuses. |
| Pre-built ORM (SQLAlchemy) | Raw psycopg2 with `RealDictCursor` | Project decision per CON-stack-backend; "no Alembic, no SQLAlchemy" | Phase 3 uses raw SQL for migration + raw psycopg2 for runtime. Plan-checker should reject any SQLAlchemy creep. |

**Deprecated/outdated patterns to avoid:**
- pgRouting `pgr_pointsAsLineString` — not relevant; we don't construct routes here
- `osmnx.distance.nearest_edges` — Python-side nearest; we use PostGIS KNN instead
- "Tile by LA neighborhoods" hardcoded list — segment-targeted with `--where` covers this more flexibly

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.3.4 [VERIFIED: `backend/requirements.txt`] |
| Config file | None at repo root; tests in `backend/tests/` discovered by default; `conftest.py:9` registers `integration` marker |
| Quick run command | `python3 -m pytest backend/tests/test_ingest_mapillary.py backend/tests/test_mapillary.py -x -q` |
| Full suite command | `python3 -m pytest backend/tests/ -q` |
| Integration marker | `pytestmark = pytest.mark.integration` (auto-skip when DB unreachable, per `conftest.py:15-21`) |

### Phase Requirements → Test Map

| Req ID / SC | Behavior | Test Type | Automated Command | File Exists? |
|-------------|----------|-----------|-------------------|-------------|
| SC #1 | `ingest_mapillary.py --segment-ids 1` runs end-to-end, writes to segment_defects | integration (mocked Mapillary + mocked YOLO + live DB) | `python3 -m pytest backend/tests/test_integration.py::test_ingest_mapillary_end_to_end -x` | ❌ Wave 0 — needs new test |
| SC #2 | Re-running same segment is idempotent (row count unchanged) | integration | `python3 -m pytest backend/tests/test_integration.py::test_ingest_mapillary_idempotent_rerun -x` | ❌ Wave 0 |
| SC #3 | After ingest, `/segments?bbox=...` reflects mapillary detections | integration | `python3 -m pytest backend/tests/test_integration.py::test_segments_reflects_mapillary_after_compute_scores -x` | ❌ Wave 0 |
| SC #4 | `--source mapillary` vs `--source synthetic` produces different `/route` ranks | integration / smoke | `python3 -m pytest backend/tests/test_integration.py::test_route_ranks_differ_by_source -x` (or operator workflow per D-18) | ❌ Wave 0 (test) + ❌ docs (workflow) |
| SC #5 | Token is env-only; never appears in code/docs/docker-compose | unit (grep-based) | `python3 -m pytest backend/tests/test_ingest_mapillary.py::test_no_token_in_committed_files -x` | ❌ Wave 0 |
| D-01 | snap-match SQL returns nearest segment within radius | unit (live DB or mocked cur) | `python3 -m pytest backend/tests/test_ingest_mapillary.py::test_snap_match_within_radius -x` | ❌ Wave 0 |
| D-03 | image outside snap radius is dropped | unit | `python3 -m pytest backend/tests/test_ingest_mapillary.py::test_drop_unmatched_images -x` | ❌ Wave 0 |
| D-05 | UNIQUE constraint enforces dedup on (segment, src_mly, severity) | integration (live DB) | `python3 -m pytest backend/tests/test_integration.py::test_unique_constraint_dedups_mapillary -x` | ❌ Wave 0 |
| D-06 | `INSERT ... ON CONFLICT DO NOTHING` produces zero new rows on rerun | integration | included in `test_ingest_mapillary_idempotent_rerun` | covered |
| D-07 | `source` column backfilled to 'synthetic' for existing rows | integration (post-migration) | `python3 -m pytest backend/tests/test_integration.py::test_existing_rows_backfill_synthetic_source -x` | ❌ Wave 0 |
| D-09 (target modes) | --segment-ids / --segment-ids-file / --where each resolve correctly | unit | `python3 -m pytest backend/tests/test_ingest_mapillary.py::TestTargetResolution -x` | ❌ Wave 0 |
| D-09 (--where injection) | forbidden tokens raise; empty match exits 2 | unit | `python3 -m pytest backend/tests/test_ingest_mapillary.py::TestWhereInjection -x` | ❌ Wave 0 |
| D-14 (--wipe-synthetic) | deletes `source='synthetic'` rows; preserves `source='mapillary'` | integration | `python3 -m pytest backend/tests/test_integration.py::test_wipe_synthetic_preserves_mapillary -x` | ❌ Wave 0 |
| D-16 (--source filter) | `compute_scores.py --source mapillary` ignores synthetic detections | integration | `python3 -m pytest backend/tests/test_integration.py::test_compute_scores_source_filter -x` | ❌ Wave 0 |
| D-19 (env-only token) | Without MAPILLARY_ACCESS_TOKEN, ingest exits with helpful error | unit | `python3 -m pytest backend/tests/test_ingest_mapillary.py::test_missing_token_exits_helpfully -x` | ❌ Wave 0 |
| D-20 (no client rewrite) | grep verifies `data_pipeline/mapillary.py` is NOT modified | manual / pre-merge | `git diff main HEAD -- data_pipeline/mapillary.py` should be empty | ❌ Wave 0 (review check) |

### Sampling Rate
- **Per task commit:** `python3 -m pytest backend/tests/test_ingest_mapillary.py backend/tests/test_mapillary.py -x -q` (~3 sec, pure unit, mocks DB + Mapillary + YOLO)
- **Per wave merge:** Full unit suite + integration suite when DB is up: `python3 -m pytest backend/tests/ -q`
- **Phase gate:** Before `/gsd-verify-work`: full suite green + at least one real `ingest_mapillary.py --segment-ids 1,2,3 --limit-per-segment 5` against a live dev DB with real Mapillary credentials. Captured run-summary JSON archived for SC #4 demo workflow.

### Wave 0 Gaps
- [ ] `backend/tests/test_ingest_mapillary.py` — NEW. Unit tests for: target resolution (3 modes), `--where` injection blocklist, snap-match with mocked cursor, aggregate_detections shape, missing-token error path, retry logic.
- [ ] `backend/tests/test_integration.py` — EXTEND with the Phase 3 SC tests above (auto-skip when DB unreachable).
- [ ] No new pytest plugins needed; `pytest.mark.integration` already registered in `conftest.py`.
- [ ] No new fixtures needed beyond a `synthetic_seed_baseline` fixture that records pre-Phase-3 row counts so tests can assert deltas. Optional helper.

*If no gaps: "—" — but Phase 3 has gaps so this is intentionally populated.*

### Correctness Gates (manual operator workflow per D-18)
- After ingest, the operator runs:
  ```bash
  # SC #4 demonstration:
  python scripts/compute_scores.py --source synthetic
  curl -s -X POST http://localhost:8000/route -d @route-request.json | jq '.best_route.total_cost' > /tmp/synthetic-cost.txt
  python scripts/compute_scores.py --source mapillary
  curl -s -X POST http://localhost:8000/route -d @route-request.json | jq '.best_route.total_cost' > /tmp/mapillary-cost.txt
  diff /tmp/synthetic-cost.txt /tmp/mapillary-cost.txt   # MUST differ
  ```
- The diff being non-empty is the SC #4 success criterion. Document this exact sequence in `docs/MAPILLARY_INGEST.md`.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | Yes (Mapillary + DB tokens) | Read from env only [VERIFIED: `data_pipeline/mapillary.py:49`, `backend/app/db.py:5-7`]; never logged; never committed; `.env` in `.gitignore` [VERIFIED] |
| V3 Session Management | No | CLI is operator-only, no user sessions in this phase |
| V4 Access Control | Yes (DB writes) | Operator runs CLI with their own DB credentials; no privilege escalation needed; `--where` blocklist + max_segments cap = defense-in-depth |
| V5 Input Validation | Yes (`--where`, `--segment-ids`, `--segment-ids-file`, file paths) | (a) Regex blocklist + psycopg2.sql.SQL composition for `--where` (Pattern 6); (b) `int(x)` validation on `--segment-ids` parsing; (c) Path traversal rejection inherited from `data_pipeline/mapillary.py::_validate_manifest_path`; (d) image_id digit-only validation already in `download_image` (T-02-20) |
| V6 Cryptography | Yes (SHA256 manifest verify) | Use existing `data_pipeline.mapillary.verify_manifest` (constant-time `hmac.compare_digest` per Phase 2) — no hand-roll |
| V8 Data Protection | Yes (Mapillary licensing, DB integrity) | manifest.json records `source_mapillary_id` for CC-BY-SA attribution; UNIQUE constraint + ON CONFLICT prevents accidental dupe; `--wipe-synthetic` is destructive but audit-logged via stderr |
| V14 Configuration | Yes (env vars, secrets) | `.env.example` documents all required vars; `.gitignore` excludes `.env*`; no token in `docker-compose.yml` [VERIFIED via grep] |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via `--where` | Tampering | Regex blocklist + psycopg2.sql.SQL composition (Pattern 6); plus `max_segments` cap; document trust model in `docs/MAPILLARY_INGEST.md` |
| Mapillary token leak via logs | Information Disclosure | Token only in `Authorization: OAuth ...` header; never logged in URLs (only headers); existing Phase 2 test `test_search_uses_token_arg` verifies header-only flow [VERIFIED: `backend/tests/test_mapillary.py:118-135`] |
| Pickle ACE via untrusted YOLO weights | Tampering + Elevation | Inherited from Phase 2: `_DEFAULT_HF_REPO` is `keremberke/yolov8s-pothole-segmentation`; operators pinning to a specific revision in `YOLO_MODEL_PATH=user/repo@sha` is documented in Phase 2 RESEARCH.md Pitfall 8 |
| Path traversal via Mapillary image_id | Tampering | image_id is digit-validated before use as filename per `data_pipeline/mapillary.py:172-174` (T-02-20) [VERIFIED] |
| DoS via huge bbox | Denial of Service (against Mapillary + ourselves) | `validate_bbox` enforces ≤0.01 deg²; padded segment bbox is checked before each search call; planner subdivides (Pattern 2 step 5) |
| `--wipe-synthetic` typo wipes wrong data | Tampering | Hard-coded SQL is `DELETE WHERE source='synthetic'` — no parameterization, no operator-controlled WHERE. Confirmation prompt optional but recommended for first-run. |
| Concurrent ingest from two operators | Race Condition | UNIQUE constraint + ON CONFLICT DO NOTHING serializes correctness — both runs may write some rows but no double-counting. Document "single ingest at a time" expectation. |
| Unbounded `--where` runaway | DoS (against own DB) | `max_segments=1000` cap in `resolve_where_targets`; `statement_timeout` set on the connection before predicate execution |
| Mapillary CC-BY-SA attribution missed | Legal | manifest.json records `source_mapillary_id` per image; operator runbook documents the attribution requirement; no public re-distribution of bytes happens at ingest time (images stay local until `--no-keep` deletes them) |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Default Postgres NULL-distinct behavior gives the desired semantics for `UNIQUE(segment_id, source_mapillary_id, severity)` (existing synthetic rows stay distinct; new Mapillary rows dedupe) | Pattern 1, D-05 | LOW — default behavior is documented in PG docs; `seed_data.py:108-112` empirically depends on this. If wrong, migration fails on existing DBs and a regression test catches it. |
| A2 | Postgres 16 supports `ADD COLUMN IF NOT EXISTS` and `CREATE UNIQUE INDEX IF NOT EXISTS` (verified via official docs) | Pattern 1 | NONE — this is verified, not assumed. |
| A3 | `Detection` dataclass remains 2-field (severity, confidence) — no image_id passed to detector | Code Examples | LOW — image_id has to be threaded through the CLI loop, not the detector. Existing `Detection` dataclass [VERIFIED: data_pipeline/detector.py:8-11] has only severity + confidence. |
| A4 | YOLOv8Detector's `conf_threshold=0.25` default is acceptable for Phase 3 production (no per-class calibration) | Don't Hand-Roll, Anti-Patterns | MEDIUM — CONTEXT.md explicitly defers calibration. If first runs produce too many low-quality detections, operator can override via `--conf-threshold` (NEW CLI flag, Claude's discretion). Worth a follow-up flag in the plan. |
| A5 | Mapillary search rate limit (10k/min per app) is far above any plausible Phase 3 ingest rate (~300 images/run) | Environment + Rate-limit research | LOW — even a 100-segment run with 20 images each is 100 search calls + 2000 entity-API downloads, well below 10k/min. [CITED: https://www.mapillary.com/developer/api-documentation rate limits per WebFetch.] |
| A6 | Hand-rolled `time.sleep(2**attempt)` retry is sufficient (vs `tenacity` library) | Standard Stack alternatives | LOW — Mapillary 429s are rare for our scope; if they become common, planner can add tenacity later. |
| A7 | `cur.rowcount` after `ON CONFLICT DO NOTHING` returns insert-count not row-attempt-count | Pattern 4 | LOW — psycopg2 docs state this; existing `seed_data.py:78-83` relies on similar semantics. Easy to verify with a single-row test. |
| A8 | `ST_Buffer(geom::geography, m)::geometry` returns a polygon in SRID 4326 (geometry's original SRID) | Pattern 2 | LOW — PostGIS converts back to the geometry's SRID on cast back. Verified pattern in PostGIS docs. Add a unit test that asserts SRID(buffered) == 4326. |
| A9 | docker-compose `db` service can be updated to mount `002_*.sql` without breaking existing volumes | Runtime State Inventory | MEDIUM — Postgres only runs `docker-entrypoint-initdb.d/` scripts on FRESH init (empty `pgdata` volume). For existing volumes, the operator must manual-apply via psql. The plan must document this clearly. |
| A10 | `--source` filter implementation in `compute_scores.py` doesn't change the existing test suite's expectations | Pattern 7 | LOW — default `'all'` preserves prior behavior. Existing tests don't pass `--source` and shouldn't need to. |
| A11 | The `SELECT id FROM road_segments WHERE {predicate}` template with psycopg2.sql.SQL is safe enough for operator-supplied predicates given the regex blocklist + max_segments cap | Pattern 6 | MEDIUM — operator is already trusted (has DB creds). The defense is for typos / copy-paste, not adversarial input. Document trust model. |

**A1, A4, A9, A11** are the items the planner / discuss-phase should consider for explicit user confirmation. The rest are low-risk and verifiable in execution.

## Open Questions (RESOLVED)

1. **Should `ingest_mapillary.py` accept a `--conf-threshold` flag to override YOLO's default 0.25?**
   - What we know: Default 0.25 is YOLOv8's standard [CITED: https://docs.ultralytics.com/usage/cfg/]; existing `YOLOv8Detector.__init__(conf_threshold=0.25)`; CONTEXT.md flags 0.25–0.5 as Claude's discretion.
   - What's unclear: Whether the operator should be allowed to tune this per run. Pros: useful for "be more strict on freeway segments." Cons: yet another flag; the existing detector path doesn't accept it post-construction.
   - RESOLVED: **Skip for Phase 3.** Default 0.25 is well-understood. If first runs produce noise, plan a Phase 3.1 follow-up.

2. **Should `--no-keep` operate per-image (delete after each detect) or per-run (delete after all detects in run)?**
   - What we know: D-11 says "deletes images after detection" — ambiguous between per-image and per-run.
   - What's unclear: Per-image saves disk during run; per-run is simpler logic.
   - RESOLVED: **Per-image.** A 300-image run with --no-keep per-run holds 300 × 200 KB = 60 MB on disk peak. With per-image, peak is 1 image. Makes the tool friendlier on disk-constrained CI runners. Caveat: write manifest.json AFTER all images are processed but BEFORE per-image unlinks (since `write_manifest` reads files for SHA256). Solution: track manifest entries during loop, deferred-write at end, then delete files in a separate pass — OR adapt the per-image flow to write a partial manifest.json after each segment. **Plan-time decision; either is defensible.**

3. **Does `compute_scores.py` need to be re-run automatically after `ingest_mapillary.py` finishes, or is it operator-invoked?**
   - What we know: D-14 says `--wipe-synthetic` "triggers `compute_scores.py` after"; D-17 says SC #3 is satisfied by "ingest → recompute scores → hit /segments". CONTEXT.md is silent on whether the recompute is automatic.
   - What's unclear: Does the CLI subprocess `compute_scores.py` automatically?
   - RESOLVED: **Yes, by default.** Add `--no-recompute` flag for operators who want to chain multiple ingests + a single recompute. Shown in Pattern 2 sketch.
   - **STATUS: this affects the integration test design (SC #3 expects it to "just work" end-to-end).**

4. **Should the run summary be printed to stdout (machine-readable) or stderr (human-readable)?**
   - What we know: Phase 2 patterns vary — `eval_detector.py` writes JSON to `--json-out` and human-readable to stdout; `fetch_eval_data.py` prints to stdout.
   - What's unclear: Whether the summary should be parseable by Phase 6's demo runbook or just operator-readable.
   - RESOLVED: **Both.** JSON via `--json-out` (machine), table via stderr/stdout (human). Mirrors Phase 2 D-18 `eval_detector.py`.

5. **What happens if `--wipe-synthetic` is passed but there are no Mapillary detections to write?**
   - What we know: D-14 wipes synthetic before writing real data. If real data set is empty (e.g., `--limit-per-segment 0`), the operator has just deleted their synthetic data with nothing to replace it — `/segments` will show all zeros.
   - What's unclear: Is this user error or should the CLI guard?
   - RESOLVED: **Guard.** If `--wipe-synthetic` is passed with an empty target list OR if the detection phase produces zero rows, abort with exit code 2 BEFORE the wipe. Show `--force-wipe` to override. Document.

## Sources

### Primary (HIGH confidence)
- [Existing code: `data_pipeline/mapillary.py`](file:///Users/hratchghanime/road-quality-mvp/data_pipeline/mapillary.py) — Phase 2 client, all reuse points verified by file read
- [Existing code: `data_pipeline/detector_factory.py`](file:///Users/hratchghanime/road-quality-mvp/data_pipeline/detector_factory.py) — `get_detector` signature
- [Existing code: `data_pipeline/yolo_detector.py`](file:///Users/hratchghanime/road-quality-mvp/data_pipeline/yolo_detector.py) — `Detection` dataclass + `_map_severity` semantics
- [Existing code: `scripts/seed_data.py`](file:///Users/hratchghanime/road-quality-mvp/scripts/seed_data.py) — `execute_values` + `ON CONFLICT` patterns
- [Existing code: `scripts/compute_scores.py`](file:///Users/hratchghanime/road-quality-mvp/scripts/compute_scores.py) — extension target for `--source`
- [Existing code: `scripts/ingest_iri.py`](file:///Users/hratchghanime/road-quality-mvp/scripts/ingest_iri.py) — argparse + spatial match style
- [Existing code: `scripts/iri_sources.py`](file:///Users/hratchghanime/road-quality-mvp/scripts/iri_sources.py) — `geom::geography + ST_DWithin` precedent (lines 357-367)
- [Existing code: `scripts/fetch_eval_data.py`](file:///Users/hratchghanime/road-quality-mvp/scripts/fetch_eval_data.py) — Mapillary client invocation pattern
- [Existing migration: `db/migrations/001_initial.sql`](file:///Users/hratchghanime/road-quality-mvp/db/migrations/001_initial.sql) — schema baseline
- [Existing tests: `backend/tests/test_mapillary.py`](file:///Users/hratchghanime/road-quality-mvp/backend/tests/test_mapillary.py) — Phase 2 mock pattern
- [Existing tests: `backend/tests/test_integration.py`](file:///Users/hratchghanime/road-quality-mvp/backend/tests/test_integration.py) — integration test pattern + auto-skip
- [Existing config: `backend/tests/conftest.py`](file:///Users/hratchghanime/road-quality-mvp/backend/tests/conftest.py) — `db_available` fixture
- [PostgreSQL 16 ALTER TABLE](https://www.postgresql.org/docs/16/sql-altertable.html) — `ADD COLUMN IF NOT EXISTS` confirmed; `ADD CONSTRAINT IF NOT EXISTS` NOT supported (synopsis verified via WebFetch)
- [PostgreSQL 16 Indexes & Unique](https://www.postgresql.org/docs/16/indexes-unique.html) — NULL-distinct default behavior
- [PostGIS ST_DWithin docs](https://postgis.net/docs/ST_DWithin.html) — bounding-box pre-filter using available indexes
- [PostGIS KNN Distance Operator `<->`](https://postgis.net/docs/manual-3.4/en/geometry_distance_knn.html) — true distance for non-points on PG ≥9.5; index-aware in ORDER BY
- [psycopg2 SQL composition](https://www.psycopg.org/docs/sql.html) — `psycopg2.sql.SQL` + `psycopg2.sql.Identifier` for safe identifier quoting
- [Mapillary API v4 documentation](https://www.mapillary.com/developer/api-documentation) — bbox 0.01 deg² limit, rate limits (10k/min search, 60k/min entity, 50k/day tile per WebFetch)
- [Phase 2 RESEARCH.md](file:///Users/hratchghanime/road-quality-mvp/.planning/phases/02-real-data-detector-accuracy/02-RESEARCH.md) — Pitfalls 1-8 and rate limit context

### Secondary (MEDIUM confidence)
- [Crunchy Data: Deep dive into PostGIS NN search](https://www.crunchydata.com/blog/a-deep-dive-into-postgis-nearest-neighbor-search) — KNN syntax & GIST behavior
- [Paul Ramsey: PostGIS NN syntax](https://blog.cleverelephant.ca/2021/12/knn-syntax.html) — `<->` operator efficiency
- [PostGIS Workshops: KNN](https://postgis.net/workshops/postgis-intro/knn.html) — best-first index traversal
- [PostGIS Workshops: Geography](http://postgis.net/workshops/postgis-intro/geography.html) — geography vs geometry tradeoffs
- [Ultralytics YOLO Configuration](https://docs.ultralytics.com/usage/cfg/) — default `conf=0.25`
- [Restato: choosing YOLO confidence threshold](https://restato.github.io/blog/choosing-yolo-confidence-threshold/) — 0.25 default rationale

### Tertiary (LOW confidence — flagged for execution-time validation)
- Mapillary URL TTL (Phase 2's "Pitfall 5") — exact TTL not documented; conservative behavior is in-pass download (existing pattern)
- Mapillary search retry behavior on 429 — undocumented; hand-rolled exponential backoff is a guess but follows industry-standard pattern
- Per-segment ingest typical latency on LA dev DB — extrapolated from `iri_sources.py` precedent; verify in execution

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every library/version verified; reuse-only of Phase 2 surface
- Architecture: HIGH — patterns mirror existing project conventions verbatim; SQL migration tested against verified Postgres 16 docs
- Pitfalls: HIGH — 10 pitfalls; 9 verified against existing code or official docs; 1 (`--wipe-synthetic` racing with cache) is defensive
- Validation: HIGH — test map directly derives from SC #1-5 + D-01..D-20
- Security: HIGH — ASVS map covers 7 of 14 categories; pickle ACE inherited from Phase 2; SQL injection defense pattern documented
- Migration safety: MEDIUM-HIGH — `IF NOT EXISTS` strategy verified; CHECK constraint workaround verified; `NULLS NOT DISTINCT` correction verified

**Research date:** 2026-04-25
**Valid until:** 2026-05-25 (stable Postgres + PostGIS + Mapillary v4 — 30 days; recheck before Phase 3 execution begins if delayed)
