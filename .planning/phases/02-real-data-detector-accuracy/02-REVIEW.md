---
phase: 02-real-data-detector-accuracy
reviewed: 2026-04-23T00:00:00Z
depth: standard
files_reviewed: 21
files_reviewed_list:
  - data_pipeline/detector_factory.py
  - data_pipeline/eval.py
  - data_pipeline/mapillary.py
  - data_pipeline/requirements.txt
  - scripts/eval_detector.py
  - scripts/fetch_eval_data.py
  - scripts/finetune_detector.py
  - backend/tests/test_detector_factory.py
  - backend/tests/test_eval_detector.py
  - backend/tests/test_fetch_eval_data.py
  - backend/tests/test_finetune_detector.py
  - backend/tests/test_mapillary.py
  - backend/tests/test_yolo_detector.py
  - requirements-train.txt
  - .env.example
  - .gitignore
  - data/eval_la/data.yaml
  - data/eval_la/manifest.json
  - docs/DETECTOR_EVAL.md
  - docs/FINETUNE.md
  - README.md
findings:
  critical: 0
  warning: 6
  info: 5
  total: 11
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-04-23T00:00:00Z
**Depth:** standard
**Files Reviewed:** 21
**Status:** issues_found

## Summary

Phase 02 delivers a cohesive end-to-end detector accuracy pipeline: a pure
`data_pipeline/eval.py` math module, a Mapillary fetch/verify client with
robust security guards (bbox DoS cap, constant-time SHA256 compare,
path-traversal rejection, digits-only image-id validation), a factory that
correctly resolves HF repo ids with optional `@revision` pinning, and three
well-partitioned CLI scripts (`eval_detector.py`, `fetch_eval_data.py`,
`finetune_detector.py`) with D-18 exit-code discipline.

Security posture is notably strong: `hmac.compare_digest` is used for hash
comparison, tokens are read via module-top env reads, image ids are validated
against a digits-only regex before being joined into filesystem paths, and
`--push-to-hub` fails fast before spending hours on training when
`HUGGINGFACE_TOKEN` is missing. Tests cover these guards with direct
path-traversal, malformed-hash, and oversized-bbox cases.

No Critical issues found. Six Warnings involve latent bugs (dead-code format
string, `--build` behavior mismatching docstring, silent zero-image build,
mutex group masked by default=True, inconsistent bbox-area epsilon semantics)
and five Info items on style and documentation polish. None block merging,
but several would surface in corner-case production use.

## Warnings

### WR-01: `_build_model_card` crashes if `eval_metrics` contains string "TBD" sentinels

**File:** `scripts/finetune_detector.py:84-90`
**Issue:**
```python
metrics_md = (
    "## Eval Results (test split, held out per D-09)\n"
    f"- Precision: {eval_metrics.get('precision', 'TBD'):.3f}\n"
    ...
)
```
The `.get('precision', 'TBD'):.3f` pattern is self-contradictory: if the key
is missing, the fallback is the string `'TBD'`, but `.3f` format spec will
raise `TypeError: unsupported format string passed to str.__format__` on a
`str`. The `eval_metrics` branch is currently only entered when the dict is
truthy, and the one existing caller passes `eval_metrics=None` (line 230),
so this is a latent bug — but any future caller that passes a partial dict
with missing precision/recall/map50 keys will crash after a successful HF
upload has already occurred.

**Fix:**
```python
def _fmt(v: float | str | None) -> str:
    return f"{v:.3f}" if isinstance(v, (int, float)) else "TBD"

metrics_md = (
    "## Eval Results (test split, held out per D-09)\n"
    f"- Precision: {_fmt(eval_metrics.get('precision'))}\n"
    f"- Recall:    {_fmt(eval_metrics.get('recall'))}\n"
    f"- mAP@0.5:   {_fmt(eval_metrics.get('map50'))}\n\n"
)
```

