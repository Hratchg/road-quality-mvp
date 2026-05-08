# Technology Stack — v0.4.0 Crash-Aware Routing

**Project:** road-quality-mvp
**Researched:** 2026-05-07
**Scope:** Crash-data ingest pipeline additions only. Existing v0.3.0 stack (Python 3.12 / FastAPI 0.115.6 / PostGIS 3.4 / pgRouting 3.6 / React 18 / psycopg2-binary 2.9.11) is **locked and out of scope** — see `.planning/codebase/STACK.md`.
**Overall confidence:** HIGH for ingest libraries (verified via Context7 + official docs). MEDIUM for data-source operational details (TIMS has no programmatic API and the LAPD source is mid-transition — see Pitfalls).

## TL;DR for the operator

You need **almost nothing new** in `requirements.txt`. The crash-ingest pipeline is the existing Mapillary-ingest pipeline with three substitutions:

| Mapillary pipeline (shipped v0.3.0) | Crash-data pipeline (v0.4.0) |
|--------------------------------------|------------------------------|
| `data_pipeline/mapillary.py` (HTTP client to Mapillary v4) | **Two thin clients**: `data_pipeline/tims.py` (parses an operator-downloaded CSV) + `data_pipeline/lacity_socrata.py` (`requests`-based SoQL fetcher) |
| ST_Buffer → Envelope → search_images(bbox) → YOLO detect | **Skip all of that.** Crashes already arrive geocoded — read CSV/JSON, build `points_from_xy(lon, lat)` |
| Snap-match each detection's lon/lat (ST_DWithin + `<->`) | **Same exact pattern**, reused unchanged |
| `segment_defects` insert with ON CONFLICT (segment_id, source_mapillary_id, severity) | New table `segment_crashes` with ON CONFLICT (segment_id, source, source_record_id, severity) |

The single load-bearing new dependency is **`geopandas>=1.0`** (already pinned at `>=0.14` in `scripts/requirements.txt`; bump to `>=1.0,<2.0` to get the pyogrio engine). Everything else (`requests`, `psycopg2-binary`, `numpy`) is already in the tree.

## Recommended Stack Additions

### Crash-data fetch / parse (the only NEW concern)

| Library | Version | Purpose | Why this version |
|---------|---------|---------|-------------------|
| **None new for Socrata** — use already-installed `requests>=2.31` | (already pinned in `data_pipeline/requirements.txt`) | Direct SoQL queries against `https://data.lacity.org/resource/d5tf-ez2w.json` | sodapy's maintenance status is "officially unmaintained Aug 2022, ownership transferred Mar 2025" with no new release since 2.2.0 (PyPI). The Mapillary client (`data_pipeline/mapillary.py`) already proves that a thin `requests` wrapper is the right pattern for this repo — adding another HTTP-client dependency is over-engineering. |
| `geopandas` | **`>=1.0,<2.0`** (bump from current `>=0.14`) | Read TIMS shapefile/CSV exports + reproject to WGS84 + `points_from_xy(lon,lat)` for non-geocoded fallback CSV | GeoPandas 1.0 made **pyogrio** the default I/O engine — 5-20× speedup on shapefile reads vs the old fiona engine (verified via Context7 + official migration guide). 1.x line is current; 2.x not yet released. |
| `pyogrio` | **transitive (`>=0.9`)** — installed automatically with geopandas 1.0 | Bulk shapefile/CSV/GPKG read engine that geopandas 1.0 uses by default | Replaces fiona; explicitly the geopandas team's recommendation. Wheels available on PyPI for macOS arm64 (Apple Silicon) and Linux x86_64 — no source build. |

**That is the entire new-library list.** No sodapy, no Socrata-specific SDK, no separate snap-match library.

### Existing libraries reused unchanged

| Library | Already pinned at | Reused for |
|---------|-------------------|------------|
| `requests>=2.31` | `data_pipeline/requirements.txt` | LA City Socrata SoQL JSON pulls (mirror Mapillary v4 client pattern) |
| `psycopg2-binary==2.9.11` | `backend/requirements.txt` + `scripts/requirements.txt` | All DB writes via `execute_values` + `ON CONFLICT DO NOTHING`; ThreadedConnectionPool wrapper for query path |
| `numpy>=2.2` | `scripts/requirements.txt` | Crash density normalization (per-segment count → 0..1 scale via min/max or log-scale) |
| `PostGIS 3.4` extension | shipped in `db/Dockerfile` | `ST_DWithin` + `<->` operator for nearest-segment snap (no new functions needed) |

