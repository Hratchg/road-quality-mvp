# Phase 2: Real-Data Detector Accuracy — Pattern Map

**Mapped:** 2026-04-23
**Files analyzed:** 16 new/modified files
**Analogs found:** 13 / 16 (3 have no close analog — flagged in "No Analog Found")

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `scripts/eval_detector.py` | script (CLI) | batch / request-response | `scripts/ingest_iri.py` | role-match (different domain, same CLI shape) |
| `scripts/finetune_detector.py` | script (CLI) | batch / file-I/O | `scripts/ingest_iri.py` | role-match |
| `scripts/fetch_eval_data.py` | script (CLI + external client) | request-response / file-I/O | `scripts/ingest_iri.py` + `scripts/iri_sources.py` | role-match (external-source fetch + verify) |
| `data_pipeline/detector_factory.py` (modify) | factory / config | config-resolution | self (existing) + `backend/app/db.py` (env-var read) | exact (in-place edit) |
| `data_pipeline/yolo_detector.py` (minimal modify) | adapter / model wrapper | request-response | self (existing) | exact |
| `data_pipeline/mapillary.py` (new) | external client | request-response / file-I/O | `scripts/iri_sources.py` (loader module split from script) | role-match |
| `data_pipeline/eval.py` (new) | utility / pure functions | transform | `scripts/iri_sources.py` (pure helpers grouped by domain) | role-match |
| `data/eval_la/manifest.json` (new) | config / data artifact | file-I/O | none (see "No Analog Found") | no analog |
| `data/eval_la/data.yaml` (new) | config | file-I/O | none (external format — YOLO) | no analog |
| `docs/DETECTOR_EVAL.md` (new) | documentation | — | `docs/PRD.md` (style/tone) | role-match |
| `docs/FINETUNE.md` (new) | documentation | — | `docs/SETUP.md` (run-this-command style) | role-match |
| `backend/tests/test_detector_factory.py` (new) | test | unit / mocked | `backend/tests/test_yolo_detector.py` | exact |
| `backend/tests/test_eval_detector.py` (new) | test | unit / mocked | `backend/tests/test_iri_ingestion.py` + `backend/tests/test_yolo_detector.py` | role-match |
| `backend/tests/fixtures/eval_fixtures/` (new) | test fixture | file-I/O | `scripts/sample_iri_data.csv` (in-repo sample for tests) | role-match (analogous convention; fixtures/ dir new) |
| `requirements-train.txt` (new) | config / build | — | `data_pipeline/requirements.txt` / `scripts/requirements.txt` | role-match |
| `requirements.txt` / `data_pipeline/requirements.txt` (modify) | config / build | — | self | exact |
| `.env.example` (append) | config | — | self (existing `.env.example` entries) | exact |

## Pattern Assignments

### `scripts/eval_detector.py` (script, CLI request-response)

**Analog:** `scripts/ingest_iri.py`

**Module-level imports + env-var read** — copy shape from `scripts/ingest_iri.py:21-46`:
```python
from __future__ import annotations

import argparse
import logging
import os
import sys
# ...domain-specific imports...

# Ensure sibling modules are importable (if splitting into eval helpers)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Env var read at module top (matches backend/app/db.py:5-7 pattern too)
YOLO_MODEL_PATH = os.environ.get("YOLO_MODEL_PATH")  # None = factory default

logger = logging.getLogger(__name__)
```

**Argparse + logging init** — mirror `scripts/ingest_iri.py:183-225`:
```python
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate YOLOv8 detector against a labelled eval set.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--data", type=Path, default=Path("data/eval_la/data.yaml"), help="...")
    parser.add_argument("--split", choices=["val", "test"], default="test", help="...")
    parser.add_argument("--iou", type=float, default=0.5, help="D-07 = 0.5")
    parser.add_argument("--bootstrap-resamples", type=int, default=1000, help="D-08")
    parser.add_argument("--min-precision", type=float, default=None, help="Exit 2 if below")
    parser.add_argument("--min-recall", type=float, default=None, help="Exit 2 if below")
    parser.add_argument("--json-out", type=Path, default=None, help="Write metrics JSON")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
```

