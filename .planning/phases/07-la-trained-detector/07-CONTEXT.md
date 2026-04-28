# Phase 7: LA-Trained Detector — Context

**Gathered:** 2026-04-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Source ~10× more LA Mapillary imagery, hand-label to ≥150 positive bboxes (vs 17 today), fine-tune YOLOv8 on the new dataset, *measurably* beat the Phase 6 public-baseline (P=0.143, R=0.333), publish the trained model to HuggingFace at `Hratchg/road-quality-la-yolov8@<sha>`, re-ingest production with the trained detector, and replace the baseline numbers in `docs/DETECTOR_EVAL.md`.

**In scope:**
1. Imagery acquisition: ~1500 candidate Mapillary images from 8-10 LA spread zones + 1-2 known-bad-pavement zones
2. Pre-labeling assist + hand-correction in CVAT to clear ≥150 positive bboxes (≥30 in test split)
3. Fine-tune on EC2 g5.xlarge (Recipe C) with 2-3 hyperparameter iterations
4. Re-evaluate the public baseline on the new test split (apples-to-apples) + report mAP@0.5 alongside P/R
5. HF publish at `Hratchg/road-quality-la-yolov8` with pinned revision SHA
6. Update `_DEFAULT_HF_REPO` in `data_pipeline/detector_factory.py`
7. Add `--wipe-mapillary` flag to `scripts/ingest_mapillary.py`
8. Re-ingest production: wipe ALL synthetic + ALL mapillary, ingest training-zone + adjacent-expansion bboxes with the trained model
9. Update `docs/DETECTOR_EVAL.md` (preserve Phase 6 baseline as "Previous baseline" section) and README

**Out of scope:**
- Multi-city support (M2)
- RDD2020 / Roboflow Universe dataset supplementation (rejected — preserves LA-specificity claim)
- Detector accuracy improvements beyond Phase 7's one-trained-iteration milestone (M2)
- Continuous eval / CI gate on detector accuracy (Phase 2 deferred; still deferred)
- Frontend UI changes (no UI hint per ROADMAP)
- Confidence calibration / temperature scaling

</domain>

<decisions>
## Implementation Decisions

### Imagery Sourcing

- **D-01:** **Source = Mapillary, LA-only.** No RDD2020, no Roboflow Universe, no IRI-driven targeting. Preserves the "LA-specific detector" claim that's the whole point of Phase 7.
- **D-02:** **Coverage strategy = both more zones AND denser sampling.** Expand from Phase 6's 3 zones / 12 sub-tiles to 8-10 spread zones + 1-2 known-bad-pavement zones. Each zone keeps the 0.005-deg sub-tile grid that fixed the Mapillary 500-error issue (Phase 6 D-03).
- **D-03:** **Target candidate count = ~1500 images.** At Phase 6's ~10.7% positive rate, this yields ~160 positives — just past the ≥150 SC #1 bar. Comfortable margin if hit rate holds.
- **D-04:** **Zone selection = spread + known-bad-pavement.** 8-10 zones for geographic spread (north/south/east/west LA coverage) + 1-2 zones explicitly chosen for known bad pavement (Mid-City east of La Brea, Boyle Heights, parts of South LA per general LA knowledge). Hedges spread vs positive rate.
- **D-05:** **Image filtering = Claude's discretion.** Recommended baseline: drop bottom-quartile by Mapillary `quality_score` (if exposed in v4 search API) AND filter to `captured_at >= 2023` (3-year recency window). Both are cheap API filters; planner confirms during research.
- **D-06:** **Phase 6's 158 images and 17 hand-labels can be carried forward OR fully replaced.** Planner picks based on whether the new bbox set overlaps the Phase 6 zones. If not, the existing labels are sunk cost — preserved as `data/eval_la_phase6/` for traceability but not re-used in training.

### Compute / Training Environment

