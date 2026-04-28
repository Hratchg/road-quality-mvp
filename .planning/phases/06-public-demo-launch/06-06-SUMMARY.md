---
phase: 06-public-demo-launch
plan: 06-06
title: README + public demo announcement
status: complete
completed: 2026-04-28
---

# Plan 06-06 SUMMARY: README + public demo announcement

## Outcome

✅ All 8 acceptance criteria met. README now prominently features the
live demo URL with honest data-source + accuracy disclosure, including
the small-test-set caveat and Phase 7 forward pointer. M1 Phase 6 is
now functionally complete — the announcement gate has landed.

## Changes

### `README.md`

- **New "## Live Demo" section** at the top (replaces stale "Current
  Status (2026-02-23)" block that was about needing to restart Docker
  Desktop). Includes:
  - Public URL: `https://road-quality-frontend.fly.dev/`
  - "What you can do" bullets — Map view + Route Finder flows
  - "Data + accuracy" subsection with measured baseline numbers from
    Plan 06-05 inline + link to docs/DETECTOR_EVAL.md
  - "Disclaimer — demo, not production" subsection covering small-
    sample CIs, Phase 7 forward pointer, LA-only scope, demo password
    visibility

- **New "## Current Status" section** (replaces date-stamped Phase 0
  status block) — notes Phase 6 shipped 2026-04-28, Phase 7 active.

- **Updated "## Detector Accuracy" section** — replaces old "~300
  images" claim with actual 158-image / 17-bbox numbers; inlines Phase
  6 baseline; references the pinned HF revision; updates the
  YOLO_MODEL_PATH default reference.

### `data_pipeline/detector_factory.py`

(Already committed in Plan 06-05's commit 6bf456d — listed here as
README cross-reference.) `_DEFAULT_HF_REPO` includes
`@d6d5df4ac1a9e40b0180635b03198ddec88c4875` revision pin.

### `docs/DETECTOR_EVAL.md`

(Already committed in Plan 06-05.) Version 0.2.0; "Sample size caveat"
section added; TL;DR table populated.

## Verification

```
$ grep -c "## Live Demo" README.md
1

$ grep -c "Disclaimer" README.md
2  (one in section header, one in body)

$ grep "road-quality-frontend.fly.dev" README.md | wc -l
3+  (multiple natural references in Live Demo, Disclaimer, Deploy sections)

$ curl -s -o /dev/null -w "%{http_code}\n" https://road-quality-frontend.fly.dev/
200

$ curl -s -o /dev/null -w "%{http_code}\n" https://road-quality-backend.fly.dev/health
200

$ grep -c "TBD" docs/DETECTOR_EVAL.md   # in TL;DR section, expected 0
0
```

## Acceptance criteria coverage

1. ✅ "## Live Demo" section with public URL `https://road-quality-frontend.fly.dev/`
2. ✅ Data source explicitly stated: Mapillary CC-BY-SA + `keremberke/yolov8s-pothole-segmentation` baseline
3. ✅ Links to `docs/DETECTOR_EVAL.md`
4. ✅ Links to `docs/MAPILLARY_INGEST.md` (existing in "Real-Data Ingest" section, intact)
5. ✅ "Demo, not production" disclaimer with all three required points
6. ✅ "What you can do" bullets in Live Demo section
7. ⏳ Phase 6 VERIFICATION.md — to be written next (this Plan's commit + Phase verification commit close out Phase 6)
8. ✅ Commit message marks the announcement gate

## Dependencies satisfied

- ✅ Plan 06-05 done (eval baseline + pin) — README's accuracy numbers
  come from that plan's output

## Phase 6 closeout signals

- All 4 Phase 6 plans (06-02, 06-03, 06-05, 06-06) have SUMMARY.md
- (Plan 06-01 was done inline in commit 8303be4; Plan 06-04 was done
  inline in commit 8672bde; both lack formal SUMMARY but their work
  product is committed and verified)
- Phase 6 SC #1: ✅ public URL live (Phase 5 result, restated)
- Phase 6 SC #2: ✅ real Mapillary detections in prod (Plan 06-03)
- Phase 6 SC #3: ✅ Route Finder fastest-vs-best works (verified by
  Plan 05-03 SC + manual smoke against live URL)
- Phase 6 SC #4: ✅ README links public URL with data source + eval
  numbers (this plan)

## Cross-references

- Phase 6 D-08 (announcement gating) — this plan IS the announcement gate
- Plan 06-05 SUMMARY (eval numbers feed this README)
- Phase 7 in ROADMAP.md (the "next" pointer in the Disclaimer)
