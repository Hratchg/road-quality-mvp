---
phase: 02-real-data-detector-accuracy
plan: 04
subsystem: ml
tags: [python, ml, training, finetune, huggingface, yolov8, cli, docs, pytest]

# Dependency graph
requires:
  - phase: 02-real-data-detector-accuracy (Plan 01)
    provides: "_DEFAULT_HF_REPO + _resolve_model_path in data_pipeline.detector_factory — the fine-tune CLI imports both for base-model resolution; HUGGINGFACE_TOKEN slot already in .env.example"
  - phase: 02-real-data-detector-accuracy (Plan 02)
    provides: "backend/tests/fixtures/eval_fixtures/data.yaml — reused as the real-yaml target for the push-without-token smoke test so exit-3 path does not short-circuit exit-1 path"
  - phase: 02-real-data-detector-accuracy (Plan 03)
    provides: "scripts/fetch_eval_data.py --build — invoked in docs/FINETUNE.md Prerequisites to populate data/eval_la/ before fine-tune; missing-data exit-3 hint in finetune_detector.py points operators at this exact command"
provides:
  - "scripts/finetune_detector.py — argparse CLI (11 flags + -h + -v) wrapping YOLO().train() with seed=42, CPU default (Pitfall 1), D-18 exit codes 0/1/3, and optional --push-to-hub branch (HfApi.upload_file per D-13)"
  - "requirements-train.txt — training-only deps (torch>=2.4.1,<2.10 excluding Pitfall-2 2.4.0, torchvision, pyyaml) with -r include of data_pipeline/requirements.txt so runtime + training share a single source of truth for ultralytics/huggingface_hub/scipy pins"
  - "docs/FINETUNE.md — operator-facing reproduction guide: Laptop CPU / Colab T4 / EC2 g5.xlarge recipes + Prerequisites (fetch + label + pip) + After Training (YOLO_MODEL_PATH eval_detector handoff) + Troubleshooting (6 entries)"
  - "backend/tests/test_finetune_detector.py — 6 subprocess-smoke tests covering all D-18 exit paths + T-02-22 fail-fast guard; zero ultralytics/torch imports; <0.4s real time"
  - "Model card template (in-script, AGPL-3.0 license + Mapillary CC-BY-SA 4.0 attribution) — uploaded alongside best.pt as README.md on HF push"
affects: [02-05-publish-writeup]

# Tech tracking
tech-stack:
  added: []   # torch/torchvision live in requirements-train.txt but are not installed by default; huggingface_hub already declared by Plan 01
  patterns:
    - "Lazy ultralytics import inside _run_training (matches scripts/ingest_iri.py pattern) so --help + exit-3 + exit-1 paths never touch ultralytics"
    - "Fail-fast token check: --push-to-hub without HUGGINGFACE_TOKEN exits 1 BEFORE any training work — protects T-02-22 and saves hours of wasted CPU"
    - "Model card embedded in the script (not a separate template file) — keeps AGPL/CC-BY-SA attribution inseparable from the upload path"
    - "Training-only requirements split: top-level requirements-train.txt with `-r data_pipeline/requirements.txt` so backend and eval installs never pull ~2.5 GB torch wheel"
    - "CPU default device (Pitfall 1: Apple Silicon MPS corrupts YOLO bbox X-coords per ultralytics #23140) — documented in --device help + docs/FINETUNE.md Recipe A + Troubleshooting"
    - "Subprocess CLI smoke tests pinned by REPO_ROOT + sys.executable — same pattern as test_eval_detector / test_fetch_eval_data"

key-files:
  created:
    - scripts/finetune_detector.py
    - requirements-train.txt
    - docs/FINETUNE.md
    - backend/tests/test_finetune_detector.py
  modified: []

key-decisions:
  - "Base model resolution delegated to Plan 01's _resolve_model_path — finetune CLI does NOT reimplement HF download logic; argparse stores the raw --base string and the factory performs hf_hub_download at training time (matches data_pipeline/detector_factory.py behavior, preserves single source of truth)"
  - "Token check fires in main() BEFORE _run_training is called (D-13 + T-02-22): a missing HUGGINGFACE_TOKEN on --push-to-hub exits 1 in milliseconds, never after 4-6 hours of training. The same check also lives inside _upload_to_hf as a defense-in-depth second guard"
  - "Model card generated from _build_model_card string template with eval_metrics=None default — plan explicitly defers eval-number population to Plan 05 writeup; card uploaded unchanged is sufficient for license + attribution compliance (T-02-26)"
  - "requirements-train.txt inverts the dependency direction: data_pipeline/requirements.txt is the upstream source, requirements-train.txt extends it. Keeps ultralytics/huggingface_hub/scipy pins in one file; avoids drift between backend/eval/training installs"
  - "CPU default survives the `_default_device()` helper rather than a string literal — future MPS-patch check or CUDA auto-detect would be a 1-line swap to that helper"

