---
phase: 2
slug: real-data-detector-accuracy
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-23
last_updated: 2026-04-23
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (existing, under `backend/tests/`) |
| **Config file** | pytest uses repo defaults; no `pytest.ini` at repo root |
| **Quick run command** | `pytest backend/tests/test_yolo_detector.py backend/tests/test_detector_factory.py backend/tests/test_eval_detector.py backend/tests/test_mapillary.py backend/tests/test_fetch_eval_data.py backend/tests/test_finetune_detector.py -x -q` |
| **Full suite command** | `pytest backend/tests/ -q` |
| **Estimated runtime** | ~30-45 seconds (no GPU; ultralytics+requests mocked everywhere) |

---

## Sampling Rate

- **After every task commit:** `pytest backend/tests/test_detector_factory.py backend/tests/test_eval_detector.py backend/tests/test_mapillary.py -x -q` (~10s)
- **After every plan wave:** `pytest backend/tests/ -q` + `python3 scripts/eval_detector.py --help; python3 scripts/fetch_eval_data.py --help; python3 scripts/finetune_detector.py --help` (each exits 0)
- **Before `/gsd-verify-work`:** Full suite green + 3 `--help` exits 0 + exit-code-3 smoke (all three scripts reject missing data with exit 3)
- **Max feedback latency:** ~45 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| P01-T1 factory env resolve | 02-01 | 1 | REQ-real-data-accuracy SC #2, #3 | T-02-01, T-02-02, T-02-05 | hf_hub_download defaults to trusted repo, no token logged | unit | `pytest backend/tests/test_detector_factory.py -x -q` | ⏳ post-plan | ⬜ pending |
| P01-T2 requirements+env.example | 02-01 | 1 | REQ-real-data-accuracy SC #3 | T-02-02 | .env.example placeholders empty | grep | `grep -q "^YOLO_MODEL_PATH=$" .env.example` | ⏳ | ⬜ pending |
| P01-T3 factory tests | 02-01 | 1 | REQ-real-data-accuracy SC #2, #3 | T-02-05 | HF download mocked; no network | unit | `pytest backend/tests/test_detector_factory.py backend/tests/test_yolo_detector.py -x -q` | ⏳ | ⬜ pending |
| P02-T1 eval.py helpers | 02-02 | 2 | REQ-real-data-accuracy SC #1 | — | Pure fns, no I/O | unit | `pytest backend/tests/test_eval_detector.py::TestBootstrapCiDeterministic -x` | ⏳ | ⬜ pending |
| P02-T2 eval_detector CLI | 02-02 | 2 | REQ-real-data-accuracy SC #1 | T-02-11 | Lazy ultralytics import, exit-3 on missing data | smoke | `python3 scripts/eval_detector.py --data /nonexistent.yaml; [ $? -eq 3 ]` | ⏳ | ⬜ pending |
| P02-T3 eval tests | 02-02 | 2 | REQ-real-data-accuracy SC #1 | T-02-11 | No real model inference | unit+smoke | `pytest backend/tests/test_eval_detector.py -x -q` | ⏳ | ⬜ pending |
| P03-T1 mapillary client | 02-03 | 2 | REQ-real-data-accuracy SC #1 | T-02-13, T-02-14, T-02-15, T-02-18, T-02-20 | hmac.compare_digest; bbox ≤ 0.01 deg²; path traversal guard | unit | `pytest backend/tests/test_mapillary.py -x -q` | ⏳ | ⬜ pending |
| P03-T2 fetch CLI + env + gitignore | 02-03 | 2 | REQ-real-data-accuracy SC #1 | T-02-16, T-02-19 | No token logged; CC-BY-SA noted; data gitignored (manifest committed) | smoke | `python3 scripts/fetch_eval_data.py --manifest /nonexistent.json --root /tmp/nope; [ $? -eq 3 ]` | ⏳ | ⬜ pending |
| P03-T3 fetch tests | 02-03 | 2 | REQ-real-data-accuracy SC #1 | T-02-13..T-02-20 | All guards exercised | unit+smoke | `pytest backend/tests/test_mapillary.py backend/tests/test_fetch_eval_data.py -x -q` | ⏳ | ⬜ pending |
| P04-T1 finetune CLI | 02-04 | 3 | REQ-real-data-accuracy SC #1 | T-02-22, T-02-25, T-02-26 | Fail-fast on missing HUGGINGFACE_TOKEN; AGPL+CC-BY-SA card; seed=42; device=cpu default | smoke | `pytest backend/tests/test_finetune_detector.py -x -q` | ⏳ | ⬜ pending |
| P04-T2 requirements-train.txt | 02-04 | 3 | REQ-real-data-accuracy | — | Pitfall 2: torch!=2.4.0 | grep | `grep -q "torch>=2.4.1,<2.10" requirements-train.txt` | ⏳ | ⬜ pending |
| P04-T3 FINETUNE.md | 02-04 | 3 | REQ-real-data-accuracy SC #4 | — | Pitfall 1 (Apple Silicon MPS) documented | doc-verify | `grep -q "^## Recipe [ABC]:" docs/FINETUNE.md` (returns 3) | ⏳ | ⬜ pending |
| P04-T4 finetune tests | 02-04 | 3 | REQ-real-data-accuracy | T-02-22 | No real training; mock + subprocess | smoke | `pytest backend/tests/test_finetune_detector.py -x -q` | ⏳ | ⬜ pending |
| P05-T1 data.yaml seed | 02-05 | 4 | REQ-real-data-accuracy | — | Single-class; committed (un-gitignored) | grep | `python3 -c "import yaml; d=yaml.safe_load(open('data/eval_la/data.yaml')); assert d['nc']==1"` | ⏳ | ⬜ pending |
| P05-T2 DETECTOR_EVAL.md | 02-05 | 4 | REQ-real-data-accuracy SC #4 | T-02-01, T-02-19, T-02-30 | Pickle ACE + CC-BY-SA/AGPL chain documented | doc-verify | `grep -c "^## [1-7]\\." docs/DETECTOR_EVAL.md` (returns 7) | ⏳ | ⬜ pending |
| P05-T3 README.md update | 02-05 | 4 | REQ-real-data-accuracy SC #4 | — | New section + 2 Documentation links | grep | `grep -q "^## Detector Accuracy$" README.md` | ⏳ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*
*Execution-phase updates these rows after each task commit.*

