---
status: complete
phase: 03-mapillary-ingestion-pipeline
source: [03-VERIFICATION.md]
started: 2026-04-25T16:00:00Z
updated: 2026-04-26T12:50:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Live Mapillary smoke run against real API + real DB
expected: |
  Run end-to-end against the real Mapillary v4 API + live DB to prove SC #1, SC #2, SC #3, SC #5 pass through the network boundary.

  Setup:
    docker compose down -v && docker compose up --build -d
    /tmp/rq-venv/bin/python scripts/seed_data.py   # OSMnx LA network + synthetic baseline

  Run (target the 10 roughest segments, 5 images each — per docs/MAPILLARY_INGEST.md SC #4 demo workflow):
    /tmp/rq-venv/bin/python scripts/ingest_mapillary.py \
      --where "iri_norm > 0.6 ORDER BY iri_norm DESC LIMIT 10" \
      --limit-per-segment 5 \
      --cache-root data/ingest_la/runA \
      --no-keep --no-recompute \
      --json-out data/ingest_la/runA/run_summary.json

  Then re-run with same `--where` (Mapillary API is non-deterministic across calls so a natural re-run rarely hits the same image IDs).
  Then explicitly probe the dedup primitive via SQL.

  Pass criteria:
    - First run: rows_inserted > 0, exit 0 (SC #1)
    - Idempotency proven via SQL: ON CONFLICT (segment_id, source_mapillary_id, severity) DO NOTHING skips duplicates; raw INSERT raises uniq_defects_segment_source_severity (SC #2)
    - GET /segments returns rows with non-zero pothole_score_total — confirmed via Test 2 (SC #3)
    - No MAPILLARY_ACCESS_TOKEN value in any manifest, run-summary, or committed file (SC #5)
result: pass
evidence: |
  Setup: docker compose down -v + up --build -d → backend healthy, migration 002 landed, seed_data.py inserted 209,856 segments + 125,632 synthetic defects + 209,856 scores.

  4 ingest runs executed (runA/B/C/D) against real Mapillary v4 API with live token:
    - runA: 21 images_found, 17 matched_to_neighbor, rows_inserted=2
    - runB: 24 images_found, 24 matched_to_neighbor, rows_inserted=1
    - runC: 15 images_found, 11 matched_to_neighbor, rows_inserted=2
    - runD: 13 images_found, 8 matched_to_neighbor, rows_inserted=3 (forced --segment-ids targeting)

  DB state after runs: 8 mapillary rows, 8 distinct source_mapillary_id values, no dupes.

  Mapillary API non-determinism observation: same --where query returned different image sets across runs (21 / 24 / 15 images), so natural re-run rarely repeats image IDs. This is a Mapillary API behavior, not a Phase 3 defect.

  Idempotency proven directly at SQL primitive (via psql in-container):
    INSERT ... ON CONFLICT (segment_id, source_mapillary_id, severity) DO NOTHING RETURNING id;
    → 0 rows (correct skip)
    INSERT ... (without ON CONFLICT)
    → ERROR: duplicate key value violates unique constraint "uniq_defects_segment_source_severity"
    DETAIL: Key (segment_id, source_mapillary_id, severity)=(114199, 1043271767824651, moderate) already exists.

  Token leakage: grep -rE "MLY\|26364393" across data/ingest_la/, scripts/, docs/, .planning/ → 0 matches. Manifests record only source_mapillary_id (image id), never the access token.

### 2. SC #4 demo workflow end-to-end via /route POST + diff
expected: |
  Prove /route returns DIFFERENT rankings for synthetic vs real-Mapillary data on the same bbox.
  Toggle `compute_scores.py --source synthetic` then `--source mapillary`, POST /route between, hash the geometry.
result: pass
evidence: |
  Origin: (34.055, -118.395), Destination: (34.058, -118.391). Same payload, only --source differs.

  Step 1 — synthetic only:
    compute_scores.py --source synthetic → 62,930 segments scored with pothole data
    POST /route best_route: 20 points, hash bc1b20e99eef
      avg_iri_norm=0.307, total_cost=45.640, total_moderate_score=0.4695

  Step 2 — mapillary only:
    POST /cache/clear  (bust /segments + /route TTL caches)
    compute_scores.py --source mapillary → 5 segments scored with pothole data
    POST /cache/clear
    POST /route best_route: 27 points, hash 8db3a03d97b6
      avg_iri_norm=0.249, total_cost=42.849, total_moderate_score=0.0

  Verdict: best_route geometry hashes differ; total_cost diff = 2.79; the mapillary-source best_route happens to match fastest_route (because only 5/209,856 segments carry real signal, so the optimizer converges on travel-time-only). This is the expected behavior at low real-data coverage and is documented in docs/MAPILLARY_INGEST.md ## SC #4 ranking-comparison demo workflow.

  When Phase 6 deploys with broader Mapillary coverage (10s of thousands of segments rather than 5), the synthetic-vs-mapillary route divergence will widen — but SC #4 itself is satisfied today: routes ARE different.

## Summary

total: 2
passed: 2
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

[none — both tests pass]

## Acknowledged Issues (advisory, not blocking SCs)

- **Latent: yolo_detector.py silently no-ops on missing ultralytics.** When `data_pipeline.yolo_detector.YOLOv8Detector` is imported successfully but the lazy `from ultralytics import YOLO` inside `_load_model()` raises `ModuleNotFoundError`, `detect()` swallows the exception and returns `[]`. Result: ingest runs to "success" with `rows_inserted: 0` instead of falling back to `StubDetector` like the factory's adapter-import path does. Pre-existing behavior (Phase 2), not introduced by Phase 3, but worth a follow-up plan in Phase 4+ to either log a louder warning or escalate to StubDetector at lazy-load time. Mitigation: operators get a per-image `[ERROR]` log line, and the `--json-out` summary makes `rows_inserted: 0` visible.
- **Documentation drift in 03-HUMAN-UAT.md original draft:** the initial UAT template I wrote referenced `--bbox` / `--max-images` / `--output` flags that don't exist on `scripts/ingest_mapillary.py`, and used `start`/`end` + `lat`/`lng` for `/route` (the API uses `origin`/`destination` + `lat`/`lon`). The official runbook `docs/MAPILLARY_INGEST.md` is correct on all of these — drift was only in the UAT scaffold. Fixed in this revision.
