---
phase: 02-real-data-detector-accuracy
plan: 05
subsystem: docs
tags: [docs, ml, eval, readme, yaml, licensing, security]

# Dependency graph
requires:
  - phase: 02-real-data-detector-accuracy (Plan 01)
    provides: "_DEFAULT_HF_REPO + _resolve_model_path in data_pipeline.detector_factory — cited in DETECTOR_EVAL.md Security section as the default-publisher mitigation and the @<revision> pinning surface"
  - phase: 02-real-data-detector-accuracy (Plan 02)
    provides: "scripts/eval_detector.py CLI + JSON report schema + per-image CI degeneracy caveat — referenced verbatim in DETECTOR_EVAL.md Reproduction section (step 5) and Methodology section (caveat)"
  - phase: 02-real-data-detector-accuracy (Plan 03)
    provides: ".gitignore !data/eval_la/data.yaml un-ignore rule (already in place) — makes the Task-1 seed commit land as tracked content; scripts/fetch_eval_data.py --verify-only default referenced in Reproduction step 3"
  - phase: 02-real-data-detector-accuracy (Plan 04)
    provides: "docs/FINETUNE.md + scripts/finetune_detector.py --push-to-hub — cross-linked from DETECTOR_EVAL.md Reproduction (step 4) and README '## Detector Accuracy' + Documentation list; 'After Training' invocation copied into Reproduction step 5"
provides:
  - "docs/DETECTOR_EVAL.md — operator-facing writeup (D-10, ROADMAP SC #4) with methodology, TBD metric placeholders, caveats, reproduction, security, licensing, changelog — ready for Phase 6 public demo to cite"
  - "data/eval_la/data.yaml — committed YOLO single-class seed (nc=1, names[0]=pothole) for reproducibility; git-tracked via existing !data/eval_la/data.yaml un-ignore rule"
  - "README.md '## Detector Accuracy' section + 2 new Documentation-list bullets — first-stop link graph for new visitors"
affects: [06-public-demo, 05-production-readiness]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Writeup-as-citation-target: docs/DETECTOR_EVAL.md lives at a stable path (docs/) so the public demo and HF model card can link to it without restructuring"
    - "TBD-placeholder discipline: methodology + structure fixed now; numbers populated after first real fine-tune + eval pass via manual substitution from eval_report.json (auto-substitution formatter deferred)"
    - "Committed YOLO data.yaml seed + selective .gitignore: large image/label content stays excluded, schema file (nc, names, split paths) is tracked so downstream eval contracts are stable even on a fresh clone"
    - "Doc-to-CLI one-liner discipline: every Reproduction step shows the exact command + exit-code semantics, matching the invocation forms already tested by backend/tests/test_eval_detector.py + test_fetch_eval_data.py + test_finetune_detector.py"

key-files:
  created:
    - data/eval_la/data.yaml
    - docs/DETECTOR_EVAL.md
  modified:
    - README.md

key-decisions:
  - "data.yaml comment block references _map_severity confidence thresholds verbatim (0.7/0.4) so downstream consumers who read the YAML alone know how severity is derived without reading Python source"
  - "DETECTOR_EVAL.md includes a dedicated 'Caveat: per-image CI degeneracy' subsection under Methodology — honors Plan 04 executor's flag about Plan 02's _collect_per_image_counts aggregated-bucket fallback"
  - "Pickle ACE risk (T-02-01) gets its own subsection in Section 5 (Security), not just a one-liner; mitigations enumerate _DEFAULT_HF_REPO, @<revision> pinning, and upstream weights_only=True tracking"
  - "License chain tabled as 5 rows (Mapillary imagery, labels, base model, fine-tuned weights, service code) — makes the AGPL-3.0 reach question (A8) visually obvious without burying it in prose"
  - "README section placed between API Endpoints and Frontend Pages (not at bottom) — detector accuracy is API-adjacent product surface; existing section ordering preserved otherwise"

requirements-completed: [REQ-real-data-accuracy]

# Metrics
duration: ~3min
completed: 2026-04-24
---

# Phase 2 Plan 05: Publish Eval Writeup Summary

**D-10 writeup at docs/DETECTOR_EVAL.md (291 lines, 7 sections, TBD placeholders preserved) plus committed data/eval_la/data.yaml seed plus README '## Detector Accuracy' section linking both — ROADMAP SC #4 satisfied, public demo citation path ready.**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-04-24T02:38:27Z
- **Completed:** 2026-04-24T02:41:58Z
- **Tasks:** 3 / 3 complete
- **Files created:** 2 (data.yaml seed + DETECTOR_EVAL.md)
- **Files modified:** 1 (README.md)
- **Total lines added:** 337 (21 yaml + 291 md + 25 readme)