---

## Wave 0 Requirements (satisfied by Plan 02 Task 1)

- [x] `backend/tests/test_detector_factory.py` — **Plan 02-01 Task 3** creates this file with ≥ 10 tests covering `_resolve_model_path` and `get_detector` env-var precedence.
- [x] `backend/tests/test_eval_detector.py` — **Plan 02-02 Task 3** creates this file with ≥ 18 tests covering bootstrap, per-severity, match, and CLI exit codes.
- [x] `backend/tests/fixtures/eval_fixtures/` — **Plan 02-02 Task 1** creates 3 tiny JPEG images, 3 label `.txt` files (one empty), and `data.yaml`. Total < 10 KB.
- [x] `backend/tests/conftest.py` — NO CHANGES REQUIRED: existing conftest provides `db_available`, `client`, `db_conn` session fixtures which are unrelated to Phase 2 pure-unit tests. Phase 2 tests use `monkeypatch` fixture + `patch.dict(sys.modules)` directly — no new shared fixtures needed.
- [x] `requirements-train.txt` — **Plan 02-04 Task 2** creates this file with the torch!=2.4.0 pin.

*All Wave 0 artifacts are created as the FIRST task of the plan that needs them — no separate "Wave 0 pre-setup" task is required because Plan 02 and Plan 04 own their own fixtures/requirements. Waves 1 and 2 can start in parallel after planning completes.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Actual fine-tuning run on 300-image LA set produces valid `best.pt` | REQ-real-data-accuracy | Requires GPU/Colab/EC2; 300-image labelling is human-in-the-loop; cannot automate in CI | Follow one of the three recipes in `docs/FINETUNE.md`. Verify `runs/detect/la_pothole/weights/best.pt` exists after completion. |
| HF Hub upload of fine-tuned weights | REQ-real-data-accuracy | Requires valid `HUGGINGFACE_TOKEN`; side-effects on public HF repo | Run `HUGGINGFACE_TOKEN=... python scripts/finetune_detector.py --data data/eval_la/data.yaml --push-to-hub <user>/road-quality-la-yolov8`. Verify `https://huggingface.co/<user>/road-quality-la-yolov8` resolves with `best.pt` + `README.md`. |
| Mapillary API image pull for ~300 LA images | REQ-real-data-accuracy | Requires `MAPILLARY_ACCESS_TOKEN`; rate-limited; long-running | Run `MAPILLARY_ACCESS_TOKEN=... python scripts/fetch_eval_data.py --build --count 100`. Verify `data/eval_la/images/{train,val,test}/` has ~300 files total across splits; `python scripts/fetch_eval_data.py` (verify mode) exits 0 with all hashes matching. |
| Hand-labelling of ~300 LA images to YOLO .txt format | REQ-real-data-accuracy D-05 | Human annotation, single-operator | Use CVAT 1.1 native YOLO export. Labels go under `data/eval_la/labels/<split>/<image_id>.txt`. One line per detection: `0 <cx> <cy> <w> <h>`, all floats in [0, 1]. |
| `docs/DETECTOR_EVAL.md` numbers reflect actual eval run | REQ-real-data-accuracy SC #4 | Doc writeup is human-curated from script JSON output | After `python scripts/eval_detector.py --data data/eval_la/data.yaml --split test --json-out eval_report.json`, substitute `TBD` cells in Section 2 tables of `docs/DETECTOR_EVAL.md` with values from `eval_report.json`. |
| LA-specific honesty check | REQ-real-data-accuracy SC #4 | Subjective — does writeup acknowledge limitations? | Reviewer confirms `docs/DETECTOR_EVAL.md` Section 3 (Caveats) contains: small test set, LA-specific scope, single-operator labelling, severity-via-confidence proxy, deferred items. No cherry-picked thresholds. |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify OR Wave 0 dependencies satisfied in-plan
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (each plan ends with a test task)
- [x] Wave 0 covers all MISSING references (fixtures created by Plan 02-02, test files created alongside the code they cover)
- [x] No watch-mode flags (pytest runs in single-shot mode throughout)
- [x] Feedback latency < 45s (full suite)
- [x] `nyquist_compliant: true` set in frontmatter after all plans validated

**Approval:** ✅ plans validated 2026-04-23
