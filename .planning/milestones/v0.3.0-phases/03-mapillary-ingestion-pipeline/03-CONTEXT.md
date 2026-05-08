# Phase 3: Mapillary Ingestion Pipeline - Context

**Gathered:** 2026-04-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Replace the synthetic pothole seed with a real, rerunnable pipeline that pulls Mapillary imagery for **operator-targeted road segments**, runs the YOLOv8 detector, matches detections back to `road_segments` via PostGIS, and writes them into `segment_defects` with full provenance. The pipeline is idempotent, accumulative across runs, and produces a clean real-data-only state for the public demo.

**In scope:**
- New CLI `scripts/ingest_mapillary.py` with multi-mode segment targeting
- New migration `db/migrations/002_*.sql` adding `source_mapillary_id` and `source` to `segment_defects` (with UNIQUE constraint)
- Image-to-segment matching via PostGIS (`ST_DWithin` + nearest, configurable snap radius)
- Image cache + manifest.json on disk (CC-BY-SA audit trail; reuses Phase 2 manifest format)
- `--wipe-synthetic` flag and public-demo deploy procedure
- `compute_scores.py` extension: `--source {synthetic|mapillary|all}` filter
- End-to-end smoke verification: SC #4 (real-vs-synthetic ranking diff) demonstrable in dev