## Accomplishments

- `data/eval_la/data.yaml` (21 LOC) committed with single-class pothole schema (nc=1, names[0]=pothole, train/val/test paths). Header comment block references `_map_severity` confidence thresholds (0.7 severe, 0.4 moderate, drop below) verbatim so readers can understand severity derivation from the YAML alone. Plan 03's existing `!data/eval_la/data.yaml` un-ignore rule makes the file git-tracked automatically; `git check-ignore -q data/eval_la/data.yaml` exits 1 (not ignored).
- `docs/DETECTOR_EVAL.md` (291 LOC) ships TL;DR + seven numbered sections (Methodology, Results, Caveats, Reproduction, Security, Licensing, Changelog). Methodology fixed, metric cells are TBD placeholders substituted manually from `eval_report.json` after the first real fine-tune + eval pass. Every Plan 04 executor flag is honored:
  - **Pickle ACE risk (T-02-01)** called out in Section 5 with `_DEFAULT_HF_REPO` + `@<revision>` pinning mitigations (Pitfall 8)
  - **docs/FINETUNE.md** linked from Section 4 as the reproduction entry point (no recipe duplication)
  - **Per-image CI degeneracy caveat** documented in Section 1 (Methodology → Caveat subsection) and Section 3
  - **Exact `YOLO_MODEL_PATH=... eval_detector.py --split test` invocation** from FINETUNE.md's "After Training" reproduced in Reproduction step 5
- `README.md` gains `## Detector Accuracy` section between `## API Endpoints` and `## Frontend Pages` with a three-line methodology summary, copy-pasteable `fetch_eval_data.py` + `eval_detector.py` commands, and a `YOLO_MODEL_PATH` configuration pointer. Documentation list extended with `docs/DETECTOR_EVAL.md` and `docs/FINETUNE.md` bullets (4 → 6 total). Section ordering preserved everywhere else.
- `pytest backend/tests/ -q` — 131 passed / 6 skipped / 0 failed (Phase 2 aggregate smoke; 6 skips are live-DB integration tests that auto-skip when DB is down, unchanged from prior plans).

## Task Commits

Each task was committed atomically (`--no-verify` per parallel-executor protocol):

1. **Task 1: Commit data/eval_la/data.yaml single-class YOLO seed** — `81ae8b0` (feat)
2. **Task 2: Author docs/DETECTOR_EVAL.md LA evaluation report** — `ffa4bd7` (docs)
3. **Task 3: Update README with Detector Accuracy section + doc links** — `31669b8` (docs)

All three commits sit on `worktree-agent-a5c69536` branched from `55002fd` (phase-02 wave-3-merged base).

## Files Created/Modified

### Created

- `data/eval_la/data.yaml` (21 LOC) — single-class YOLO dataset config. Public surface consumed by `scripts/eval_detector.py`, `scripts/finetune_detector.py`, and `scripts/fetch_eval_data.py --build` (which regenerates the file but preserves `nc` + `names`). Header comment pins severity-from-confidence rules so the YAML is self-documenting.
- `docs/DETECTOR_EVAL.md` (291 LOC) — operator + public-demo writeup. Section map (1-indexed lines):
  - Lines 1-9: title + Version/Last Updated/Status header
  - Lines 11-38: TL;DR (dataset + base model + metric placeholder table + severity breakdown)
  - Lines 42-98: Section 1 — Methodology (Dataset, Metrics, Image-level bootstrap rationale, Per-image CI degeneracy caveat)
  - Lines 102-129: Section 2 — Results (headline + per-severity + eval config tables with TBD cells)
  - Lines 133-158: Section 3 — Caveats & Limitations (7 bullets + deferred-items pointer)
  - Lines 162-209: Section 4 — Reproduction (6-step clean-checkout recipe)
  - Lines 213-243: Section 5 — Security (pickle ACE + mitigations + token handling + SHA256 compare_digest)
  - Lines 247-281: Section 6 — Licensing & Attribution (5-row license table + A8 risk flag + attribution requirements)
  - Lines 285-287: Section 7 — Changelog (v0.1.0 entry)
  - Lines 290-292: operator-voice footer

### Modified