**Exit-code + `__main__` pattern** — unlike `ingest_iri.py` which uses `sys.exit(1)` on error inline, Phase 2 requires four distinct exit codes per D-18. Use a module-level constants block:
```python
# D-18 exit codes
EXIT_OK = 0
EXIT_OTHER = 1
EXIT_BELOW_FLOOR = 2
EXIT_MISSING_DATA = 3

# ... main() returns one of these ...

if __name__ == "__main__":
    sys.exit(main())
```
Base `__main__` guard copied from `scripts/ingest_iri.py:256-257`, but wrapping `sys.exit(main())` (not just `main()`) because `main()` returns an int per D-18.

**Header docstring** — copy the `"""Usage: ..."""` shape from `scripts/ingest_iri.py:1-19`. Include a "Requires:" line and concrete example invocations.

---

### `scripts/finetune_detector.py` (script, CLI batch + file-I/O)

**Analog:** `scripts/ingest_iri.py` (CLI shape) + RESEARCH.md Pattern 5 (HF upload) + Example 3 (ultralytics training)

**Argparse + logging** — identical skeleton to `eval_detector.py` above (itself lifted from `ingest_iri.py`).

**External-SDK invocation pattern** — follow the lazy-import + try/except style already used by `data_pipeline/yolo_detector.py:53-63`:
```python
try:
    from ultralytics import YOLO
except ImportError:
    logger.error("ultralytics not installed. Install with: pip install -r requirements-train.txt")
    return EXIT_OTHER

model = YOLO(base_weights_path)
results = model.train(
    data=str(args.data),
    epochs=args.epochs,
    batch=args.batch,
    imgsz=640,
    device=args.device,   # "cpu" default on Apple Silicon (Pitfall 1)
    patience=10,
    project="runs/detect",
    name="la_pothole",
    seed=42,              # matches project seed=42 convention (seed_data.py:22, iri_sources line 274)
)
```

**Seed convention** — copy the `SEED = 42` module constant from `scripts/seed_data.py:22` so finetune results are reproducible across runs.

**HF upload (optional `--push` flag)** — from RESEARCH.md Pattern 5; wrap in try/except and read token exactly as the DB read pattern:
```python
HUGGINGFACE_TOKEN = os.environ.get("HUGGINGFACE_TOKEN")

if args.push:
    if not HUGGINGFACE_TOKEN:
        print("ERROR: --push requires HUGGINGFACE_TOKEN env var", file=sys.stderr)
        return EXIT_OTHER
    from huggingface_hub import HfApi
    api = HfApi(token=HUGGINGFACE_TOKEN)
    api.upload_file(
        path_or_fileobj=str(best_path),
        path_in_repo="best.pt",
        repo_id=args.repo_id,
        commit_message="Fine-tuned on LA eval train split",
    )
```

---

### `scripts/fetch_eval_data.py` (script, CLI + external client)

**Analog:** `scripts/ingest_iri.py` (overall CLI shape) + `scripts/iri_sources.py` (domain-helpers-in-sibling-module split)

**Script/helpers split pattern** — `ingest_iri.py` keeps the CLI thin and delegates to `iri_sources.py` for loaders. Mirror this: `fetch_eval_data.py` is the CLI; `data_pipeline/mapillary.py` owns the Mapillary client; SHA256 verification can live inline (stdlib `hashlib`, small) or in `data_pipeline/mapillary.py` as a util. See `scripts/ingest_iri.py:34-39` for the cross-module import style.

**FileNotFoundError + exit-code-3 pattern** — the existing analog for "missing required input" is `iri_sources.py:96-97`:
```python
if not path.exists():
    raise FileNotFoundError(f"CSV file not found: {csv_path}")
```
For D-17 we translate that into a fetch-hint + exit code 3 at the script boundary:
```python
if not manifest_path.exists():
    print(
        f"Manifest not found at {manifest_path}. "
        f"Expected location: data/eval_la/manifest.json",
        file=sys.stderr,
    )
    return EXIT_MISSING_DATA  # = 3 per D-18
```

