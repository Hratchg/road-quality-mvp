# Architecture Research — v0.4.0 Crash-Aware Routing

**Domain:** Crash-data integration into existing PostGIS road-quality pipeline
**Researched:** 2026-05-07
**Confidence:** HIGH (grounded in repo source — `db/migrations/001_initial.sql`, `db/migrations/002_mapillary_provenance.sql`, `backend/app/routes/routing.py`, `backend/app/routes/segments.py`, `backend/app/scoring.py`, `backend/app/models.py`, `scripts/compute_scores.py`, `scripts/ingest_mapillary.py`. Patterns mirror Phase 3 Mapillary work.)

This is a **subsequent-milestone integration** research, not a greenfield architecture. The seven sub-questions (a–g) drive the structure below; the standard "ASCII diagram + scaling tiers" sections are present but truncated where Phase 3/8 already settled the answer.

---

## TL;DR — Architectural Decisions (one-liners)

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| a | Crash storage | **NEW table `crash_records`** (not extend `segment_defects`) | Different cardinality, different schema (severity tier, date, casualties), different lifecycle (quarterly truncate-and-reload vs. incremental Mapillary append), different source-of-truth identity (state crash report ID vs. image ID). Forcing it into `segment_defects` would corrupt the source CHECK constraint and the `(segment_id, source_mapillary_id, severity)` UNIQUE semantics. |
| b | Where `crash_norm` lives | **NEW column `segment_scores.crash_norm` DOUBLE PRECISION DEFAULT 0.0**, computed by extending `scripts/compute_scores.py`, persisted at ingest/recompute time | Single segment-keyed table already used by `/segments` and `/route` LEFT JOINs (segments.py:25-36, routing.py:75-85). Read-time recomputation would re-aggregate ~205k segments per request — defeats the cache and the Phase 8 sub-3s budget. |
| c | Cost-formula combination | **Bake crash_norm into `segment_scores` row, return all three components separately on `/segments`, combine inside `compute_segment_cost()` at route-cost time using locked constants** | `/segments` already returns `iri_norm + moderate_score + severe_score + pothole_score_total` separately for frontend color rendering — keep the contract symmetric. Routing-cost combination stays in scoring.py where the locked weights live as module constants. |
| d | Snap-match for crash POINTS | **Reuse `snap_match_image()` SQL pattern (ingest_mapillary.py:255-281): ST_DWithin geography filter + ORDER BY `geom <-> point` KNN + LIMIT 1**, but with a wider `snap_meters` (75–100 m, not 25 m) | Mapillary images snap to the lane the camera car was driving in (tight tolerance). Crashes are reported at intersection centroids or imprecise on-ramp locations — wider tolerance prevents losing 30–50% of crashes to "outside snap." Same SQL primitive, different magic number. |
| e | Migration plan | **NEW `db/migrations/004_crash_records.sql`** — additive; no breaks. Adds `crash_records` table + `segment_scores.crash_norm` column + indexes. `001`/`002`/`003` untouched. | Migrations are additive append-only per CONSTRAINTS (no Alembic). Consistent with Phase 3 (`002_mapillary_provenance.sql`) and Phase 4 (`003_users.sql`) precedent. |
| f | Routing.py weight handling | **Replace `normalize_weights()` call with module constants `W_IRI=0.40, W_POT=0.35, W_CRASH=0.25`**; keep `RouteRequest.weight_iri / weight_potholes` fields for backwards-compat (Pydantic accepts but `find_route()` ignores) | CONSTRAINTS line 136 mandates silent-ignore. Lets the existing curl/UI clients keep posting payloads while the math is locked. |
| g | Build order | **Schema migration → ingest script → score recompute → routing.py constants → frontend slider removal** | Schema must exist before INSERTs. Score recompute reads ingested rows. Routing constants must read a populated `crash_norm` column or the `LEFT JOIN COALESCE(0)` will silently zero out the third term. Frontend last because backend changes are the load-bearing ones. |

---

## System Overview

