# Phase 6: Public Demo Launch - Context

**Gathered:** 2026-04-28
**Status:** Ready for planning
**Mode:** Decisions captured from user choice (Option A — full Tier 2, no shortcuts) + Phase 5 UAT closure

<domain>
## Phase Boundary

Anyone with the URL can open the app and see real LA pothole data informing routes — the user-visible payoff of M1. Concretely:

**In scope:**
1. Real Mapillary detections populate `segment_defects` in production via `scripts/ingest_mapillary.py` (run against deployed road-quality-db, NOT proxy)
2. YOLOv8 pothole detector trained on hand-labelled LA imagery (Tier 2 work folded in per user choice 2026-04-28)
3. `docs/DETECTOR_EVAL.md` substituted with real precision/recall/mAP numbers from the test split (replaces 14 TBD placeholders)
4. HuggingFace publish of the trained model + `_DEFAULT_HF_REPO @<revision>` pin in `data_pipeline/detector_factory.py`
5. README updated with public URL + brief data-source + detector-eval explanation
6. Public URL announcement (whatever channel — blog, share, etc. — is the operator's call)

**Out of scope:**
- Detector accuracy improvements beyond initial fine-tune (M2 territory)
- Multi-city support
- Mobile apps
- Synthetic-data fallback (we're committing to real-data-only per Option A)
- Any change to `/health`, `/route`, `/segments`, or auth contracts (Phase 5 settled)
- CI deploy-backend end-to-end CI exercise (Phase 5 follow-up; auto-validates next backend commit)

**Phase 5 UAT non-blocking follow-ups intentionally deferred to Phase 6:**
- UAT #3 in-browser DevTools confirmation of in-app modal flow (will happen naturally during demo polish)
- UAT #4 503-path verification (covered by unit test; intentionally not exercised against live DB)

</domain>

<decisions>
## Implementation Decisions

### D-01: Full Tier 2, no shortcuts (USER CHOICE 2026-04-28)
Tier 2 work (Phase 2 HUMAN-UAT items #1-#4) is folded into Phase 6 as a hard prerequisite. No public-model fallback (Option B), no synthetic-data banner (Option C). Demo launches with honest measured numbers from a detector trained on hand-labeled LA imagery.

**Why:** User explicitly chose Option A on 2026-04-28. The trade-off is clear: 3-6 hours of CVAT labeling + ~hours of training compute + 5 minutes of HF publish in exchange for a demo with credible accuracy claims.

**How to apply:** Phase 6 plans gate the public announcement (Plan 06-06) on real eval numbers being substituted (Plan 06-04). Plans 06-02 and 06-03 are USER-GATED — execution pauses for human labeling work.

### D-02: Hand-labeling tool — CVAT (cloud or self-hosted)
Recommend `app.cvat.ai` (free, hosted, no setup). Self-hosted CVAT via Docker also fine. Per docs/FINETUNE.md and docs/DETECTOR_EVAL.md, single-class label = "pothole" regardless of severity (severity comes from detector confidence at inference).

**Why:** Already the recommended tool in Phase 2 docs; no new tooling needed. Cloud variant minimizes setup time.

**How to apply:** Operator opens CVAT, creates a single-class project, uploads `data/eval_la/images/{train,val,test}/`, draws bboxes around potholes, exports as YOLO 1.1 format, drops the `<image_id>.txt` files into `data/eval_la/labels/{train,val,test}/`.

### D-03: Eval dataset bbox subdivision (FIXED 2026-04-28)
The Phase 2 `scripts/fetch_eval_data.py` had three 0.01-deg LA zones. Mapillary API 500s on these (their dense-tile dataset overflows server-side). Fixed by subdividing each zone into a 2x2 grid of 0.005-deg sub-tiles (12 total). Default `--count` adjusted from 100 to 25 to keep the 300-image target.

**Why:** Empirical fix from 2026-04-28: 0.005-deg bboxes return 200 OK; 0.01-deg returned 500 "Please reduce the amount of data". Mapillary's API behavior likely changed after Phase 2 was tested.

**How to apply:** Default invocation `python scripts/fetch_eval_data.py --build` now uses subdivided zones automatically. No flags needed.

### D-04: Training compute path
**Default:** Laptop CPU (Apple Silicon M-series) per docs/FINETUNE.md Recipe A. Slow (~4-6 hours for 300 images × 50 epochs) but no setup. NOT MPS (Pitfall 1 — silently breaks).

**Escalation:** If laptop training is infeasible, escalate to Colab T4 (Recipe B, free tier, ~30 min) or EC2 g5.xlarge (Recipe C, ~10 min, costs ~$0.20/hr). The script (`scripts/finetune_detector.py`) is identical across recipes.

**Why:** Default minimizes setup friction. Operator picks based on their patience/availability.

**How to apply:** Plan 06-03 documents both options; operator picks at execution time.

### D-05: HuggingFace repo + revision pin
Repo name: `Hratchg/road-quality-la-yolov8` (operator's HF account `Hratchg` matches their GitHub). Pinned revision: SHA hash of the first published commit, NOT `main` (per Phase 2 D-13 + Pitfall 8 — pickle-ACE risk).

**Why:** Floating `main` tag means anyone with HF write access (including a future compromised token) can replace the model with a malicious one. Pinned revision freezes the artifact.

**How to apply:** Plan 06-04: after `finetune_detector.py --push-to-hub Hratchg/road-quality-la-yolov8`, capture the HF commit SHA and update `_DEFAULT_HF_REPO` constant in `data_pipeline/detector_factory.py` to include `@<sha>`.

### D-06: Real Mapillary ingestion against prod DB
Run `scripts/ingest_mapillary.py` once against the deployed road-quality-db (via flyctl ssh, NOT proxy — see Phase 5 BLOCKING anti-pattern in 05-LESSONS-LEARNED.md). Populates `segment_defects` rows with `source='mapillary'` so Map View shows real detections.

**Why:** Phase 6 SC #2 requires "real Mapillary-ingested detections." Ingestion pipeline shipped in Phase 3 (Plan 03-03). Just needs to run once.

**How to apply:** Plan 06-05. Use the same direct-flyctl-ssh pattern from Phase 5 UAT (Plan 05's Lessons Learned).

### D-07: README messaging
README links to https://road-quality-frontend.fly.dev/ and includes:
- One-paragraph description of what the user is looking at
- Link to docs/DETECTOR_EVAL.md for accuracy numbers
- Link to docs/MAPILLARY_INGEST.md for data source
- Disclaimer: "LA-only; trained on ~300 images; demo, not production"

**Why:** Phase 6 SC #4 explicitly requires this.

**How to apply:** Plan 06-06. Single-file README edit + commit.

### D-08: Demo announcement gating
The public URL `road-quality-frontend.fly.dev` is ALREADY accessible (Phase 5). Phase 6 doesn't gate access to the URL — anyone can hit it now. Phase 6 gates the *announcement* (README link, sharing externally, etc.) on real eval numbers being in DETECTOR_EVAL.md.

**Why:** Pragmatic — the URL leaking now (e.g., to Hratchg's social media) is fine; announcing "look at our LA pothole demo" before we have real numbers would mean retracting/updating later.

**How to apply:** Plan 06-06 is the gate. README update + announcement happen as a single PR. Until that lands, anyone hitting the URL just sees a working demo with synthetic data.

</decisions>

<code_context>
## Existing Code Insights

**Already shipped (Phase 1-5):**
- `road-quality-db` Fly app: 2GB / 5GB volume, fully seeded with 209k synthetic segments + 125k synthetic defects + 74k vertices (post-Phase 5)
- `road-quality-backend` Fly app: live, /health 200 + db:reachable
- `road-quality-frontend` Fly app: live, Vite bundle baked with backend URL
- `scripts/fetch_eval_data.py`: builds eval dataset (NEW: 12 sub-tiles after 2026-04-28 fix)
- `scripts/finetune_detector.py`: YOLOv8 training wrapper (Phase 2 ship)
- `scripts/eval_detector.py`: precision/recall/mAP eval with bootstrap CIs (Phase 2 ship)
- `scripts/ingest_mapillary.py`: Mapillary → segment_defects pipeline (Phase 3 ship)
- `docs/FINETUNE.md`: 3 training recipes (laptop/Colab/EC2)
- `docs/DETECTOR_EVAL.md`: methodology doc with 14 TBD placeholders for measured numbers
- `docs/MAPILLARY_INGEST.md`: Mapillary ingestion operator runbook

**Code paths Phase 6 will exercise but not modify:**
- `data_pipeline/detector_factory.py::_DEFAULT_HF_REPO` — needs `@<sha>` revision pin (Plan 06-04)
- `frontend/src/MapView.tsx` (or similar) — already renders segment_defects color-coded; Plan 06-05 just adds rows the existing UI consumes

**Files Phase 6 WILL modify:**
- `docs/DETECTOR_EVAL.md` — substitute 14 TBDs with real numbers (Plan 06-04)
- `data_pipeline/detector_factory.py` — pin HF revision (Plan 06-04)
- `README.md` — add public URL + data-source + accuracy section (Plan 06-06)
- `_DEFAULT_LA_BBOXES` already fixed in this session (commit pending)

</code_context>

<specifics>
## Specific Ideas

**Plan structure (~6 plans, multi-day):**

- **Plan 06-01: Eval dataset prep** (automatable; mostly DONE 2026-04-28)
  - ✅ Subdivide bboxes (commit pending)
  - 🚧 Run `fetch_eval_data.py --build --clean` (in progress as of 2026-04-28T07:24Z)
  - Verify ~300 images written under `data/eval_la/images/{train,val,test}/`
  - Verify manifest.json hashes
  - Commit the dataset (or just the manifest, since images may be too large) per repo convention

- **Plan 06-02: Hand-labeling** (USER GATE — 3-6 hours human work)
  - Operator opens CVAT (cloud at app.cvat.ai or self-hosted)
  - Creates single-class project, uploads images
  - Draws bboxes around potholes (ignore non-pothole defects per D-02)
  - Exports as YOLO 1.1 format
  - Drops .txt files into `data/eval_la/labels/{train,val,test}/`
  - Commits the labels
  - Phase 6 execution PAUSES until this is complete

- **Plan 06-03: Train detector** (automatable; ~hours of compute)
  - Operator picks recipe A/B/C from docs/FINETUNE.md based on hardware availability
  - Runs `python scripts/finetune_detector.py --data data/eval_la/data.yaml --epochs 50`
  - Verifies `runs/detect/train*/weights/best.pt` is non-empty
  - Optional: `--push-to-hub Hratchg/road-quality-la-yolov8` to publish

- **Plan 06-04: Eval + HF publish + revision pin** (automatable, ~10 min)
  - `python scripts/eval_detector.py --data data/eval_la/data.yaml --split test --json-out eval_results.json`
  - Substitute 14 TBDs in docs/DETECTOR_EVAL.md from eval_results.json
  - If not already pushed in Plan 06-03, push to HF
  - Capture HF commit SHA, update `_DEFAULT_HF_REPO` to `Hratchg/road-quality-la-yolov8@<sha>`

- **Plan 06-05: Real Mapillary ingestion against prod DB** (automatable, ~10-30 min)
  - Use the same direct-flyctl-ssh pattern from Phase 5 UAT — NOT proxy
  - Run `scripts/ingest_mapillary.py` against road-quality-db
  - Verify `segment_defects` has rows with `source='mapillary'`
  - Run `scripts/compute_scores.py --source mapillary` to update segment_scores

- **Plan 06-06: README + announcement** (automatable, ~30 min)
  - Update README.md with public URL + data-source + accuracy paragraph
  - Add disclaimer ("LA-only, ~300 image train, demo not production")
  - Commit + push (this is the announcement gate)

</specifics>

<deferred>
## Deferred Ideas

- **CVAT custom export plugin / automation:** out of scope. Manual export is fine for a 300-image one-shot.
- **Detector accuracy improvements beyond first fine-tune:** M2 work. Phase 6 ships first measured numbers, not optimal numbers.
- **Multi-city support:** explicitly out of M1 scope per PROJECT.md.
- **Synthetic-data parallel demo:** rejected (Option A excludes this).
- **Auto-pseudo-labeling via existing pretrained detector:** rejected (Option A excludes this).
- **A/B comparison between trained-on-LA detector and public-model baseline:** interesting but not in scope for first launch.

</deferred>
