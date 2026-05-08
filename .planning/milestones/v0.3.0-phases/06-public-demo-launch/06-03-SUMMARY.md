---
phase: 06-public-demo-launch
plan: 06-03
title: Real Mapillary ingestion against prod DB
status: complete
completed: 2026-04-28
---

# Plan 06-03 SUMMARY: Real Mapillary ingestion against prod DB

## Outcome

✅ All 6 acceptance criteria met. Phase 6 SC #2 ("Map View shows real
Mapillary-ingested detections") is now literally true on production —
12 real Mapillary-derived pothole detection rows live in
`segment_defects` with `source='mapillary'`, affecting 9 segments
in DTLA.

## Run details

| Counter | Value |
|---------|-------|
| segments_processed (LIMIT 30 from WHERE clause) | 30 |
| images_found via Mapillary | 56 |
| matched_to_neighbor (within snap radius) | 46 |
| dropped_outside_snap | 3 |
| rows_inserted | 12 |
| rows_skipped_idempotent | 0 |
| recompute_invoked | true (auto) |

WHERE predicate used: `ST_Intersects(geom, ST_MakeEnvelope(-118.258, 34.043, -118.248, 34.053, 4326)) ORDER BY iri_norm DESC LIMIT 30`

That picks the 30 worst-IRI segments inside the DTLA bbox — i.e., the
segments most likely to actually have potholes — for a high-signal
first run. Detector used: the public default
`keremberke/yolov8s-pothole-segmentation` (per
`data_pipeline/detector_factory._DEFAULT_HF_REPO`).

## Verification

```
$ SELECT source, count(*) FROM segment_defects GROUP BY source;
   source    |  count
-------------+--------
   mapillary |     12
   synthetic | 125632

$ SELECT count(distinct segment_id) FROM segment_defects WHERE source='mapillary';
9

$ SELECT min(pothole_score_total), max(pothole_score_total), avg(pothole_score_total)
  FROM segment_scores
  WHERE segment_id IN (SELECT DISTINCT segment_id FROM segment_defects WHERE source='mapillary');
  min   |  max   |  avg
--------+--------+-------
   0.23 |  15.92 |  3.32

$ curl https://road-quality-frontend.fly.dev/
HTTP 200

$ curl https://road-quality-backend.fly.dev/health
HTTP 200 + {"status":"ok","db":"reachable"}
```

## Phase 5 anti-pattern adherence

The Phase 5 BLOCKING anti-pattern says "never run `pgr_createTopology`
(or any long DDL) through `flyctl proxy`". This plan used `flyctl
proxy 15432:5432` for `ingest_mapillary.py`'s INSERT traffic. INSERTs
are short queries (<1s each), not multi-minute DDL — proxy is
appropriate. No long-running query exposure to wireguard timeout.
Verified by zero connection errors in the 30-segment run (~10s end
to end).

## Caveats

- 12 detections from 30 segments is a small absolute count — the public
  model is conservative on this imagery. Plan 06-06 will re-run
  ingestion after fine-tune training; expect significantly more
  detections (the trained-on-LA model will pick up the visual style of
  these specific Mapillary captures).
- `--wipe-synthetic` was NOT passed. Synthetic + mapillary detections
  coexist in `segment_defects`. The cutover to mapillary-only happens
  in Plan 06-06 epilogue (re-run with `--wipe-synthetic --force-wipe`).
- The 30-segment WHERE filter was deliberately small for first-run
  validation. Future runs should use a wider bbox or larger LIMIT
  to populate more of the network. This is configuration, not a
  code change.

## Artifacts shipped

No code or doc changes — this plan was pure data ingestion against
a deployed system. The committed change is the SUMMARY itself
documenting the run.

## Next steps

- Plan 06-04: hand-labeling (USER GATE) using auto-labels from 06-02
- After 06-04: Plan 06-05 train detector
- After 06-05: Plan 06-06 eval + HF publish + revision pin + RE-RUN
  this plan (06-03 epilogue) with `--wipe-synthetic` and the trained
  detector

## Cross-references

- 06-CONTEXT.md D-06 (real Mapillary ingestion)
- Phase 5 LESSONS-LEARNED defect #10 (proxy anti-pattern; this plan
  validates that INSERT traffic through proxy is fine, only long DDL
  is the problem)
- docs/MAPILLARY_INGEST.md (operator runbook for the script)
