---
phase: 3
slug: mapillary-ingestion-pipeline
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-25
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (existing in `backend/tests/`) |
| **Config file** | `backend/pytest.ini` (existing) |
| **Quick run command** | `pytest backend/tests/test_ingest_mapillary.py backend/tests/test_compute_scores_source.py -x` |
| **Full suite command** | `pytest backend/tests/ -x` |
| **Estimated runtime** | ~10 seconds (mocked); ~30 seconds (live DB integration) |

---

## Sampling Rate

- **After every task commit:** Run quick run command
- **After every plan wave:** Run full suite command
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

> Filled in by planner — each task in PLAN.md must map to a row here with an automated command or a Wave 0 dependency.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | REQ-mapillary-pipeline | TBD | TBD | TBD | TBD | TBD | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_ingest_mapillary.py` — new test file: subprocess smokes, snap-match unit tests with fixture geometries, target-resolver injection-defense tests
- [ ] `backend/tests/test_compute_scores_source.py` — new test file: `--source {synthetic|mapillary|all}` filter behavior
- [ ] `backend/tests/test_migration_002.py` — new test file: idempotent migration application + UNIQUE constraint behavior with NULL `source_mapillary_id`

*Existing `backend/tests/test_mapillary.py` (Phase 2) covers the underlying client; do NOT duplicate.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| End-to-end against live Mapillary | REQ-mapillary-pipeline (SC #1, SC #3) | Requires `MAPILLARY_ACCESS_TOKEN` and live DB; auto-skip if env missing | Set `MAPILLARY_ACCESS_TOKEN`, run `python scripts/ingest_mapillary.py --segment-ids <small set> --limit-per-segment 5`, verify rows in `segment_defects` with `source='mapillary'` and `source_mapillary_id IS NOT NULL`, then `curl /segments?bbox=...` and confirm new pothole_score_total reflects the writes |
| SC #4 ranking comparison | REQ-mapillary-pipeline (SC #4) | Demo workflow, not a CI test | Operator runs `compute_scores.py --source synthetic`, captures `/route` response; runs `--source mapillary`, captures again; diffs route segment lists. Document in `docs/MAPILLARY_INGEST.md` |
| `--wipe-synthetic` Phase 6 deploy step | D-15 forward flag | Pre-deploy operational step | Documented in operator runbook; not a test |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
