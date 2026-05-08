---
phase: 3
slug: mapillary-ingestion-pipeline
status: draft
nyquist_compliant: true
wave_0_complete: true
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
| 03-01-T1 | 03-01 | 1 | REQ-mapillary-pipeline (D-05, D-07) | T-03-08, T-03-09 | Idempotent migration DDL with `IF NOT EXISTS`; UNIQUE index without `NULLS NOT DISTINCT` (Pitfall 6) | grep + file existence | `test -f db/migrations/002_mapillary_provenance.sql && grep -q "ADD COLUMN IF NOT EXISTS source_mapillary_id TEXT" db/migrations/002_mapillary_provenance.sql && grep -q "CREATE UNIQUE INDEX IF NOT EXISTS uniq_defects_segment_source_severity" db/migrations/002_mapillary_provenance.sql && ! grep -qi "NULLS NOT DISTINCT" db/migrations/002_mapillary_provenance.sql` | ✅ created by task | ⬜ pending |
| 03-01-T2 | 03-01 | 1 | REQ-mapillary-pipeline (Pitfall 10) | T-03-10, T-03-12 | docker-compose mounts new migration on fresh init; `data/ingest_la/*` git-ignored with `.gitkeep` exception | grep | `grep -q "002_mapillary_provenance.sql:/docker-entrypoint-initdb.d/03-mapillary.sql" docker-compose.yml && grep -q "data/ingest_la/\*" .gitignore && grep -q "!data/ingest_la/.gitkeep" .gitignore && test -f data/ingest_la/.gitkeep` | ✅ created by task | ⬜ pending |
| 03-01-T3 | 03-01 | 1 | REQ-mapillary-pipeline (D-05, D-07, SC #2 foundation) | T-03-08, T-03-09 | Migration is safe to re-apply; UNIQUE allows multiple NULL synthetic rows; backfilled `source` defaults to `'synthetic'` | pytest (integration, DB-bound, auto-skip) | `python3 -m pytest backend/tests/test_migration_002.py -x -q` | ✅ Wave 0 file (created here) | ⬜ pending |
| 03-02-T1 | 03-02 | 1 | REQ-mapillary-pipeline (D-16, SC #4) | T-03-13, T-03-15 | `--source` argparse `choices=("synthetic","mapillary","all")`; psycopg2 `%s` parameterization; filter in JOIN clause not WHERE (Pattern 7) | grep + exit-code probe | `python3 scripts/compute_scores.py --help 2>&1 \| grep -q -- "--source" && python3 scripts/compute_scores.py --source bogus; test $? -eq 2 && grep -q "AND sd.source = %s" scripts/compute_scores.py && grep -q 'VALID_SOURCES = ("synthetic", "mapillary", "all")' scripts/compute_scores.py` | ✅ extends existing file | ⬜ pending |
| 03-02-T2 | 03-02 | 1 | REQ-mapillary-pipeline (D-16, SC #4 foundation, Pitfall 7) | T-03-13, T-03-14, T-03-15 | Subprocess CLI smoke + DB-state assertions; warning to stderr when no mapillary rows; segment retention regression guard | pytest (integration, DB-bound, auto-skip) | `python3 -m pytest backend/tests/test_compute_scores_source.py -x -q` | ✅ Wave 0 file (created here) | ⬜ pending |
| 03-03-T1 | 03-03 | 2 | REQ-mapillary-pipeline (D-01..D-12, D-19, D-20, SC #1, SC #2, SC #5) | T-03-01, T-03-02, T-03-03, T-03-04, T-03-05, T-03-16, T-03-17 | Token from env (D-19); `--where` regex blocklist + sql.SQL composition + max_segments cap (Pattern 6); `ON CONFLICT DO NOTHING` idempotency (D-08); `data_pipeline/mapillary.py` untouched (D-20) | ast-parse + grep + git diff | `python3 scripts/ingest_mapillary.py --help 2>&1 \| tail -5; python3 -c "import ast; ast.parse(open('scripts/ingest_mapillary.py').read())" && grep -q "ON CONFLICT (segment_id, source_mapillary_id, severity)" scripts/ingest_mapillary.py && grep -q "ST_Buffer(geom::geography" scripts/ingest_mapillary.py && grep -q "ST_DWithin" scripts/ingest_mapillary.py && grep -q "geom <-> ST_SetSRID" scripts/ingest_mapillary.py && [[ $(git diff HEAD -- data_pipeline/mapillary.py 2>/dev/null \| wc -l) -eq 0 ]]` | ✅ created by task | ⬜ pending |
| 03-03-T2 | 03-03 | 2 | REQ-mapillary-pipeline (D-09, D-19, RESEARCH Pattern 6, Pitfall 9) | T-03-02, T-03-03, T-03-17 | 14 parametrized injection-defense cases over forbidden-token regex; CLI smokes (`--help`, missing-token, no-target); pure-unit retry tests | pytest (mixed: pure-unit + integration auto-skip) | `python3 -m pytest backend/tests/test_ingest_mapillary.py -x -q` | ✅ Wave 0 file (created here) | ⬜ pending |
| 03-04-T1 | 03-04 | 3 | REQ-mapillary-pipeline (D-14, D-17, RESEARCH Open Questions #3 + #5) | T-03-18, T-03-19, T-03-20 | `wipe_synthetic_rows` hard-coded literal WHERE (no operator input); `trigger_recompute` uses `[sys.executable, repo_root/"scripts/compute_scores.py"]` (no shell, no PATH); empty-write guard + `--force-wipe` override; structured summary fields | ast-parse + grep | `python3 -c "import ast; ast.parse(open('scripts/ingest_mapillary.py').read())" && python3 scripts/ingest_mapillary.py --help 2>&1 \| grep -q -- "--wipe-synthetic" && python3 scripts/ingest_mapillary.py --help 2>&1 \| grep -q -- "--no-recompute" && python3 scripts/ingest_mapillary.py --help 2>&1 \| grep -q -- "--force-wipe" && grep -q "def wipe_synthetic_rows" scripts/ingest_mapillary.py && grep -q "def trigger_recompute" scripts/ingest_mapillary.py && grep -q "DELETE FROM segment_defects WHERE source = 'synthetic'" scripts/ingest_mapillary.py && grep -q "wipe_synthetic_applied" scripts/ingest_mapillary.py && grep -q "recompute_invoked" scripts/ingest_mapillary.py && grep -q "rows_skipped_idempotent" scripts/ingest_mapillary.py && [[ $(git diff HEAD -- data_pipeline/mapillary.py 2>/dev/null \| wc -l) -eq 0 ]]` | ✅ extends 03-03 script | ⬜ pending |
| 03-04-T2 | 03-04 | 3 | REQ-mapillary-pipeline (SC #1, #2, #3, #4, D-14, D-17) | T-03-18, T-03-19, T-03-21, T-03-22 | End-to-end ingest writes mapillary rows; second run idempotent; `/segments` reflects scores after auto-recompute (deterministic mock-injected detection); `--source` snapshot diff; `--wipe-synthetic` preserves mapillary | pytest (integration, DB-bound, auto-skip) | `python3 -m pytest backend/tests/test_integration.py -x -q -k "ingest_mapillary or route_ranks_differ or wipe_synthetic"` | ✅ extends existing file | ⬜ pending |
| 03-05-T1 | 03-05 | 3 | REQ-mapillary-pipeline (D-15, D-18, runbook) | T-03-23, T-03-25, T-03-26 | Token placeholder only (never live); Phase 6 cutover heading verbatim; SC #4 demo workflow; trust-model section enumerating rejected `--where` token classes | grep + line-count | `test -f docs/MAPILLARY_INGEST.md && test $(wc -l < docs/MAPILLARY_INGEST.md) -gt 100 && grep -q "MAPILLARY_ACCESS_TOKEN" docs/MAPILLARY_INGEST.md && grep -q "wipe-synthetic" docs/MAPILLARY_INGEST.md && grep -q "Phase 6 public-demo cutover" docs/MAPILLARY_INGEST.md && grep -q "SC #4 ranking-comparison demo workflow" docs/MAPILLARY_INGEST.md && grep -q "Trust model" docs/MAPILLARY_INGEST.md` | ✅ created by task | ⬜ pending |
| 03-05-T2 | 03-05 | 3 | REQ-readme-docs (Phase 3 reaffirmation) | T-03-24 | README "Real-Data Ingest" section cross-links to runbook; section count preserved | grep | `grep -q "## Real-Data Ingest" README.md && grep -q "docs/MAPILLARY_INGEST.md" README.md && grep -q "MAPILLARY_ACCESS_TOKEN" README.md && grep -c "^## " README.md \| awk '{ if ($1 < 9) { print "FAIL"; exit 1 } }'` | ✅ extends existing file | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `backend/tests/test_ingest_mapillary.py` — new test file: subprocess smokes, snap-match unit tests with fixture geometries, target-resolver injection-defense tests *(created by 03-03 Task 2)*
- [x] `backend/tests/test_compute_scores_source.py` — new test file: `--source {synthetic|mapillary|all}` filter behavior *(created by 03-02 Task 2)*
- [x] `backend/tests/test_migration_002.py` — new test file: idempotent migration application + UNIQUE constraint behavior with NULL `source_mapillary_id` *(created by 03-01 Task 3)*

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

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