### WR-02: `fetch_eval_data.py --build` does NOT overwrite existing image/label files, contradicting its docstring

**File:** `scripts/fetch_eval_data.py:11-12, 141-168`
**Issue:** The module docstring states
`--build ... OVERWRITES existing data/eval_la/ contents.` but the
implementation is partial at best:
- `download_image` uses `out_path.write_bytes(r.content)` which does replace
  existing bytes (OK).
- Label file creation (line 159) is gated by `if not label_path.exists()`,
  so hand-labels from a prior run are preserved — the OPPOSITE of "overwrite".
- No pre-`--build` cleanup of `out_root`: stale images whose `image_id` does
  not re-appear in a new Mapillary query remain on disk AND no longer match
  any manifest entry. A subsequent `--verify-only` will pass (manifest has
  only the new entries), but operators will see orphan files.

Combined, a user re-running `--build` after a data model change gets: new
images mixed with stale orphans, preserved labels that may now belong to a
re-downloaded-but-semantically-different image, and a manifest that silently
lies about what a "fresh" state looks like.

**Fix:** Decide the contract and enforce it. Recommended: remove the
misleading "OVERWRITES" language and add an explicit `--clean` flag that
calls `shutil.rmtree(out_root / "images"); shutil.rmtree(out_root / "labels")`
before downloading. Also remove the `if not label_path.exists()` gate if the
intent truly is to start fresh — preserving stale labels across a `--build`
is the surprising behavior. At minimum, update the docstring to say "Writes
new images and an overwriting manifest; preserves existing labels so hand-
annotation is not lost across `--build` runs."

### WR-03: `_build_fresh` silently writes an empty manifest if zero sequences survive the split

**File:** `scripts/fetch_eval_data.py:107-133, 170-197`
**Issue:** The function rejects an empty fetch (`if not all_fetched:`) but
not an empty *survivable* split. If `n_total` sequences is small (e.g. 1 or
2) and `int(n_total * train_pct)` / `int(n_total * val_pct)` produce zero
for some split, or if every download fails (continue on line 145), the
manifest is still written with whatever survived — possibly zero entries.
The function returns `EXIT_OK`, printing a "Build complete" summary with
`n_total` sequences but never re-asserting that at least one file reached
disk. A CI job blindly trusting exit code 0 would then "verify OK" a 0-file
dataset on the very next step.

**Fix:** After the download loop, assert `len(manifest_entries) > 0`:
```python
if not manifest_entries:
    print(
        "ERROR: no files survived download. Check Mapillary rate limits "
        "and URL TTL (Pitfall 5).",
        file=sys.stderr,
    )
    return EXIT_OTHER
```
Also consider rejecting `n_total < 3` (one per split) with a clear error
before writing the manifest, since a 0-image split is a training dead end.

### WR-04: Mutually exclusive group `--verify-only` / `--build` has no effect because `default=True` is always applied

**File:** `scripts/fetch_eval_data.py:253-264`
**Issue:**
```python
group = parser.add_mutually_exclusive_group()
group.add_argument("--verify-only", action="store_true", default=True, ...)
group.add_argument("--build", action="store_true", ...)
```
`add_mutually_exclusive_group` only prevents *both flags being explicitly
passed on the same command line*. Because `--verify-only` carries
`default=True`, `args.verify_only` is `True` even when the operator passes
`--build`. The code coincidentally works (line 313 checks `args.build` first
and only falls through to `_verify` if not), but the mutex group adds no
real safety — pass `--build --verify-only` and argparse errors out; pass
just `--build` and both flags are True. The group's signal-to-noise ratio
is negative: readers assume it enforces "exactly one mode," but in practice
the default decides.

**Fix:** Drop the mutex group and flip to a clear single-flag design:
```python
parser.add_argument(
    "--build",
    action="store_true",
    help="Fresh pull from Mapillary (default: verify existing dataset)",
)
```
Then `if args.build: _build_fresh(...) else: _verify(...)`. Or keep the
group but remove `default=True` and add an explicit post-parse check:
`mode = "build" if args.build else "verify"`.