**SHA256 verification** — inline (see RESEARCH.md Code Example 5). No existing analog in the repo; use `hashlib.sha256` from stdlib. For the hash comparison use `hmac.compare_digest` (Security doc §V6) rather than `==` for constant-time compare.

**Header docstring** — mirror `scripts/ingest_iri.py:1-19` "Usage: ..." style, with concrete invocations like:
```
# Download eval set declared by the committed manifest:
python scripts/fetch_eval_data.py

# Verify-only (no download) over an already-populated local copy:
python scripts/fetch_eval_data.py --verify-only
```

---

### `data_pipeline/detector_factory.py` (modify — factory / config)

**Analog:** self (existing `detector_factory.py:1-64`) + `backend/app/db.py:5-7` for env-var read pattern

**Existing signature to preserve** (lines 26-29) — DO NOT change:
```python
def get_detector(
    use_yolo: bool = False,
    model_path: str | None = None,
) -> PotholeDetector:
```

**Existing lazy-import fallback to preserve** (lines 46-53):
```python
try:
    from data_pipeline.yolo_detector import YOLOv8Detector
except ImportError:
    logger.warning(
        "ultralytics is not installed — falling back to StubDetector. "
        "Install with: pip install ultralytics>=8.1"
    )
    return StubDetector()
```

**Env-var read pattern to add at module top** — copied exactly from `backend/app/db.py:5-7`:
```python
# ADD at module top of detector_factory.py
import os
YOLO_MODEL_PATH_ENV = os.environ.get("YOLO_MODEL_PATH")
```

**New resolution function** — RESEARCH.md Pattern 1 (lines 253-305). This is new code with no direct analog; the HF-vs-local detection + `hf_hub_download` is introduced in this phase.

**Logging pattern to preserve** — `detector_factory.py:59-62`:
```python
logger.info(
    "Using YOLOv8Detector (model_path=%s)",
    model_path or "models/pothole_yolov8.pt",
)
```
Update the fallback string to reflect the new default (HF repo id), e.g. `resolved or _DEFAULT_HF_REPO`.

---

### `data_pipeline/yolo_detector.py` (minimal modify — adapter)

**Analog:** self. Only change = default constructor value; interface, `detect()`, `_load_model()`, and `_map_severity()` are frozen per CONTEXT.md code_context.

**Existing constructor to modify** (`yolo_detector.py:40-47`):
```python
def __init__(
    self,
    model_path: str = "models/pothole_yolov8.pt",  # <-- change default; factory always supplies
    conf_threshold: float = 0.25,
) -> None:
```
RESEARCH.md §Architecture says default becomes `None` OR is left as-is since the factory resolves first. Either change is local; **don't** touch `_load_model`, `detect`, `_map_severity`, or `Detection`.

**Preserve lazy-load + FileNotFoundError pattern** (`yolo_detector.py:49-63`) exactly — eval tests rely on the "model missing → empty list" behavior (see `backend/tests/test_yolo_detector.py:116-124`).

---

### `data_pipeline/mapillary.py` (new — external client)

**Analog:** `scripts/iri_sources.py` — a sibling helper module to a script, same role in the file tree.

**Module docstring pattern** — copy the shape from `scripts/iri_sources.py:1-26`:
```python
"""Mapillary API v4 client: search images by bbox, download for offline use.

Supports:
  - Image search by bbox + fields (id, thumb_url, geometry, sequence_id)
  - Streaming download of thumbnails with URL-TTL awareness (Pitfall 5)

Mapillary API reference:
  https://www.mapillary.com/developer/api-documentation

Token acquisition:
  https://www.mapillary.com/dashboard/developers — free, OAuth bearer
"""
```

**Imports + module logger + env-var pattern** — mirror `scripts/iri_sources.py:27-38`:
```python
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)
```

**Token read** — `scripts/iri_sources.py` doesn't read env vars (the script does), but `backend/app/db.py:5-7` does. Follow the db.py pattern:
```python
MAPILLARY_TOKEN = os.environ.get("MAPILLARY_ACCESS_TOKEN")
```