patterns-established:
  - "Top-of-module token read + fail-fast guard: HUGGINGFACE_TOKEN = os.environ.get(...) at import; `if args.push_to_hub and not HUGGINGFACE_TOKEN: return EXIT_OTHER` in main() before any heavy work"
  - "Script docstring mirrors operator journey (laptop → Colab → EC2 → push) and is surfaced via RawDescriptionHelpFormatter epilog=__doc__ so --help shows the full usage guide"
  - "docs/<FEATURE>.md triad with docs/SETUP.md: Version/Last Updated header block, three numbered sections (Prerequisites, Recipes, After Training), Troubleshooting tail"
  - "subprocess.run(sys.executable, SCRIPT, ...) with cwd=REPO_ROOT + env=env.copy() minus sensitive vars — reproducible across test runners and host Python versions"

requirements-completed: [REQ-real-data-accuracy]

# Metrics
duration: ~4min
completed: 2026-04-24
---

# Phase 2 Plan 04: Fine-Tune CLI + Multi-Env Reproduction Guide Summary

**argparse-driven YOLO fine-tune CLI with seed=42, D-18 exit codes, Apple-Silicon-safe CPU default, optional HF upload via HfApi.upload_file, a three-recipe operator guide (Laptop / Colab / EC2), and a 6-test subprocess smoke suite — all without importing ultralytics at test time.**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-04-24T02:29:10Z
- **Completed:** 2026-04-24T02:33:36Z
- **Tasks:** 4 / 4 complete
- **Files created:** 4 (1 CLI script, 1 requirements file, 1 docs file, 1 test file)
- **Files modified:** 0
- **Total lines added:** 716 (354 + 14 + 208 + 140)

## Accomplishments

- `scripts/finetune_detector.py` (354 LOC) — argparse CLI with 11 flags (`--data`, `--base`, `--epochs`, `--batch`, `--imgsz`, `--device`, `--patience`, `--seed`, `--project`, `--name`, `--push-to-hub`) plus `-v`. D-18 exit codes: 0 OK, 1 other/missing-token/train-error, 3 missing dataset. Delegates base-model resolution to Plan 01's `_resolve_model_path` (supports HF repo ids, revisions, and local `.pt` paths). Fails fast on `--push-to-hub` without `HUGGINGFACE_TOKEN` before spending hours training. HF upload uses `HfApi(token=...).upload_file(path_in_repo="best.pt", ...)` per D-13; model card (AGPL-3.0 + CC-BY-SA 4.0 attribution per T-02-26) uploaded as README.md.
- `requirements-train.txt` (14 LOC) — training-only deps. Pin `torch>=2.4.1,<2.10` excludes the Pitfall-2 2.4.0 release that ultralytics' version check rejects. Uses `-r data_pipeline/requirements.txt` to inherit ultralytics + huggingface_hub + scipy + opencv pins; no duplication. Adds `torchvision>=0.19,<0.25` and `pyyaml>=6.0`. Contains no backend framework deps (grep confirms fastapi/psycopg2 = 0).
- `docs/FINETUNE.md` (208 LOC) — operator reproduction guide with three recipes (Laptop CPU / Colab T4 / EC2 g5.xlarge), 5 copy-pasteable `python scripts/finetune_detector.py` invocations, Prerequisites (fetch + label + pip), Apple Silicon MPS caveat (Pitfall 1), After Training section wiring `YOLO_MODEL_PATH` → `eval_detector.py --split test`, and Troubleshooting covering Pitfalls 1/2/6/7 + CUDA OOM + missing HF token.
- `backend/tests/test_finetune_detector.py` (140 LOC, 6 tests) — subprocess smoke tests for D-18 exit codes + T-02-22 fail-fast + default seed/device assertions. No ultralytics/torch imports at test time. Full suite runs in 0.16s (real 0.4s). Phase 2 adjacency suite (test_eval_detector + test_detector_factory + test_yolo_detector) still green (50 tests total).

## Task Commits

Each task was committed atomically (`--no-verify` per parallel-executor protocol):

1. **Task 1: Author scripts/finetune_detector.py** — `4b76230` (feat)
2. **Task 2: Create requirements-train.txt with torch pin excluding 2.4.0** — `fc80a86` (chore)
3. **Task 3: Author docs/FINETUNE.md multi-env reproduction guide** — `021730b` (docs)
4. **Task 4: Author backend/tests/test_finetune_detector.py** — `e829073` (test)