**Out of scope (deferred to other phases):**
- Public demo URL wiring and `/segments` filtering UX — Phase 6
- Cloud deploy automation, scheduled ingestion, secrets management — Phase 5
- User authentication on the ingest endpoint (it's a CLI, not an HTTP route) — Phase 4
- Confidence calibration / threshold tuning per-class — Claude's discretion within Phase 3
- Heading-filtered or sequence-filtered Mapillary queries — deferred unless first runs show noise
- A continuous CI gate on ingestion correctness — future phase

</domain>

<decisions>
## Implementation Decisions

### Image-to-Segment Matching
- **D-01:** Matching approach = **simple PostGIS**: `SELECT id FROM road_segments WHERE ST_DWithin(geom::geography, ST_Point(lon,lat)::geography, snap_m) ORDER BY ST_Distance(geom::geography, point) LIMIT 1`. One query per image, leverages existing `idx_segments_geom` GIST index. Standard pattern; trivial to debug a single image's match (`psql -c '...'`).
- **D-02:** Snap radius default = **25 m**, tunable via `--snap-meters` CLI flag. 25 m covers Mapillary's typical 5–15 m GPS error plus jitter, without bridging LA's parallel residential streets (~30–60 m apart).
- **D-03:** Images outside the snap radius are **dropped** (not force-attributed). Counted in the run summary but not written to `segment_defects`.
- **D-04:** Match-drift policy = **attribute to closest segment**. Even if an image was fetched while targeting segment X, it's written against the segment closest within `snap_m` — which may be a neighbor Y. This produces "free coverage" of adjacent segments and is the geometrically honest answer.

### Idempotency & Provenance
- **D-05:** New migration adds `source_mapillary_id TEXT` to `segment_defects` plus a **`UNIQUE(segment_id, source_mapillary_id, severity)`** constraint. Existing synthetic rows have `source_mapillary_id IS NULL` and do not participate in the UNIQUE check (Postgres ignores NULL in unique indexes by default; if multi-NULL collisions become a concern, the planner can use `UNIQUE NULLS NOT DISTINCT` on PG 15+).
- **D-06:** Inserts use **`INSERT ... ON CONFLICT DO NOTHING`** — second run on the same images silently skips, satisfies SC #2 (no double-counting on rerun).
- **D-07:** The same migration adds **`source TEXT NOT NULL DEFAULT 'synthetic' CHECK (source IN ('synthetic', 'mapillary'))`** so existing rows auto-tag as synthetic and Mapillary writes tag as `'mapillary'`. Two columns, one migration trip.
- **D-08:** Resumability falls out of idempotency for free: if a long run is killed, rerun the same command — already-ingested images skip on conflict. No checkpoint file needed for MVP.

### CLI: Targeting & Orchestration
- **D-09:** CLI shape = **`scripts/ingest_mapillary.py`** with three mutually-exclusive target modes (operator picks one):
  - `--segment-ids 1,2,3` — explicit comma-separated list
  - `--segment-ids-file path.txt` — one segment id per line
  - `--where "iri_norm > 0.5 ORDER BY iri_norm DESC LIMIT N"` — SQL predicate appended after `WHERE` against `road_segments`. **Planner must defend against SQL injection** — operator-supplied SQL is a knife; the simplest safe path is psycopg2 parameterized queries with the predicate restricted to a whitelist of column names + comparison operators, or running it as an explicit SQL string only when the operator has DB credentials anyway (it's a local-run CLI, but document the risk).
- **D-10:** Per-segment workflow:
  1. Compute padded bbox around the segment's geometry (padding ≥ `snap_m`; **default 50 m**, Claude's discretion)
  2. If bbox area > 0.01 deg², subdivide (reuses `validate_bbox` failure as a tiling signal — planner can split lazily if needed)
  3. `mapillary.search_images(bbox, limit=...)` → for each image: download, detect, snap-match, upsert
  4. Append to manifest, write to disk
- **D-11:** Image cache = **`data/ingest_la/<segment_id>/<image_id>.jpg`** with a per-run manifest.json (mirrors Phase 2's manifest format). `--no-keep` flag deletes images after detection for disk-conscious operators. Default keeps everything for re-detection on future fine-tunes.
- **D-12:** Limits: `--limit-per-segment N` (default 20) caps API cost and disk per segment. Operator can raise it knowingly.

### Synthetic-Data Coexistence & Demo Cutover
- **D-13:** **Hybrid policy**: tag everything via `source` column AND provide a wipe path. During dev, synthetic + Mapillary coexist (distinguishable). Before the public demo, synthetic is wiped.
- **D-14:** `--wipe-synthetic` flag on `ingest_mapillary.py` runs `DELETE FROM segment_defects WHERE source = 'synthetic'` BEFORE writing real data, then triggers `compute_scores.py` after to refresh `segment_scores`. Deferred until operator opts in; default keeps synthetic.
- **D-15:** **Phase 6 deploy procedure MUST document `--wipe-synthetic`** as part of the public-demo cutover. Planner should propagate this expectation forward.
- **D-16:** `compute_scores.py` gains `--source {synthetic|mapillary|all}` flag; default `'all'` (preserves existing behavior). SC #4 ("real-vs-synthetic ranking comparison") is demonstrable in dev by running `compute_scores.py --source synthetic`, capturing a `/route` response, then `--source mapillary`, capturing again, and diffing.

### End-to-End Verification (SC #3, #4)
- **D-17:** SC #3 (real data flows to `/segments`/`/route`) is satisfied by: ingest → recompute scores → hit `/segments?bbox=...` and `/route` against the same bbox. Planner should add an integration smoke that runs this loop against a fixture DB or real DB if available.
- **D-18:** SC #4 ranking-difference verification = a documented operator workflow in `docs/`, plus an optional `scripts/compare_rankings.py` helper if it falls out cheaply (Claude's discretion). The demo claim is honesty — show the comparison once, archive the result.

### Token & Reuse from Phase 2
- **D-19:** Mapillary token via env-only: `MAPILLARY_ACCESS_TOKEN`, already read at module top of `data_pipeline/mapillary.py`. Phase 3 does not introduce a second token surface. Add to `.env.example` if not already present.
- **D-20:** All Mapillary HTTP/auth/SHA256/path-traversal hardening from Phase 2 stays — `validate_bbox`, `download_image` id-validation, `verify_manifest` constant-time compare, `_validate_manifest_path` traversal rejection. Phase 3 imports, does not reimplement.

### Claude's Discretion
- Confidence threshold for filtering low-confidence YOLO detections (likely 0.25–0.5; researcher/planner tunes after seeing real model outputs on the LA fine-tune)
- Detection-row aggregation policy — one row per detection vs grouped (segment_id, severity, image_id) batches. Schema (D-05/D-07) accepts both; pick whichever is simpler given the chosen YOLO output format
- Bbox padding around each target segment (D-10 step 1) — default 50 m suggested; planner adjusts if first runs are too sparse
- Mapillary rate-limit / retry / exponential backoff specifics
- Run summary format — JSON to stdout? Pretty table? Should match existing `scripts/` style (probably mirror `scripts/eval_detector.py` D-18 from Phase 2)
- Whether `--where` SQL uses parameterized queries or whitelisting (D-09 flags both as acceptable; planner picks the safer one)
- Whether to drop existing `seed_data.py` synthetic-pothole insert when running `seed_data.py --no-defects` for a clean dev start (low-priority polish)

### Folded Todos
*None — no todos cross-referenced for this phase at discussion time.*

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope + requirements
- `.planning/ROADMAP.md` — Phase 3 section (goal, dependencies on Phase 2, 5 success criteria)
- `.planning/REQUIREMENTS.md` — `REQ-mapillary-pipeline` acceptance criteria
- `.planning/PROJECT.md` — `CON-db-schema`, `CON-stack-backend`, secret-handling constraints
- `.planning/codebase/CONCERNS.md` — hardcoded DB credentials in scripts (Phase 3 must use env vars)

### Existing Mapillary client (must use, not rewrite — Phase 2 build)
- `data_pipeline/mapillary.py` — `validate_bbox`, `search_images`, `download_image`, `verify_manifest`, `write_manifest`, `_validate_manifest_path`, `_sha256_of_file`. Includes the bbox area DoS guard (≤0.01 deg²), constant-time SHA256 compare, image-id digit validation, and CC-BY-SA license string
- `.planning/phases/02-real-data-detector-accuracy/02-CONTEXT.md` — Phase 2 decisions, especially D-04 (manifest format), D-12 (HF Hub for weights)
- `.planning/phases/02-real-data-detector-accuracy/02-RESEARCH.md` — Mapillary API v4 pitfalls, rate-limit notes, license details

### Existing detector path (must use through factory)
- `data_pipeline/detector_factory.py` — `get_detector(use_yolo=True, model_path=...)` with `YOLO_MODEL_PATH` env resolution. Phase 3 ingest invokes the factory, never imports `YOLOv8Detector` directly
- `data_pipeline/yolo_detector.py` — `Detection` dataclass shape (`severity`, `confidence`, `bbox`); ingest writes use these fields
- `data_pipeline/detector.py` — `PotholeDetector` Protocol (interface contract; do not break)

### Existing scripts pattern (style to mirror)
- `scripts/seed_data.py` — synthetic defect insert pattern, TRUNCATE-based reset (Phase 3 does NOT TRUNCATE; uses `WHERE source = 'synthetic'`)
- `scripts/compute_scores.py` — score recomputation; Phase 3 extends this with `--source` filter (D-16)
- `scripts/ingest_iri.py` — argparse + module-top env-var read pattern, exit codes
- `scripts/fetch_eval_data.py` (Phase 2) — Mapillary-using CLI; reference for ingest_mapillary.py structure

### Database
- `db/migrations/001_initial.sql` — current `segment_defects` schema (no source columns yet); Phase 3 adds migration `002_*.sql`
- `backend/app/db.py` — connection pattern (read `DATABASE_URL` at module top)

### Backend integration points (read-only — Phase 3 does not modify routes)
- `backend/app/routes/segments.py` — `/segments` query that surfaces `segment_defects` data via `segment_scores`
- `backend/app/routes/routing.py` — `/route` endpoint that consumes scores
- `backend/tests/test_integration.py` — integration test pattern (auto-skip when DB unreachable); Phase 3 should add tests here

### Stack context
- `.planning/codebase/STACK.md` — Python 3.12, psycopg2 with RealDictCursor, ultralytics
- `.planning/codebase/STRUCTURE.md` — `data_pipeline/`, `scripts/`, `db/migrations/`, `backend/tests/` layout
- `.planning/codebase/CONVENTIONS.md` — coding patterns

### External docs (researcher should fetch current versions)
- Mapillary API v4 docs — image search by bbox, attribution requirements, sequence/heading filters (deferred but document as available)
- PostGIS docs — `ST_DWithin`, `ST_Distance` with `geography` type, GIST index behavior
- Postgres `INSERT ... ON CONFLICT` semantics with NULL columns (PG 15+ `NULLS NOT DISTINCT` option for UNIQUE)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets (from Phase 2)
- `data_pipeline/mapillary.py`: full client surface (`search_images`, `download_image`, `validate_bbox`, `verify_manifest`, `write_manifest`). Phase 3 imports, does not modify.
- `data_pipeline/detector_factory.py::get_detector(...)`: single injection point for the real model. Phase 3 calls `get_detector(use_yolo=True)` once at startup; reads `YOLO_MODEL_PATH` automatically.
- `scripts/compute_scores.py`: existing score recomputation. Phase 3 extends with a `--source` flag (D-16) and is invoked at end of ingest.
- `scripts/seed_data.py`: existing synthetic insert pattern. Phase 3 does not change its behavior; only the new migration backfills `source = 'synthetic'` on existing rows. Optional follow-up: add a `--no-defects` flag for clean dev starts.

### Established Patterns (must follow)
- **Scripts are flat, argparse-based, standalone.** No framework. Each script handles its own argparse, logging setup, and exit codes (0 success, 1 generic error, 2 validation/threshold, 3 missing-resource — Phase 2 D-18).
- **Env vars read at module top** (matches `backend/app/db.py:5-7`). `MAPILLARY_ACCESS_TOKEN`, `DATABASE_URL`, `YOLO_MODEL_PATH` all already follow this.
- **`.env.example` is authoritative** (Phase 1 deliverable). Phase 3 confirms `MAPILLARY_ACCESS_TOKEN` is listed; appends nothing new.
- **Migrations are single SQL files** under `db/migrations/`, no Alembic (`CON-stack-backend`). Phase 3 adds `002_mapillary_provenance.sql` (or similar — name is Claude's discretion).
- **psycopg2 with RealDictCursor** for ad-hoc reads; named parameters via `%(name)s` to defend against injection (critical for D-09's `--where` mode).

### Integration Points
- `db/migrations/002_*.sql` — new file, additive ALTER TABLE on `segment_defects`. Must be idempotent (use `IF NOT EXISTS` where possible).
- `scripts/ingest_mapillary.py` — new file, the operator entrypoint.
- `scripts/compute_scores.py` — modified: add `--source` arg.
- `data/ingest_la/` — new on-disk directory tree for the image cache + manifests.
- `backend/tests/test_ingest_mapillary.py` — new test file (subprocess smokes + matching unit tests in the spirit of Phase 2's test pattern).
- `.env.example` — verify `MAPILLARY_ACCESS_TOKEN` is documented (was added in Phase 2).
- `README.md` — link to a new `docs/MAPILLARY_INGEST.md` operator runbook (Claude's discretion on writeup; Phase 6 will cite it for the demo's "data source" paragraph).

### Cross-phase coordination
- **Phase 5 (cloud deploy)** will package `ingest_mapillary.py` invocation as a scheduled job and surface `MAPILLARY_ACCESS_TOKEN` via cloud secrets. Keep the CLI flag-driven and env-driven; no hard-coded paths or tokens.
- **Phase 6 (public demo launch)** runs the demo cutover: `--wipe-synthetic` ingestion + `compute_scores.py` + smoke `/route` request. Deploy runbook must capture this sequence.
- **Phase 4 (auth)** does not touch ingestion (it's a CLI, not an HTTP route) but the operator that runs ingestion in production needs DB credentials. Keep the script using `DATABASE_URL` env var, no auth handshake.

</code_context>

<specifics>
## Specific Ideas

- **"I don't want synthetic data when the project is finished"** — drove D-13/D-14/D-15 (hybrid tagging + wipe-synthetic flag + Phase 6 deploy procedure). Synthetic stays during dev for fast iteration; production demo is real-only.
- **Segment-targeted, not bbox-tile-sweep** — operator drives ingestion from a list of segments they care about. Imagery flows for those + free coverage of neighbors via attribute-to-closest matching. Demo gets directed coverage on segments that matter.
- **Provenance as a first-class column** — every defect row answers "where did this come from?" without a JOIN. Critical for CC-BY-SA + the "honest data source" demo claim.
- **Reuse, do not rewrite** — `data_pipeline/mapillary.py` from Phase 2 is the entire client surface. Phase 3 is orchestration + matching + DB writes around an existing client.

</specifics>

<deferred>
## Deferred Ideas

- **Confidence calibration / per-class threshold tuning** — Claude's discretion within Phase 3 (probably one global threshold), full calibration is post-MVP.
- **Mapillary heading/orientation filter** — not used in Phase 2 either; defer unless first runs show direction-related noise (e.g., images facing perpendicular to the road).
- **Continuous CI gate on ingestion correctness** — future phase. For now, ingestion is operator-triggered and human-verified.
- **Auto-tile sweep mode** (`--bbox` instead of segments) — segment-targeted is the locked default. If a future workflow wants "ingest everything in this area," the planner can layer a `--bbox` mode on top — the per-tile loop logic is mostly the same.
- **Named target sets** (e.g., `--target downtown-arterials`) — over-engineered for MVP. Operator can express via `--where`.
- **Migration of synthetic seed to a separate `segment_defects_synthetic` table** — heavy refactor; the `source` column achieves the same separation with zero schema sprawl.
- **Confidence histograms / per-class precision-recall on real ingest data** — eval lives in Phase 2's harness; ingest doesn't re-evaluate.
- **Segment-defects "soft delete" via `deleted_at` for rollback by run** — `source_mapillary_id` already enables `DELETE WHERE` rollback by image; soft-delete adds complexity without proportional value.

</deferred>

---

*Phase: 03-mapillary-ingestion-pipeline*
*Context gathered: 2026-04-25*