**Function shape** — copy signature/docstring density from `scripts/iri_sources.py:71-151` (`load_iri_from_csv` — a module-level loader with explicit typed args, full docstring with Args/Returns/Raises, and clean `logger.info("Loaded %d records", ...)` at the end).

**Cross-phase reuse note** — Phase 3's `ingest_mapillary.py` will import from this module. Keep everything framework-agnostic (no `argparse`, no `sys.exit`) per the `iri_sources.py` convention.

---

### `data_pipeline/eval.py` (new — pure utility functions)

**Analog:** `scripts/iri_sources.py` (module of pure domain functions consumed by a script)

**Top-of-file structure** — mirror `scripts/iri_sources.py:1-64`:
```python
"""Eval helpers: precision/recall/bootstrap CI/per-severity breakdown.

These functions are pure — no DB, no I/O, no network. `scripts/eval_detector.py`
orchestrates the CLI; this module does the math.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)
```

**Bootstrap CI function** — full sketch in RESEARCH.md Pattern 3 (lines 420-453). Use `seed=42` (project convention per `scripts/seed_data.py:22`).

**Per-severity breakdown function** — mirror `yolo_detector.py::_map_severity` logic exactly (lines 129-157) so eval metrics match runtime. This is the explicit direction in CONTEXT.md code_context.

---

### `backend/tests/test_detector_factory.py` (new — unit test)

**Analog:** `backend/tests/test_yolo_detector.py` (lines 1-181 — same file covers factory today; tests 2-3 are the direct template)

**sys.path + imports pattern** — copy `backend/tests/test_yolo_detector.py:7-17`:
```python
import sys
import os
import types
from unittest.mock import MagicMock, patch

import pytest

# Ensure the project root is on sys.path so data_pipeline is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from data_pipeline.detector import Detection, StubDetector
```

**Mock-ultralytics helper** — copy verbatim from `test_yolo_detector.py:26-30`:
```python
def _make_mock_ultralytics():
    """Create a mock ultralytics module with a YOLO class."""
    mock_mod = types.ModuleType("ultralytics")
    mock_mod.YOLO = MagicMock  # type: ignore[attr-defined]
    return mock_mod
```

**`patch.dict(sys.modules, {"ultralytics": mock_ul})` pattern** — copy from `test_yolo_detector.py:41-57`:
```python
def test_yolo_detector_protocol():
    mock_ul = _make_mock_ultralytics()
    with patch.dict(sys.modules, {"ultralytics": mock_ul}):
        from data_pipeline.yolo_detector import YOLOv8Detector
        detector = YOLOv8Detector(model_path="fake.pt")
        assert hasattr(detector, "detect")
```

**Env-var monkeypatch pattern** — pytest's `monkeypatch` fixture (not used in `test_yolo_detector.py` today but a standard pytest pattern). Add new tests using:
```python
def test_factory_reads_yolo_model_path_env(monkeypatch):
    monkeypatch.setenv("YOLO_MODEL_PATH", "./local/model.pt")
    # ... patch hf_hub_download so test doesn't hit network ...
```

**Factory-reload pattern** for testing module-top env reads — adapt the reload dance from `test_yolo_detector.py:85-108`:
```python
import importlib
from data_pipeline import detector_factory
importlib.reload(detector_factory)
```

**HF download mock** — new pattern (no existing analog). Use `unittest.mock.patch` on `huggingface_hub.hf_hub_download` to return a sentinel local path string:
```python
with patch("huggingface_hub.hf_hub_download", return_value="/tmp/sentinel/best.pt") as mock_dl:
    resolved = detector_factory._resolve_model_path("user/repo")
    assert resolved == "/tmp/sentinel/best.pt"
    mock_dl.assert_called_once_with(repo_id="user/repo", filename="best.pt")
```

---

### `backend/tests/test_eval_detector.py` (new — unit test)

**Analog:** `backend/tests/test_iri_ingestion.py` (lines 1-80) for scripts-adjacent testing; `backend/tests/test_yolo_detector.py` for mocking style.