- **D-07:** **Training compute = EC2 g5.xlarge (Recipe C).** Phase 6 D-04's laptop CPU default does not scale to ~1500 images at 50 epochs (~25-30 hr CPU vs ~30-50 min on A10G). Operator picks AWS region, instance lifecycle, and dataset transit (S3 vs scp). ~$1-2 total estimated cost for full phase work including iterations.
- **D-08:** **Iteration budget = Claude's discretion.** Recommended: 2-3 training runs. First run = ultralytics defaults; if it underperforms baseline, vary lr / batch / epochs / augmentation. Cap at 3 to bound calendar. Cleanly hand-off to D-12 hybrid iterate-once-then-close contingency.
- **D-09:** **Apple Silicon MPS = NOT used.** Phase 2 Pitfall 1 (ultralytics #23140 — MPS corrupts bbox X-coords) is the conservative default. Re-testing MPS is itself a research task; not worth the risk on a load-bearing training run. Re-evaluate in M2 if MPS appears in `docs/FINETUNE.md`'s validated recipes.

### "Beat Baseline" Success Criterion

- **D-10:** **Comparison = re-eval baseline on the NEW test split + report mAP@0.5 alongside P/R.** Phase 6 baseline CIs were computed on a 3-positive test split (P=[0, 0.5], R=[0, 1]) — too wide to compare fairly to a model evaluated on ≥30 positives. Re-running `keremberke/yolov8s-pothole-segmentation@d6d5df4ac1a9e40b0180635b03198ddec88c4875` on the new test split first gives apples-to-apples ground truth. Both numbers (re-eval'd baseline + trained) live in `docs/DETECTOR_EVAL.md`.
- **D-11:** **Win definition = non-overlapping 95% CI on at least one of {Precision, Recall, mAP@0.5}.** mAP integrates the P/R curve, has tighter CIs by construction, and is the metric most likely to show separation at modest test-set sizes. Stricter than Phase 6 SC #2's "P or R" framing — but defensible given the wider test split.
- **D-12:** **Absolute floors = Claude's discretion.** Recommended: precision-only floor of P ≥ 0.5 on the test split. Logic: the demo's correctness story is bounded by FP rate (false alarms erode user trust faster than missed potholes). Recall is secondary as long as enough segments get tagged for the routing diff to function. Planner confirms during plan creation.
- **D-13:** **Contingency = hybrid iterate-once, then close.** If first trained run ≤ baseline, do one targeted iteration (most likely fix from the failure mode — e.g., switch to a detection-only base if val()-pipeline issues recur; add data if precision is FP-limited; tune augmentation if recall is bbox-shape-limited). If second run also ≤ baseline, close as documented negative result. Hard cap on calendar time.

### Production Re-Ingestion

- **D-14:** **Wipe ALL synthetic + ALL mapillary; production becomes real-data-only.** Synthetic data per `scripts/seed_data.py` is pure deterministic random noise (seed=42), not an approximate measurement — keeping it as a "backstop" preserves zero real signal, only visual filler. Real-data-only is the honest closure state. Trade-off: ~80% of LA segments outside trained-zone bboxes will render as no-defect (lowest color band) until M2 expands coverage. **Operator-visible side effect: routing diff outside trained zones will collapse — both fastest and best routes will look identical there because there's no defect signal to differentiate. Document this in the README disclaimer.**
- **D-15:** **Add `--wipe-mapillary` flag to `scripts/ingest_mapillary.py`.** Mirrors existing `wipe_synthetic_rows()` (`scripts/ingest_mapillary.py:332`) — `DELETE FROM segment_defects WHERE source = 'mapillary'`, hard-coded WHERE clause, paired `--force-wipe` safety latch. Small code add (~30 lines). Same `CHECK (source IN ('synthetic', 'mapillary'))` constraint from `db/migrations/002_mapillary_provenance.sql:30` keeps the literal-only safety property.
- **D-16:** **Coverage = training zones + adjacent expansions.** Run `ingest_mapillary.py` against the same 8-10 spread + 1-2 bad-pavement bboxes used for training, PLUS adjacent bboxes the model wasn't trained on. Wider visible coverage on the demo map. **Caveat called out in DETECTOR_EVAL.md:** eval numbers are honest only on training-zone tiles; segments inside adjacent-expansion bboxes are out-of-distribution inference. The model's predictions there are best-effort, not measured. Bbox-driven (not "top-N worst-IRI segments") because synthetic IRI is random — ranking by it is meaningless (per D-14 logic).
- **D-17:** **Always re-ingest with the trained model, even if it underperforms the re-eval'd baseline.** Logic: "trained on LA imagery" is a more honest production claim than "trained on global pothole imagery from a third party," regardless of small-N test outcome. The published model gates DETECTOR_EVAL.md content (D-11), but does NOT gate prod data swap. Reject the safety-net option — sticking with the public baseline in prod after deliberately training an LA-specific replacement is a worse story than shipping the trained model with measured caveats.
- **D-18:** **Order of operations = wipe-then-ingest, single transaction where possible.** Existing `--wipe-synthetic` already runs before INSERT (`scripts/ingest_mapillary.py:594-639`). New `--wipe-mapillary` follows the same pattern. Ingestion via `flyctl proxy 15432:5432` is fine (INSERT traffic is short queries — Phase 5 anti-pattern is specifically about long DDL like `pgr_createTopology`). Auto-recompute `segment_scores` after.

### Claude's Discretion

- Detection-only vs segmentation-base model choice. Phase 6 Plan 06-05 hit `IndexError: index is out of bounds` in `ultralytics.YOLO.val()` because `keremberke/*-segmentation` is a segmentation model with bbox-only labels. Two paths: (a) switch to a detection-only base (yolov8n.pt / yolov8s.pt COCO-pretrained, or arnabdhar pothole detection variants) so `val()` works clean, OR (b) keep the segmentation base and reuse the manual eval bypass from Plan 06-05 (pure inference + IoU + bootstrap). Planner picks based on whether `val()` integration is worth the base-model swap.
- Pre-labeling workflow. Recommended baseline: reuse `scripts/prelabel.py` (Plan 06-02 ship) on the new image set, accept the FP-heavy auto-suggestions as a starting point, hand-correct in CVAT. If the auto-suggest is too noisy at 1500-image scale, planner can swap in a stronger pre-label model (RDD2020-trained, larger YOLO variant) or a multi-pass workflow (cheap-then-careful).
- AWS region / instance lifecycle / S3 bucket / dataset transit on EC2.
- HF token handling on the training instance (env var, never logged).
- Mapillary `--count` per sub-tile (currently 25 in `_DEFAULT_LA_BBOXES`; need ~30-40 to hit ~1500 across 12-15 sub-tiles).
- Whether to publish the labeled dataset to HF Datasets (Phase 2 D-12 alluded to this; deferred so far). M2 territory unless trivially cheap.
- Augmentation recipe for fine-tuning. YOLOv8 defaults (HSV jitter, mosaic, flip) usually fine for ~150-positive scale.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope + requirements
- `.planning/ROADMAP.md` — Phase 7 section (goal, dependencies, 7 success criteria, "Why this phase exists")
- `.planning/REQUIREMENTS.md` — `REQ-trained-la-detector` row
- `.planning/PROJECT.md` — "Cloud infra sizing" + "Long DDL operations on Fly DB" constraints (load-bearing for re-ingestion against prod)

### Prior phase context (decisions inherited)
- `.planning/phases/02-real-data-detector-accuracy/02-CONTEXT.md` — D-05 (YOLO label format), D-07 (IoU=0.5), D-08 (image-level bootstrap, 1000 resamples, seed=42), D-09 (70/20/10 sequence-grouped split), D-11 (HF base model), D-13 (HF revision pin), D-14 (`YOLO_MODEL_PATH` env), D-16 (multi-env training reproducibility)
- `.planning/phases/02-real-data-detector-accuracy/02-RESEARCH.md` — Pitfall 1 (Apple MPS broken — informs D-09), Pitfall 7 (sequence-grouped split — required for fair eval), Pitfall 8 (pickle-ACE — informs D-15 revision pin pattern), Assumption A1 (image-level bootstrap rationale)
- `.planning/phases/06-public-demo-launch/06-CONTEXT.md` — D-04 (compute path origins), D-05 (HF repo + revision pin spec), D-09 (Phase 7 existence rationale + Option II framing)
- `.planning/phases/06-public-demo-launch/06-05-SUMMARY.md` — `ultralytics.YOLO.val()` incompatibility with segmentation-base + bbox-only labels; manual eval bypass methodology (Phase 7 may need to reuse this)
- `.planning/phases/05-cloud-deployment/05-LESSONS-LEARNED.md` — BLOCKING anti-pattern: long DDL on Fly DB via `flyctl ssh`, NOT proxy; INSERT traffic via proxy is fine

### Existing implementation (must read before touching)
- `data_pipeline/detector_factory.py` — `_DEFAULT_HF_REPO` (currently `keremberke/...@d6d5df4...`), `_resolve_model_path()` HF-repo regex, revision-pin pattern
- `data_pipeline/yolo_detector.py` — `YOLOv8Detector`, `_map_severity()`, `Detection` dataclass
- `data_pipeline/detector.py` — `PotholeDetector` Protocol (must not break)
- `data_pipeline/eval.py` — `bootstrap_ci` reference implementation (Phase 7 reuses for re-eval'd baseline + trained CIs)
- `scripts/finetune_detector.py` — training wrapper, `--push-to-hub`, `--device 0` for CUDA, exit codes (D-18 from Phase 2)
- `scripts/eval_detector.py` — `val()`-based path; broken on segmentation base; planner picks "detection-only base for clean val()" or "manual bypass like Plan 06-05"
- `scripts/fetch_eval_data.py` — current `_DEFAULT_LA_BBOXES` (3 zones × 4 sub-tiles); Phase 7 expands to 8-12 + 1-2 zones
- `scripts/prelabel.py` — Plan 06-02 pre-label workflow (reusable)
- `scripts/ingest_mapillary.py` — current `--wipe-synthetic` (D-15 adds matching `--wipe-mapillary`); idempotent INSERT pattern
- `scripts/seed_data.py` — synthetic IRI + defect generation (load-bearing context for D-14 wipe-everything decision: synthetic data is uncorrelated random noise, not approximate measurement)

### Schema + migration
- `db/migrations/002_mapillary_provenance.sql` — `segment_defects.source` CHECK constraint (defines the wipe vocabulary); ON CONFLICT dedup index

### Docs that get updated
- `docs/DETECTOR_EVAL.md` — substitute Phase 6 baseline numbers with re-eval'd-on-new-split + trained numbers; preserve Phase 6 numbers in "Previous baseline" section per SC #6
- `docs/FINETUNE.md` — Recipe C (EC2 g5.xlarge) is the validated path for D-07; keep recipes A/B for documentation but flag C as Phase 7's chosen
- `docs/MAPILLARY_INGEST.md` — operator runbook (already covers `--wipe-synthetic`; needs `--wipe-mapillary` doc added per D-15)
- `README.md` — replace Phase 6 "public baseline" disclosure with "LA-trained detector" status per SC #7

### External docs (researcher should fetch current versions)
- Ultralytics YOLOv8 docs — training API, HF integration, segmentation-vs-detection task discrimination, MPS status (informs D-09 re-test option)
- HuggingFace Hub upload docs — `huggingface-cli upload`, revision SHA capture via `HfApi().model_info(repo).sha`
- Mapillary API v4 docs — image search by bbox, `quality_score` field availability, `captured_at` filter (informs D-05)
- AWS EC2 g5.xlarge docs — instance setup, NVIDIA driver, ultralytics CUDA wheel compatibility (informs D-07 operator notes)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- **`scripts/finetune_detector.py`** (Phase 2 ship) — supports `--device 0` for CUDA, `--push-to-hub`, exit codes 0/1/3 per Phase 2 D-18. Reusable as-is for Recipe C on EC2.
- **`scripts/prelabel.py`** (Plan 06-02 ship) — public-model auto-suggest workflow. Reusable on the new image set; planner decides whether a stronger pre-label model is worth the swap.
- **`scripts/eval_detector.py`** (Phase 2 ship) — `val()`-based path. Broken on `keremberke/*-segmentation`; works on detection-only bases. Phase 7 base-model choice decides whether this script is reusable or whether the Plan 06-05 manual bypass is reused.
- **`data_pipeline/eval.py::bootstrap_ci`** — reusable for both the re-eval'd baseline (D-10) and the trained-model eval. Image-level bootstrap, 1000 resamples, seed=42 (Phase 2 D-08).
- **`data_pipeline/detector_factory.py::_resolve_model_path`** — HF-repo regex + revision-pin pattern. Reusable as-is; Phase 7 just updates `_DEFAULT_HF_REPO` constant after publish.
- **`scripts/ingest_mapillary.py::wipe_synthetic_rows`** (Plan 03-04, line 332) — template for new `wipe_mapillary_rows` function (D-15). Same hard-coded-WHERE pattern, same T-03-18 mitigation.
- **CVAT cloud workflow** (Plan 06-04) — operator-validated for the 158-image set. Single-class "pothole" project, YOLO 1.1 export, CVAT-XML-to-YOLO conversion script (inline in Plan 06-04). Reusable at 1500-image scale, but split labeling across multiple sessions to avoid fatigue.

### Established Patterns

- **HF revision pin via `@<sha>` in `_DEFAULT_HF_REPO`** (Phase 6 Plan 06-05) — pickle-ACE mitigation. Phase 7 follows the same pattern: capture HF commit SHA after `--push-to-hub`, update constant, comment block explains rationale + how to bump.
- **Image-level bootstrap for CIs** (Phase 2 D-08) — 1000 resamples, seed=42, 95% percentile interval. `data_pipeline/eval.py::bootstrap_ci` is the reference impl.
- **Sequence-grouped train/val/test splits** (Phase 2 Pitfall 7) — adjacent Mapillary frames from the same drive must never span split boundaries. `scripts/fetch_eval_data.py::_build` already implements this; Phase 7 inherits.
- **Single-class "pothole" label, severity at inference** (Phase 2 D-05; Phase 6 D-02) — CVAT export remains single-class regardless of severity. `data_pipeline/yolo_detector.py::_map_severity` derives severity from confidence at runtime.
- **Long DDL via `flyctl ssh -C "psql ..."`, NOT `flyctl proxy`** (Phase 5 BLOCKING anti-pattern). INSERT traffic via proxy is fine (Phase 6 Plan 06-03 confirmed). Phase 7 re-ingestion is INSERT-heavy → proxy is the right tool.
- **Hard-coded WHERE in wipe functions** (Plan 03-04, T-03-18 mitigation) — no parameterization, no operator-controlled filter. Phase 7's `wipe_mapillary_rows` MUST follow this; planner enforces in code review.

### Integration Points

- `data_pipeline/detector_factory.py::_DEFAULT_HF_REPO` — single line update after publish: `Hratchg/road-quality-la-yolov8@<new_sha>`
- `scripts/ingest_mapillary.py` — add `--wipe-mapillary` flag, `wipe_mapillary_rows()` helper, plumb through `main()` next to existing `--wipe-synthetic` (Plan 06's `--wipe-mapillary` plan)
- `data/eval_la/manifest.json` — regenerate via `scripts/fetch_eval_data.py --build` with the new bbox set; SHA256 + sequence-grouped split logic from Phase 2 already handles this
- `data/eval_la/data.yaml` — stays single-class; just regenerated by `--build`
- `data/eval_la/labels/` — Phase 6's 17 hand-labels carry forward IF the Phase 6 zones overlap the Phase 7 zones (D-06); otherwise preserved as `data/eval_la_phase6/` for traceability
- `docs/DETECTOR_EVAL.md` — version bump 0.2.0 → 0.3.0; "Sample size caveat" section updates to reflect new test split size; "Previous baseline" section freezes Phase 6's P=0.143/R=0.333 numbers; new TL;DR populated from re-eval'd-baseline + trained `eval_results.json`
- `README.md` — "Detector Accuracy" section updated; "Disclaimer" section adds the trained-zone-vs-real-data-only caveat (D-14 + D-16)
- `.env.example` — no new vars expected (`HUGGINGFACE_TOKEN`, `MAPILLARY_ACCESS_TOKEN`, `YOLO_MODEL_PATH` all from Phase 2)

### Cross-phase coordination

- **Phase 6 D-09** is the rationale for Phase 7's existence — preserve the framing in DETECTOR_EVAL.md "Previous baseline" section so the reader can see the pivot.
- **Phase 5 BLOCKING anti-pattern** governs the prod re-ingestion (D-18). Operator MUST use `flyctl proxy` for INSERT traffic, NOT `flyctl ssh psql -c "INSERT ..."` (slower, no benefit).
- **Phase 2 RESEARCH Pitfalls 1, 7, 8** all flow into D-09, D-04 (sequence-grouping inherited), D-15 (revision pin) respectively.

</code_context>

<specifics>
## Specific Ideas

- **"Trained on LA imagery is a more honest production claim than trained on global pothole imagery, regardless of small-N test outcome"** — the philosophical anchor behind D-17 (always-re-ingest). This is the demo's narrative; the eval delta is secondary.
- **"Synthetic backstop is fictional, not approximate"** — the realization that flipped the wipe-everything decision (D-14). `scripts/seed_data.py:98-112` independently generates pothole defects with `p=0.3` per segment, uncorrelated with the segment's (also synthetic) IRI. Keeping it preserves zero real signal — only visual map density. Real-data-only is the only honest demo state.
- **"Ranking by random IRI is meaningless"** — corollary of the above (D-16). Phase 6 Plan 06-03's `ORDER BY iri_norm DESC LIMIT 30` was effectively random sampling. Phase 7 coverage is bbox-driven, not segment-driven.
- **Mid-City east of La Brea, Boyle Heights, parts of South LA** — operator-supplied known-bad-pavement zones for D-04. Planner's job to translate these into Mapillary bboxes during research.
- **Phase 6 Plan 06-05's manual eval bypass** — `keremberke/yolov8s-pothole-segmentation` (segmentation model) + bbox-only labels broke `ultralytics.YOLO.val()`. Phase 7 inherits this constraint OR sidesteps it by switching to a detection-only base. D-10 (re-eval baseline) means we WILL run the segmentation model again — must reuse the manual bypass for that re-eval, even if the trained model uses a detection base.

</specifics>

<deferred>
## Deferred Ideas

- **Multi-city support** — explicitly out of M1/M2 scope per PROJECT.md; would require new train+eval datasets per city.
- **Roboflow Universe / RDD2020 dataset supplementation** — rejected during sourcing discussion; preserves LA-specificity claim. M2+ if generalization becomes a goal.
- **Iterating beyond 2 trained runs** — capped by D-13. Open-ended hyperparameter tuning is M2 territory.
- **Apple Silicon MPS re-test** — D-09 conservatively skips. M2 task: re-test with newer ultralytics, validate against CPU baseline on a small set.
- **Continuous eval / CI gate on detector accuracy** — Phase 2 deferred this; Phase 7 also defers. Eval is run manually when fine-tune updates.
- **Confidence calibration / temperature scaling** — Phase 2 deferred; Phase 7 also defers.
- **Frontend disclosure UI for trained-zone vs uncovered-zone visual difference** — surfaced and rejected. D-14 wipe-everything makes this less load-bearing (the whole map gets the same "real-data-only" claim); README disclaimer is sufficient.
- **HF Datasets publish of the labeled dataset** — Phase 2 D-12 alluded; deferred so far. M2 unless trivially cheap during the HF model upload.
- **Inter-rater agreement for hand labels** — single-operator labeling continues. Phase 7 docs the limitation in DETECTOR_EVAL.md but doesn't fix it.
- **Adjacent-expansion bbox ingestion as out-of-distribution inference** — D-16 caveats this in DETECTOR_EVAL.md. Future phase: train on the expanded distribution OR cap prod ingestion to training-zone bboxes only.

</deferred>

---

*Phase: 07-la-trained-detector*
*Context gathered: 2026-04-28*
