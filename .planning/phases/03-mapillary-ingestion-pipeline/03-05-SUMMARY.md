---
phase: 03-mapillary-ingestion-pipeline
plan: 05
subsystem: documentation
tags: [documentation, operator-runbook, sc4, phase-6-handoff, cc-by-sa]

# Dependency graph
requires:
  - phase: 03-mapillary-ingestion-pipeline
    plan: 01
    provides: |
      db/migrations/002_mapillary_provenance.sql (apply procedure
      documented), source/source_mapillary_id columns + UNIQUE INDEX
      uniq_defects_segment_source_severity (idempotency narrative).
  - phase: 03-mapillary-ingestion-pipeline
    plan: 02
    provides: |
      scripts/compute_scores.py --source {synthetic|mapillary|all}
      flag (SC #4 demo workflow toggles between synthetic and
      mapillary; auto-recompute uses --source all).
  - phase: 03-mapillary-ingestion-pipeline
    plan: 03
    provides: |
      scripts/ingest_mapillary.py 10 base flags (--segment-ids,
      --segment-ids-file, --where, --snap-meters, --pad-meters,
      --limit-per-segment, --cache-root, --no-keep, --json-out, -v) +
      Pattern 6 trust model for --where + the four exit codes (D-18).
  - phase: 03-mapillary-ingestion-pipeline
    plan: 04
    provides: |
      scripts/ingest_mapillary.py 3 cutover flags (--wipe-synthetic,
      --force-wipe, --no-recompute) with wipe-after-detect-before-INSERT
      ordering, auto-recompute default, and the run-summary keys
      (wipe_synthetic_applied, recompute_invoked, rows_skipped_idempotent,
      synthetic_rows_wiped). The runbook's flag table reflects the
      shipped 13-flag inventory verbatim.
provides:
  - "docs/MAPILLARY_INGEST.md operator runbook (398 lines, 12 ## sections) covering: prerequisites, migration apply, CLI reference (13 flags + 4 exit codes), --where trust model with explicit forbidden-token enumeration, idempotency narrative, CC-BY-SA provenance + manifest mechanism, SC #4 ranking-comparison demo workflow, Phase 6 public-demo cutover sequence, 8 RESEARCH-pitfall-mapped gotchas, out-of-scope deferral list, internal+external references"
  - "README.md ## Real-Data Ingest section between ## Detector Accuracy and ## Frontend Pages, plus a docs/MAPILLARY_INGEST.md entry in ## Documentation alongside docs/DETECTOR_EVAL.md (consistency)"
  - "## Phase 6 public-demo cutover heading is the load-bearing forward-flag for plan 06; preserved verbatim and grep-targetable"