**No new ML libraries.** Crash data is already geocoded (POINT_X/POINT_Y from TIMS, lat/lon from LA City). There is nothing to detect — just snap.

### What we are explicitly NOT adding

| Rejected option | Why not |
|-----------------|---------|
| `sodapy` (Socrata Python client) | Officially unmaintained Aug 2022 → Mar 2025 ownership transfer with no release since 2.2.0; PyPI metadata still claims "Python 3.5–3.10" (no 3.12 declared, even though it works in practice). The repo's existing pattern (`data_pipeline/mapillary.py`) already demonstrates how to write a 60-line thin client over `requests` with proper bbox/token guards. Adding sodapy buys nothing and adds a stale-dependency risk. **HIGH confidence.** |
| `pyrosm` / `osmium-tool` | We already ingested OSM via OSMnx in v0.2.0; not relevant to crash ingest. |
| `geoalchemy2` / SQLAlchemy ORM | Project constraint: raw psycopg2 is the chosen pattern (`PROJECT.md` § Constraints). Don't introduce ORM for one new table. |
| `shapely` direct usage in scripts | All spatial logic stays in PostGIS via SQL (consistent with `seed_data.py` + `ingest_mapillary.py`). Shapely is a transitive dep of geopandas; we don't import it directly. |
| Alembic migrations | Project constraint: raw SQL in `db/migrations/NNN_*.sql` (`PROJECT.md` § Out of Scope). Add `004_crash_table.sql` not a migration framework. |
| Redis cache for crash data | Crash data is read-once-per-quarter; no caching layer needed. The /route endpoint reads the precomputed `crash_norm` column on `road_segments` — no separate query path. |
| Background job queue (celery, dramatiq, RQ) | Quarterly refresh runs as `python scripts/ingest_crashes.py …` from operator's host venv (matches the `/tmp/rq-venv` Python 3.12 pattern from MEMORY). No web-triggered ingest. |
| `httpx` for the Socrata client | Sync `requests` already in tree; the ingest is a one-shot CLI not an async service. Don't introduce a parallel HTTP stack. |

## Data Sources — Operational Details

### Source 1: LA City Open-Data Portal (Socrata)

**Dataset:** Traffic Collision Data from 2010 to Present
**Dataset ID:** `d5tf-ez2w`
**Endpoint pattern:** `https://data.lacity.org/resource/d5tf-ez2w.json` (SoQL JSON) or `.csv`
**Update frequency:** **FROZEN as of LAPD's March 2024 NIBRS migration.** The dataset is preserved for historical reference but receives no new rows. **For the v0.4.0 use case (last-5-years historical aggregate, refresh quarterly), this is acceptable for the 2010–early-2024 window** but means quarterly refreshes will not produce new LA-City rows — the "refresh" is really a re-pull of the static set plus newer SWITRS rows.
**Auth:** Optional Socrata App Token (`X-App-Token` header). Without it, requests are subject to strict throttling (~1000/hr per IP). With a free App Token, throttling is loose enough for our use case (one quarterly bulk pull). **Recommend:** `LACITY_SOCRATA_APP_TOKEN` env var, mirror the `MAPILLARY_ACCESS_TOKEN` pattern from Phase 3 D-19.
**Schema (verified against `dev.socrata.com/foundry/data.lacity.org/d5tf-ez2w`):** Includes `dr_number` (record id, use as ON CONFLICT key), `date_occurred`, `time_occurred`, `area`, `crime_code` (mvc → traffic), **`location_1`** as a Socrata Point object `{type: "Point", coordinates: [lon, lat]}`. Severity is **NOT a first-class field** — must be inferred from `mocodes` or `victim_descent`/`victim_age` (or accept a binary "collision occurred" flag). **Confidence: MEDIUM** — the `mocodes`-to-severity mapping is documented but lossy.

**SoQL query pattern:**
```python
# Mirror data_pipeline/mapillary.py module-top env-var pattern
LACITY_TOKEN = os.environ.get("LACITY_SOCRATA_APP_TOKEN")
url = "https://data.lacity.org/resource/d5tf-ez2w.json"
params = {
    "$where": "date_occurred >= '2021-01-01T00:00:00.000'",
    "$limit": 1000,
    "$offset": 0,
}
headers = {"X-App-Token": LACITY_TOKEN} if LACITY_TOKEN else {}
# Page until len(response) < $limit (matches Socrata pagination idiom)
```

