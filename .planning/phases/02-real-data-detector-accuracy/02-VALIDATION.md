---
phase: 2
slug: real-data-detector-accuracy
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-23
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (existing, under `backend/tests/`) |
| **Config file** | pytest uses repo defaults; add `pytest.ini` or rely on `backend/pytest.ini` if present (planner to verify) |
| **Quick run command** | `pytest backend/tests/test_yolo_detector.py -x -q` |
| **Full suite command** | `pytest backend/tests/ -q` |
| **Estimated runtime** | ~30 seconds (no GPU required for unit tests; model is mocked) |

---

## Sampling Rate

- **After every task commit:** Run `pytest backend/tests/test_yolo_detector.py -x -q`
- **After every plan wave:** Run `pytest backend/tests/ -q`
- **Before `/gsd-verify-work`:** Full suite must be green + `scripts/eval_detector.py --help` exits 0
- **Max feedback latency:** ~30 seconds

---

## Per-Task Verification Map

> Populated during planning — each PLAN.md task gets a row here. Columns filled from PLAN task IDs.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD — populated by planner | — | — | REQ-real-data-accuracy | — | — | — | — | — | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_detector_factory.py` — stub tests for `get_detector(use_yolo=True, model_path=None)` env-var resolution (REQ-real-data-accuracy SC #2, #3)
- [ ] `backend/tests/test_eval_detector.py` — stub tests for `scripts/eval_detector.py` metric computation on a 3-image fixture (REQ-real-data-accuracy SC #1)
- [ ] `backend/tests/fixtures/eval_fixtures/` — 3 fixture images + YOLO .txt labels + tiny manifest.json for smoke tests
- [ ] `backend/tests/conftest.py` — shared fixture for `tmp_path` model file and env-var patching (extend if exists)
- [ ] `requirements-train.txt` — fine-tuning-only deps (torch, torchvision, ultralytics pinned) split from runtime `requirements.txt`

*These must be created in Wave 1 tasks before Wave 2 detector/eval implementation tasks depend on them.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Actual fine-tuning run on 300-image LA set produces valid `best.pt` | REQ-real-data-accuracy | Requires GPU/Colab/EC2; 300-image labelling is human-in-the-loop; cannot automate in CI | Run `python scripts/finetune_detector.py --data data/eval_la/data.yaml --epochs 50 --device cuda` (or `mps` with smoke test first — see A7); verify `runs/detect/train/weights/best.pt` exists and `val/metrics.json` shows mAP@0.5 > 0 |
| HF Hub upload of fine-tuned weights | REQ-real-data-accuracy | Requires valid `HUGGINGFACE_TOKEN`; side-effects on public HF repo | After fine-tune, `huggingface-cli upload <user>/road-quality-la-yolov8 runs/detect/train/weights/best.pt` → verify `https://huggingface.co/<user>/road-quality-la-yolov8` resolves with file |
| Mapillary API image pull for 300 LA images | REQ-real-data-accuracy | Requires MAPILLARY_TOKEN; rate-limited; long-running | Run `python scripts/fetch_eval_data.py --build --count 300 --bbox "downtown,residential,freeway"`; verify `data/eval_la/images/` has ~300 files with SHA256 matches in `manifest.json` |
| docs/DETECTOR_EVAL.md numbers reflect actual eval run | REQ-real-data-accuracy SC #4 | Doc writeup is human-curated from script JSON output | After `python scripts/eval_detector.py --data data/eval_la/data.yaml --out eval_report.json`, verify `docs/DETECTOR_EVAL.md` precision/recall/mAP tables match `eval_report.json` within ±0.01 |
| LA-specific honesty check | REQ-real-data-accuracy SC #4 | Subjective — does writeup acknowledge limitations? | Reviewer confirms DETECTOR_EVAL.md contains: dataset caveats section, CI ranges, reproduction instructions, no cherry-picked thresholds |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags (pytest runs in single-shot mode)
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter after all plans validated

**Approval:** pending
