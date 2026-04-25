# Mapillary Ingestion Pipeline — Operator Runbook

**Phase:** 3 (M1)
**Script:** scripts/ingest_mapillary.py
**Migration:** db/migrations/002_mapillary_provenance.sql
**Requirement:** REQ-mapillary-pipeline

This is the operator runbook for the Mapillary -> YOLOv8 -> `segment_defects`
ingestion pipeline. It covers prerequisites, all CLI modes, the SC #4 ranking-
comparison demo workflow, the Phase 6 public-demo cutover sequence, the trust
model for `--where`, and the operational pitfalls you are most likely to hit.
If you can clone the repo and follow this document end-to-end, the pipeline
should produce real LA pothole detections in `segment_defects` and surface
them through `/segments` and `/route`.

## What this pipeline does

The pipeline is a per-segment, idempotent, attribute-to-closest ingest. For
every target road segment in the operator's list, the script:

1. **Pads the segment's bounding box** by `--pad-meters` (default 50 m) using
   `ST_Buffer(geom::geography, pad_m)::geometry -> ST_Envelope`. The
   geography cast is required so the pad is in meters, not degrees. If the
   resulting envelope exceeds `0.01 deg^2` (Mapillary API limit) it is
   subdivided into 4 quadrants.
2. **Pulls Mapillary imagery** within the (sub-)bbox via
   `data_pipeline/mapillary.py::search_images`, capped at
   `--limit-per-segment` images per segment (default 20).
3. **Runs the YOLOv8 detector** (`data_pipeline/detector_factory.py::get_detector(use_yolo=True)`)
   on each downloaded image. Detector resolution and pickle-ACE mitigations
   are inherited from Phase 2.
4. **Snap-matches** each image's reported lon/lat to the nearest segment
   within `--snap-meters` (default 25 m) via
   `ST_DWithin + ORDER BY <-> + LIMIT 1`. Images outside the snap radius
   are dropped (counter `dropped_outside_snap`).
5. **Writes idempotent rows** tagged `source = 'mapillary'` and
   `source_mapillary_id = <image_id>` via
   `INSERT ... ON CONFLICT (segment_id, source_mapillary_id, severity) DO NOTHING`.
   Re-runs produce zero new rows (counter `rows_skipped_idempotent`).
6. **Auto-runs `compute_scores.py --source all`** so `/segments` and
   `/route` immediately reflect the new detections. Pass `--no-recompute` to
   opt out (e.g. for chained-ingest workflows).

## Prerequisites

| Requirement | How to provide it | Notes |
|-------------|-------------------|-------|
| `MAPILLARY_ACCESS_TOKEN` env var | Get a free token at <https://www.mapillary.com/dashboard/developers>; export it in your shell | **NEVER commit this** to git. `.env` is gitignored; place the token there for local dev. The token is read at module-top in `data_pipeline/mapillary.py` (D-19) and never accepted via CLI flag. |
| `DATABASE_URL` env var | Default is `postgresql://rq:rqpass@localhost:5432/roadquality`; export `DATABASE_URL=...` for cloud overrides | Production deploys MUST override the default (which uses dev creds). |
| `YOLO_MODEL_PATH` env var (optional) | Default falls back to HuggingFace `keremberke/yolov8s-pothole-segmentation`; pin to `user/repo@<commit_sha>` for production | See [`docs/FINETUNE.md`](FINETUNE.md) for laptop / Colab / EC2 fine-tuning recipes. Pinning to a revision protects against silent weight swaps. |
| Migration 002 applied | See "Applying the migration" below | Adds `source`, `source_mapillary_id`, the CHECK constraint, and the dedup UNIQUE INDEX. |
| Python deps | `pip install -r data_pipeline/requirements.txt` | Pulls psycopg2, ultralytics, requests, etc. |
| `seed_data.py` already run | `python scripts/seed_data.py` | The pipeline ingests INTO `road_segments`; the seed populates that table. |

## Applying the migration

### Fresh dev DB

`docker compose up` mounts `db/migrations/` into the container's
`/docker-entrypoint-initdb.d/`, so migration 002 is applied automatically on
first boot. No operator action needed.

### Existing dev DB

Apply the migration manually against a running container:

```bash
docker compose exec -T db psql -U rq -d roadquality < db/migrations/002_mapillary_provenance.sql
```