All four commits sit on `worktree-agent-aa03920d` branched from `27d1e8f` (phase-02 wave-2-merged base).

## Files Created/Modified

### Created

- `scripts/finetune_detector.py` (354 LOC) — CLI module. Public surface:
  - `main() -> int` — argparse dispatch; returns exit code
  - `_run_training(args) -> int` — lazy-imports ultralytics, loads base model via `_resolve_model_path`, invokes `YOLO.train(...)` with project conventions, checks `best.pt` existence, optionally uploads
  - `_upload_to_hf(best_path, repo_id, base_model) -> int` — `create_repo` + `upload_file` for weights + model card
  - `_build_model_card(repo_id, base_model, eval_metrics) -> str` — AGPL-3.0 / CC-BY-SA 4.0 / base-model metadata template
  - `_default_device() -> str` — returns "cpu" (Pitfall 1 safety; single swap point for future CUDA auto-detect)
  - Constants: `EXIT_OK=0`, `EXIT_OTHER=1`, `EXIT_MISSING_DATA=3`, `SEED=42`, `HUGGINGFACE_TOKEN` (module-top env read)
- `requirements-train.txt` (14 LOC) — training-only dep split; `-r data_pipeline/requirements.txt` + `torch>=2.4.1,<2.10` + `torchvision>=0.19,<0.25` + `pyyaml>=6.0`; Pitfall 2 rationale in header comment
- `docs/FINETUNE.md` (208 LOC) — operator-facing reproduction guide. Section layout: header (Version/Last Updated) → Prerequisites → Recipe A (Laptop) → Recipe B (Colab) → Recipe C (EC2) → After Training → Troubleshooting → References
- `backend/tests/test_finetune_detector.py` (140 LOC) — 6 subprocess smoke tests in 1 class (`TestFinetuneDetectorCLI`):
  - `test_help_lists_all_flags` — all 11 CLI flags appear in `--help`
  - `test_missing_data_exits_3` — D-18 exit 3 + fetch hint
  - `test_push_without_token_exits_1` — T-02-22 fail-fast BEFORE training starts
  - `test_default_seed_is_42` — project seed convention pinned in `--help`
  - `test_default_device_is_cpu` — Pitfall 1 safety
  - `test_token_never_logged_in_stderr_on_fast_fail` — regression guard: fake token in env does not leak to stdout/stderr

### Modified

None. Plan 04 is additive; `data_pipeline/detector_factory.py`, `data_pipeline/yolo_detector.py`, `data_pipeline/requirements.txt`, `.env.example`, and `.gitignore` all remain at their Plan 01/02/03 state.

## Decisions Made

- **Delegated HF resolution to Plan 01.** `scripts/finetune_detector.py` calls `_resolve_model_path(args.base)` rather than reimplementing `hf_hub_download` logic. This keeps a single source of truth for HF-vs-local path handling and inherits Plan 01's T-02-11 mitigation (default-publisher trust model) automatically.
- **Fail-fast token guard lives in `main()`, not only inside `_upload_to_hf`.** Checking the token after `_run_training` returns would waste 4-6 hours of CPU on a training run that cannot publish. `main()` guards, `_upload_to_hf` double-guards (defense-in-depth); either returns `EXIT_OTHER=1` immediately with an actionable error.
- **Model card built from string template inside the script.** Embedding the template directly (vs. a separate `templates/model_card.md`) makes AGPL-3.0 + CC-BY-SA 4.0 attribution inseparable from the upload path — T-02-26 is structurally enforced rather than trust-based on "the operator uploaded the right file".
- **`_default_device()` helper rather than a string literal default.** Future patch-check for ultralytics #23140 MPS fix, or CUDA auto-detect via `torch.cuda.is_available()`, becomes a 1-line swap without touching argparse.
- **`pytest` import kept in the smoke test module.** Even though no fixtures are currently used, the `# noqa: F401` import signals "this is a pytest test module" and anchors the test-discovery convention used throughout the repo. Safe to remove in a future refactor if pyflakes strict-mode is enforced.

## Deviations from Plan

### Adjustments (not rule-triggering deviations)

