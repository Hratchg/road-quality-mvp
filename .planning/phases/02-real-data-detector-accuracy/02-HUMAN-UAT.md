---
status: partial
phase: 02-real-data-detector-accuracy
source: [02-VERIFICATION.md]
started: "2026-04-24T02:50:00Z"
updated: "2026-04-24T02:50:00Z"
---

## Current Test

[awaiting human testing]

## Tests

### 1. End-to-end LA dataset build + fine-tune run
expected: `MAPILLARY_ACCESS_TOKEN=… python scripts/fetch_eval_data.py --build --count 300` downloads imagery; operator hand-labels ~300 images via CVAT; `HUGGINGFACE_TOKEN=… python scripts/finetune_detector.py --data data/eval_la/data.yaml --epochs 50` trains to convergence on CPU/CUDA (NOT MPS). Final `runs/detect/train*/weights/best.pt` exists and is non-empty.
result: [pending]

### 2. Real eval run producing real numbers
expected: `YOLO_MODEL_PATH=<path-to-best.pt> python scripts/eval_detector.py --data data/eval_la/data.yaml --split test --json-out eval_results.json` exits 0 and produces a JSON report with `precision_ci_95` and `recall_ci_95` 3-tuples populated from bootstrap.
result: [pending]

### 3. Substitute TBD placeholders in docs/DETECTOR_EVAL.md
expected: All `TBD` entries in the Results section of docs/DETECTOR_EVAL.md replaced with numbers from Test #2 (precision, recall, per-severity counts, CI bands). Writeup is "honest enough to cite in the public demo" (ROADMAP SC #4).
result: [pending]

### 4. Production `@<revision>` pin for published HF model
expected: After first HF publish, `_DEFAULT_HF_REPO` constant in `data_pipeline/detector_factory.py` (or an operator-facing override doc) pins a specific revision hash, not a floating `main` tag. Prevents drift in the pickle-ACE risk window (Pitfall 8).
result: [pending]

## Summary

total: 4
passed: 0
issues: 0
pending: 4
skipped: 0
blocked: 0

## Gaps