- `README.md` (+25 LOC; no existing content modified):
  - After existing `### GET /segments...` block (line 115), inserted new `## Detector Accuracy` section (lines 117-138) with one-paragraph methodology, `fetch_eval_data.py` + `eval_detector.py` copy-pasteable commands, and `YOLO_MODEL_PATH` config note. Blank line before `## Frontend Pages` preserved.
  - In `## Documentation` section (after existing 4 bullets), appended 2 new bullets: `[Detector Accuracy Report](docs/DETECTOR_EVAL.md)` and `[Fine-Tuning Guide](docs/FINETUNE.md)`.

## Decisions Made

- **data.yaml comment block documents severity thresholds at the YAML level**, not just in the Python source. Anyone who opens `data/eval_la/data.yaml` in isolation (e.g. a CVAT operator preparing to label) sees why severity is derived from confidence rather than a second class. Duplicates one line from `yolo_detector.py::_map_severity` but is explicitly flagged in the comment ("severity is derived from confidence at inference time per data_pipeline/yolo_detector.py::_map_severity").
- **DETECTOR_EVAL.md places the per-image CI degeneracy caveat in Methodology Section 1 AND Caveats Section 3.** The caveat is both a methodology choice (how bootstrap is computed) and a limitation (when it fails). Mentioning it twice under different framings costs ~5 lines and makes it hard to miss.
- **Pickle ACE mitigations enumerated as 3 bullets, not prose.** Readers scanning the Security section need to see the attack surface (`.pt` = pickle = RCE), the current defense (default HF publisher trust), and the production hardening step (`@<revision>` pin) in that order. Bullets make the escalation ladder obvious.
- **License table is 5 rows, not 3.** The short version (Mapillary CC-BY-SA + base model AGPL + fine-tuned AGPL) obscures the middle-layer questions: what license do the label .txt files inherit? What about the service code that loads the model at runtime? Explicit rows for "Labels" and "Service code" close those gaps.
- **README section placed mid-document (between API Endpoints and Frontend Pages), not at bottom.** Detector accuracy is API-adjacent product surface (the backend exposes detection outputs). Existing heading order is preserved everywhere else per plan `<acceptance_criteria>`.
- **Awk acceptance-criterion quirk noted (not fixed).** Plan 03 Task 3's acceptance criterion `awk '/^## Documentation/,/^##[^#]/ { if (/^- /) print }' README.md | wc -l` relies on a trailing `##` heading after Documentation, but Documentation is the last section — so the range never closes and awk returns 0. The intent (>=6 bullets after Documentation) is satisfied (6 bullets verified via `awk '/^## Documentation/{flag=1; next} flag && /^- /'`). No README change needed; plan-generator's awk snippet is the issue.

## Deviations from Plan

None — plan executed exactly as written. Task 1 (data.yaml), Task 2 (DETECTOR_EVAL.md), and Task 3 (README) all landed with their specified shapes. No Rule 1/2/3 auto-fixes triggered and no Rule 4 architectural checkpoints required.

**Total auto-fixes:** 0 (Rule 1 bugs, Rule 2 missing critical functionality, Rule 3 blocking issues).
**Total architectural checkpoints:** 0 (Rule 4).
**Impact on plan scope:** Zero — all three tasks landed with their specified acceptance criteria intact.

## Issues Encountered

- **Python 3.9.6 host `python3` gap** (same issue every prior Plan 02 executor flagged): worktree host `/usr/bin/python3` is 3.9, which chokes on `backend/tests/conftest.py` (transitively imports `backend/app/cache.py` with PEP 604 `dict | None` syntax). Resolution: reused `/tmp/rq-venv` (Python 3.12.13 venv) created by Plan 01's executor — already populated with `pytest pyyaml pillow numpy scipy huggingface_hub` by prior plans. Only used for yaml-shape verification and pytest smoke. No project file touched; no new deps installed.
- **Awk range-expression acceptance criterion quirk** (noted under Decisions Made). Plan's literal awk command returns 0 because Documentation is the last section. Verified the criterion intent via a one-sided awk expression instead (`awk '/^## Documentation/{flag=1; next} flag && /^- /'` returned 6). Not a deviation — plan-generator's acceptance syntax is the issue, not the README structure.

## Known Stubs

The TBD-placeholder cells in `docs/DETECTOR_EVAL.md` Sections "TL;DR" and 2 (Results) are **intentional**, not stubs:

- The plan explicitly states numbers are populated from `eval_report.json` after the first real fine-tune + eval pass (per `docs/FINETUNE.md` "After Training").
- Fine-tuning requires 300 hand-labelled Mapillary LA images — an operator task performed post-Phase-2-merge (CONTEXT.md `deferred_ideas` + Plan 03 SUMMARY `User Setup Required`).
- The "Results" section heading explicitly says "*Populated from `eval_report.json`...*" so readers know cells are intentionally empty.
- Plan `<output>` requires a runbook entry for this substitution (see "Operator runbook" below); runbook is part of this SUMMARY, not a stub in the document.

This is a designed placeholder pattern, not a wiring gap.

## Threat Flags

None. Every threat enumerated in the plan's `<threat_model>` (T-02-28, T-02-29, T-02-30, T-02-31) is either accepted with documented rationale (T-02-28/29/31) or mitigated by structural means (T-02-30: Section 6 tables CC-BY-SA + AGPL chain with propagation rules). No new security-relevant surface introduced beyond what the plan enumerates — Plan 05 is document-heavy and adds no new code paths, network endpoints, auth paths, file access patterns, or schema changes at trust boundaries.

## Operator Runbook (post-first-fine-tune)

Per plan `<output>` directive. When the operator completes the first real fine-tune + eval pass:

1. **Run the eval** with the published fine-tune:
   ```bash
   YOLO_MODEL_PATH=<user>/road-quality-la-yolov8@<commit_sha> \
   python scripts/eval_detector.py --data data/eval_la/data.yaml --split test \
       --json-out eval_report.json
   ```
2. **Substitute TBD cells in DETECTOR_EVAL.md Section 2.** Read `eval_report.json` and manually fill:
   - Headline table: `precision`, `recall`, `map50` + `precision_ci_95[0]`/`[2]`, `recall_ci_95[0]`/`[2]`
   - Per-severity counts table: `per_severity.moderate.count`, `per_severity.severe.count`, `per_severity.dropped.count`
   - TL;DR tables (top-of-doc): same metric values
   - Changelog section: add new entry with date + version bump to `v0.2.0`
3. **Update `_DEFAULT_HF_REPO`** in `data_pipeline/detector_factory.py` to point at the published fine-tune with a pinned revision (Pitfall 8 discipline):
   ```python
   _DEFAULT_HF_REPO = "<user>/road-quality-la-yolov8@<commit_sha>"
   ```
4. **Run `pytest backend/tests/` -q** — should still be green (131 passed / 6 skipped). If `test_detector_factory.py` regressed because the default constant changed, update the test's expected default string.
5. **Re-read README '## Detector Accuracy'** — the YOLO_MODEL_PATH example still works because the commit_sha syntax is already documented.
6. **Commit:** `docs(detector-eval): populate v0.2.0 numbers from <commit_sha> fine-tune`

This runbook is reproducible by any operator with the published fine-tune + `HUGGINGFACE_TOKEN` (for `--push-to-hub` in future re-trains) or just the public HF model for eval-only.

## User Setup Required

None for this plan. Future operator work is the TBD-cell substitution runbook above, which requires:

1. A populated `data/eval_la/` (delivered by Plan 03's `fetch_eval_data.py --build` + hand-labeling)
2. A fine-tuned model on HF (delivered by `scripts/finetune_detector.py --push-to-hub` per Plan 04)
3. A successful `scripts/eval_detector.py --json-out eval_report.json` run

None of the three is a Plan-05 deliverable; they are operator tasks performed post-merge.

## Next Phase Readiness

- **Phase 6 (public demo)** — ROADMAP SC #4 satisfied. Demo landing page can cite `docs/DETECTOR_EVAL.md` by stable path; numbers will be substituted by the operator before public launch per the runbook above. The writeup is methodology-fixed, so even without populated numbers it's defensibly citable ("see docs/DETECTOR_EVAL.md for methodology"). TBD cells honestly signal "numbers coming" rather than hiding weakness.
- **Phase 5 (production readiness)** — `YOLO_MODEL_PATH=<user>/repo@<commit_sha>` pinning discipline is now documented in two places (README + DETECTOR_EVAL.md Section 5); production deploys can reference either. The AGPL-3.0/CC-BY-SA license chain (Section 6) is the legal-review input if commercialization is ever considered.
- **Model card continuity** — `scripts/finetune_detector.py::_build_model_card` (Plan 04) already embeds AGPL-3.0 + CC-BY-SA attribution per the chain documented here. `docs/DETECTOR_EVAL.md` Section 6 and the model card now describe the same attribution graph; they must stay in sync if either is updated. (Flagged for future cross-ref.)
- **CI gate on detector accuracy (deferred)** — the plan's `<deferred>` block lists this; `scripts/eval_detector.py --min-precision` / `--min-recall` (Plan 02) is the mechanism. Adding a CI job that runs the eval CLI against a pinned fine-tune + pinned data.yaml + a minimum-metric floor is ~20 lines of GitHub Actions; deferred to post-M1.

## Phase 2 Aggregate

This plan closes Phase 2's documentation track. Across five plans:

- **Plan 01** — detector_factory env-var resolution (_DEFAULT_HF_REPO + _resolve_model_path)
- **Plan 02** — eval harness (scripts/eval_detector.py + data_pipeline/eval.py + fixtures)
- **Plan 03** — LA dataset tooling (data_pipeline/mapillary.py + scripts/fetch_eval_data.py + manifest skeleton)
- **Plan 04** — fine-tune CLI + reproduction guide (scripts/finetune_detector.py + docs/FINETUNE.md)
- **Plan 05** — eval writeup + README wiring (docs/DETECTOR_EVAL.md + data/eval_la/data.yaml + README section)

Phase 2's `REQ-real-data-accuracy` is structurally complete: tooling + methodology + reproduction path + writeup shipped. Actual number-substitution is the operator runbook above, which is deliberately factored as a post-merge activity so Phase 2 can close without blocking on a 300-image hand-label effort.

## Self-Check: PASSED

Verified post-write:

```
$ test -f data/eval_la/data.yaml                                 → FOUND
$ test -f docs/DETECTOR_EVAL.md                                  → FOUND
$ [ $(wc -l < docs/DETECTOR_EVAL.md) -ge 150 ]                   → 291 (pass)
$ grep -q "^## Detector Accuracy$" README.md                     → OK
$ git log --oneline | grep 81ae8b0                               → FOUND (Task 1)
$ git log --oneline | grep ffa4bd7                               → FOUND (Task 2)
$ git log --oneline | grep 31669b8                               → FOUND (Task 3)
$ /tmp/rq-venv/bin/python -c "import yaml; d=yaml.safe_load(open('data/eval_la/data.yaml')); assert d['nc']==1 and d['names'][0]=='pothole'"   → OK
$ grep -c "^## [1-7]\\." docs/DETECTOR_EVAL.md                   → 7
$ grep -q "pickle" docs/DETECTOR_EVAL.md                         → OK
$ grep -q "CC-BY-SA" docs/DETECTOR_EVAL.md                       → OK
$ grep -q "AGPL" docs/DETECTOR_EVAL.md                           → OK
$ grep -q "docs/DETECTOR_EVAL.md" README.md                      → OK
$ grep -q "docs/FINETUNE.md" README.md                           → OK
$ grep -q "scripts/eval_detector.py" docs/DETECTOR_EVAL.md       → OK
$ grep -q "FINETUNE.md" docs/DETECTOR_EVAL.md                    → OK
$ ! git check-ignore -q data/eval_la/data.yaml                   → OK (not ignored)
$ /tmp/rq-venv/bin/python -m pytest backend/tests/ -q            → 131 passed, 6 skipped (no regressions)
$ git diff --diff-filter=D --name-only 55002fd..HEAD             → (empty; no deletions)
$ git status --short                                             → (clean working tree)
```

All plan `<success_criteria>` bullets pass:
- data/eval_la/data.yaml committed (nc=1, names[0]=pothole, train/val/test paths) ✓
- docs/DETECTOR_EVAL.md 291 lines ≥ 150 with all 7 sections + TL;DR ✓
- Pickle ACE risk + @<revision> mitigation ✓
- CC-BY-SA + AGPL-3.0 chain tabled ✓
- Reproduction references all 3 CLIs with concrete one-liners ✓
- Image-level bootstrap choice (A1) documented ✓
- Deferred items (RDD2020, calibration, CI gate, paper-grade) acknowledged ✓
- README gains '## Detector Accuracy' section between API Endpoints and Frontend Pages ✓
- README Documentation section lists both new docs ✓
- No existing README content modified ✓
- Phase 2 aggregate: pytest backend/tests/ -q green (131/131 non-skipped) ✓

---

*Phase: 02-real-data-detector-accuracy*
*Completed: 2026-04-24*
