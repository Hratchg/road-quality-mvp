---
status: partial
phase: 03-mapillary-ingestion-pipeline
source: [03-VERIFICATION.md]
started: 2026-04-25T16:00:00Z
updated: 2026-04-25T16:00:00Z
---

## Current Test

[awaiting human testing — both items require live MAPILLARY_ACCESS_TOKEN + running Docker stack]

## Tests

### 1. Live Mapillary smoke run against real API + real DB
expected: |
  Run end-to-end against the real Mapillary v4 API and the live `road_quality` DB to prove SC #1, SC #2, SC #3 pass through the network boundary.

  Setup:
    docker compose down -v && docker compose up --build -d
    docker compose exec backend pytest backend/tests/test_migration_002.py -v -m integration
  Run:
    export MAPILLARY_ACCESS_TOKEN=...real token...
    docker compose exec backend python scripts/ingest_mapillary.py \
      --bbox -118.40,34.05,-118.39,34.06 \
      --max-images 25 \
      --output data/ingest_la/runA \
      --no-keep
  Then re-run the same command (idempotent re-run check).
  Then run:
    docker compose exec backend curl -s http://localhost:8000/segments | jq 'length'

  Pass criteria:
    - First run: manifest written to data/ingest_la/runA/manifest.json with `inserted > 0`, exit 0
    - Re-run on same bbox: `inserted == 0`, `rows_skipped_idempotent == previous inserted`, exit 0 (SC #2)
    - GET /segments returns rows with non-zero `pothole_score_total` from `source = 'mapillary'` (SC #3)
    - No `MAPILLARY_ACCESS_TOKEN` value appears in stdout, stderr, or manifest.json (SC #5)
result: [pending]

### 2. SC #4 demo workflow end-to-end via /route POST + diff
expected: |
  Prove `/route` returns DIFFERENT rankings for synthetic vs real data on the same bbox — the headline demo for the milestone.

  Prerequisites: complete Test 1 first (real Mapillary data must be in the DB).

  Run:
    # Re-score from synthetic only
    docker compose exec backend python scripts/compute_scores.py --source synthetic
    curl -s -X POST http://localhost:8000/route \
      -H 'Content-Type: application/json' \
      -d '{"start":{"lat":34.055,"lng":-118.395},"end":{"lat":34.058,"lng":-118.391}}' \
      | jq '.segment_ids' > /tmp/route_synthetic.json

    # Re-score from real Mapillary only
    docker compose exec backend python scripts/compute_scores.py --source mapillary
    curl -s -X POST http://localhost:8000/route \
      -H 'Content-Type: application/json' \
      -d '{"start":{"lat":34.055,"lng":-118.395},"end":{"lat":34.058,"lng":-118.391}}' \
      | jq '.segment_ids' > /tmp/route_mapillary.json

    diff /tmp/route_synthetic.json /tmp/route_mapillary.json

  Pass criteria:
    - The two .json files DIFFER (segment_ids list ordering or membership changes)
    - If they don't differ on this bbox, try one or two other bboxes documented in docs/MAPILLARY_INGEST.md ## SC #4 ranking-comparison demo workflow
    - Capture the diff for the demo recording
result: [pending]

## Summary

total: 2
passed: 0
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
