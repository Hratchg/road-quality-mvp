"""Fine-tune a YOLOv8 pothole detector on the LA eval training split.

Wraps ultralytics' YOLO().train() with project conventions (seed=42,
CPU-default on Apple Silicon per Pitfall 1) plus optional HuggingFace
upload of the resulting best.pt (D-13).

Usage:
    # Laptop CPU (default, slow but safe on Apple Silicon):
    python scripts/finetune_detector.py --data data/eval_la/data.yaml

    # Colab T4 GPU:
    python scripts/finetune_detector.py --data data/eval_la/data.yaml --device 0 --batch 32

    # EC2 g5.xlarge (CUDA):
    python scripts/finetune_detector.py --data data/eval_la/data.yaml --device 0 --epochs 100

    # After training, push to HF Hub (requires HUGGINGFACE_TOKEN):
    python scripts/finetune_detector.py --data data/eval_la/data.yaml \\
        --push-to-hub user/road-quality-la-yolov8

Exit codes (D-18):
    0 = OK
    1 = Other error (ultralytics missing, HF token missing when --push-to-hub
        set, training failure)
    3 = Missing dataset (--data path does not exist)

Base model resolution (D-11):
    --base defaults to 'keremberke/yolov8s-pothole-segmentation' (HF). Use
    --base yolov8n.pt to fall back to ultralytics' GitHub-hosted default.

Security Note:
    `.pt` files are pickled PyTorch state. Loading untrusted weights is code
    execution. This script resolves --base through data_pipeline.detector_
    factory._resolve_model_path, which defaults to the project's well-known HF
    publisher (keremberke). Set --base to a different source only if you trust
    the publisher. Pin downloaded weights to a specific revision
    (`user/repo@<commit_sha>`) in production (see Pitfall 8).

Licensing:
    Fine-tuned weights inherit the base model's license (check HF repo).
    Keremberke bases are AGPL-3.0 per ultralytics. Mapillary-derived training
    data is CC-BY-SA 4.0; model card MUST attribute.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_pipeline.detector_factory import _DEFAULT_HF_REPO, _resolve_model_path

HUGGINGFACE_TOKEN = os.environ.get("HUGGINGFACE_TOKEN")

logger = logging.getLogger(__name__)

# D-18 exit codes
EXIT_OK = 0
EXIT_OTHER = 1
EXIT_MISSING_DATA = 3

# Project seed convention (scripts/seed_data.py:22)
SEED = 42


def _default_device() -> str:
    """CPU default. Pitfall 1: Apple Silicon MPS is broken (issue #23140).

    MPS corrupts YOLO bbox X-coordinates on Apple Silicon, so we never default
    to it. Operator overrides with --device 0 on CUDA or --device mps on newer
    ultralytics builds where the bug is patched.
    """
    return "cpu"


def _build_model_card(
    repo_id: str, base_model: str, eval_metrics: dict | None
) -> str:
    def _fmt(v: float | str | None) -> str:
        # Guard against partial dicts: if a metric key is missing or non-numeric,
        # fall back to "TBD" rather than crashing in ``str.__format__`` after a
        # successful HF upload has already happened (WR-01 in 02-REVIEW.md).
        return f"{v:.3f}" if isinstance(v, (int, float)) else "TBD"

    metrics_md = ""
    if eval_metrics:
        metrics_md = (
            "## Eval Results (test split, held out per D-09)\n"
            f"- Precision: {_fmt(eval_metrics.get('precision'))}\n"
            f"- Recall:    {_fmt(eval_metrics.get('recall'))}\n"
            f"- mAP@0.5:   {_fmt(eval_metrics.get('map50'))}\n\n"
        )
    return f"""---
license: agpl-3.0
datasets:
  - mapillary/street-level-imagery (CC-BY-SA 4.0)
base_model: {base_model}
tags:
  - yolov8
  - pothole-detection
  - los-angeles
---

# {repo_id.split('/')[-1]}

Fine-tuned YOLOv8 for pothole detection on Los Angeles street-level imagery
(Mapillary crowdsourced). Part of the [road-quality-mvp](https://github.com/)
project.

{metrics_md}See `docs/DETECTOR_EVAL.md` in the source repo for methodology
(image-level bootstrap CIs, 70/20/10 split, IoU=0.5).

## Data Attribution
Training images sourced from Mapillary (https://www.mapillary.com) under
CC-BY-SA 4.0. Per-image source IDs are recorded in the manifest accompanying
this model.

## Security Note
`.pt` files are pickled PyTorch state. Loading untrusted weights is code
execution. Pin to a specific git revision (`user/repo@<commit_sha>`) in
production (see road-quality-mvp `docs/DETECTOR_EVAL.md` security section).
"""


def _run_training(args: argparse.Namespace) -> int:
    try:
        from ultralytics import YOLO
    except ImportError:
        print(
            "ERROR: ultralytics not installed. "
            "Install training deps: pip install -r requirements-train.txt",
            file=sys.stderr,
        )
        return EXIT_OTHER

    # Resolve base model via factory (HF repo id or local path)
    base_resolved = _resolve_model_path(args.base)
    logger.info("Loading base model: %s (resolved: %s)", args.base, base_resolved)
    model = YOLO(base_resolved)

    logger.info(
        "Training with data=%s epochs=%d batch=%d device=%s seed=%d",
        args.data,
        args.epochs,
        args.batch,
        args.device,
        args.seed,
    )
    try:
        results = model.train(
            data=str(args.data),
            epochs=args.epochs,
            batch=args.batch,
            imgsz=args.imgsz,
            device=args.device,
            patience=args.patience,
            project=str(args.project),
            name=args.name,
            seed=args.seed,
            exist_ok=True,  # allow re-runs under same name
        )
    except Exception:
        import traceback

        traceback.print_exc()
        return EXIT_OTHER

    save_dir = Path(results.save_dir)
    best_path = save_dir / "weights" / "best.pt"
    if not best_path.exists():
        print(
            f"ERROR: training completed but best.pt not found at {best_path}",
            file=sys.stderr,
        )
        return EXIT_OTHER
    logger.info("Fine-tuned weights saved at: %s", best_path)

    # Optional HF upload
    if args.push_to_hub:
        rc = _upload_to_hf(best_path, args.push_to_hub, args.base)
        if rc != EXIT_OK:
            return rc

    print(f"\nDONE.\n  Weights: {best_path}\n")
    if args.push_to_hub:
        print(f"  Published: https://huggingface.co/{args.push_to_hub}")
    print(
        f"\n  NEXT: evaluate on held-out test split (D-09):\n"
        f"    YOLO_MODEL_PATH={best_path} python scripts/eval_detector.py \\\n"
        f"        --data {args.data} --split test --json-out eval_report.json\n"
    )
    return EXIT_OK


def _upload_to_hf(best_path: Path, repo_id: str, base_model: str) -> int:
    if not HUGGINGFACE_TOKEN:
        print(
            "ERROR: --push-to-hub requires HUGGINGFACE_TOKEN env var. "
            "Create one at https://huggingface.co/settings/tokens (write scope).",
            file=sys.stderr,
        )
        return EXIT_OTHER
    try:
        from huggingface_hub import HfApi, create_repo
    except ImportError:
        print(
            "ERROR: huggingface_hub not installed. "
            "Install: pip install huggingface_hub>=0.24",
            file=sys.stderr,
        )
        return EXIT_OTHER

    api = HfApi(token=HUGGINGFACE_TOKEN)
    logger.info("Creating/ensuring HF repo: %s", repo_id)
    create_repo(
        repo_id=repo_id,
        exist_ok=True,
        repo_type="model",
        private=False,
        token=HUGGINGFACE_TOKEN,
    )

    logger.info("Uploading %s -> %s/best.pt", best_path, repo_id)
    api.upload_file(
        path_or_fileobj=str(best_path),
        path_in_repo="best.pt",
        repo_id=repo_id,
        commit_message="Fine-tuned on LA eval train split (Phase 2)",
    )

    # Model card
    card_text = _build_model_card(repo_id, base_model, eval_metrics=None)
    card_path = best_path.parent / "README.md"
    card_path.write_text(card_text)
    api.upload_file(
        path_or_fileobj=str(card_path),
        path_in_repo="README.md",
        repo_id=repo_id,
        commit_message="Add model card",
    )
    logger.info("Uploaded model card")
    return EXIT_OK


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fine-tune YOLOv8 pothole detector on LA eval training split.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=Path("data/eval_la/data.yaml"),
        help="YOLO data.yaml (from scripts/fetch_eval_data.py --build)",
    )
    parser.add_argument(
        "--base",
        type=str,
        default=_DEFAULT_HF_REPO,
        help=(
            f"Base model HF repo id or local .pt path "
            f"(default: {_DEFAULT_HF_REPO})"
        ),
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=50,
        help=(
            "Training epochs (default 50; bump to 100 with --patience 20 if "
            "early-stop not triggered)"
        ),
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=16,
        help="Batch size (16 CPU, 32-64 GPU)",
    )
    parser.add_argument(
        "--imgsz", type=int, default=640, help="Input image size"
    )
    parser.add_argument(
        "--device",
        type=str,
        default=_default_device(),
        help=(
            "Device: 'cpu', '0' (CUDA), 'mps' (Apple Silicon — see Pitfall 1 "
            "in 02-RESEARCH.md). Default: cpu"
        ),
    )
    parser.add_argument(
        "--patience",
        type=int,
        default=10,
        help="Early-stopping patience",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=SEED,
        help=f"Random seed (default {SEED})",
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=Path("runs/detect"),
        help="Ultralytics project dir (where weights/logs go)",
    )
    parser.add_argument(
        "--name",
        type=str,
        default="la_pothole",
        help="Run name under --project",
    )
    parser.add_argument(
        "--push-to-hub",
        type=str,
        default=None,
        help=(
            "HF repo id to upload best.pt to (requires HUGGINGFACE_TOKEN)"
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if not args.data.exists():
        print(
            f"Eval set data.yaml not found at {args.data}.\n"
            f"  Run: python scripts/fetch_eval_data.py --build",
            file=sys.stderr,
        )
        return EXIT_MISSING_DATA

    # If --push-to-hub set, fail-fast on missing token BEFORE spending hours
    # training (T-02-22 mitigation).
    if args.push_to_hub and not HUGGINGFACE_TOKEN:
        print(
            "ERROR: --push-to-hub requires HUGGINGFACE_TOKEN env var. "
            "Create at https://huggingface.co/settings/tokens (write scope).",
            file=sys.stderr,
        )
        return EXIT_OTHER

    return _run_training(args)


if __name__ == "__main__":
    sys.exit(main())