**sys.path pattern for cross-directory import** — copy from `test_iri_ingestion.py:18-24`:
```python
SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts",
)
sys.path.insert(0, SCRIPTS_DIR)

# Then import the script module or a helper subset
```

**Test class grouping** — copy the class-per-behavior-bucket pattern from `test_iri_ingestion.py:40-70`:
```python
class TestBootstrapCiDeterministic:
    """Bootstrap CI is seeded and reproducible."""
    def test_same_input_same_output(self): ...
    def test_different_seed_different_output(self): ...

class TestPerSeverityBreakdown:
    """Per-severity breakdown mirrors yolo_detector._map_severity logic."""
    def test_moderate_class_maps_to_moderate(self): ...
    ...
```

**Subprocess smoke test for exit codes** (new test type, no strict analog) — use `subprocess.run` with `check=False` and assert `.returncode`:
```python
import subprocess, sys
result = subprocess.run(
    [sys.executable, "scripts/eval_detector.py", "--data", "/nonexistent.yaml"],
    capture_output=True, text=True,
)
assert result.returncode == 3  # EXIT_MISSING_DATA
```
This is novel; no existing test in the repo shells out to a script.

---

### `backend/tests/fixtures/eval_fixtures/` (new — test fixture directory)

**Analog:** `scripts/sample_iri_data.csv` — the existing "sample file used by a test" convention. No `backend/tests/fixtures/` dir exists today (`ls backend/tests/` returned no fixtures dir).

**Structure** — RESEARCH.md §Wave 0 Gaps: 3-5 tiny dummy images (10×10 solid-color PNG generated programmatically in a conftest helper, OR committed as real tiny JPGs) + matching `.txt` label files + a minimal `data.yaml`. Labels validated via the regex pitfall-6 check.

**Fixture-generation pattern** — if generated programmatically, put the generator in `backend/tests/conftest.py` using pytest's `tmp_path` fixture. `backend/tests/conftest.py` exists today — read it before adding to respect existing style.

---

### `docs/DETECTOR_EVAL.md` (new — documentation)

**Analog:** `docs/PRD.md:1-40` (style/tone/version-header) + RESEARCH.md §Architecture "Recommended Project Structure" table.

**Header pattern** — copy the `# Title` + `**Version:**` + `**Last Updated:**` + `---` block from `docs/PRD.md:1-6`:
```markdown
# Detector Accuracy — LA Evaluation Report

**Version:** 0.1.0
**Last Updated:** 2026-04-23

---
```

**Section list** per D-10: methodology, dataset description, per-metric tables with CIs, caveats/limitations, reproduction instructions, security/licensing note (pickle ACE + CC-BY-SA attribution per RESEARCH.md Security domain).

**Numbers format** — precision/recall/mAP@0.5 with `[95% CI: x, y]` suffix; explicitly document the image-level bootstrap choice (A1 in Assumptions Log) so reviewers know which convention is used.

---

### `docs/FINETUNE.md` (new — reproduction guide)

**Analog:** `docs/SETUP.md` (run-these-commands style — similar purpose: operator-facing how-to). Header style still mirrors `docs/PRD.md:1-6`.

**Three-section structure** per D-16: laptop (CPU, Apple Silicon caveat), Colab (T4 GPU, notebook stub), EC2/SageMaker (launch commands). Each section has a copy-pasteable command block.

---

### `requirements-train.txt` (new — build config)

**Analog:** `data_pipeline/requirements.txt` + `scripts/requirements.txt` (both are pinned per-area requirements files). No existing analog uses `-r` includes; RESEARCH.md suggests using one:
```
-r data_pipeline/requirements.txt
huggingface_hub>=0.24,<1.0
scipy>=1.13
torch>=2.4.1,<2.10
torchvision>=0.19,<0.25
```

Version-pin style — copy from `data_pipeline/requirements.txt:1-2`:
```
ultralytics>=8.1
opencv-python-headless>=4.8
```

---

### `data_pipeline/requirements.txt` (modify)