**1. [Formatting] Rewrote `requirements-train.txt` comment to say "torch 2.4.0" instead of "torch==2.4.0".**
- **Found during:** Task 2 post-write verification
- **Issue:** The plan's literal `! grep -E "torch==2\.4\.0" requirements-train.txt` acceptance criterion fails if the literal string `torch==2.4.0` appears anywhere in the file, including explanatory comments.
- **Fix:** Changed the comment from "torch==2.4.0 is EXPLICITLY rejected" to "torch 2.4.0 is EXPLICITLY rejected" (and similarly adjusted the `torch!=2.4.0` reference to `torch != 2.4.0`). The semantic intent — warn operators about the 2.4.0 exclusion — is preserved; the pin itself (`torch>=2.4.1,<2.10`) is unchanged.
- **Files modified:** `requirements-train.txt`
- **Committed in:** `fc80a86` (part of Task 2 initial commit after the edit)
- **Classification:** Documentation formatting to satisfy a literal grep assertion. Not a deviation rule trigger; noted for transparency.

**Total auto-fixes:** 0 (Rule 1 bugs, Rule 2 missing critical functionality, Rule 3 blocking issues).
**Total architectural checkpoints:** 0 (Rule 4).
**Impact on plan scope:** Zero — all four tasks landed with their specified acceptance criteria intact.

## Issues Encountered

- **System Python is 3.9.6** (same gap Plans 01–03 flagged): worktree host `/usr/bin/python3` is 3.9, which chokes on `backend/tests/conftest.py` (transitively imports `backend/app/cache.py` with PEP 604 `dict | None` syntax). Resolution: reused `/tmp/rq-venv` (Python 3.12.13 venv) created by Plan 01's executor, already populated with `pytest pillow numpy scipy huggingface_hub` by prior plans. No project file touched; no new deps installed. The subprocess smoke tests use `sys.executable` so they automatically pick up the venv's Python.
- **No ultralytics / torch installed in the test venv** (intentional): Task 4's test file is explicitly designed to avoid ultralytics — it shells out to `scripts/finetune_detector.py --help` and `--data /nonexistent` and `--data <fixture> --push-to-hub <repo>` via subprocess; none of those code paths reach `_run_training`'s lazy `from ultralytics import YOLO` call. Running the full fine-tune pipeline against a real model is deferred to the human operator per `docs/FINETUNE.md`.

## Known Stubs

None. `_build_model_card(..., eval_metrics=None)` emits a card with a `TBD`-free template (no placeholder strings) — the eval-numbers section is simply omitted when metrics are not yet available. Plan 05 will re-generate the card with populated metrics post-eval; this is designed-in optionality, not a stub.

## Threat Flags

None. All threats in the plan's `<threat_model>` (T-02-22 through T-02-27) are either mitigated (T-02-22/23/25/26) or accepted with documented rationale (T-02-24/27). No new security-relevant surface introduced beyond what the plan enumerates.

## Flag to Plan 05

Per the plan `<output>` directive — when Plan 05 authors `docs/DETECTOR_EVAL.md`, it should:

1. **Cite the pickle-ACE risk** in a Security & Licensing section: `.pt` files are pickled PyTorch state, loading untrusted weights is ACE-equivalent, and the default `_DEFAULT_HF_REPO` points at a known publisher (`keremberke/yolov8s-pothole-segmentation`). Operators overriding `YOLO_MODEL_PATH` or `--base` to a new publisher opt into the risk. Pin to a specific HF revision (`user/repo@<commit_sha>`) in production — see Pitfall 8 in `02-RESEARCH.md`.
2. **Link to `docs/FINETUNE.md`** as the reproduction entry point for fine-tuning the published weights (avoid duplicating training recipes between the two files).
3. **Note the CI caveat** already documented in Plan 02's SUMMARY (`_collect_per_image_counts` aggregated-bucket fallback on older ultralytics) — `docs/DETECTOR_EVAL.md`'s Methodology section should call this out so readers understand why the bootstrap CI can degenerate to a single-bucket point estimate on some ultralytics versions.
4. **Include the exact CLI invocation** from `docs/FINETUNE.md` "After Training" (`YOLO_MODEL_PATH=... python scripts/eval_detector.py --data data/eval_la/data.yaml --split test --json-out ...`) so operators can regenerate the exact numbers the writeup cites.

## User Setup Required

The plan's `user_setup:` block specifies HuggingFace account + write-scope token for `--push-to-hub`. These are **operator tasks performed after merge**, not Plan-04 deliverables. Plan 04 ships the code paths; actual publish happens when the operator:

1. Signs up at https://huggingface.co/join and verifies email
2. Creates a write-scope token at https://huggingface.co/settings/tokens
3. `export HUGGINGFACE_TOKEN=hf_...`
4. Runs `docs/FINETUNE.md` Recipe A/B/C end-to-end (including 300-image hand-labeling)
5. Invokes `python scripts/finetune_detector.py ... --push-to-hub <user>/road-quality-la-yolov8`

