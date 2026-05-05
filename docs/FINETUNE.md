# Fine-Tuning the LA Pothole Detector

**Version:** 0.2.0
**Last Updated:** 2026-05-05

**Changelog:**
- 0.2.0 (2026-05-05, Phase 7): Recipe C tuned for 1500-image LA-trained run on EC2 g5.xlarge with `yolov8s.pt` detection base. SHA-capture step added for Plan 07-07 constant swap.
- 0.1.0 (2026-04-23, Phase 2): Initial three-recipe (laptop / Colab / EC2) fine-tune doc.

---

Three reproducible recipes for fine-tuning YOLOv8 on the LA eval training
split (per D-16: laptop / Colab / EC2, no cloud-specific code in the script
itself).

## Prerequisites

1. Dataset built under `data/eval_la/` — run **once**:
   ```bash
   export MAPILLARY_ACCESS_TOKEN=...   # from https://www.mapillary.com/dashboard/developers
   python scripts/fetch_eval_data.py --build --count 100
   ```
   (`--count 100` × 3 LA zones = ~300 images target per D-01.)

2. Hand-label images under `data/eval_la/images/{train,val}/` using a YOLO-
   compatible tool (CVAT recommended — free, native YOLO `.txt` export).
   Labels go under `data/eval_la/labels/<split>/<image_id>.txt`.
   **Single-class labels** (`pothole`) — severity comes from confidence at
   inference time per `data_pipeline/yolo_detector.py::_map_severity`.
   Never touch `test/` during training (D-09: held-out test split).

3. Train-only deps installed:
   ```bash
   pip install -r requirements-train.txt
   ```
   Python 3.12+ is required (the backend/test stack uses PEP 604 `dict | None`
   syntax). If your system `python3` is older, create a venv:
   `uv venv --python 3.12 .venv && source .venv/bin/activate`.

---

## Recipe A: Laptop (CPU, safe everywhere)

Slow (~4-6 hours for 300 images × 50 epochs on an M-series Mac CPU) but
always works. **Required on Apple Silicon** until ultralytics issue #23140
(MPS coordinate corruption — horizontally shifts predicted bboxes) is
resolved. See Pitfall 1 in
`.planning/phases/02-real-data-detector-accuracy/02-RESEARCH.md`.

```bash
python scripts/finetune_detector.py \
    --data data/eval_la/data.yaml \
    --epochs 50 \
    --batch 8 \
    --device cpu \
    --patience 10
```

Weights land at `runs/detect/la_pothole/weights/best.pt`.

**MPS smoke test** (optional — unlock if the bug is fixed in your
ultralytics version): run 1 epoch with `--device mps` and inspect the boxes
in `runs/detect/la_pothole/val_batch0_pred.jpg` — if horizontally shifted
from ground truth, fall back to `--device cpu`.

---

## Recipe B: Google Colab (free T4 GPU)

Fast (~15-20 minutes for 300 images × 50 epochs) but single-session.

1. Upload `data/eval_la/` as a zip to Colab (drag into file browser).
2. Paste into a fresh notebook cell:
   ```python
   !pip install -q ultralytics>=8.3 huggingface_hub>=0.24 scipy>=1.13
   !unzip -q eval_la.zip -d data/
   !git clone https://github.com/<your-fork>/road-quality-mvp.git
   %cd road-quality-mvp

   # Train (T4 GPU = device 0)
   !python scripts/finetune_detector.py \
       --data ../data/eval_la/data.yaml \
       --epochs 50 \
       --batch 32 \
       --device 0 \
       --patience 10

   # Download weights back
   from google.colab import files
   files.download("runs/detect/la_pothole/weights/best.pt")
   ```

Optional — push directly from Colab:
```python
import os
os.environ["HUGGINGFACE_TOKEN"] = "hf_..."  # Write-scope token
!python scripts/finetune_detector.py \
    --data ../data/eval_la/data.yaml \
    --push-to-hub <user>/road-quality-la-yolov8
```

---

## Recipe C: EC2 g5.xlarge (CUDA, paid) — Phase 7 chosen path