**Analog:** self. Two appends only:
```
huggingface_hub>=0.24,<1.0
scipy>=1.13
```
Keep existing `ultralytics>=8.1` and `opencv-python-headless>=4.8` lines. Both additions are runtime deps (factory uses `hf_hub_download`, eval uses `scipy.stats`).

---

### `.env.example` (append)

**Analog:** self (existing `.env.example:1-22`). Follow its comment style — each section has:
- section header `# ----- Name -----`
- `# Consumed by: <file_path>` line
- explanation paragraph
- the var with a safe default or empty

Append block template:
```
# ----- YOLOv8 Detector Model -----
# Consumed by: data_pipeline/detector_factory.py
# Either an HF repo id ("user/repo" or "user/repo:filename.pt") or a local .pt path.
# If unset, the factory uses a default HF repo baked into detector_factory.py.
YOLO_MODEL_PATH=

# ----- HuggingFace Hub (fine-tune upload only) -----
# Consumed by: scripts/finetune_detector.py (--push flag)
# Create a write-scope token at https://huggingface.co/settings/tokens.
# Leave empty if you won't be publishing new fine-tunes.
HUGGINGFACE_TOKEN=

# ----- Mapillary API (eval-set + Phase 3 ingestion) -----
# Consumed by: data_pipeline/mapillary.py, scripts/fetch_eval_data.py
# Create a free token at https://www.mapillary.com/dashboard/developers.
# Required for fetching eval images; not needed once the labelled set is cached.
MAPILLARY_ACCESS_TOKEN=
```

---

## Shared Patterns

### Env-var read at module top

**Source:** `backend/app/db.py:5-7`
**Apply to:** `data_pipeline/detector_factory.py`, `data_pipeline/mapillary.py`, and (inside `main()`) all three new scripts.

```python
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://rq:rqpass@localhost:5432/roadquality"
)
```

Pattern: `os.environ.get("VAR_NAME", default_or_None)` at module top. Do **not** read env vars inside functions called repeatedly (cost + test-surprise). Scripts may additionally accept an override arg (e.g., `--model` overrides `YOLO_MODEL_PATH`) to match `scripts/ingest_iri.py:207-211`:
```python
parser.add_argument("--db-url", type=str, default=None,
                    help="Database URL (overrides DATABASE_URL env var)")
```

### Standalone script skeleton

**Source:** `scripts/ingest_iri.py:183-257`
**Apply to:** All three new scripts (`eval_detector.py`, `finetune_detector.py`, `fetch_eval_data.py`).

Shape:
1. Module docstring with `Usage:` block and concrete invocations (`ingest_iri.py:1-19`)
2. `from __future__ import annotations` (`ingest_iri.py:21`)
3. Ordered imports: stdlib → third-party → local (`ingest_iri.py:23-39`)
4. `sys.path.insert(0, ...)` if importing sibling script modules (`ingest_iri.py:32`)
5. Env-var reads at module top (`ingest_iri.py:41-43`)
6. `logger = logging.getLogger(__name__)` (`ingest_iri.py:45`)
7. Private helpers prefixed `_` (`ingest_iri.py:48-91, 94-117`)
8. Public action functions (`ingest_iri.py:120-180`)
9. `def main() -> None:` (or `-> int` for Phase 2 scripts) with argparse block (`ingest_iri.py:183-225`)
10. `if __name__ == "__main__": main()` (or `sys.exit(main())`) at the bottom (`ingest_iri.py:256-257`)

### Lazy-import of heavy deps with graceful fallback

**Source:** `data_pipeline/detector_factory.py:46-53` + `data_pipeline/yolo_detector.py:53-63`
**Apply to:** `scripts/eval_detector.py`, `scripts/finetune_detector.py`, and `data_pipeline/detector_factory.py` (preserve existing behavior).

```python
try:
    from ultralytics import YOLO
except ImportError:
    logger.warning("ultralytics not installed — ...")
    return EXIT_OTHER  # or StubDetector() in factory context
```

### Mocking ultralytics in tests

**Source:** `backend/tests/test_yolo_detector.py:26-30, 41-57`
**Apply to:** `backend/tests/test_detector_factory.py`, `backend/tests/test_eval_detector.py`

