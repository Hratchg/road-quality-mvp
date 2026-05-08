# Phase 7: LA-Trained Detector — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-28
**Phase:** 07-la-trained-detector
**Areas discussed:** Imagery sourcing, Compute / training environment, "Beat baseline" success criterion + contingency, Production re-ingestion scope

---

## Imagery Sourcing

### Q1: What's the primary sourcing strategy for the ~10× dataset?

| Option | Description | Selected |
|--------|-------------|----------|
| Mapillary, wider/smarter LA coverage | Stay Mapillary, expand beyond 3 zones / 12 sub-tiles. Either widen geographic spread or target high-IRI segments. Tests both hypotheses head-on; preserves "LA Mapillary" purity. | ✓ |
| Mapillary + RDD2020 hybrid | Few hundred new LA Mapillary for test split; bulk of training from RDD2020 (~10k pre-labeled). Bigger train set without 10× labeling burden. Risk: domain shift. | |
| Roboflow Universe pothole datasets | Find a curated CC-licensed pre-labeled dataset on Roboflow. Skip most hand-labeling. Risk: dataset quality varies. | |
| IRI-targeted Mapillary pull | Query DB for top-N segments by `iri_norm`; pull Mapillary by location. Highest signal-to-noise. Tests hypothesis A directly. | |

**User's choice:** Mapillary, wider/smarter LA coverage.
**Notes:** Preserves LA-specificity claim. Tests both Phase 6 D-09 hypotheses (public model FP rate vs. Mapillary 2D-shot inherent sparsity) by scaling Mapillary itself.

---

### Q2: How do we scale the Mapillary pull?

| Option | Description | Selected |
|--------|-------------|----------|
| More zones (geographic spread) | 8-12 zones (South LA, East LA, Mid-City, Westside, Valley) keeping the 0.005-deg sub-tile grid. | |
| Same 3 zones, denser sampling | Increase `--count` from 25 to ~150 per sub-tile. Tests "is the issue density or geography?" | |
| Both: more zones AND denser | 8-12 zones × ~50-100 images per sub-tile. Largest dataset; biggest labeling burden. Highest chance of clearing ≥150-bbox bar. | ✓ |
| IRI-targeted hybrid | Half spread, half IRI-targeted. | |

**User's choice:** Both — more zones AND denser.
**Notes:** Maximum surface area; will need careful labeling pacing.

---

### Q3: What's the target candidate-image count to label?

| Option | Description | Selected |
|--------|-------------|----------|
| ~1000 images | At Phase 6's 10.7% rate → ~107 positives (below ≥150 bar). | |
| ~1500 images | ~160 positives at Phase 6 rate; comfortable margin. ~6-8 hr labeling with pre-label assist. | ✓ |
| ~2500 images | Conservative; ~10-15 hr labeling burden. | |
| Adaptive: pull in waves | Pull 500, pre-label, count expected positives, pull more if needed. | |

**User's choice:** ~1500 images.
**Notes:** Mid-target balancing labeling burden against SC #1's ≥150-positive bar.

---

### Q4: How are the new zones picked?

| Option | Description | Selected |
|--------|-------------|----------|
| Geographic spread only | Zones to cover north/south/east/west LA evenly. Maximizes generalization claim. | |
| Biased toward residential streets | Older pavement, more potholes per mile. Risk: model overfits to residential. | |
| Mix: spread + 1-2 known-bad-pavement zones | 8-10 spread + 1-2 known-bad zones. Hedges spread vs positive rate. | ✓ |
| Claude picks zones | Defer to Claude. | |

**User's choice:** Mix — spread + 1-2 known-bad-pavement zones.
**Notes:** Specifically called out Mid-City east of La Brea, Boyle Heights, parts of South LA per general LA knowledge.

---

### Q5: Any image-filter criteria during the pull?

| Option | Description | Selected |
|--------|-------------|----------|
| Mapillary defaults only | No extra filtering. | |
| Filter blurred/low-quality at fetch | Use `quality_score` to drop bottom-quartile. | |
| Filter to recent captures (last 3 years) | Pothole surface conditions change; recency improves ground-truth currency. | |
| Claude picks filtering | Defer to planner; recommended quality_score quartile + recency together. | ✓ |

