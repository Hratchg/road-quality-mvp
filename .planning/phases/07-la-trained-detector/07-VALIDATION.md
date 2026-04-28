---
phase: 7
slug: la-trained-detector
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-28
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Sourced from `07-RESEARCH.md` "## Validation Architecture" section.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (existing; `backend/tests/` + `data_pipeline/tests/`) |
| **Config file** | None — run via `pytest` from repo root |
| **Quick run command** | `pytest data_pipeline/tests/ -x -q` |
| **Full suite command** | `pytest -x -q` (skips DB-dependent tests when DB unreachable) |
| **Estimated runtime** | ~30-60 seconds (full suite, no DB) |

---

## Sampling Rate

- **After every task commit:** Run `pytest data_pipeline/tests/ -x -q`
- **After every plan wave:** Run `pytest -x -q` (full suite)
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 7-XX-XX | TBD | 0 | REQ-trained-la-detector (SC #2) | — | bootstrap_ci returns (low, point, high) for `metric="map50"` with `0 ≤ low ≤ point ≤ high ≤ 1` | unit | `pytest data_pipeline/tests/test_eval.py::test_bootstrap_ci_map50 -x` | ❌ W0 | ⬜ pending |
| 7-XX-XX | TBD | 0 | REQ-trained-la-detector (SC #5) | T-03-18 (hard-coded WHERE) | wipe_mapillary_rows uses hard-coded `WHERE source='mapillary'`, returns rowcount, calls conn.commit() | unit | `pytest backend/tests/test_ingest_mapillary.py::test_wipe_mapillary_rows -x` | ❌ W0 | ⬜ pending |
| 7-XX-XX | TBD | 0 | REQ-trained-la-detector (SC #4) | T-02-01 (pickle-ACE) | `_DEFAULT_HF_REPO` starts with `Hratchg/road-quality-la-yolov8@` (revision-pinned) | unit | `pytest backend/tests/test_detector_factory.py::test_default_hf_repo_pin -x` | ⚠️ W0 update | ⬜ pending |
| 7-XX-XX | TBD | 1 | REQ-trained-la-detector (SC #1) | — | `_build_fresh` produces label files and sequence-grouped splits | unit | `pytest data_pipeline/tests/test_fetch_eval_data.py -x` | ✅ existing | ⬜ pending |
| 7-XX-XX | TBD | N | REQ-trained-la-detector (SC #3) | T-02-01 (pickle-ACE) | Model published to HF at `Hratchg/road-quality-la-yolov8@<sha>` | manual smoke | `python -c "from huggingface_hub import HfApi; print(HfApi().model_info('Hratchg/road-quality-la-yolov8').sha)"` | N/A | ⬜ pending |
| 7-XX-XX | TBD | N | REQ-trained-la-detector (SC #6) | — | DETECTOR_EVAL.md v0.3.0 with "Previous baseline" section | manual gate | `grep "Previous baseline" docs/DETECTOR_EVAL.md && grep "0.3.0" docs/DETECTOR_EVAL.md` | N/A | ⬜ pending |
| 7-XX-XX | TBD | N | REQ-trained-la-detector (SC #7) | — | README no longer says "public baseline" | manual gate | `! grep "public baseline" README.md` | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Note: Task IDs (`7-XX-XX`) will be filled in by gsd-planner after PLAN.md files are created.*

---

## Wave 0 Requirements

- [ ] `data_pipeline/tests/test_eval.py` — add `test_bootstrap_ci_map50`: verify the `metric="map50"` path in `bootstrap_ci` returns a `(low, point, high)` tuple with `0 ≤ low ≤ point ≤ high ≤ 1` for known-good input. Covers Plan 07's mAP CI extension (RESEARCH §2.4).
- [ ] `backend/tests/test_ingest_mapillary.py` — add `test_wipe_mapillary_rows`: mock psycopg2 cursor, verify DELETE SQL uses hard-coded `WHERE source = 'mapillary'`, verify return is rowcount, verify `conn.commit()` is called. Covers D-15 + T-03-18 mitigation.
- [ ] `backend/tests/test_detector_factory.py` — update `test_default_hf_repo_pin` to verify `_DEFAULT_HF_REPO` starts with `Hratchg/road-quality-la-yolov8@` after Phase 7 constant update. Covers SC #4 + Pitfall 8 (pickle-ACE).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Eval dataset has ≥150 positive bboxes (≥30 in test split) | SC #1 | Depends on operator hand-labeling work; not reproducible from code | After CVAT export, run: `wc -l data/eval_la/labels/{train,val,test}/*.txt \| awk '{n+=$1} END {print n}'` per split + total |
| Trained model beats baseline (non-overlapping 95% CI on P/R/mAP@0.5) | SC #2 | Requires training run + eval run + bootstrap output; gated on operator running fine-tune | Run `python scripts/eval_detector.py --data data/eval_la/data.yaml --split test --json-out eval_results.json --bootstrap` for both baseline and trained, compare CI tuples |
| Model published to `Hratchg/road-quality-la-yolov8@<sha>` | SC #3 | HF Hub network call; not in CI | `python -c "from huggingface_hub import HfApi; print(HfApi().model_info('Hratchg/road-quality-la-yolov8').sha)"` |
| Production DB re-ingested with `--wipe-mapillary --wipe-synthetic` | SC #5 (D-14) | Requires flyctl proxy + prod credentials | `flyctl proxy 15432:5432 -a road-quality-db &` then ingest_mapillary, verify `SELECT count(*) FROM segment_defects` per source |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending — gsd-planner fills Task IDs; final approval after PLAN.md verification.