**SoQL pagination caveat:** `$limit` defaults to 1000; SODA 2.1 endpoints have no upper bound but server-side performance degrades over ~50,000. Page in 5,000-row chunks via `$offset`. **HIGH confidence** (verified against `dev.socrata.com/docs/queries/limit`).

### Source 2: SWITRS via Berkeley TIMS

**Tool:** `https://tims.berkeley.edu` (Transportation Injury Mapping System)
**Auth:** **Free TIMS account required** (operator manually registers, logs in, runs a query, downloads CSV). No API. **HIGH confidence — TIMS explicitly states "If you have any questions … contact the TIMS team" and lists no programmatic endpoint** in the help pages. The export is operator-driven, not script-driven.
**Coverage:** Last 11 years available. Provides **fatal + injury crashes only** — Property-Damage-Only (PDO) crashes are **NOT in TIMS** (TIMS spec). **This impacts the locked v0.4.0 three-tier severity decision** — see Pitfalls.
**Export format:** CSV with `POINT_X` (lon, WGS84) + `POINT_Y` (lat, WGS84) columns. Shapefile export also available for the GIS Map tool. **CSV is the right choice** — geopandas `points_from_xy` handles it directly; shapefile requires GDAL bindings via pyogrio (works but heavier).
**Severity field:** `COLLISION_SEVERITY` integer:
- `1` = Fatal
- `2` = Injury (Severe)
- `3` = Injury (Other Visible)
- `4` = Injury (Complaint of Pain)
- `0` = PDO — but **never appears in TIMS exports** (filtered upstream)

**Operator workflow (cannot be automated):**
1. Log into TIMS web UI
2. Run "SWITRS Query & Map" → filter by jurisdiction (City of Los Angeles) + date range (last 5 years)
3. Click "Download" → save CSV to `data/crashes/tims_la_YYYYMMDD.csv`
4. `python scripts/ingest_crashes.py --tims-csv data/crashes/tims_la_YYYYMMDD.csv`

This is the same operator-runbook pattern as Phase 2's `data/eval_la/` manual labeling — document it once, run it quarterly.

### Source 3 (optional fallback): California CCRS via data.ca.gov

**Dataset:** California Crash Reporting System (CCRS) on `https://data.ca.gov/dataset/ccrs`
**Format:** CSV only. **Daily updates.** Coverage 2016–present. Source-of-truth for new crashes since CHP's January 2025 ISWITRS shutdown.
**Auth:** None (CKAN open data).
**Geocoding status:** **MEDIUM confidence** — the dataset's "Raw Data Template" (DOCX) is the schema authority but couldn't be verified for explicit lat/lon columns from the dataset listing alone. CCRS is the SWITRS successor and inherits the codebook but the public CSV's geocoding completeness is unverified. **Recommend treating CCRS as v0.5.0 backlog** — for v0.4.0, TIMS-CSV + LA-City-Socrata is sufficient.

## Installation

The deltas to existing `requirements.txt` files:

```diff
# scripts/requirements.txt
 osmnx==2.0.1
 psycopg2-binary==2.9.11
 numpy>=2.2
-geopandas>=0.14
+geopandas>=1.0,<2.0  # 1.0 makes pyogrio the default engine (5-20× shapefile read speedup)
```

```diff
# data_pipeline/requirements.txt
 ultralytics>=8.1
 opencv-python-headless>=4.8
 huggingface_hub>=0.24,<1.0
 scipy>=1.13
 requests>=2.31
+# (no new lines — Socrata client is a thin wrapper over requests, mirroring data_pipeline/mapillary.py)
```

**No changes to `backend/requirements.txt`** — the backend never talks to TIMS or Socrata directly. It only reads the precomputed `road_segments.crash_norm` column.

**Apple Silicon / Linux compatibility verified:**
- `geopandas 1.x`: macOS arm64 + Linux x86_64 wheels on PyPI (HIGH confidence).
- `pyogrio 0.9+`: macOS arm64 wheels available since 0.7 (Oct 2023, verified via PyPI).
- `requests`, `psycopg2-binary`, `numpy`: already validated on the existing tri-app deploy.

## Integration Points with Existing Pipeline