```
┌────────────────────────────────────────────────────────────────────────┐
│                         INGEST LAYER (offline / quarterly)              │
├────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   SWITRS/TIMS CSV          LA City open-data API                        │
│   (statewide, annual)      (city, near-real-time)                       │
│         │                          │                                     │
│         ▼                          ▼                                     │
│   ┌─────────────────────────────────────────┐                           │
│   │  scripts/ingest_crashes.py  [NEW]        │                           │
│   │  • parse + normalize severity tier       │                           │
│   │  • snap_match_crash() (ST_DWithin/KNN)   │                           │
│   │  • INSERT crash_records ON CONFLICT       │                           │
│   │  • subprocess compute_scores.py           │                           │
│   └─────────────────────────────────────────┘                           │
│                          │                                               │
└──────────────────────────┼───────────────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      SCORE RECOMPUTE (offline, idempotent)              │
├────────────────────────────────────────────────────────────────────────┤
│   scripts/compute_scores.py  [MODIFIED]                                 │
│   --source {synthetic|mapillary|crash|all}                              │
│   • aggregates segment_defects → moderate/severe/pothole_score_total    │
│   • aggregates crash_records   → crash_norm                  [NEW]      │
│   • single UPSERT into segment_scores                                   │
└────────────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        DATABASE (PostGIS + pgRouting)                   │
├────────────────────────────────────────────────────────────────────────┤
│  road_segments  ──▶  segment_defects (mapillary, synthetic)             │
│       │              segment_scores (iri + pothole + crash)  [extended] │
│       │              crash_records (NEW: lon/lat/sev/date)              │
│       │                                                                  │
│       ▼                                                                  │
│  road_segments_vertices_pgr  (pgr_createTopology output)                │
└────────────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────────────────┐
│                          API LAYER (FastAPI)                            │
├────────────────────────────────────────────────────────────────────────┤
│   GET /segments         POST /route                                     │
│   (segments.py:9-59)    (routing.py:243-485)                            │
│   • UNCHANGED route     • compute_segment_cost() reads locked W_*       │
│     contract; adds      • RouteRequest.weight_iri/weight_potholes       │
│     crash_norm to       •   accepted but ignored (silent compat)        │
│     properties          • crash_norm fed via SEGMENTS_BY_IDS_SQL        │
│                                                                          │
└────────────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────────────────┐
│                         FRONTEND (React + Leaflet)                      │
├────────────────────────────────────────────────────────────────────────┤
│   ControlPanel.tsx  [MODIFIED — sliders removed]                         │
│   MapView.tsx       [UNCHANGED — color comes from cost,                  │
│                       which now silently includes crash_norm]            │
└────────────────────────────────────────────────────────────────────────┘
```

---

## (a) Schema: New `crash_records` table — NOT extend `segment_defects`

### Decision

Add a NEW table `crash_records`. Do NOT shoehorn crashes into `segment_defects` with `source='crash'`.

### Rationale

`segment_defects` was designed for **per-image YOLO detections** with this contract (`db/migrations/002_mapillary_provenance.sql`):

```sql
CHECK (source IN ('synthetic', 'mapillary'))
UNIQUE INDEX (segment_id, source_mapillary_id, severity)
```

Crashes break this contract on three axes:

1. **Severity vocabulary mismatch.** Defects are `'moderate' | 'severe'`. Crashes are `'fatal' | 'injury' | 'pdo'` (three-tier per CONTEXT). Adding crash severities to the existing CHECK constraint pollutes Mapillary recompute logic in `compute_scores.py:85-101` (which CASEs only `'moderate'` and `'severe'`).
2. **Identity column mismatch.** `source_mapillary_id` is image-keyed (TEXT, digits-only validated). Crash IDs are state report numbers (SWITRS `case_id`) or LA City incident IDs — different vocabularies, different uniqueness shapes. Reusing the column requires either (i) NULL it (loses dedup) or (ii) namespace-prefix the value (corrupts the existing column semantics).
3. **Lifecycle mismatch.** Mapillary ingest is **incremental append** (D-08 ON CONFLICT DO NOTHING). Crash ingest is **quarterly truncate-and-reload of the historical aggregate** — a different operational model that wants a different table to truncate without touching defects.

### `crash_records` schema (proposed)

```sql
CREATE TABLE crash_records (
    id              BIGSERIAL PRIMARY KEY,
    source          TEXT NOT NULL CHECK (source IN ('switrs', 'la_city')),
    source_record_id TEXT NOT NULL,    -- SWITRS case_id or LA City incident_id
    crash_date      DATE,              -- nullable for sources without exact dates
    severity        TEXT NOT NULL CHECK (severity IN ('fatal', 'injury', 'pdo')),
    geom            GEOMETRY(Point, 4326) NOT NULL,
    segment_id      INTEGER REFERENCES road_segments(id) ON DELETE SET NULL,
    snap_meters     DOUBLE PRECISION,  -- distance to matched segment (audit)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_crash_geom    ON crash_records USING GIST(geom);
CREATE INDEX idx_crash_segment ON crash_records(segment_id);
CREATE INDEX idx_crash_source  ON crash_records(source);
CREATE UNIQUE INDEX uniq_crash_source_record ON crash_records(source, source_record_id);
```

**Notes:**
- `segment_id` is FK with `ON DELETE SET NULL` (not CASCADE) — preserves the raw crash record if segment topology is rebuilt by `pgr_createTopology`. Audit-friendly.
- `snap_meters` stored for QA (operator can query "how many crashes snapped > 50 m away?" — useful for tuning the next refresh).
- `UNIQUE (source, source_record_id)` mirrors `(source_mapillary_id, source)` pattern from migration 002 — gives idempotent re-ingest.
- No `count` or `confidence_sum` columns. One crash = one row. Aggregation happens in `compute_scores.py`.

---

## (b) Where `crash_norm` is computed and stored

### Decision

- **Storage:** NEW column `segment_scores.crash_norm DOUBLE PRECISION DEFAULT 0.0`
- **Computation:** EXTEND `scripts/compute_scores.py` (do not create a separate `compute_crash_scores.py`)
- **Trigger:** Same idempotent UPSERT pattern as the existing pothole aggregation (compute_scores.py:85-101)

### Rationale: bake at ingest-time, not read-time