### WR-05: `_BBOX_AREA_TOLERANCE` in `mapillary.py` is asymmetric and under-tested

**File:** `data_pipeline/mapillary.py:55-84`
**Issue:** The tolerance
`if area > MAX_BBOX_AREA_DEG2 + _BBOX_AREA_TOLERANCE` is `1e-9`, but the
comment cites a concrete IEEE-754 artifact of
`0.010000000000000002 - 0.01 = 2e-18`. A `1e-9` tolerance is ~1e9× the
demonstrated artifact and also ~1e-5× the MAX_BBOX_AREA_DEG2 value — i.e.
the guard will silently accept a bbox whose *intended* area is
`0.010000001` deg² (1e-8 above limit), which is an actually-slightly-too-
large bbox, not a float-point artifact. `test_bbox_at_limit_ok` covers the
`(0.0, 0.0, 0.1, 0.1)` case but does not pin down the tolerance ceiling. A
malicious or accidentally-large bbox that exploits the 1e-9 slop will pass
the DoS guard with no test signal.

**Fix:** Either tighten the tolerance to match the demonstrated artifact
(`_BBOX_AREA_TOLERANCE = 1e-15` is plenty for a 64-bit float `0.01`) OR add
a regression test that constructs a bbox whose computed area is exactly
`MAX_BBOX_AREA_DEG2 + _BBOX_AREA_TOLERANCE / 2` and asserts it passes, and
one at `MAX_BBOX_AREA_DEG2 + 2 * _BBOX_AREA_TOLERANCE` and asserts it fails.
Document the tolerance unit explicitly (deg²).

### WR-06: `_resolve_model_path` accepts `foo/bar.pt` as an HF repo id

**File:** `data_pipeline/detector_factory.py:52-83`
**Issue:** The regex `^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(@[A-Za-z0-9_.-]+)?$`
matches `foo/bar.pt` because `.pt` passes the `[A-Za-z0-9_.-]+` character
class. The local-path bail-out at line 66-69 requires either a leading
`./`/`/`/`..` OR `endswith(".pt") and Path(target).exists()`. So a
*non-existing* `foo/bar.pt` is handed to `hf_hub_download(repo_id="foo/bar.pt")`,
which will fail with a confusing "repository not found" error rather than
the clearer "file not found". More concerning: `foo/bar.pt` could
accidentally match an attacker-registered HF repo with that exact name,
turning a typo'd local path into a remote pickle load (T-02-01 pickle ACE
vector). Low likelihood, but the current test suite has no case asserting
the error message or the non-download path for this input.

**Fix:** Reject HF repo ids whose second segment ends in `.pt` (no legitimate
HF repo uses that suffix):
```python
repo_with_rev, _, filename = target.partition(":")
repo_id, _, revision = repo_with_rev.partition("@")
if not _HF_REPO_PATTERN.match(repo_with_rev) or repo_id.endswith(".pt"):
    return target  # treat as local; YOLOv8Detector raises FileNotFoundError
```
Add a test:
```python
def test_local_path_without_prefix_not_treated_as_hf(self):
    with patch("huggingface_hub.hf_hub_download") as mock_dl:
        assert _resolve_model_path("models/latest.pt") == "models/latest.pt"
        mock_dl.assert_not_called()
```

## Info

### IN-01: `eval_detector.py` stuffs all detections into a single `[dets]` bucket, negating per-image resolution for severity