### File-by-file delta (mirror Phase 3 conventions)

| New file | Mirrors / Reuses | Lines (estimate) |
|----------|------------------|------------------|
| `data_pipeline/tims.py` | `data_pipeline/mapillary.py` (module-top env, framework-agnostic, no argparse) | ~80 — pure parser; `parse_tims_csv(path) -> list[dict]` returning `{record_id, severity, lon, lat, occurred_at}` |
| `data_pipeline/lacity_socrata.py` | `data_pipeline/mapillary.py` (token via env, `requests` session, paged generator) | ~120 — `iter_collisions(start_date, end_date) -> Iterator[dict]` with `$where` + `$offset` pagination |
| `scripts/ingest_crashes.py` | `scripts/ingest_mapillary.py` (D-18 exit codes, `--source` CLI flag, ThreadedConnectionPool unused — runs via direct psycopg2 like ingest_iri.py) | ~250 — accepts `--tims-csv PATH` AND/OR `--lacity` to run either or both; writes to `segment_crashes`; calls `compute_crash_norm.py` unless `--no-recompute` |
| `scripts/compute_crash_norm.py` | `scripts/compute_scores.py` (aggregator pattern; reads `segment_crashes`, writes `road_segments.crash_norm`) | ~100 — three-tier weighting `crash_score = 1.0*fatal + 0.5*injury + 0.1*pdo` (PDO column will always be 0 if only TIMS+LACity used), then min-max norm to 0..1 |
| `db/migrations/004_crash_data.sql` | `db/migrations/002_mapillary_provenance.sql` (DDL idempotency, CHECK constraint pattern) | ~40 |
| `docs/CRASH_INGEST.md` | `docs/MAPILLARY_INGEST.md` (operator runbook style) | ~150 |

### Schema delta (`004_crash_data.sql`)

```sql
-- Migration 004: Crash-data ingest tables for v0.4.0 (REQ-crash-ingest).
-- Mirrors 002_mapillary_provenance.sql conventions: idempotent, DEFAULT-backfill,
-- DROP-then-ADD CHECK constraints, NULL-distinct UNIQUE indexes.

CREATE TABLE IF NOT EXISTS segment_crashes (
    id BIGSERIAL PRIMARY KEY,
    segment_id BIGINT NOT NULL REFERENCES road_segments(id) ON DELETE CASCADE,
    source TEXT NOT NULL,                    -- 'tims_switrs' | 'lacity_socrata' | 'ccrs'
    source_record_id TEXT NOT NULL,          -- TIMS CASE_ID | LACity dr_number | CCRS report_id
    severity TEXT NOT NULL,                  -- 'fatal' | 'injury' | 'pdo'
    occurred_at TIMESTAMPTZ,                 -- nullable; some sources have date-only
    raw_geom GEOMETRY(POINT, 4326) NOT NULL, -- pre-snap coordinate (auditable)
    snap_distance_m DOUBLE PRECISION,        -- distance from raw_geom to road_segments.geom
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE segment_crashes
    DROP CONSTRAINT IF EXISTS segment_crashes_source_check;
ALTER TABLE segment_crashes
    ADD CONSTRAINT segment_crashes_source_check
    CHECK (source IN ('tims_switrs', 'lacity_socrata', 'ccrs'));

ALTER TABLE segment_crashes
    DROP CONSTRAINT IF EXISTS segment_crashes_severity_check;
ALTER TABLE segment_crashes
    ADD CONSTRAINT segment_crashes_severity_check
    CHECK (severity IN ('fatal', 'injury', 'pdo'));

-- ON CONFLICT key for idempotent re-ingest (mirrors uniq_defects_segment_source_severity).
CREATE UNIQUE INDEX IF NOT EXISTS uniq_crashes_source_record
    ON segment_crashes (source, source_record_id, severity);

-- Routing-side filter index (matches segment_defects.idx_defects_source pattern).
CREATE INDEX IF NOT EXISTS idx_crashes_segment ON segment_crashes(segment_id);
CREATE INDEX IF NOT EXISTS idx_crashes_geom_gist ON segment_crashes USING GIST(raw_geom);

-- The denormalized crash_norm column lives on road_segments to keep /route hot-path
-- schema unchanged (one LEFT JOIN per segment is the cost model in routing.py).
ALTER TABLE road_segments ADD COLUMN IF NOT EXISTS crash_norm DOUBLE PRECISION DEFAULT 0.0;
```

