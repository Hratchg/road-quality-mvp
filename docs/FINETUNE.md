# Fine-Tuning the LA Pothole Detector

**Version:** 0.1.0
**Last Updated:** 2026-04-23

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

## Recipe C: EC2 / SageMaker (CUDA, paid)

For when you need a reproducible long-lived GPU box.

**EC2 g5.xlarge (NVIDIA A10G)** — ~$1/hr, 50 epochs in ~10 minutes:

```bash
# On your laptop:
aws ec2 run-instances \
    --image-id ami-0c... \                    # Deep Learning AMI (Ubuntu) 22.04
    --instance-type g5.xlarge \
    --key-name <your-keypair> \
    --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=100}' \
    --count 1

# SSH in, then:
git clone https://github.com/<your-fork>/road-quality-mvp.git
cd road-quality-mvp
pip install -r requirements-train.txt
aws s3 sync s3://<your-bucket>/eval_la data/eval_la/   # or scp from laptop

export HUGGINGFACE_TOKEN=hf_...
python scripts/finetune_detector.py \
    --data data/eval_la/data.yaml \
    --epochs 100 \
    --batch 64 \
    --device 0 \
    --patience 20 \
    --push-to-hub <user>/road-quality-la-yolov8

# Tear down
aws ec2 terminate-instances --instance-ids <id>
```

**SageMaker** — not recommended for a one-off 300-image fine-tune; cost and
setup complexity not justified (Context `deferred_ideas` rejects this).
If the project later moves to continuous retraining, revisit.

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