Verify the migration applied cleanly by counting rows per source:

```bash
docker compose exec db psql -U rq -d roadquality -c "SELECT source, COUNT(*) FROM segment_defects GROUP BY source"
```

Expected result: all existing rows fall under `source = 'synthetic'` (the
`DEFAULT 'synthetic'` clause in the migration backfills any pre-existing
rows). If you see `source = 'mapillary'` rows already, the migration has
been applied and an ingest run has already happened on this DB.

The migration is idempotent (uses `ADD COLUMN IF NOT EXISTS`,
`CREATE UNIQUE INDEX IF NOT EXISTS`, and a DROP-then-ADD pattern for the
CHECK constraint) so it is safe to re-run.

## CLI reference

### Target modes (mutually exclusive, one required)

| Flag | Example | When to use |
|------|---------|-------------|
| `--segment-ids 1,2,3` | `--segment-ids 12,34,56` | You already know the exact segment ids you care about (e.g. from a previous `/segments` query). |
| `--segment-ids-file PATH` | `--segment-ids-file priority.txt` | You have a long list (one id per line, `#`-comments and blanks ignored). |
| `--where "..."` | `--where "iri_norm > 0.5 ORDER BY iri_norm DESC LIMIT 50"` | You want to attack a slice expressed declaratively (e.g., "top 50 roughest segments"). See "Trust model for --where" below. |

### Options

| Flag | Default | Purpose |
|------|---------|---------|
| `--snap-meters FLOAT` | `25.0` | Snap radius for image -> nearest segment. Wider = more matches but more cross-segment drift; tighter = fewer matches. |
| `--pad-meters FLOAT` | `50.0` | Bbox padding around each segment for the Mapillary search. Wider = more imagery candidates per segment; tighter = fewer false matches. |
| `--limit-per-segment INT` | `20` | Max images fetched per segment. Lower this to bound runtime / Mapillary rate-limit pressure. |
| `--cache-root PATH` | `data/ingest_la` | Image cache root. The directory is gitignored (only `.gitkeep` is committed). |
| `--no-keep` | off | Delete downloaded images after detection. The manifest is still written first (Pattern 5). |
| `--json-out PATH` | unset | Write the run summary JSON to this path in addition to printing it to stdout. |
| `--wipe-synthetic` | off | **Destructive.** `DELETE FROM segment_defects WHERE source = 'synthetic'` BEFORE writing real data. Aborts (exit 2) if zero detections will be written, unless `--force-wipe` is also passed. |
| `--force-wipe` | off | Allow `--wipe-synthetic` even when zero detections will be written. Use with care: deletes synthetic data with nothing to replace it. |
| `--no-recompute` | off | Skip the post-ingest `compute_scores.py --source all` subprocess. Default is auto-recompute on success. |
| `-v, --verbose` | off | DEBUG-level logging. |

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success. |
| 1 | Generic error (e.g. `MAPILLARY_ACCESS_TOKEN` missing, DB connect failed, unhandled exception). |
| 2 | Validation error (`--where` rejected, `--segment-ids` invalid, no targets matched, `--wipe-synthetic` with zero detections and no `--force-wipe`, no target mode passed). |
| 3 | Missing resource (e.g. a target segment id is not present in `road_segments`). |

## Trust model for --where

`--where` accepts an operator-supplied SQL predicate that is composed into
`SELECT id FROM road_segments WHERE <predicate>` via `psycopg2.sql.SQL`. The
operator already has DB credentials, so `--where` is **not** a security
boundary in the adversarial sense. Its job is to defend against typos and
copy-paste-from-the-internet accidents, and to bound runaway queries.

**Forbidden token classes** (the regex rejects any of these, case-insensitive):

- DDL/DML keywords: `DELETE`, `UPDATE`, `INSERT`, `DROP`, `ALTER`, `CREATE`,
  `GRANT`, `REVOKE`, `EXECUTE`, `TRUNCATE`, `COPY`, `EXEC`
- System catalogs: any token matching `pg_*` or `information_schema`
- Statement separators: `;`
- Comment markers: `--`, `/*`, `*/`

If your predicate trips one of these, you will get exit 2 with the offending
token printed.

**Bounds:**

- `max_segments = 1000` — the resolver fetches `max_segments + 1` rows and
  raises if it gets more, so a typo'd predicate that matches the entire
  table fails fast with a "matched > 1000 segments" error.