| Approach | Cross-LA `/route` budget impact | Verdict |
|----------|----------------------------------|---------|
| **Bake (ingest-time)** — store `crash_norm` per segment | Zero — `LEFT JOIN segment_scores` already happens (routing.py:75-85, segments.py:25-36); adding a column is free | ✅ Adopt |
| **Read-time aggregation** — compute `crash_norm = COUNT/AGG(crash_records) per segment` inside the route query | ~205k segments × KNN-radius scan per request; Phase 8 budget is 2.5s and pgr_dijkstra already eats 1.7s of it. Even with a GiST index, this would add 200–500ms and break the cache (cache key would have to include crash data hash) | ✗ Reject |

Read-time aggregation is also wrong on principle: crash data refreshes **quarterly**, scoring weights are **constants**, the routing-graph topology is **static**. Three immutable inputs ⇒ pre-bake the output. This is the same logic that put `pothole_score_total` in `segment_scores` instead of computing it from `segment_defects` per request (compute_scores.py:85-101).

### Why extend `compute_scores.py` not create a sibling

The existing UPSERT (compute_scores.py:85-101) writes ALL columns of `segment_scores` in one statement. Splitting into `compute_scores.py` (potholes) + `compute_crash_scores.py` (crashes) creates a race window where a recompute partially completes and the `segment_scores` row has stale potholes OR stale crashes. The single-INSERT-with-ON-CONFLICT-UPDATE pattern guarantees atomic refresh per segment.

The existing `--source {synthetic|mapillary|all}` flag already filters defects-only computation (compute_scores.py:78-94). Add `crash` to `VALID_SOURCES` and route the crash-aggregation SQL through the same flag.

### Proposed compute_scores.py extension

The single UPSERT becomes:

```sql
INSERT INTO segment_scores
    (segment_id, moderate_score, severe_score, pothole_score_total, crash_norm)
SELECT
    rs.id,
    COALESCE(SUM(CASE WHEN sd.severity='moderate' THEN 0.5 * sd.count * sd.confidence_sum ELSE 0 END), 0),
    COALESCE(SUM(CASE WHEN sd.severity='severe'   THEN 1.0 * sd.count * sd.confidence_sum ELSE 0 END), 0),
    COALESCE(SUM(CASE WHEN sd.severity='moderate' THEN 0.5 * sd.count * sd.confidence_sum ELSE 0 END), 0)
      + COALESCE(SUM(CASE WHEN sd.severity='severe' THEN 1.0 * sd.count * sd.confidence_sum ELSE 0 END), 0),
    -- NEW: crash_norm aggregation in a correlated subquery
    -- (avoid JOIN explosion: one row per crash * one row per defect = cross-product)
    COALESCE((
        SELECT
            (SUM(CASE WHEN cr.severity='fatal'  THEN 3.0 ELSE 0 END)
           + SUM(CASE WHEN cr.severity='injury' THEN 1.0 ELSE 0 END)
           + SUM(CASE WHEN cr.severity='pdo'    THEN 0.3 ELSE 0 END))
          / GREATEST(rs.length_m / 1000.0, 0.05)  -- per-km density, floor at 50m
        FROM crash_records cr
        WHERE cr.segment_id = rs.id
    ), 0)
FROM road_segments rs
LEFT JOIN segment_defects sd ON rs.id = sd.segment_id {join_filter}
GROUP BY rs.id, rs.length_m
ON CONFLICT (segment_id) DO UPDATE SET
    moderate_score      = EXCLUDED.moderate_score,
    severe_score        = EXCLUDED.severe_score,
    pothole_score_total = EXCLUDED.pothole_score_total,
    crash_norm          = EXCLUDED.crash_norm,
    updated_at          = NOW();
```

**Crash-norm formula assumptions** (these belong in REQUIREMENTS.md, listed here for the architecture record):
- Per-segment severity-weighted sum, normalized by segment length in km (density per km, not raw count).
- Severity weights: `fatal=3.0, injury=1.0, pdo=0.3`. To be tuned in REQUIREMENTS or first-implementation phase.
- `GREATEST(length_km, 0.05)` floor prevents a 5-meter sliver segment with one crash from hitting `crash_norm = 60`. The floor is a domain choice — research finding, not architectural.
- Final normalization to [0, 1] (matching `iri_norm`) should happen by dividing by the 95th percentile across all segments — this requires a two-pass compute or a CTE. To be settled at implementation time; pre-bake makes either approach feasible.

The correlated subquery avoids cross-joining `segment_defects × crash_records` — without it, a segment with 5 defect rows and 3 crash rows would produce 15 rows pre-GROUP-BY and double-count.

---

## (c) Should `/segments` return `crash_norm` separately or pre-combined?

### Decision

Return all three normalized fields **separately** on `/segments`. Combine them in `compute_segment_cost()` at route-time using locked constants.

### Rationale