**File:** `scripts/eval_detector.py:255-271`
**Issue:** The comment on line 253 acknowledges this ("One bucket for all
predictions is acceptable — the severity rule is per-detection, not
per-image"), but the variable `per_image_dets` is misleading — it contains
exactly one inner list of *every* detection across every image. A reader
scanning the name assumes per-image resolution that isn't there. Since
`per_severity_breakdown` only aggregates counts, the result is correct
today, but any future per-image severity stat (e.g., "fraction of images
with severe potholes") will silently produce nonsense.

**Fix:** Rename to `all_dets_single_bucket` (or refactor to populate one
inner list per image when ultralytics exposes per-image prediction
indices — see `_collect_per_image_counts` for the matching pattern).

### IN-02: `finetune_detector.py --epochs 0` suggestion in FINETUNE.md is likely non-functional

**File:** `docs/FINETUNE.md:160-164`
**Issue:** The "Optional — publish weights after manual inspection" recipe
uses `--epochs 0` as a no-op retrain trigger. Ultralytics' `YOLO.train()`
historically rejects `epochs < 1` with a validation error; even if it
accepts 0, the training loop still instantiates a dataloader, runs
validation, and writes a new `best.pt` that may NOT be the file the
operator meant to upload. This recipe probably does not do what the doc
claims.

**Fix:** Remove the `--epochs 0` recipe entirely; if upload-without-retrain
is a supported flow, expose it as a dedicated `--upload-only <path>` flag
on `finetune_detector.py` that skips `_run_training` and calls
`_upload_to_hf(path, repo_id, base)` directly. Or document the correct
manual alternative:
```bash
huggingface-cli upload <repo> runs/detect/la_pothole/weights/best.pt best.pt
```

### IN-03: Four scripts duplicate the `sys.path.insert` bootstrap

**File:** `scripts/eval_detector.py:46`,
`scripts/fetch_eval_data.py:43`,
`scripts/finetune_detector.py:53`,
`backend/tests/test_eval_detector.py:21`,
`backend/tests/test_mapillary.py:20`
**Issue:** Each file repeats
```python
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```
(or a slight variant). Code duplication at the bootstrap layer makes it
hard to refactor the project layout later — a rename of `data_pipeline/`
requires touching each of these files.

**Fix:** Package the project (`pip install -e .` with a minimal
`pyproject.toml`) so `import data_pipeline` resolves without path mangling.
Interim: extract a `scripts/_bootstrap.py` single-liner and do
`from _bootstrap import *  # noqa: F401` — less intrusive than packaging.

### IN-04: `finetune_detector.py --imgsz` help text omits the "must be divisible by 32" YOLO constraint

**File:** `scripts/finetune_detector.py:280-281`
**Issue:** Help: `"Input image size"`. YOLOv8 requires `imgsz` to be a
multiple of 32; passing 400, 500, etc. triggers ultralytics' own sanity
check with a less-helpful traceback. A user on a constrained device who
picks `--imgsz 320` or `--imgsz 512` will succeed; `--imgsz 400` will fail
only after model construction.

**Fix:**
```python
parser.add_argument(
    "--imgsz",
    type=int,
    default=640,
    help="Input image size (must be a multiple of 32; ultralytics requirement)",
)
```
Optionally validate post-parse: `if args.imgsz % 32: parser.error("--imgsz must be divisible by 32")`.

### IN-05: `bootstrap_ci` drops NaN samples without reporting sample survival count

**File:** `data_pipeline/eval.py:155-166`
**Issue:** `vals = vals[~np.isnan(vals)]` silently discards resamples where
the metric was undefined (denominator zero). If the input is lopsided — e.g.,
90% of images have zero predictions and zero ground truth — a large fraction
of resamples become NaN and the returned CI is computed from a small
surviving subset. The function has no signal for this; callers see a CI
that looks well-formed but is based on 50 samples out of 1000 requested.

**Fix:** Add a `min_valid_fraction: float = 0.5` parameter and log a warning
when the survival ratio falls below it. Alternatively, surface the
surviving-sample count in the return type so `eval_detector.py` can include
it in the report:
```python
return (low, point, high, len(vals))  # breaks current callers
```
Or the non-breaking variant — emit a `logger.warning` when
`len(vals) < n_resamples * min_valid_fraction`.

---

_Reviewed: 2026-04-23T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