- `SET statement_timeout = '30s'` — applied before the predicate executes,
  so the worst case is a 30-second sequential scan.

If you genuinely need to ingest more than 1000 segments, chunk via
`LIMIT N OFFSET M` and run multiple `--where` invocations (each one is
idempotent, so re-runs are safe). Combine with `--no-recompute` and a
single `compute_scores.py --source all` at the end.

## Idempotency

Every Mapillary row carries `source = 'mapillary'` and a non-NULL
`source_mapillary_id` (the Mapillary image id). The UNIQUE INDEX
`uniq_defects_segment_source_severity` on
`(segment_id, source_mapillary_id, severity)` is the dedup key. The CLI's
`INSERT ... ON CONFLICT ... DO NOTHING` resolves any collision silently, so
**a second run on the same target inserts zero new rows by construction**.

The run summary surfaces the dedup math:

- `counters.rows_inserted` — new rows actually written this run
  (`cur.rowcount` after the INSERT).
- `counters.rows_skipped_idempotent` — `len(all_rows) - rows_inserted`, i.e.
  detections that were queued but rejected by the ON CONFLICT.

On a clean run, `rows_skipped_idempotent` is 0; on a re-run with the same
images, `rows_inserted` is 0 and `rows_skipped_idempotent` equals the count
from the first run.

## Provenance and licensing