affects: [06-public-deploy-cutover]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Operator-runbook style mirrored from docs/DETECTOR_EVAL.md: ATX (#/##/###) headings, fenced code blocks for every paste-runnable command, comparison tables for flag references and gotchas (readers scan, they do not read line-by-line)"
    - "Forward-flag heading convention: a literal heading (## Phase 6 public-demo cutover) is named in this plan AND in plan 06's grep gauntlet, so renaming the heading would break the cross-plan reference and is caught at plan-boot"
    - "Trust-model-as-documentation: --where's regex blocklist is the documentation of the trust model, NOT the security primitive (psycopg2.sql.SQL is). The runbook enumerates the rejected token classes explicitly so operators learn what the regex blocks"

key-files:
  created:
    - docs/MAPILLARY_INGEST.md
  modified:
    - README.md

key-decisions:
  - "Mirrored docs/DETECTOR_EVAL.md's markdown style (ATX headings, code-block conventions, table layouts) -- the project already has one operator-facing demo doc and adopting the same shape minimizes reader cognitive load when they cross-reference between the two"
  - "Section ordering keeps prerequisites + migration first (operator's blocking actions), CLI reference + trust model in the middle (the surface), demo + cutover near the end (the headline workflows), gotchas last (the asymmetric-failure-cost reference). This is the order an operator hits problems in"
  - "Both demo (## SC #4 ranking-comparison demo workflow) and cutover (## Phase 6 public-demo cutover) headings are load-bearing for cross-plan references and were committed verbatim. Plan 06's plan-author should grep for these"
  - "## Real-Data Ingest in README inserted between ## Detector Accuracy and ## Frontend Pages -- the same insertion-point convention Phase 2 used for ## Detector Accuracy. README ## Documentation also gets a docs/MAPILLARY_INGEST.md entry adjacent to docs/DETECTOR_EVAL.md so the doc-list ordering matches the section ordering"
  - "Out-of-scope section explicitly enumerates the 7 deferred items from 03-CONTEXT.md (per-class confidence calibration, heading filter, --bbox auto-tile-sweep, named target sets, segment_defects_synthetic separate table, deleted_at soft-delete, continuous CI gate) plus a note that REQ-user-auth (Phase 4) is N/A for this CLI -- so operators don't try to invent these features"
  - "Manual-only verifications (live Mapillary smoke + SC #4 archival run) are intentionally NOT automated by this plan -- they require an external token + live API + visual demo recording. The runbook is the artifact that makes those manual verifications reproducible"

patterns-established:
  - "operator-runbook-section-template: prerequisites -> migration apply -> CLI reference (target modes / options / exit codes) -> trust model -> idempotency -> provenance/licensing -> headline workflow -> deploy cutover -> gotchas -> out-of-scope -> references. Reusable for future CLIs with similar surface complexity"
  - "load-bearing-heading-as-cross-plan-anchor: ## Phase 6 public-demo cutover is named in 03-05 AND plan 06's must-haves. A rename in either side breaks the contract. This pattern lets future plans grep-target sections without an external registry"

requirements-completed: []
# REQ-mapillary-pipeline is the parent requirement; final completion stamp
# is owned by the orchestrator after all phase-3 plans merge. The runbook is
# a documentation deliverable inside that requirement.

# Metrics
duration: ~25min
completed: 2026-04-25
---

# Phase 03 Plan 05: Operator Runbook + README Entry Point Summary

**Shipped `docs/MAPILLARY_INGEST.md` (398 lines, 12 ## sections) covering the entire `scripts/ingest_mapillary.py` operator surface end-to-end — prerequisites, migration apply, all 13 flags, `--where` trust model, idempotency narrative, CC-BY-SA provenance mechanism, the canonical SC #4 ranking-comparison demo workflow, the Phase 6 public-demo cutover sequence, 8 RESEARCH-pitfall-mapped gotchas — and added a `## Real-Data Ingest` section to `README.md` linking to it, closing the operator-readable loop on REQ-mapillary-pipeline.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-04-25T22:08:00Z (worktree setup + reads)
- **Completed:** 2026-04-25T22:33:00Z
- **Tasks:** 2 (runbook + README entry)
- **Files created:** 1 (`docs/MAPILLARY_INGEST.md`, 398 lines)
- **Files modified:** 1 (`README.md`, +23 / -0)

## Final Section List of `docs/MAPILLARY_INGEST.md`

The 12 top-level (`##`) headings, in order. Phase 6's plan-author will reference these:

1. `## What this pipeline does`
2. `## Prerequisites`
3. `## Applying the migration`
4. `## CLI reference`
5. `## Trust model for --where`
6. `## Idempotency`
7. `## Provenance and licensing`
8. `## SC #4 ranking-comparison demo workflow`
9. `## Phase 6 public-demo cutover` ← **load-bearing forward-flag for plan 06**
10. `## Common gotchas`
11. `## What this pipeline does NOT do (out of scope)`
12. `## References`

H1 title: `# Mapillary Ingestion Pipeline — Operator Runbook`
H3 subsections inside `## CLI reference`: `### Target modes (mutually exclusive, one required)`, `### Options`, `### Exit codes`
H3 subsections inside `## Applying the migration`: `### Fresh dev DB`, `### Existing dev DB`

## README.md Insertion Point

The new `## Real-Data Ingest` section is inserted at line 140 of `README.md`:

- **Predecessor:** `## Detector Accuracy` (lines 117–138) — closing prose ends at line 138, blank line at 139
- **New section:** lines 140–161 (`## Real-Data Ingest` + 4 paragraphs + 1 fenced code block)
- **Successor:** `## Frontend Pages` (line 162)

A second additive change appended `docs/MAPILLARY_INGEST.md` to the existing `## Documentation` bullet list (line 188), adjacent to the existing `docs/DETECTOR_EVAL.md` entry (line 187). This consistency rule is documented in Task 2's `<action>` block: "if `docs/DETECTOR_EVAL.md` IS listed in `## Documentation`, also add `docs/MAPILLARY_INGEST.md` adjacent to it for consistency."

Net README diff: 23 insertions, 0 deletions. Top-level section count: 9 → 10.

## Forward-Flag Confirmation

`## Phase 6 public-demo cutover` (heading text exact-matched, no rename) is the load-bearing forward-flag for plan 06's deploy cutover documentation. Plan 06's plan-author can:

```bash
grep -A 50 "^## Phase 6 public-demo cutover" docs/MAPILLARY_INGEST.md
```

to extract the canonical 4-step sequence: (1) apply migration to cloud DB, (2) ingest with `--wipe-synthetic`, (3) `POST /cache/clear` against the deployed API, (4) smoke a `/route` request and verify `pothole_score_total > 0`. The "do not re-run `seed_data.py` on the demo DB after cutover" warning is also inside this section.

The plan's threat model (T-03-24: "Phase 6 plan-author can't find the cutover sequence") is mitigated by this naming contract.

## Phase 3 Manual-Only Verifications Still Outstanding

Per `.planning/phases/03-mapillary-ingestion-pipeline/03-VALIDATION.md` (Manual-Only Verifications table), two operator actions still require a live environment and are NOT automated by this plan or any prior plan in Phase 3:

| Verification | What's needed | Why it's manual |
|--------------|---------------|-----------------|
| Live Mapillary smoke run | Operator with `MAPILLARY_ACCESS_TOKEN`, a running stack, and a target segment list runs `python scripts/ingest_mapillary.py --segment-ids <real LA ids> --limit-per-segment 5` end-to-end and confirms `rows_inserted > 0`, `manifest-*.json` written, `/segments` returns `pothole_score_total > 0` for the affected segment(s) | Requires live Mapillary API + valid token + running DB; no mock harness can prove the integration is wired correctly all the way to the network boundary |
| SC #4 archival demo | Operator runs the 5-step SC #4 workflow from this runbook (`compute_scores.py --source synthetic` then `--source mapillary`, `/route` POSTs, `diff` of the two `total_cost` snapshots) and archives `/tmp/synthetic-cost.txt` + `/tmp/mapillary-cost.txt` for the demo recording | The mechanical proof is in `backend/tests/test_integration.py::test_route_ranks_differ_by_source` (shipped in plan 03-04); the visual proof requires a live demo + recording for the public-demo claim |

Both are now reproducible from this runbook alone — that was the entire point of plan 03-05. The operator does not need to consult any other doc to perform either verification.

## Task Commits

Each task was committed atomically (no-verify per parallel-executor protocol):

1. **Task 1: docs/MAPILLARY_INGEST.md operator runbook** — `6dea016` (docs)
2. **Task 2: README.md ## Real-Data Ingest section + Documentation list entry** — `54b58e8` (docs)

Plan-level metadata (this SUMMARY.md) is committed as the third commit.

## Verification Run

| Check | Command | Result |
|-------|---------|--------|
| File exists | `test -f docs/MAPILLARY_INGEST.md` | OK |
| Line count >= 100 | `test $(wc -l < docs/MAPILLARY_INGEST.md) -gt 100` | 398 lines |
| Section count >= 12 | `grep -c "^## " docs/MAPILLARY_INGEST.md` | 12 |
| Balanced fences | `python3 -c "t=open('docs/MAPILLARY_INGEST.md').read(); assert t.count('` + chr(96)*3 + `') % 2 == 0"` | balanced |
| MAPILLARY_ACCESS_TOKEN present | `grep -q "MAPILLARY_ACCESS_TOKEN" docs/MAPILLARY_INGEST.md` | match |
| Migration filename present | `grep -q "002_mapillary_provenance.sql" docs/MAPILLARY_INGEST.md` | match |
| --wipe-synthetic documented | `grep -q "wipe-synthetic" docs/MAPILLARY_INGEST.md` | match |
| --source synthetic documented | `grep -q "source synthetic" docs/MAPILLARY_INGEST.md` | match |
| --source mapillary documented | `grep -q "source mapillary" docs/MAPILLARY_INGEST.md` | match |
| Phase 6 cutover heading | `grep -q "Phase 6 public-demo cutover" docs/MAPILLARY_INGEST.md` | match |
| SC #4 demo heading | `grep -q "SC #4 ranking-comparison demo workflow" docs/MAPILLARY_INGEST.md` | match |
| CC-BY-SA license | `grep -q "CC-BY-SA" docs/MAPILLARY_INGEST.md` | match |
| Trust model section | `grep -q "Trust model" docs/MAPILLARY_INGEST.md` | match |
| Common gotchas section | `grep -q "Common gotchas" docs/MAPILLARY_INGEST.md` | match |
| Cache layout reference | `grep -q "data/ingest_la" docs/MAPILLARY_INGEST.md` | match |
| max_segments cap reference | `grep -q "max_segments" docs/MAPILLARY_INGEST.md` | match |
| All 13 flags documented | `for f in --segment-ids --segment-ids-file --where --snap-meters --pad-meters --limit-per-segment --cache-root --no-keep --json-out --wipe-synthetic --force-wipe --no-recompute --verbose; do grep -q -- "$f" docs/MAPILLARY_INGEST.md; done` | 13/13 |
| README has Real-Data Ingest | `grep -q "## Real-Data Ingest" README.md` | match |
| README links to runbook | `grep -q "docs/MAPILLARY_INGEST.md" README.md` | match |
| README mentions token | `grep -q "MAPILLARY_ACCESS_TOKEN" README.md` | match |
| README sections count | `grep -c "^## " README.md` | 10 (was 9) |
| Pure-additive README | `git diff --numstat HEAD~1 README.md` | 23 insertions, 0 deletions |
| Section ordering | `grep -n "^## " README.md \| grep -B1 -A1 "Real-Data Ingest"` | Real-Data Ingest is between Detector Accuracy and Frontend Pages |

## Decisions Made

- **Mirrored docs/DETECTOR_EVAL.md's markdown style.** ATX (`#/##/###`) headings, fenced code blocks for every paste-runnable command, comparison tables for flag references and gotchas. The project already has one operator-facing demo doc — adopting the same shape minimizes reader cognitive load when they cross-reference between the two. Verified by spot-checking heading depth, code-block fencing, and table-vs-prose ratio against `docs/DETECTOR_EVAL.md`.
- **Section ordering puts blocking actions first.** Prerequisites + migration apply come immediately after the intro because an operator who hasn't done these cannot do anything else. The CLI reference + trust model are in the middle (the API surface). Demo + cutover are near the end (the headline workflows). Gotchas are last because they are an asymmetric-failure-cost reference, not a linear-read section.
- **Both `## SC #4 ranking-comparison demo workflow` and `## Phase 6 public-demo cutover` are load-bearing headings.** Plan 06's plan-author will grep for these. Renaming either would break the cross-plan reference. Acceptance criteria assert exact match.
- **Quick-start in README's `## Real-Data Ingest` is one fenced bash block, not three.** The runbook itself has the full set of CLI invocations. The README job is to point at the runbook, not duplicate it.
- **Out-of-scope section enumerated explicitly.** All 7 items from `03-CONTEXT.md`'s `<deferred>` block are listed verbatim, plus a Phase 4 auth-gate N/A note. This prevents an operator from looking for a `--bbox` mode or a `deleted_at` soft-delete column that doesn't exist.
- **Phase 6 cutover documents `POST /cache/clear` explicitly.** Plan 03-04's threat model accepted T-03-21 (cache-staleness race) as an operator concern; this runbook is where it gets closed. The cutover sequence has a dedicated step for it.
- **Trust model section enumerates rejected token classes verbatim.** Pattern 6 in 03-RESEARCH.md is the source. The runbook reproduces the exact list (DDL/DML keywords, system catalogs, statement separators, comment markers) so operators learn what the regex blocks without having to read the source. T-03-26 mitigation.

## Deviations from Plan

### None

The plan executed exactly as written. Both tasks landed at first commit:

- Task 1's 13-string grep gauntlet passed on first run (no iteration needed).
- Task 2's section ordering, link presence, and pure-additive constraints were all satisfied by the single Edit operation.
- The optional Documentation-list addition was triggered (since `docs/DETECTOR_EVAL.md` IS listed in the existing `## Documentation` block) and applied as a second Edit in the same task.

No auto-fixes (Rules 1-3) needed. No checkpoints hit. No architectural questions surfaced (Rule 4).

## Issues Encountered

None.

This plan is pure-documentation; the previous worktree's timeout was unrelated to plan content (likely a session-level issue, not a code/file blocker). On this fresh attempt:

- Both target files are markdown — no Python runtime / Docker / DB needed.
- Verification gauntlet is shell-grep only; no test runner involved.
- Both task commits succeeded `--no-verify` (parallel-executor protocol).

## User Setup Required

None.

This is documentation only. No new dependencies, no new env vars, no new ports. Existing `MAPILLARY_ACCESS_TOKEN` documentation (plan 03-03) is now linked from the README's `## Real-Data Ingest` section as the operator's blocking action before clicking through to the runbook.

## Next Phase Readiness

**Plan 06-public-deploy-cutover** can now reference the runbook directly:

- `docs/MAPILLARY_INGEST.md ## Phase 6 public-demo cutover` is the canonical 4-step sequence. Plan 06's plan-author can either:
  1. Grep-extract the section verbatim into the deploy-runbook plan, OR
  2. Cite the URL directly and let the public-demo plan focus on the cloud-host-specific deltas (CORS lock-down, auth gate, secret rotation).
- The wipe-guard (`--wipe-synthetic` + `--force-wipe`) is documented as a forward-flag with explicit safety semantics; plan 06 does NOT need to re-document the wipe — only the cloud-deploy sequence around it.
- The `POST /cache/clear` step is documented as part of the cutover; plan 06 only needs to confirm the cloud API exposes the same admin endpoint with the same shape.

**Operator-facing manual verifications** (Phase 3 VALIDATION.md):

- Live Mapillary smoke run is now reproducible from `docs/MAPILLARY_INGEST.md` Prerequisites + CLI reference + Quick-start example in README.
- SC #4 archival run is now reproducible from `docs/MAPILLARY_INGEST.md ## SC #4 ranking-comparison demo workflow` (5-step sequence with literal `curl` template + `jq` pipeline).

No blockers. Phase 3 is feature-complete pending the orchestrator's roadmap merge.

## Self-Check: PASSED

Verified post-write:

- `docs/MAPILLARY_INGEST.md` — FOUND (398 lines, 12 ## sections, balanced code fences)
- `README.md` — modified (23 insertions, 0 deletions, 10 sections)
- Commit `6dea016` (Task 1) — FOUND in `git log`
- Commit `54b58e8` (Task 2) — FOUND in `git log`
- All 13 Task 1 grep gauntlet strings — match
- All 5 Task 2 acceptance criteria — pass
- All 13 ingest_mapillary.py CLI flags — present in runbook
- `## Phase 6 public-demo cutover` heading — exact match, load-bearing forward-flag preserved
- `## SC #4 ranking-comparison demo workflow` heading — exact match
- No deferred features positively documented (per-image bbox, --bbox mode, deleted_at all absent or in out-of-scope)
- Pure-additive on README (no prior content removed; verified by `git diff --numstat`)

## TDD Gate Compliance

Plan-level type is `execute`, NOT `tdd`. Both tasks are `type="auto"` (not `tdd="true"`). Documentation tasks do not have a RED/GREEN/REFACTOR cycle — the verification gauntlet (greps + section count + fence balance + acceptance criteria) IS the test, and it ran successfully against both commits.

No gate sequence required.

---
*Phase: 03-mapillary-ingestion-pipeline*
*Plan: 05*
*Completed: 2026-04-25*