Fast (~30-90 minutes for 1500 images × 50 epochs on a single A10G GPU)
and cheap (~$1-2 for the full Phase 7 phase including 2-3 iteration
runs). **This is the validated path for Phase 7's LA-trained detector**
(per `.planning/phases/07-la-trained-detector/07-CONTEXT.md` D-07).

### Instance setup

| Parameter | Value | Notes |
|-----------|-------|-------|
| Instance type | `g5.xlarge` | 4 vCPU, 1× NVIDIA A10G (24 GB VRAM), 16 GiB RAM (~$1.006/hr per AWS pricing) |
| AMI | AWS Deep Learning OSS AMI GPU PyTorch 2.5+ (Ubuntu 22.04) | Pre-installed PyTorch + CUDA 12.x; G5's proprietary driver loads dynamically (DLAMI handles it) |
| EBS storage | 50 GB gp3 | Image cache + ultralytics + dataset + weights |
| Region | Operator's preference | us-west-2 / us-east-1 most common; SHA capture is region-agnostic |
| Security group | Allow SSH from operator IP | Egress to HF Hub (huggingface.co) needed for model download + push |

Keep the instance running ONLY for the duration of training + HF push.
Terminate immediately after to avoid runaway cost.

### Setup commands (one-time per instance)

```bash
# SSH into the instance (assumes key pair + sg already configured)
ssh -i ~/.ssh/<your-key>.pem ubuntu@<ec2-host>

# Verify CUDA available (DLAMI ships PyTorch + CUDA pre-installed)
python3 -c "import torch; print(torch.__version__, torch.cuda.is_available())"
# expected: 2.5.x or 2.8.x  True

# Clone the repo
git clone https://github.com/<your-fork>/road-quality-mvp.git
cd road-quality-mvp

# Install training-only deps (data_pipeline/requirements.txt + torch + torchvision are already there)
pip install -r requirements-train.txt
```

### Transfer the dataset

Phase 7's `data/eval_la/` is ~300-450 MB total (1500 × ~200KB JPEGs +
~150 small label .txt files). `scp` is fast enough; S3 adds setup
complexity for no material benefit at this size.

From operator workstation:
```bash
cd /Users/<you>/road-quality-mvp
scp -i ~/.ssh/<your-key>.pem -r data/eval_la \
    ubuntu@<ec2-host>:~/road-quality-mvp/data/
```

### Set HF token via environment (NEVER UserData — visible in AWS logs)

Once SSH'd into the instance:
```bash
export HUGGINGFACE_TOKEN="hf_..."   # write-scope token, single-repo limited
```

### Phase 7 training invocation

Per `.planning/phases/07-la-trained-detector/07-CONTEXT.md` D-09 (NOT MPS) +
Claude's discretion in D-10 (detection-only base `yolov8s.pt`) +
RESEARCH §2.3 hyperparams (50 epochs, batch 32, patience 15):

```bash
cd ~/road-quality-mvp
python scripts/finetune_detector.py \
    --data data/eval_la/data.yaml \
    --base yolov8s.pt \
    --device 0 \
    --epochs 50 \
    --batch 32 \
    --patience 15 \
    --push-to-hub Hratchg/road-quality-la-yolov8 \
    --verbose 2>&1 | tee /tmp/finetune-phase7-run1.log
```

Notes:
- `--base yolov8s.pt` is auto-downloaded by ultralytics from GitHub
  releases on first reference (~21 MB). This is the **detection-only**
  base (NOT segmentation) so Phase 7's `eval_detector.py val()` path
  works cleanly (RESEARCH §2.2 + Pitfall 2).
- `--device 0` selects the A10G. NEVER `--device mps` (Pitfall 1: closed
  not-planned).
- `--push-to-hub Hratchg/road-quality-la-yolov8` requires
  `HUGGINGFACE_TOKEN` set in env. The script uploads `best.pt` + a
  generated model card.
- `--verbose` enables debug logging — useful when iterating because
  ultralytics' default level is INFO and obscures dataloader warnings.

Expected runtime: ~30-50 minutes on the first run. Output:
`runs/detect/la_pothole/weights/best.pt`.

### Capture the HF revision SHA (REQUIRED for Plan 07-07)

Immediately after `--push-to-hub` completes, run on the EC2 instance:

```bash
python3 -c "
import os
from huggingface_hub import HfApi
api = HfApi(token=os.environ['HUGGINGFACE_TOKEN'])
info = api.model_info('Hratchg/road-quality-la-yolov8')
print(info.sha)
"
```

Copy the SHA to a note. Plan 07-07 substitutes it into
`data_pipeline/detector_factory.py::_DEFAULT_HF_REPO` as
`"Hratchg/road-quality-la-yolov8@<sha>"`.

### Iteration (D-13 contingency)

If the first trained run UNDERPERFORMS the re-eval'd baseline at the
Plan 07-06 win check, do ONE targeted iteration. Likely fixes:
- Precision floor not met: bump `--patience 20`, retrain longer
- Recall under baseline: try `--epochs 100` + `--batch 16` (smaller
  batch, more updates per epoch)
- Dataset-shape issue (wide bboxes): try `--imgsz 800` + `--batch 16`

Cap at 2 trained runs total per D-13. If second run also underperforms,
close the phase as a documented negative result; D-17 still says
re-ingest with the trained model regardless.

### Terminate the instance

```bash
# On operator workstation:
aws ec2 stop-instances --instance-ids i-xxxxxxxx
aws ec2 terminate-instances --instance-ids i-xxxxxxxx  # if no need to retain EBS
```

Total cost estimate: $1-2 for 60-90 minutes A10G time + iteration buffer.

---

## After Training

Evaluate on the held-out test split (D-09 — test split never touched during
train):

```bash
YOLO_MODEL_PATH=runs/detect/la_pothole/weights/best.pt \
python scripts/eval_detector.py \
    --data data/eval_la/data.yaml \
    --split test \
    --json-out eval_report.json
```

Pipe the JSON into `docs/DETECTOR_EVAL.md` tables (Plan 05 covers the
writeup).

Optional — publish weights after manual inspection:

```bash
export HUGGINGFACE_TOKEN=hf_...
python scripts/finetune_detector.py \
    --data data/eval_la/data.yaml \
    --epochs 0 \                              # no-op retrain; just use --push-to-hub alone
    --push-to-hub <user>/road-quality-la-yolov8
```

Update the default in `data_pipeline/detector_factory.py::_DEFAULT_HF_REPO`
to point at your new repo (pin `@<revision>` to avoid silent weight swaps —
see Pitfall 8).

---

## Troubleshooting

**`torch==2.4.0` version-check error from ultralytics**
→ Pin `torch>=2.4.1,<2.10` (already in `requirements-train.txt`). Pitfall 2.

**mAP stuck at 0 after training looks normal**
→ Label format error. Inspect a `.txt` file: every line should be
`0 <cx> <cy> <w> <h>` with all four floats in `[0, 1]`. CVAT's "YOLO 1.1"
export is native. Pitfall 6.

**Test precision identical to val precision (suspicious)**
→ Train/test split leaked adjacent frames. `fetch_eval_data.py --build`
splits by `sequence_id` to avoid this (Pitfall 7). If a previous run didn't,
rerun `--build` then re-label from scratch.

**OOM on CUDA**
→ Drop `--batch` to 8 or 16. Keep `--imgsz 640`.

**`HUGGINGFACE_TOKEN` missing during `--push-to-hub`**
→ Script fails fast BEFORE training starts with a link to
https://huggingface.co/settings/tokens. Create a write-scope token there,
`export HUGGINGFACE_TOKEN=hf_...`, and rerun.

**Apple Silicon MPS predictions look horizontally shifted**
→ Pitfall 1 (ultralytics #23140). `--device cpu` is the safe default; do
not force `--device mps` on a production training run.

---

## References
- `scripts/finetune_detector.py` — the CLI this guide drives
- `data_pipeline/detector_factory.py::_resolve_model_path` — how the weight
  gets loaded at runtime
- `.planning/phases/02-real-data-detector-accuracy/02-RESEARCH.md` — full
  research notes + pitfalls
- Ultralytics training docs — https://docs.ultralytics.com/modes/train/
- HuggingFace `HfApi.upload_file` — https://huggingface.co/docs/huggingface_hub/package_reference/hf_api