- **Frontend already consumes them separately.** `segments.py:25-36` returns `iri_norm`, `moderate_score`, `severe_score`, `pothole_score_total` as discrete fields. The frontend's color-coding uses these for legend/breakdowns. Pre-combining `crash_norm` into a single `composite_score` would break frontend display logic and prevent the user from understanding *why* a road is red.
- **Decoupling weight changes from data.** If the weights ever change (CONTEXT says they're locked for v0.4.0, but future milestones might tune them), the data layer doesn't need to be re-baked — only `compute_segment_cost()` needs an edit. Pre-combining couples the weights into the API contract.
- **Cost combination already lives in scoring.py.** `compute_segment_cost(travel_time_s, iri_norm, pothole_score_total, w_iri, w_pot)` (scoring.py:24-35) is the single chokepoint. Extending it to take `crash_norm` keeps the cost formula in one place.

### Proposed changes

**`segments.py:25-55`** — extend the SELECT and the response dict:

```sql
-- Add to SELECT:
COALESCE(ss.crash_norm, 0) AS crash_norm
```

```python
# Add to properties dict:
"crash_norm": row["crash_norm"],
```

**`scoring.py:24-35`** — extend signature:

```python
def compute_segment_cost(
    travel_time_s: float,
    iri_norm: float,
    pothole_score_total: float,
    crash_norm: float,
    w_iri: float = 0.40,
    w_pot: float = 0.35,
    w_crash: float = 0.25,
) -> float:
    return travel_time_s + w_iri * iri_norm + w_pot * pothole_score_total + w_crash * crash_norm
```

**`routing.py:75-85`** — extend `SEGMENTS_BY_IDS_SQL` to fetch crash_norm and pass to `compute_segment_cost()` at line 424.

---

## (d) Snap-match for crash POINTS vs Mapillary IMAGE points

### Decision

Reuse the exact SQL primitive from `ingest_mapillary.snap_match_image()` (ingest_mapillary.py:255-281) — same ST_DWithin + KNN ORDER BY pattern. **Differ only in the `snap_meters` magic number** (75–100 m for crashes vs. 25 m for Mapillary).

### Why the snap-pattern is the same

Both inputs are SRID-4326 lon/lat points. Both want "nearest road segment within tolerance, or NULL". The PostGIS pattern is identical:

```sql
SELECT id FROM road_segments
WHERE ST_DWithin(
    geom::geography,
    ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
    %s
)
ORDER BY geom <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326)
LIMIT 1
```

This uses the existing GIST index `idx_segments_geom` (migration 001 line 14). No new index needed.

### Why the tolerance differs (the substantive insight)

| Source | Reported coordinate represents | Typical accuracy | Recommended snap_meters |
|--------|--------------------------------|------------------|--------------------------|
| **Mapillary image** | Camera-car GPS along the lane | ~5–15 m in urban LA | **25 m** (DEFAULT_SNAP_METERS in ingest_mapillary.py:88) |
| **SWITRS crash** | Often the intersection centroid the officer mapped, or beat-cop-estimated location | 30–80 m (state crash data is notoriously coarse) | **75–100 m** |
| **LA City crash** | City GIS-snapped to nearest reported intersection or address | 20–60 m | **50 m** |

If you reuse `25 m` for crashes you will lose 30–50% of records to "outside snap" — the same dropped-counter you see in ingest_mapillary's `dropped_outside_snap` (ingest_mapillary.py:478-482). Empirical tuning belongs in REQUIREMENTS, but the architecture should expose `snap_meters` as a CLI flag (default 75) just like ingest_mapillary.py does.

### What's NOT the same as Mapillary

- **No bbox padding / quadrant subdivision.** Mapillary subdivides because it queries the Mapillary API by bbox and the API caps response size (ingest_mapillary.py:237-252). Crash CSVs/APIs return rows directly — there is no per-segment bbox query. Iterate over crash rows, not over road segments.
- **No image download / detector.** Crashes have ground-truth severity in the source. No YOLO call. The crash ingest script is much shorter than ingest_mapillary.py (probably ~200 LOC vs. its 700+).
- **Different driver loop.** Mapillary iterates over **target segments** and pulls images for each. Crash ingest iterates over **crash rows** and asks "which segment, if any, does this crash belong to?" The driver direction is inverted.

### Proposed snap_match function (mirror of ingest_mapillary:255)

```python
def snap_match_crash(cur, lon: float, lat: float, snap_meters: float = 75.0) -> int | None:
    """Nearest road_segment within snap_meters, or None.

    Mirrors snap_match_image() (ingest_mapillary.py:255). Wider default
    tolerance than Mapillary because state crash data is geocoded at
    intersection centroids, not lane-precise.
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
    return None if not row else int(row["id"] if isinstance(row, dict) else row[0])
```

---

## (e) Migration plan: NEW file, additive, non-breaking

### Decision

Create `db/migrations/004_crash_records.sql`. Do NOT modify existing migrations.

### Rationale

- **Migration numbering precedent:** 001 (initial), 002 (mapillary provenance), 003 (users) — strict sequential. 004 is next.
- **Idempotency precedent (migration 002):** `CREATE TABLE IF NOT EXISTS`, `CREATE UNIQUE INDEX IF NOT EXISTS`, `ALTER TABLE … ADD COLUMN IF NOT EXISTS`, DROP-then-ADD CHECK constraints. Migration 004 must follow the same pattern so a re-apply against a partially-applied DB is safe.
- **CONSTRAINTS line 143:** "raw SQL in `db/migrations/` is fine; adopt [Alembic] only if 5+ migrations land without ADR." 004 is the fourth — still under threshold.

### Proposed `004_crash_records.sql` outline

```sql
-- Migration 004: crash_records + segment_scores.crash_norm.
-- v0.4.0 Crash-Aware Routing milestone.
-- Idempotency: mirrors 002_mapillary_provenance.sql pattern (CREATE IF NOT EXISTS,
-- separate UNIQUE INDEX, DROP-then-ADD CHECK).

-- 1. crash_records table (NEW)
CREATE TABLE IF NOT EXISTS crash_records (
    id               BIGSERIAL PRIMARY KEY,
    source           TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    crash_date       DATE,
    severity         TEXT NOT NULL,
    geom             GEOMETRY(Point, 4326) NOT NULL,
    segment_id       INTEGER REFERENCES road_segments(id) ON DELETE SET NULL,
    snap_meters      DOUBLE PRECISION,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE crash_records DROP CONSTRAINT IF EXISTS crash_records_source_check;
ALTER TABLE crash_records ADD CONSTRAINT crash_records_source_check
    CHECK (source IN ('switrs', 'la_city'));

ALTER TABLE crash_records DROP CONSTRAINT IF EXISTS crash_records_severity_check;
ALTER TABLE crash_records ADD CONSTRAINT crash_records_severity_check
    CHECK (severity IN ('fatal', 'injury', 'pdo'));

CREATE INDEX IF NOT EXISTS idx_crash_geom    ON crash_records USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_crash_segment ON crash_records(segment_id);
CREATE INDEX IF NOT EXISTS idx_crash_source  ON crash_records(source);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_crash_source_record
    ON crash_records (source, source_record_id);

-- 2. segment_scores.crash_norm (NEW column, additive, default 0)
ALTER TABLE segment_scores
    ADD COLUMN IF NOT EXISTS crash_norm DOUBLE PRECISION NOT NULL DEFAULT 0.0;
```

**Why non-breaking:**
- Existing rows in `segment_scores` get `crash_norm = 0.0` automatically (DEFAULT).
- Existing `/segments` and `/route` callers don't see the new column unless backend code is updated to SELECT it.
- Existing `compute_scores.py` invocations continue to work — the existing UPSERT writes only the columns it knows about, leaving `crash_norm` at default 0 until the extended UPSERT is deployed.

This means the rollout can be staged: deploy migration → verify zero-impact on prod → deploy ingest script → deploy extended compute_scores → deploy routing.py with locked weights → frontend last.

---

## (f) Routing.py weight-handling: locked constants, silent backwards-compat

### Decision

- Replace the `normalize_weights(...)` call (routing.py:245-248) with module-level constants `W_IRI = 0.40`, `W_POT = 0.35`, `W_CRASH = 0.25`.
- Keep `RouteRequest.weight_iri / weight_potholes / include_iri / include_potholes` fields in models.py (don't remove them) — Pydantic will accept incoming JSON containing them, but `find_route()` ignores them.
- Add `W_CRASH` deliberately as a module constant (not as a request field) so the backwards-compat surface stays exactly the v0.3.0 shape.

### Rationale

CONTEXT line 136 specifies: *"existing `/route` API still accepts `w_IRI` / `w_pothole` per locked CON-route-api but backend ignores them."* This is exactly the contract here.

### Specific edits

**`routing.py:245-248`** (delete normalize_weights call):

```python
# DELETE:
w_iri, w_pot = normalize_weights(
    req.include_iri, req.include_potholes,
    req.weight_iri, req.weight_potholes,
)

# REPLACE with module-top constants:
W_IRI = 0.40    # locked v0.4.0 weight
W_POT = 0.35    # locked v0.4.0 weight
W_CRASH = 0.25  # locked v0.4.0 weight
```

**`routing.py:424`** (compute_segment_cost call):

```python
# v0.3.0:
total_cost += compute_segment_cost(t, iri, pot, w_iri, w_pot)

# v0.4.0:
total_cost += compute_segment_cost(
    t, iri, pot, crash,           # crash_norm fetched from new SEGMENTS_BY_IDS_SQL column
    W_IRI, W_POT, W_CRASH,
)
```

**`routing.py:250-256`** (cache key):

The cache key currently includes `req.include_iri, req.include_potholes, req.weight_iri, req.weight_potholes`. For v0.4.0 these are ignored — keep them in the key for now (cheap; no harm) OR strip them. Stripping is cleaner long-term but means clients posting different `weight_iri` values share a cache entry — which is correct (since the math ignores those values), but might confuse a debugger. **Recommendation: keep them in the cache key for v0.4.0 — the cache is invalidated on deploy anyway.**

**`scoring.py`** — the `normalize_weights()` function becomes dead code in production but should remain for tests (compatibility) and to be deleted in a later cleanup milestone. CONTEXT line 136: "Weight normalization rules removed (no longer needed with fixed constants)."

### Why constants in routing.py and not in a config file

`routing.py` is the only consumer. A config layer is over-engineering for three numbers locked at the milestone level. Future tuning is a code change with PR review, which is exactly the gate we want for a math change that affects every routed user.

---

## (g) Build order

### Decision (top-down dependency walk)

1. **Schema migration** (`db/migrations/004_crash_records.sql`) — adds table + column. **Non-breaking; deployable independently.**
2. **Ingest script** (`scripts/ingest_crashes.py`) — depends on the new table. Can be tested against staging DB once migration applies.
3. **Score recompute** (`scripts/compute_scores.py` modified) — depends on `crash_records` populated AND `segment_scores.crash_norm` column existing. Will write zeros if `crash_records` is empty (graceful degradation).
4. **Routing constants** (`backend/app/routes/routing.py` + `backend/app/scoring.py`) — depends on `segment_scores.crash_norm` being populated by step 3. If skipped to here, `LEFT JOIN COALESCE(0)` makes the third term zero — `cost = travel_time + 0.40·iri + 0.35·pot + 0.25·0`. Routes will be wrong but won't crash.
5. **`/segments` endpoint** (`backend/app/routes/segments.py`) — adds `crash_norm` to the GeoJSON properties dict. Independent of step 4 mechanically; both touch `SEGMENTS_BY_IDS_SQL`-style queries.
6. **Frontend slider removal** (`frontend/src/components/ControlPanel.tsx` + `RouteFinder.tsx`) — last. Depends on the backend ignoring the slider values, which is delivered in step 4.

### Why this order — three load-bearing dependencies

- **Schema before ingest:** trivially. Can't INSERT into a table that doesn't exist.
- **Ingest before recompute:** recompute reads from `crash_records`. If you flip the order, recompute writes zeros.
- **Recompute before routing.py constants:** routing.py reads `crash_norm` from `segment_scores`. If you flip, you ship locked-weights routing with all-zero crash terms — equivalent to silently dropping the milestone's value-add.

### What can be parallelized

- Steps 1+2 can be done in one PR (schema + ingest script are tightly coupled).
- Steps 4+5 can be done in one PR (both touch the routing/segments query layer).
- Step 6 is independent and can be a follow-up PR.

### Smoke test between each step

- After step 1: `\d+ crash_records` and `\d+ segment_scores` show new schema.
- After step 2: `SELECT COUNT(*) FROM crash_records WHERE segment_id IS NOT NULL` > 0.
- After step 3: `SELECT COUNT(*) FROM segment_scores WHERE crash_norm > 0` > 0.
- After step 4: `curl POST /route ...` returns a route where `total_cost - travel_time` is non-zero AND independent of any `weight_iri` value the client posts.
- After step 5: `curl /segments?bbox=...` returns features with `properties.crash_norm` field present.
- After step 6: UI no longer shows IRI/pothole sliders; max-extra-minutes slider remains.

---

## Component Responsibilities (touch table)

| Component | Path | Status | What changes |
|-----------|------|--------|---------------|
| `road_segments` table | migration 001 | UNCHANGED | — |
| `segment_defects` table | migration 002 | UNCHANGED | — |
| `segment_scores` table | migration 001/004 | **MODIFIED (additive)** | + `crash_norm DOUBLE PRECISION DEFAULT 0` |
| `crash_records` table | migration 004 | **NEW** | full DDL above |
| `scripts/ingest_crashes.py` | scripts/ | **NEW** | mirrors ingest_mapillary patterns minus image/detector |
| `scripts/compute_scores.py` | scripts/ | **MODIFIED** | extend UPSERT with crash subquery; add `'crash'` to `VALID_SOURCES` |
| `scripts/ingest_mapillary.py` | scripts/ | UNCHANGED | — |
| `scripts/seed_data.py` | scripts/ | UNCHANGED | (synthetic crashes optional follow-up; not required for v0.4.0 since real data is the goal) |
| `backend/app/scoring.py` | scoring.py:1-36 | **MODIFIED** | `compute_segment_cost` adds `crash_norm` arg + `w_crash` |
| `backend/app/routes/routing.py` | routing.py:13-485 | **MODIFIED** | locked constants; extend `SEGMENTS_BY_IDS_SQL`; extend per-segment loop at line 414-431 |
| `backend/app/routes/segments.py` | segments.py:25-55 | **MODIFIED** | SELECT + properties dict |
| `backend/app/models.py` | models.py:9-16 | UNCHANGED | (RouteRequest fields stay for backwards-compat per CONTEXT line 136) |
| `backend/app/cache.py` | cache.py | UNCHANGED | TTL caches survive (cache flushed on deploy) |
| `backend/app/main.py` | main.py | UNCHANGED | no new routers |
| `frontend/src/components/ControlPanel.tsx` | frontend | **MODIFIED** | remove IRI/pothole sliders; keep max-extra-minutes |
| `frontend/src/pages/RouteFinder.tsx` | frontend | **MODIFIED** | remove slider state; pass empty/default include_/weight_ to API |
| `frontend/src/api.ts` | frontend | UNCHANGED (or simplify) | API contract stable; can drop slider fields from request body without backend break |
| `frontend/src/pages/MapView.tsx` | frontend | UNCHANGED | color comes from cost which now includes crash term |

**Total surface:**
- 1 new migration file
- 1 new ingest script
- 4 modified files in backend (compute_scores, scoring, routing, segments)
- 2 modified files in frontend (ControlPanel, RouteFinder)
- 0 deletions, 0 breaking changes

---

## Data Flow

### Quarterly refresh flow (operator-driven)

```
operator: SWITRS CSV downloaded to data/crashes/switrs_2026_q1.csv
   │
   ▼
operator: python scripts/ingest_crashes.py \
            --source switrs --csv data/crashes/switrs_2026_q1.csv \
            --snap-meters 75 --truncate-source
   │
   ▼
ingest_crashes.py:
  • TRUNCATE crash_records WHERE source='switrs' (if --truncate-source)
  • for row in CSV:
       lon,lat,severity = parse_switrs_row(row)
       seg_id = snap_match_crash(cur, lon, lat, snap_m)
       INSERT INTO crash_records (...) ON CONFLICT DO NOTHING
  • subprocess: python scripts/compute_scores.py --source crash
   │
   ▼
compute_scores.py --source crash:
  • single UPSERT into segment_scores (recomputes ALL columns, crash + pothole)
   │
   ▼
operator: deploy/restart backend (clears in-memory cachetools cache)
   │
   ▼
next /route call: reads new segment_scores.crash_norm via LEFT JOIN
                  compute_segment_cost includes crash term
                  RouteFinder UI shows updated "best route"
```

### Per-request route flow (unchanged at the boundary, math changes inside)

```
POST /route {origin, destination}
   │
   ▼  (routing.py:243)
find_route():
  • snap origin/dest to road_segments_vertices_pgr
  • CREATE TEMP TABLE rq_filtered_edges (Phase 8 unchanged)
  • find_k_shortest_via_dijkstra (K=5 unchanged)
  • SEGMENTS_BY_IDS_SQL: SELECT iri_norm, moderate, severe, pothole_total, crash_norm
                                                                      [NEW]
  • for each path:
       for each edge:
           cost += compute_segment_cost(
               t, iri_norm, pothole_total, crash_norm,
               W_IRI=0.40, W_POT=0.35, W_CRASH=0.25,           [NEW]
           )
  • fastest = min(scored, key=time)
  • best = min(within_budget, key=cost)   ← cost now includes crash term
   │
   ▼
RouteResponse {fastest, best, warning, per_segment_metrics}
```

---

## Architectural Patterns (the three load-bearing ones)

### Pattern 1: Single-table per-segment scores, ingest-time aggregation

**What:** All per-segment derived metrics live in one row in `segment_scores`. Ingest scripts UPSERT atomically.
**When:** Read-heavy workloads (route queries) where data refreshes on a slower cadence than reads.
**Trade-off:** Recompute is O(segments × sources), not free. But it runs offline (compute_scores.py is a CLI), so the cost is paid by operators not users. Read-time aggregation would shift this cost into every API call.

### Pattern 2: Source-tagged provenance + idempotent ingest

**What:** Every ingested row carries a `source` column (CHECK-constrained). UNIQUE index on `(source, source_record_id)` makes re-ingest idempotent.
**When:** Multiple data sources writing to the same table or same downstream aggregate.
**Trade-off:** Slight schema bloat (one extra column, one extra constraint). Massive operational win — re-running an ingest after a partial failure is safe and produces no duplicates.

### Pattern 3: Module constants for locked policy, request fields for kept-for-compat parameters

**What:** Routing weights as `routing.py` module constants (W_IRI = 0.40 etc.). Pydantic request fields (weight_iri, weight_potholes) accepted by the schema but ignored by the handler.
**When:** Locking a previously-tunable parameter without breaking deployed clients.
**Trade-off:** Mild request-schema cruft. But far better than versioning the API (`/v2/route`) for a math change.

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: "Just add `source='crash'` to segment_defects"

**What people do:** Reuse the existing defects table with a third source value, claiming "fewer tables, simpler schema."
**Why it's wrong:**
- Forces severity-vocabulary union (`moderate | severe | fatal | injury | pdo`) — pollutes Phase 3 CHECK constraint.
- `source_mapillary_id` becomes a leaky abstraction (NULL for crashes, vs. NOT NULL for Mapillary).
- Quarterly truncate-and-reload would have to filter by `source='crash'` on a table that's also receiving Mapillary appends — risk of accidentally deleting Mapillary data.
**Do this instead:** Separate `crash_records` table. Aggregate at the `segment_scores` layer.

### Anti-Pattern 2: Compute crash_norm at request-time

**What people do:** Skip the `segment_scores.crash_norm` column; aggregate from `crash_records` in the routing query.
**Why it's wrong:** Adds 200–500 ms to every `/route` call (Phase 8 budget already at 2.5s). Defeats the cachetools cache because the read query becomes per-request bespoke. Re-aggregates static data on every read.
**Do this instead:** Pre-bake into `segment_scores.crash_norm` at ingest time. This is the same pattern used for `pothole_score_total` in Phase 3.

### Anti-Pattern 3: Inline crash-aggregation SQL inside routing.py

**What people do:** Add a `SELECT … FROM crash_records WHERE …` JOIN to `SEGMENTS_BY_IDS_SQL` in `routing.py:75-85`.
**Why it's wrong:** Aggregation logic spreads across two files. Recompute and route now have different SQL — easy to drift. Phase 8 RESEARCH §1 also showed that pgr_dijkstra inner SQL doesn't use GiST indices via SPI; pushing aggregation into the routing path risks the same trap.
**Do this instead:** Single aggregation in `compute_scores.py`, single read column in `segment_scores`.

### Anti-Pattern 4: New migration that ALTERs `segment_defects.severity` CHECK

**What people do:** Add `'fatal' | 'injury' | 'pdo'` to the existing severity CHECK to allow a hypothetical reuse.
**Why it's wrong:** Now compute_scores.py:85-101's CASE-on-severity branches need updating; tests break; existing operator runbooks lie. Plus it's unused if you take the new-table path (which you should).
**Do this instead:** Don't touch migration 002. Add migration 004 with its own CHECK.

---

## Integration Points

### External services

| Service | Integration pattern | Notes |
|---------|---------------------|-------|
| **California SWITRS / TIMS** | Bulk CSV download (UC Berkeley TIMS portal). Manual quarterly. | Free for academic use; check terms for commercial demo. ~120k LA-area crashes/year statewide; filter to LA bbox before insert. Coordinates often at intersection centroid (75 m snap). |
| **LA City open-data portal (data.lacity.org)** | Socrata SODA API (JSON endpoint, optional API token). Programmatic. | Auto-fetched. Rate-limited but free. Coordinates are LA-GIS-snapped (50 m snap typical). |

Both ingest paths converge on `crash_records` rows tagged with their `source` column.

### Internal boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| `ingest_crashes.py` ↔ DB | psycopg2 + execute_values (mirrors ingest_mapillary.py:60) | Same connection-pool pattern; same DATABASE_URL env var. |
| `compute_scores.py` ↔ DB | psycopg2 + ON CONFLICT UPSERT | Single statement, atomic per-segment refresh. |
| `routing.py` ↔ scoring.py | Direct function call | scoring.py is a pure-function module; routing.py imports `compute_segment_cost`. |
| `routing.py` ↔ DB | psycopg2 + ThreadedConnectionPool | Phase 5 wrapper unchanged. |
| Frontend ↔ `/route` API | fetch JSON over HTTPS | Request body shape preserved (slider fields ignored, not removed from schema). |

---

## Scaling Considerations

| Scale | Adjustments |
|-------|-------------|
| **Today (LA, ~205k segments, ~125k Mapillary defects, expected ~80–120k crashes/quarter aggregate)** | No changes needed. `crash_records` table is small (<1M rows). GIST index on geom + btree on segment_id covers the access patterns. |
| **Multi-city expansion** | Partition `crash_records` by `source` or city tag if it grows past ~10M rows. Add index on `(crash_date)` if temporal filtering is added (e.g., "crashes in last 3 years only"). |
| **Real-time crash feed (out-of-scope for v0.4.0)** | Move from quarterly truncate-and-reload to streaming ingest. Add Postgres LISTEN/NOTIFY or a refresh-on-insert trigger that recomputes affected segments only (not full table). |

### First bottleneck: compute_scores.py runtime

The extended UPSERT does a correlated subquery per segment (~205k segments). On Phase 5 hardware (`shared-cpu-1x:2048MB`) this might take 30–120 s. **Mitigation:** if it becomes a problem, materialize the crash aggregation into a CTE first, then JOIN; or split into two UPSERTs (one for defects, one for crashes) accepting the brief stale-row window.

---

## Open Questions for Implementation Phase

1. **Crash-norm normalization formula** — severity weights (`fatal=3.0, injury=1.0, pdo=0.3`?) and the [0,1] scaling step are sketched but not researched. Belongs in REQUIREMENTS.md or a dedicated implementation-phase research.
2. **SWITRS data licensing** — free for academic; need to verify the public Fly.io demo's commercial-status implications.
3. **Quarterly cron schedule** — manual operator-runbook for v0.4.0. Automation (GH Actions cron + Fly secrets pull) is a follow-up.
4. **Synthetic crash data for tests** — do we extend `seed_data.py` to generate fake crashes for integration tests? Phase 3 generated synthetic Mapillary defects; precedent supports doing it here for consistency, but it adds scope.
5. **Frontend legend update** — do we add a "crash density" tier indicator next to the existing color scale? CONTEXT says "no new map layer" but a legend addition is borderline.

---

## Sources

- **Repo source (HIGH confidence — direct read):**
  - `db/migrations/001_initial.sql` (4-table schema, CHECK constraints)
  - `db/migrations/002_mapillary_provenance.sql` (provenance + UNIQUE pattern)
  - `db/migrations/003_users.sql` (idempotency precedent)
  - `backend/app/routes/routing.py:13-485` (Phase 8 routing flow + scoring integration)
  - `backend/app/routes/segments.py:9-59` (GeoJSON response shape)
  - `backend/app/scoring.py:1-36` (cost-formula chokepoint)
  - `backend/app/models.py:1-39` (Pydantic request schemas)
  - `scripts/compute_scores.py:1-119` (UPSERT pattern + --source filter)
  - `scripts/ingest_mapillary.py:255-281, 332-391, 396-501` (snap_match pattern, wipe pattern, ingest driver)
  - `.planning/PROJECT.md` (CONTEXT, CONSTRAINTS, milestone scope)
  - `.planning/codebase/STRUCTURE.md` (file-layout conventions)

- **Domain sources (MEDIUM confidence — to verify in implementation-phase research):**
  - California SWITRS / TIMS bulk export schema (UC Berkeley)
  - LA City data.lacity.org Socrata SODA API
  - Crash severity coding: KABCO scale (NHTSA standard) → fatal/injury/PDO mapping

---

*Architecture research for: v0.4.0 Crash-Aware Routing milestone integration*
*Researched: 2026-05-07*