Mapillary's open imagery is licensed under
[CC-BY-SA 4.0](https://help.mapillary.com/hc/en-us/articles/115001770409).
This pipeline records two attribution mechanisms automatically:

1. **Per-row** — `segment_defects.source_mapillary_id` carries the Mapillary
   image id for every detection row, and `segment_defects.source = 'mapillary'`
   tags the provenance bucket. JOINing back to the manifest gives full
   traceability without a per-row attribution column.
2. **Per-run** — `data/ingest_la/manifest-<unix_timestamp>.json` records,
   for every image used, its local cache path, source Mapillary image id,
   matched segment id, and snap radius. The manifest is written BEFORE any
   `--no-keep` unlinks (Pattern 5 caveat) so the manifest's SHA256 records
   are never orphaned.

**Do not redistribute bytes from `data/ingest_la/` without preserving these
attributions.** The directory is gitignored for exactly this reason — only
`.gitkeep` is committed. If you need to publish a derivative dataset (e.g.
to HuggingFace Datasets), use the `manifest-*.json` to construct a CC-BY-SA
attribution block in your dataset card.

## SC #4 ranking-comparison demo workflow

The Phase 3 SC #4 success criterion is "the choice of detection source
demonstrably changes route rankings." This is a 5-step operator demo. The
mechanical proof is in `backend/tests/test_integration.py::test_route_ranks_differ_by_source`;
the visual demo runs against a live stack:

**Step 1 — Ingest a high-IRI slice with the real detector:**

```bash
python scripts/ingest_mapillary.py \
    --where "iri_norm > 0.6 ORDER BY iri_norm DESC LIMIT 50" \
    --limit-per-segment 15
```

This populates `segment_defects` with `source = 'mapillary'` rows on the 50
roughest segments.

**Step 2 — Score from synthetic only and capture the route response:**

```bash
python scripts/compute_scores.py --source synthetic
curl -s -X POST http://localhost:8000/route \
    -H 'Content-Type: application/json' \
    -d '{
        "origin": {"lat": 34.0522, "lon": -118.2437},
        "destination": {"lat": 34.0689, "lon": -118.4452},
        "include_iri": true,
        "include_potholes": true,
        "weight_iri": 60,
        "weight_potholes": 40,
        "max_extra_minutes": 5
    }' | jq '.best_route.total_cost' > /tmp/synthetic-cost.txt
```

**Step 3 — Score from mapillary only and capture again:**

```bash
python scripts/compute_scores.py --source mapillary
curl -s -X POST http://localhost:8000/route \
    -H 'Content-Type: application/json' \
    -d '{
        "origin": {"lat": 34.0522, "lon": -118.2437},
        "destination": {"lat": 34.0689, "lon": -118.4452},
        "include_iri": true,
        "include_potholes": true,
        "weight_iri": 60,
        "weight_potholes": 40,
        "max_extra_minutes": 5
    }' | jq '.best_route.total_cost' > /tmp/mapillary-cost.txt
```

**Step 4 — Diff and archive:**

```bash
diff /tmp/synthetic-cost.txt /tmp/mapillary-cost.txt
```

A non-empty diff satisfies SC #4. Archive both files alongside the demo
recording so reviewers can verify the ranking changed.

If the diff is empty, either (a) the synthetic and mapillary detections
happen to produce identical scores along this route (uncommon but
possible — try a different origin/destination or a different `--where`
slice), or (b) you have zero `source = 'mapillary'` rows yet (see
"Common gotchas" below — Pitfall 7).

**Step 5 — Restore default scoring:**

```bash
python scripts/compute_scores.py --source all
```

The CLI's auto-recompute hook (after Step 1) calls `--source all`, so this
step is only needed if you ran `--source synthetic` or `--source mapillary`
manually for the demo.

## Phase 6 public-demo cutover

This is the canonical procedure for the public-demo deploy (Phase 6 will
grep this exact heading). The pipeline ships a forward-flag (`--wipe-synthetic`)
specifically for this cutover; do not invent ad-hoc procedures around it.

**Step 1 — Apply the migration to the cloud DB:**

```bash
psql "$DATABASE_URL_CLOUD" < db/migrations/002_mapillary_provenance.sql
```

The migration is idempotent; safe to re-apply on a DB that already has
the columns/index/constraint.

**Step 2 — Wipe synthetic and ingest real data atomically:**

```bash
python scripts/ingest_mapillary.py \
    --where "iri_norm > 0.5 ORDER BY iri_norm DESC LIMIT 200" \
    --limit-per-segment 15 \
    --wipe-synthetic
```

The wipe runs AFTER detect-and-aggregate but BEFORE the INSERT batch, so
`/segments` never observes a synthetic+mapillary union for the affected
segments. The wipe is gated on actually having detections to write —
without `--force-wipe`, a run that produces zero detections will exit 2
rather than wipe synthetic data with nothing to replace it.

The CLI auto-runs `compute_scores.py --source all` at the end (since
`--no-recompute` was not passed), so `segment_scores` is fresh when the
next request comes in.

**Step 3 — Invalidate the API cache:**

```bash
curl -X POST "$DEMO_API_URL/cache/clear"
```

`/segments` and `/route` use TTL-bounded `cachetools` caches (5 min and 2
min respectively). Without an explicit clear, the demo will continue to
serve stale synthetic data for up to 5 minutes after the wipe.

**Step 4 — Smoke a `/route` request:**

```bash
curl -s -X POST "$DEMO_API_URL/route" \
    -H 'Content-Type: application/json' \
    -d '{
        "origin": {"lat": 34.0522, "lon": -118.2437},
        "destination": {"lat": 34.0689, "lon": -118.4452},
        "include_iri": true,
        "include_potholes": true,
        "weight_iri": 60,
        "weight_potholes": 40,
        "max_extra_minutes": 5
    }' | jq '.best_route.pothole_score_total'
```

A `pothole_score_total > 0` along the route confirms real Mapillary
detections are flowing through scoring into routing.

**Important:** after cutover, `seed_data.py` MUST NOT be re-run on the
demo DB — it would re-introduce synthetic rows and break the "real data
only" demo claim. If you need to redeploy, treat the cloud DB as
state-bearing and apply only forward-flag migrations.

## Common gotchas

| Symptom | Cause | Fix |
|---------|-------|-----|
| Detections show up on a neighbor segment, not the one you targeted | Pitfall 5: D-04 attribute-to-closest is intentional. The image's GPS centroid landed nearer a parallel street. | Check `counters.matched_to_neighbor` in the run summary — non-zero is expected and correct. If it's the dominant outcome, narrow `--snap-meters`. |
| `compute_scores.py --source mapillary` shows zeros for all segments | Pitfall 7: no `source = 'mapillary'` rows in `segment_defects` yet. | Run an ingest first, or fall back to `--source all` for the demo. The script prints a warning to stderr in this case. |
| `/segments` still shows synthetic scores after `--wipe-synthetic` | Pitfall 4: `cachetools` TTL caches are stale (5 min for `/segments`, 2 min for `/route`). | `curl -X POST "$API_URL/cache/clear"` (admin endpoint). |
| Re-running ingest doubles row counts | Pitfall 1: `source_mapillary_id` is NULL on what should be Mapillary rows, so the UNIQUE index does not dedupe. | Verify migration 002 applied (`\d segment_defects` should show `source_mapillary_id TEXT`). If NULL appears on `source = 'mapillary'` rows, file a bug — the CLI should never write NULL there. |
| Migration apply errors with `constraint already exists` | Pitfall 8: Postgres 16 has no `ADD CONSTRAINT IF NOT EXISTS`. | The migration uses a DROP-then-ADD pattern, so this should not happen. If it does, your migration file is out of date — re-fetch from git. |
| `validate_bbox` rejects with "exceeds 0.01 deg^2" | Pitfall 2: a long arterial padded by 50 m produces an envelope larger than Mapillary's API allows. | The CLI auto-subdivides into 4 quadrants; check `counters.bbox_rejected` in the summary. If quadrants still fail, lower `--pad-meters` (e.g. 25). |
| Mapillary returns HTTP 429 | Rate limit (10k/min for image search). | The CLI has hand-rolled exponential backoff. Lower `--limit-per-segment`, split runs across time, or chunk `--where` with smaller `LIMIT` clauses. |
| `data/ingest_la/` shows up in `git status` | Pitfall 10: `.gitignore` not pulled, or the directory predates the gitignore entry. | `git rm --cached -r data/ingest_la/` (preserving local files) and re-pull. The directory is gitignored except for `.gitkeep`. |

## What this pipeline does NOT do (out of scope)

These are explicit deferrals from `.planning/phases/03-mapillary-ingestion-pipeline/03-CONTEXT.md`:

- **Per-class confidence calibration / per-class threshold tuning.** One
  global threshold is used; calibration is post-MVP.
- **Heading / orientation filter on Mapillary queries.** All compass
  headings are accepted. Defer until first runs show direction-related
  noise.
- **Auto tile-sweep mode (`--bbox`).** Segment-targeted is the locked
  default. A `--bbox` mode could be added later but is not in scope here.
- **Named target sets** (e.g. `--target downtown-arterials`). Operator
  can express the same via `--where`.
- **Migration of synthetic seed to a separate `segment_defects_synthetic`
  table.** The `source` column achieves the same separation with no schema
  sprawl.
- **Soft delete via `deleted_at` for per-run rollback.** `source_mapillary_id`
  already enables `DELETE WHERE source_mapillary_id = ...` for image-level
  rollback. Soft-delete adds complexity without proportional value.
- **Continuous CI gate on ingestion correctness.** Ingest is operator-
  triggered and human-verified. CI gating is a future phase.
- **Phase 4 auth gate.** `REQ-user-auth` is N/A here — this is a CLI, not
  an HTTP endpoint. Any auth surface is on the operator's DB credentials.

## References

Internal:

- [`.planning/phases/03-mapillary-ingestion-pipeline/03-CONTEXT.md`](../.planning/phases/03-mapillary-ingestion-pipeline/03-CONTEXT.md)
  — phase decisions (D-01..D-20)
- [`.planning/phases/03-mapillary-ingestion-pipeline/03-RESEARCH.md`](../.planning/phases/03-mapillary-ingestion-pipeline/03-RESEARCH.md)
  — patterns + 10 pitfalls (this runbook surfaces 8 of them)
- [`db/migrations/002_mapillary_provenance.sql`](../db/migrations/002_mapillary_provenance.sql)
  — schema migration applied above
- [`scripts/ingest_mapillary.py`](../scripts/ingest_mapillary.py) — the CLI
  itself; module docstring lists all 13 flags + 4 exit codes
- [`scripts/compute_scores.py`](../scripts/compute_scores.py) — the
  recompute helper auto-invoked at the end of every successful run
- [`docs/DETECTOR_EVAL.md`](DETECTOR_EVAL.md) — Phase 2 detector accuracy
  report (the YOLOv8 model used here)
- [`docs/FINETUNE.md`](FINETUNE.md) — fine-tune recipes for the YOLOv8 model

External:

- Mapillary developer API docs: <https://www.mapillary.com/developer/api-documentation>
- Mapillary CC-BY-SA license terms: <https://help.mapillary.com/hc/en-us/articles/115001770409>
- Mapillary developer dashboard (token issuance): <https://www.mapillary.com/dashboard/developers>