```python
def _make_mock_ultralytics():
    mock_mod = types.ModuleType("ultralytics")
    mock_mod.YOLO = MagicMock
    return mock_mod

with patch.dict(sys.modules, {"ultralytics": mock_ul}):
    from data_pipeline.yolo_detector import YOLOv8Detector
    # ...
```
Tests MUST NOT require ultralytics to actually be installed (matches project CI convention per `test_yolo_detector.py:3-4` docstring).

### Logging format

**Source:** `scripts/ingest_iri.py:220-225`
**Apply to:** All new scripts.

```python
log_level = logging.DEBUG if args.verbose else logging.INFO
logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
```

### Error reporting to stderr before non-zero exit

**Source:** `scripts/ingest_iri.py:234-238`
**Apply to:** All three new scripts.

```python
except psycopg2.OperationalError as exc:
    print(f"ERROR: Cannot connect to database: {exc}")
    sys.exit(1)
```
Phase 2 extension: write to `sys.stderr` explicitly (`print(..., file=sys.stderr)`) so JSON output on stdout (e.g. `--json-out -`) is not polluted by error text.

### Seed discipline for reproducibility

**Source:** `scripts/seed_data.py:22` (`SEED = 42`), reused by `scripts/iri_sources.py:274` (`rng = np.random.default_rng(seed)`)
**Apply to:** `data_pipeline/eval.py` (bootstrap resampling), `scripts/finetune_detector.py` (`model.train(..., seed=42, ...)`).

Every stochastic operation in Phase 2 uses `seed=42` unless the CLI user overrides it.

### `sys.path.insert` for test imports

**Source:** `backend/tests/test_yolo_detector.py:15` and `backend/tests/test_iri_ingestion.py:18-23`
**Apply to:** Both new test files.

```python
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
```

### `.env.example` entry style

**Source:** `.env.example:1-22`
**Apply to:** The three new env-var blocks appended in Phase 2.

Each entry = section header + `# Consumed by:` line + 1-2-sentence explanation + `VAR=safe_default_or_empty`.

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `data/eval_la/manifest.json` | config / data artifact | file-I/O | No SHA256-pinned manifest exists in this repo today. Use RESEARCH.md Code Example 5's shape (`version`, `source_bucket`, `files: [{path, sha256, source_mapillary_id}]`). |
| `data/eval_la/data.yaml` | config (external YOLO format) | file-I/O | Format is defined by ultralytics, not by this repo's conventions. Use RESEARCH.md Pattern 4's shape. |
| `backend/tests/fixtures/eval_fixtures/` (directory itself) | test fixture container | file-I/O | `backend/tests/fixtures/` directory does not exist in the repo. The closest convention is `scripts/sample_iri_data.csv` — an in-repo sample file used by tests. Plan should create the directory and use it for Phase 2 + future phases. |

## Metadata

**Analog search scope:** `scripts/`, `data_pipeline/`, `backend/`, `docs/`, repo root config files
**Files scanned:** 12 source files read in full or in targeted sections
**Pattern extraction date:** 2026-04-23
**Key analogs (in priority order):**
1. `scripts/ingest_iri.py` — CLI shape, argparse, logging, exit-code discipline, header docstring
2. `scripts/iri_sources.py` — sibling helper module split from a thin CLI
3. `data_pipeline/detector_factory.py` (self) — existing factory signature + lazy-import fallback
4. `data_pipeline/yolo_detector.py` (self) — lazy `_load_model`, FileNotFoundError → empty-list graceful path
5. `backend/app/db.py` — canonical env-var-at-module-top pattern
6. `backend/tests/test_yolo_detector.py` — mock-ultralytics helper, `patch.dict(sys.modules, ...)`, factory-reload dance
7. `backend/tests/test_iri_ingestion.py` — cross-dir test import via `sys.path`, class-per-behavior-bucket layout
8. `.env.example` — section header + `Consumed by:` + explanation style
9. `scripts/seed_data.py` — `SEED = 42` project convention
10. `docs/PRD.md` — doc header/version/last-updated block
