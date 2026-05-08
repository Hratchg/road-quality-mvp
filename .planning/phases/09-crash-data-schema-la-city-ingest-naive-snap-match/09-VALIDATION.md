---
phase: 9
slug: crash-data-schema-la-city-ingest-naive-snap-match
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-08
---

# Phase 9 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: 09-RESEARCH.md § Validation Architecture (live-Socrata-verified test map).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.3.4 (already pinned in `backend/requirements.txt`) |
| **Config file** | `backend/pytest.ini` (existing) |
| **Quick run command** | `pytest backend/tests/test_lacity_mocodes.py backend/tests/test_snap.py -x` |
| **Full suite command** | `pytest backend/tests/ -x` (DB-dependent tests auto-skip if `DATABASE_URL` unreachable) |
| **Estimated runtime** | <1s quick / <30s full with seeded DB |

---

## Sampling Rate

- **After every task commit:** Run `pytest backend/tests/test_lacity_mocodes.py backend/tests/test_snap.py -x` (pure-module quick run, <1s — Nyquist sample of mocode-mapper + snap primitive at every commit)
- **After every plan wave:** Run `pytest backend/tests/test_lacity_mocodes.py backend/tests/test_snap.py backend/tests/test_lacity_socrata.py -x` (adds Socrata mock tests; <3s)
- **Before `/gsd-verify-work`:** Full suite `pytest backend/tests/` green (includes integration tests that exercise docker-postgres + CSV fixture path)
- **Max feedback latency:** 3 seconds (quick + Socrata mocks)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 9-01-01 | 01 | 1 | REQ-crash-ingest-lacity | T-9-01 | Migration applies cleanly + idempotent | unit (DDL replay) | `pytest backend/tests/test_migration_004.py::test_migration_004_idempotent -x` | ❌ W0 | ⬜ pending |
| 9-02-01 | 02 | 2 | REQ-crash-ingest-lacity | — | KABCO mocode → highest-tier resolution | unit | `pytest backend/tests/test_lacity_mocodes.py::test_multi_severity_resolves_to_highest -x` | ❌ W0 | ⬜ pending |
| 9-02-02 | 02 | 2 | REQ-crash-ingest-lacity | — | No-severity-code row raises ValueError (Pitfall 2) | unit RED | `pytest backend/tests/test_lacity_mocodes.py::test_no_severity_code_raises_value_error -x` | ❌ W0 | ⬜ pending |
| 9-02-03 | 02 | 2 | REQ-crash-ingest-lacity | — | Defensive separator parsing (space + comma) | unit | `pytest backend/tests/test_lacity_mocodes.py::test_separator_robustness -x` | ❌ W0 | ⬜ pending |
| 9-02-04 | 02 | 2 | REQ-crash-snap-match | T-9-02 | snap returns nearest within radius | unit (DB) | `pytest backend/tests/test_snap.py::test_snap_within_radius -x` | ❌ W0 | ⬜ pending |
| 9-02-05 | 02 | 2 | REQ-crash-snap-match | T-9-02 | snap returns (None, None) outside radius | unit (DB) | `pytest backend/tests/test_snap.py::test_snap_outside_radius -x` | ❌ W0 | ⬜ pending |
| 9-03-01 | 03 | 2 | REQ-crash-ingest-lacity | T-9-03 | Socrata client paginates correctly | unit (mock requests) | `pytest backend/tests/test_lacity_socrata.py::test_iter_crashes_pages -x` | ❌ W0 | ⬜ pending |
| 9-03-02 | 03 | 2 | REQ-crash-ingest-lacity | — | $where composes date + within_box | unit (URL inspect) | `pytest backend/tests/test_lacity_socrata.py::test_where_clause_composition_with_bbox -x` | ❌ W0 | ⬜ pending |
| 9-03-03 | 03 | 2 | REQ-crash-ingest-lacity | — | Fixture committed per D-09-05/07 coverage criteria | filesystem | `test -f data/crashes_la/lacity_fixture.csv && wc -l < data/crashes_la/lacity_fixture.csv` | ❌ W0 | ⬜ pending |
| 9-04-01 | 04 | 3 | REQ-crash-ingest-lacity | T-9-04 | Run-summary JSON has all 10 D-09-08 keys | integration (CSV fixture) | `pytest backend/tests/test_ingest_crashes.py::test_run_summary_shape -x` | ❌ W0 | ⬜ pending |
| 9-04-02 | 04 | 3 | REQ-crash-ingest-lacity | T-9-05 | Re-running ingest on same fixture inserts 0 new rows | integration | `pytest backend/tests/test_ingest_crashes.py::test_idempotent_reingest -x` | ❌ W0 | ⬜ pending |
| 9-04-03 | 04 | 3 | REQ-crash-snap-match | — | snap_distance_m populated correctly | integration | `pytest backend/tests/test_ingest_crashes.py::test_snap_distance_recorded -x` | ❌ W0 | ⬜ pending |
| 9-04-04 | 04 | 3 | REQ-crash-snap-match | — | Crashes outside snap radius dropped + counted | integration | `pytest backend/tests/test_ingest_crashes.py::test_dropped_outside_snap -x` | ❌ W0 | ⬜ pending |
| 9-04-05 | 04 | 3 | REQ-crash-snap-match | — | FK preserved on segment delete (ON DELETE SET NULL) | integration | `pytest backend/tests/test_ingest_crashes.py::test_fk_set_null_on_segment_delete -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Status of file existence (W0 = Wave 0 must create) is what makes this Phase 9 a Wave-0-heavy phase: every test file is new.*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_migration_004.py` — migration 004 idempotency + FK type INTEGER tests for REQ-crash-ingest-lacity (mirrors `test_migration_002.py` per-migration file pattern)
- [ ] `backend/tests/test_lacity_mocodes.py` — KABCO mocode mapper tests for REQ-crash-ingest-lacity
- [ ] `backend/tests/test_lacity_socrata.py` — Socrata client mock tests for REQ-crash-ingest-lacity
- [ ] `backend/tests/test_snap.py` — snap-match primitive tests for REQ-crash-snap-match (DB-dependent; auto-skip without DATABASE_URL)
- [ ] `backend/tests/test_ingest_crashes.py` — driver integration tests (DB + CSV fixture)
- [ ] `data/crashes_la/lacity_fixture.csv` — committed fixture per D-09-05 (~200 hand-picked rows satisfying D-09-07 a–e)
- [ ] No new framework install; pytest 8.3.4 already pinned

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live Socrata endpoint reachable + returns expected fields | REQ-crash-ingest-lacity | Network-dependent; would flake CI; per D-09-06 deferred to operator runbook | `python scripts/ingest_crashes.py --source lacity --limit 10 --dry-run` (operator confirms 10 rows fetched + parsed without DB writes) |
| Full LA-bbox 5-year ingest count is sane (~140k rows) | REQ-crash-ingest-lacity | Live API hit; happens once per quarter, not per-PR | `python scripts/ingest_crashes.py --source lacity` then `psql -c "SELECT COUNT(*) FROM crash_records WHERE source='lacity'"` (operator inspects vs Socrata `X-SODA2-Truth-Count` header) |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (5 new test files + 1 fixture)
- [ ] No watch-mode flags
- [ ] Feedback latency < 3s
- [ ] `nyquist_compliant: true` set in frontmatter once Wave 0 lands

**Approval:** pending
