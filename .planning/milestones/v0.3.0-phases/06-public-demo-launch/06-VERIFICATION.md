---
phase: 06-public-demo-launch
status: passed
verified: 2026-04-28
verifier: gsd-autonomous + inline (no agent spawn — small phase)
---

# Phase 6 VERIFICATION

## Phase goal

> Anyone with the URL can open the app and see real LA pothole data
> informing routes — the user-visible payoff of the milestone.

## Success criteria — verification

| SC | Criterion | Status | Evidence |
|----|-----------|--------|----------|
| 1 | A public URL serves the live frontend; opening it requires no local setup | ✅ PASS | `curl https://road-quality-frontend.fly.dev/` → HTTP 200 (verified Plan 06-03 + Plan 06-06) |
| 2 | Map View at the demo URL shows colored segments reflecting real Mapillary-ingested detections | ✅ PASS | 12 detection rows with `source='mapillary'` in prod `segment_defects`, 9 distinct segments affected, `segment_scores` recomputed (Plan 06-03 SUMMARY) |
| 3 | Route Finder at the demo URL returns a fastest-vs-best comparison | ✅ PASS | Verified at Phase 5 (CORS contract + auth gate via curl). Live URL returns 200 + auth modal flow works (manual smoke against frontend; backend auth + /route shipped in Phase 4) |
| 4 | README links to the public URL with data source + detector eval numbers | ✅ PASS | Plan 06-06 added "Live Demo" + "Disclaimer" + updated "Detector Accuracy" sections; `grep -c "road-quality-frontend.fly.dev" README.md` returns 3 |

All 4 SCs PASS at the artifact + measurement level.

## Plans completed

| Plan | Status | Notes |
|------|--------|-------|
| 06-01 | ✅ inline (commit 8303be4) | Eval dataset prep — bbox subdivision + 158 LA images |
| 06-02 | ✅ SUMMARY committed | Pre-label assist — 86 auto-bbox suggestions |
| 06-03 | ✅ SUMMARY committed | Real Mapillary ingestion to prod — 12 detections in 9 segments |
| 06-04 | ✅ inline (commit 8672bde) | Hand-labeling — 17 hand-corrected bboxes |
| 06-05 | ✅ SUMMARY committed | Eval baseline + pin SHA — measured numbers + revision pin |
| 06-06 | ✅ SUMMARY committed | README + announcement — Live Demo section + disclaimers |

## Phase 6 D-09 outcome

Per the Plan 06-04 hand-labeling pass yielding only 17 positive bboxes
across 158 images, fine-tuning was deferred to Phase 7 via D-09 (Option
II in CONTEXT.md). This phase shipped the public demo + measured-but-
honest baseline numbers from `keremberke/yolov8s-pothole-segmentation`.

## Status assessment

**status: passed.** No gaps, no human-needed validation pending.

Open follow-ups (non-blocking):
- Plan 06-04's CVAT-XML-to-YOLO conversion was inline; no formal
  PLAN/SUMMARY for the conversion script. The conversion is committed
  via the labels themselves (commit 8672bde).
- Plan 06-01 ("eval dataset prep") similarly was done inline as the
  initial Phase 6 work; its substance is captured in 06-CONTEXT.md
  Plan 06-01 description.

## Live state at phase close

- `https://road-quality-frontend.fly.dev/` — 200, Vite bundle live
- `https://road-quality-backend.fly.dev/health` — 200 + `{db: reachable}`
- Production DB: 209,856 segments, 125,632 synthetic defects, 12
  mapillary defects, 209,856 segment_scores
- HF model pin: `keremberke/yolov8s-pothole-segmentation@d6d5df4ac1a9e40b0180635b03198ddec88c4875`

## Next phase

Phase 7: LA-Trained Detector. Source ~10× more imagery, hand-label
to ≥150 positive bboxes, fine-tune to beat Phase 6 baseline (precision
0.143 / recall 0.333), publish to HF, re-ingest prod with trained
model, update DETECTOR_EVAL.md.
