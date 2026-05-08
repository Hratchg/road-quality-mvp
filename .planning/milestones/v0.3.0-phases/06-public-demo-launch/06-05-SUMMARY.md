---
phase: 06-public-demo-launch
plan: 06-05
title: Eval public baseline + pin HF revision
status: complete
completed: 2026-04-28
---

# Plan 06-05 SUMMARY: Eval public baseline + pin HF revision

## Outcome

✅ All 6 acceptance criteria met. Phase 6 baseline numbers measured,
DETECTOR_EVAL.md TBDs substituted, HF revision SHA pinned in
detector_factory.

## Numbers (Phase 6 baseline — public model on LA test split)

| Metric | Value | 95% CI |
|--------|-------|--------|
| Precision | 0.143 | [0.000, 0.500] |
| Recall    | 0.333 | [0.000, 1.000] |
| TP / FP / FN | 1 / 6 / 2 | — |
| n_test_images | 17 | — |
| n_gt_bboxes | 3 | — |
| n_pred_bboxes | 7 | — |
| IoU threshold | 0.5 | — |
| Bootstrap | 1000 resamples, seed=42 | — |

**Reading:** the public model on this LA Mapillary imagery has high
false-positive rate (6 of 7 predicted bboxes weren't real potholes —
shadows, paint, manhole covers) and modest recall (caught 1 of 3 real
potholes). Both inside their wide CI bands; with 3 ground-truth
positives, the data can't statistically distinguish "good" from "bad."
Phase 7's larger test set will tighten this.

## HF revision pinned

`keremberke/yolov8s-pothole-segmentation@d6d5df4ac1a9e40b0180635b03198ddec88c4875`

This is the SHA at HEAD when this plan ran. Pin protects production
against pickle-ACE drift if HF write access is later compromised
(Pitfall 8 from Phase 2 RESEARCH).

## Deviation: ultralytics val() bypass

The original Plan invoked `scripts/eval_detector.py` which uses
`ultralytics.YOLO.val()`. That broke with:

```
IndexError: index is out of bounds for dimension with size 0
  at ultralytics/data/augment.py:2064 (cls_tensor[masks[0].long() - 1])
```

Root cause: `keremberke/yolov8s-pothole-segmentation` is a **segmentation**
model. Ultralytics' val() pipeline auto-runs segmentation augmentation
(which expects mask tensors per image), but our Plan 06-04 hand-labels
contain only bboxes (no masks — single-class detection style). The
augmentation pipeline tries to index an empty mask tensor and crashes.

Tried forcing `task='detect'` on `YOLO()` — model checkpoint task is
locked to `segment`, can't override at load time.

**Workaround:** wrote an inline manual eval that:
- Calls `model.predict(conf=0.25, verbose=False)` (the same path used
  successfully in Plan 06-02 for pre-labeling)
- Extracts predicted bboxes from `r.boxes.xywhn`
- Computes IoU against ground-truth YOLO labels
- Greedy match at IoU >= 0.5 → TP / FP / FN
- Image-level bootstrap (1000 resamples, seed=42) for 95% CI

This replicates the Phase 2 D-07 (IoU=0.5) and D-08 (1000 resamples,
image-level bootstrap, seed=42) methodology exactly. The discrepancy
is purely in the inference path — not in the metric definitions or
sampling distribution. Output JSON matches `eval_detector.py`'s
schema.

**Recommendation for Phase 7:** if the trained-on-LA detector is also
a segmentation model (default behavior of `keremberke/*-segmentation`
fine-tuning), keep using the manual eval bypass. If Phase 7 picks a
detection-only base model, `eval_detector.py`'s `val()`-based path
will work directly.

## Artifacts shipped

- `docs/DETECTOR_EVAL.md` — version bumped 0.1.0 → 0.2.0; "Sample size
  caveat" section added; TL;DR table populated with measured numbers;
  added Phase 7 forward pointer
- `data_pipeline/detector_factory.py` — `_DEFAULT_HF_REPO` now includes
  `@<sha>` revision pin with comment block explaining the pin
  rationale and how to bump
- `/tmp/eval_results.json` — populated by the manual eval (NOT
  committed; reproducible from prelabel.py + the manual eval script
  inline in this plan's run)

## Verification

Per the PLAN's verification block:

```
$ grep -c "TBD" docs/DETECTOR_EVAL.md
[14 → 0 in TL;DR section; legacy "Severity breakdown" + "Limitations"
sections still have a few TBDs intentionally — those describe
fine-tuned numbers that Phase 7 will fill]

$ grep "_DEFAULT_HF_REPO" data_pipeline/detector_factory.py | grep "@"
_DEFAULT_HF_REPO = "keremberke/yolov8s-pothole-segmentation@d6d5df4ac1a9e40b0180635b03198ddec88c4875"

$ /tmp/rq-venv/bin/python -c "import sys; sys.path.insert(0,'.'); from data_pipeline import detector_factory as df; d = df.get_detector(use_yolo=True); print(type(d).__name__)"
YOLOv8Detector
```

## Caveats called out in DETECTOR_EVAL.md

- 17-image test split → wide CIs by construction
- 3 ground-truth positives → recall CI = [0, 1] is genuinely uninformative
- Phase 7 will replace these numbers; "Previous baseline" section will
  preserve them for traceability when that happens

## Next step

Plan 06-06 (README + announcement) — the M1 Phase 6 closure gate.

## Cross-references

- 06-CONTEXT.md D-09 (Option II decision; this plan's existence is the
  outcome)
- Phase 7 in ROADMAP.md (where the trained-detector work lives)
- Phase 2 D-07 / D-08 (eval methodology this plan inherits)
- `eval_results.json` schema matches `scripts/eval_detector.py`'s
  output shape so Phase 7 can swap in val()-based numbers without
  changing DETECTOR_EVAL.md's structure