**User's choice:** Claude picks filtering.
**Notes:** Recommended baseline = drop bottom-quartile by `quality_score` + filter to `captured_at >= 2023`. Planner confirms during research.

---

## Compute / Training Environment

### Q6: Where does the fine-tune run?

| Option | Description | Selected |
|--------|-------------|----------|
| Colab T4 (free) | Recipe B; ~2-3 hr. Free. Risk: 12-hr session limit, may disconnect. | |
| EC2 g5.xlarge (~$1-2 total) | Recipe C; 30-50 min on A10G. ~$0.20/hr. Stable session. | ✓ |
| Apple Silicon MPS | Pitfall 1 — was broken in Phase 2 era. Free if it works. | |
| Stay laptop CPU | Cap at ~1000 images / 30 epochs. Most predictable, slowest iteration. | |

**User's choice:** EC2 g5.xlarge.
**Notes:** Stable session matters with the 2-3 iterations budgeted in D-08.

---

### Q7: How many training runs are budgeted before declaring "done"?

| Option | Description | Selected |
|--------|-------------|----------|
| 1 run, ship whatever | Fastest. No fallback if first run underperforms. | |
| 2-3 runs with hyperparameter sweep | Defaults first, then vary lr / batch / epochs / aug if needed. | |
| Iterate until SC #2 met (open-ended) | Calendar risk: weeks. | |
| Claude picks iteration budget | Defer to planner; recommended 2-3 runs. | ✓ |

**User's choice:** Claude picks.
**Notes:** Recommended 2-3 runs; ties to D-13 hybrid contingency.

---

## "Beat Baseline" Success Criterion

### Q8: How is "trained beats baseline" measured?

| Option | Description | Selected |
|--------|-------------|----------|
| Re-eval public baseline on the NEW test split, then compare | Apples-to-apples. Most defensible. | |
| Compare trained-on-new-test vs baseline-on-old-test | Easier (no baseline re-run); technically unfair. | |
| Use mAP@0.5 instead of P/R | Tighter CIs by construction. | |
| All of the above | Re-eval baseline + report mAP alongside P/R. Strictest closure. Win = non-overlapping CI on at least one of {P, R, mAP@0.5}. | ✓ |

**User's choice:** All of the above.
**Notes:** Strictest standard; both numbers go in DETECTOR_EVAL.md.

---

### Q9: Absolute performance floors?

| Option | Description | Selected |
|--------|-------------|----------|
| No absolute floors, just beat baseline | Statistical improvement is enough. | |
| Floor: P ≥ 0.5 AND R ≥ 0.5 | Both above coin-flip. Risk: if achievable only by sacrificing one for the other, phase stalls. | |
| Floor: just P ≥ 0.5 (precision-only) | Demo cares more about no fake potholes than catching every pothole. | |
| Claude picks floor | Defer; recommended precision-only floor. | ✓ |

**User's choice:** Claude picks.
**Notes:** Recommended precision-only floor (P ≥ 0.5). FP rate bounds the demo's correctness story; recall is secondary.

---

### Q10: Contingency if trained model can't beat baseline?

| Option | Description | Selected |
|--------|-------------|----------|
| Document negative result + close phase | Honest report; production stays on public baseline. | |
| Iterate (more data / different base / different recipe) | Calendar risk: weeks of unbounded iteration. | |
| Ship trained anyway (even if worse) | Worst outcome — explicitly rejected in framing. | |
| Hybrid: iterate once, then close | If first run ≤ baseline, do one targeted iteration; if second also ≤ baseline, close as documented negative result. | ✓ |

**User's choice:** Hybrid iterate-once-then-close.
**Notes:** Hard cap on calendar.

---

## Production Re-Ingestion (re-posed after synthetic-data clarification)

### Background clarification mid-discussion

The user paused this area to ask what `--wipe-synthetic` actually does and how synthetic data is calculated. Investigation showed:

- `--wipe-synthetic` runs `DELETE FROM segment_defects WHERE source = 'synthetic'` (hard-coded WHERE per T-03-18)
- `segment_defects.source` has CHECK constraint to `('synthetic', 'mapillary')` — no other values
- No `--wipe-mapillary` flag exists today
- `scripts/seed_data.py:98-112` generates synthetic defects with `p=0.3` per segment, uncorrelated with that segment's (also synthetic) IRI value

This re-framed the wipe options: keeping synthetic isn't preserving "approximate" data, it's preserving random visual noise. Worst-IRI segment ranking is also random, not signal-driven.

---

### Q11: What gets wiped during re-ingestion?

| Option | Description | Selected |
|--------|-------------|----------|
| Wipe ALL synthetic + ALL mapillary, ship real-data-only | Honest closure. ~80% of LA segments render no-defect outside trained zones. | ✓ |
| Wipe ONLY mapillary, keep synthetic random noise as visual filler | Demo "looks populated" but colors outside trained zones are seeded random numbers. | |
| Wipe both inside training-zone bboxes (geographic carve-out) | Hybrid; complex DELETE WHERE. | |
| Wipe only mapillary; add frontend disclosure | Operator-friendly; honest via disclosure. | |

**User's choice:** Wipe ALL synthetic + ALL mapillary.
**Notes:** Real-data-only is the honest closure state. Trade-off: routing diff outside trained zones collapses; called out in README disclaimer per D-14.

---

### Q12: What's the ingestion coverage scope?

| Option | Description | Selected |
|--------|-------------|----------|
| Cover all training zones (8-10 + 1-2 bad-pavement) | Distribution-aligned with eval numbers. | |
| Wider: training zones + adjacent expansions | Wider visible coverage; out-of-distribution inference outside training tiles. | ✓ |
| Same as Phase 6: top-30 DTLA only | Reject — random IRI ranking is meaningless. | |
| Claude picks coverage | Defer. | |

**User's choice:** Wider — training zones + adjacent expansions.
**Notes:** Wider demo coverage; eval numbers honest only on training-zone tiles per D-16 caveat in DETECTOR_EVAL.md.

---

### Q13: Is re-ingestion gated on the trained model beating baseline?

| Option | Description | Selected |
|--------|-------------|----------|
| Re-ingest with whichever model wins on the new test split | If trained ≥ baseline: swap. If trained < baseline: keep public-model rows, still publish re-eval'd numbers. | |
| Always re-ingest with trained, even if it underperforms | "LA-trained" is more honest production claim regardless of small-N test outcome. | ✓ |
| Hard gate: only re-ingest if SC #2 passes | Production stays as-is on negative branch. | |

**User's choice:** Always re-ingest with trained.
**Notes:** Philosophical anchor: trained on LA imagery > trained on global imagery for production claim, regardless of eval delta.

---

## Claude's Discretion

- Detection-only vs segmentation-base model choice (planner picks based on whether `val()` integration warrants base-model swap, per Phase 6 Plan 06-05's incompatibility)
- Pre-labeling workflow (recommended: reuse `scripts/prelabel.py` baseline; swap to stronger model if FP rate at scale is unworkable)
- AWS region / instance lifecycle / S3 bucket / dataset transit on EC2
- HF token handling on the training instance
- Mapillary `--count` per sub-tile (~30-40 to hit ~1500 across 12-15 sub-tiles)
- Augmentation recipe (YOLOv8 defaults expected fine at this scale)
- Whether to publish labeled dataset to HF Datasets (deferred unless trivially cheap during model upload)

## Deferred Ideas

- Multi-city support (M2)
- RDD2020 / Roboflow Universe supplementation (preserves LA-specificity)
- Iterating beyond 2 trained runs (M2)
- Apple Silicon MPS re-test (M2 once newer ultralytics validated)
- Continuous eval / CI gate on detector accuracy (Phase 2 + 7 both defer)
- Confidence calibration / temperature scaling (Phase 2 + 7 both defer)
- Frontend trained-vs-uncovered-zone disclosure UI (D-14 makes moot)
- HF Datasets publish of labeled dataset (M2)
- Inter-rater agreement for hand labels (single-operator continues)
- Adjacent-expansion as out-of-distribution: train on expanded distribution OR cap prod ingest to training-zones only (future phase)