### Snap-match SQL (reused unchanged from Phase 3 ingest_mapillary.py)

```sql
-- For each crash row, find the nearest road_segment within snap_m metres.
-- Mirror ingest_mapillary.py's per-image snap pattern (D-01: ST_DWithin + <->).
SELECT id
FROM road_segments
WHERE ST_DWithin(
    geom::geography,
    ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
    %s   -- snap_m, default 25
)
ORDER BY geom <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326)
LIMIT 1;
```

The `geom::geography` cast and the `<->` KNN operator both already use the existing GiST index `road_segments_geom_idx`. **No new index needed on `road_segments`.** Out-of-radius crashes are dropped with a counter (mirror `dropped_outside_snap` from Phase 3).

### Routing integration (`backend/app/routes/routing.py` cost formula)

```python
# Locked v0.4.0 cost (replaces user-tunable weights from v0.3.0):
cost = travel_time_s + 0.40 * iri_norm + 0.35 * pothole_norm + 0.25 * crash_norm
```

The pgr_dijkstra-with-perturbation inner SQL changes only its `cost` expression; everything else (3-attempt fallback chain, K=5, edge-weight perturbation per Phase 8 D-08-03) is preserved.

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Socrata client | thin `requests` wrapper | `sodapy 2.2.0` | Unmaintained Aug 2022 → ownership transferred Mar 2025 with no release; existing `data_pipeline/mapillary.py` already demonstrates the right pattern. (HIGH confidence) |
| Crash data source | TIMS CSV + LA City Socrata | CCRS via data.ca.gov | CCRS is the SWITRS successor (post-Jan-2025) but its public CSV's geocoding completeness is unverified; defer to v0.5.0. (MEDIUM confidence) |
| Shapefile reader | geopandas 1.x (pyogrio default) | fiona 1.x via geopandas 0.x | pyogrio is 5-20× faster for bulk reads (verified, geopandas migration guide); fiona is being phased out as the default. (HIGH confidence) |
| TIMS data acquisition | manual web download | scripted CSV pull | TIMS has **no public API**; "If you have any questions … contact the TIMS team" is the operative phrase. Don't fight the data-source's auth model — make it an operator runbook. (HIGH confidence) |
| Snap-match algorithm | `ST_DWithin` + `<->` (reuse Phase 3) | Custom Python KDTree (e.g., `scipy.spatial.cKDTree`) | The Phase 3 PostGIS pattern already snaps 125k Mapillary detections in under 30s on Fly.io. Don't re-architect a working pipeline for ~50k crashes. (HIGH confidence) |
| New severity classifier | Three-tier from source field | ML severity scoring | TIMS provides `COLLISION_SEVERITY` directly; LA City uses `mocodes`. Mapping to {fatal, injury, pdo} is a 30-line lookup, not a model. (HIGH confidence) |
| Quarterly refresh | Operator-run `scripts/ingest_crashes.py` | Cron / GitHub Action / Fly machine task | Quarterly cadence + manual TIMS download step blocks full automation. Document the runbook; don't half-automate. (MEDIUM confidence) |

## Pitfalls (preview — full list in `PITFALLS.md`)

1. **TIMS does not include PDO crashes.** The locked v0.4.0 three-tier severity {fatal, injury, pdo} will have a permanently-zero `pdo` count if you rely solely on TIMS. LA City's `d5tf-ez2w` similarly does not have a clean PDO flag. **Recommendation:** Treat the locked weights formula as `0.40·iri_norm + 0.35·pothole_norm + 0.25·(fatal_weighted + injury_weighted)` and document `pdo_norm = 0` in `compute_crash_norm.py`. **Do NOT renegotiate the locked formula** — just be honest in the runbook that the third tier is reserved-for-future.

2. **LA City Traffic Collision dataset is FROZEN as of March 2024.** It will never get new rows. Quarterly "refresh" of LA-City data is a no-op past 2024-03 — only TIMS pulls produce new rows. **Recommendation:** `ingest_crashes.py` accepts both sources; for the next 2-3 years, the LA City re-pull will return identical row counts each quarter (idempotent ON CONFLICT DO NOTHING handles it).

3. **Apple Silicon: `geopandas 1.x` requires `numpy 2.0+` and `pyproj 3.7+`**. The repo already pins `numpy>=2.2` so this is fine; verify `pyproj` (transitive) resolves to ≥3.7 via `pip show pyproj` after upgrade.