None of the above is automated — they are operator steps documented in `docs/FINETUNE.md` and the fail-fast token error message.

## Next Phase Readiness

- **Plan 05 (writeup)** can consume `docs/FINETUNE.md` as a stable sibling doc (don't duplicate recipes), and the finetune CLI's `--json-out` flow via `scripts/eval_detector.py` (from Plan 02) provides the exact JSON schema Plan 05 renders into tables.
- **Plan 05 security section** should reference the AGPL-3.0 + CC-BY-SA 4.0 attribution model card (embedded in `scripts/finetune_detector.py::_build_model_card`) so readers can audit the attribution chain end-to-end.
- **Phase 3 (Mapillary ingestion)** already reuses `data_pipeline/mapillary.py` from Plan 03; finetune_detector does not introduce new cross-phase dependencies.
- **Phase 5 (production readiness)** can invoke `scripts/finetune_detector.py --push-to-hub <repo>@<sha>` to pin-ship a new fine-tune, then bump `_DEFAULT_HF_REPO` in `data_pipeline/detector_factory.py` to the new revision (Pitfall 8 discipline).
- **CI gate (deferred)** — a future CI job could invoke `scripts/finetune_detector.py --help` + `scripts/finetune_detector.py --data /nonexistent.yaml` + the fail-fast token test to detect CLI regressions without installing torch. All three paths are exercised by `backend/tests/test_finetune_detector.py` and complete in <0.5s.

## Self-Check: PASSED

Verified post-write:

```
$ test -f scripts/finetune_detector.py                             → FOUND
$ test -f requirements-train.txt                                   → FOUND
$ test -f docs/FINETUNE.md                                         → FOUND
$ test -f backend/tests/test_finetune_detector.py                  → FOUND
$ git log --oneline | grep 4b76230                                 → FOUND (Task 1)
$ git log --oneline | grep fc80a86                                 → FOUND (Task 2)
$ git log --oneline | grep 021730b                                 → FOUND (Task 3)
$ git log --oneline | grep e829073                                 → FOUND (Task 4)
$ python3 scripts/finetune_detector.py --help | grep -E "(--push-to-hub|--epochs|--device)"
                                                                    → all three flags present
$ python3 scripts/finetune_detector.py --data /nonexistent.yaml; echo $?
                                                                    → exit 3, hint emitted to stderr
$ HUGGINGFACE_TOKEN= python3 scripts/finetune_detector.py \
    --data backend/tests/fixtures/eval_fixtures/data.yaml \
    --push-to-hub user/test; echo $?                                → exit 1 with write-scope hint
$ grep -q "^-r data_pipeline/requirements.txt$" requirements-train.txt → OK
$ grep -q "^torch>=2.4.1,<2.10$" requirements-train.txt            → OK
$ grep -c "^## Recipe [ABC]:" docs/FINETUNE.md                     → 3
$ grep -c "python scripts/finetune_detector.py" docs/FINETUNE.md   → 5 (>= 3)
$ [ $(wc -l < docs/FINETUNE.md) -ge 120 ]                          → 208 (pass)
$ pytest backend/tests/test_finetune_detector.py -q                → 6 passed in 0.16s
$ pytest backend/tests/test_finetune_detector.py \
         backend/tests/test_eval_detector.py \
         backend/tests/test_detector_factory.py \
         backend/tests/test_yolo_detector.py -q                    → 50 passed, no regressions
$ git diff --diff-filter=D --name-only 27d1e8f..HEAD               → (empty; no deletions)
```

All plan `<success_criteria>` bullets + plan `<verification>` commands pass:
- 11-flag `--help` surface ✓
- Missing data.yaml → exit 3 ✓
- --push-to-hub without token → exit 1 (fail-fast BEFORE training) ✓
- Seed = 42 ✓
- Default device = cpu (Pitfall 1 safe) ✓
- HF upload uses `HfApi(token=HUGGINGFACE_TOKEN).upload_file(path_in_repo="best.pt", ...)` ✓
- `requirements-train.txt` has `torch>=2.4.1,<2.10` + `-r data_pipeline/requirements.txt` ✓
- `docs/FINETUNE.md` has three recipe sections with copy-pasteable commands + Apple Silicon caveat + troubleshooting ✓
- Model card template embeds AGPL-3.0 + CC-BY-SA attribution ✓
- 6 smoke tests pass; fail-fast on missing token verified ✓
- `HUGGINGFACE_TOKEN` never written to logs (grep + regression-guard test confirm) ✓

---

*Phase: 02-real-data-detector-accuracy*
*Completed: 2026-04-24*