4. **Socrata throttling without an App Token.** Anonymous requests against `data.lacity.org` get throttled at ~1000/hr per IP. A full re-pull of `d5tf-ez2w` (~600k rows since 2010 → 5-yr window ~250k rows → 250 paged requests) fits within the limit, but only barely. **Recommendation:** Register for a free App Token, store as `LACITY_SOCRATA_APP_TOKEN` Fly secret + repo `.env.example` entry. Same pattern as `MAPILLARY_ACCESS_TOKEN`.

## Confidence Summary

| Decision | Confidence | Verification source |
|----------|------------|---------------------|
| `geopandas>=1.0` is the right shapefile reader | HIGH | Context7 (`/geopandas/geopandas`) + official migration guide |
| `pyogrio` is the default geopandas 1.0 engine | HIGH | Context7 + GeoPandas changelog |
| sodapy is unmaintained / replaceable by `requests` | HIGH | PyPI metadata + GitHub README + library age (no release since Aug 2022) |
| LA City `d5tf-ez2w` is frozen | HIGH | Multiple sources: data.lacity.org dataset description + data.gov catalog + LAPD March 2024 NIBRS migration |
| TIMS has no public API | HIGH | TIMS help pages list no API; "contact tims_info@berkeley.edu" is the operative line |
| TIMS excludes PDO | HIGH | SWITRS codebook + TIMS dataset description |
| ISWITRS retired Jan 2025, CCRS is the successor | HIGH | CHP page + multiple corroborating sources |
| CCRS public CSV has lat/lon | LOW — could not verify column-level | data.ca.gov dataset listing only |
| `mocodes` → severity mapping for LA City data | MEDIUM | Documented but lossy; needs operator validation |
| GeoPandas 1.x has macOS arm64 wheels | HIGH | PyPI release files |
| Snap-match SQL pattern reuses cleanly | HIGH | Already proven in production for 125k Mapillary detections (Phase 3 + Phase 8 routing benchmarks) |

## Sources

- [GeoPandas Migration from Fiona to Pyogrio](https://geopandas.org/en/latest/docs/user_guide/fiona_to_pyogrio.html)
- [GeoPandas Releases](https://github.com/geopandas/geopandas/releases) — confirms 1.x is current line
- [Pyogrio Releases](https://github.com/geopandas/pyogrio/releases) — wheels per platform
- [Socrata SODA API LIMIT clause](https://dev.socrata.com/docs/queries/limit.html) — pagination semantics
- [Socrata Getting Started](https://dev.socrata.com/consumers/getting-started.html) — App Token throttling
- [sodapy on PyPI](https://pypi.org/project/sodapy/) — maintenance status
- [LA City Traffic Collision Dataset (d5tf-ez2w)](https://data.lacity.org/Public-Safety/Traffic-Collision-Data-from-2010-to-Present/d5tf-ez2w) — schema + frozen status
- [Socrata API Foundry: d5tf-ez2w](https://dev.socrata.com/foundry/data.lacity.org/d5tf-ez2w/no-redirect) — endpoint reference
- [Berkeley TIMS Tool](https://safetrec.berkeley.edu/tools/transportation-injury-mapping-system-tims) — official tool home
- [TIMS Query & Map docs](https://tims.berkeley.edu/help/Query_and_Map.php) — export workflow
- [SWITRS Codebook (TIMS-hosted)](https://tims.berkeley.edu/help/SWITRS.php) — `COLLISION_SEVERITY` field values
- [California CCRS dataset](https://data.ca.gov/dataset/ccrs) — SWITRS successor
- [CHP SWITRS page](https://www.chp.ca.gov/programs-services/services-information/switrs-statewide-integrated-traffic-records-system/) — ISWITRS shutdown notice
- [PostGIS ST_DWithin docs](https://postgis.net/docs/ST_DWithin.html) — snap-match index usage
- [PostGIS Nearest-Neighbour Searching](https://postgis.net/workshops/postgis-intro/knn.html) — `<->` operator pattern

---

*Stack research: 2026-05-07 — v0.4.0 milestone scoping. Reuse-first verdict: ONE new line in `scripts/requirements.txt` (geopandas version bump). Everything else is the Phase 3 Mapillary pipeline pattern with crash data substituted for image detections.*
