"""Evaluate YOLOv8 detector against a labelled YOLO-format eval set.

Reports precision, recall, mAP@0.5, and per-severity breakdown with
image-level bootstrap 95% CIs. Exit codes per Phase 2 D-18.

Usage:
    # Eval against the real LA test split (requires data/eval_la/ populated
    # via scripts/fetch_eval_data.py):
    python scripts/eval_detector.py --data data/eval_la/data.yaml --split test

    # Eval with a minimum-precision floor (exits 2 if below):
    python scripts/eval_detector.py --data data/eval_la/data.yaml --min-precision 0.50

    # Smoke test against committed tiny fixtures:
    python scripts/eval_detector.py --data backend/tests/fixtures/eval_fixtures/data.yaml \\
        --bootstrap-resamples 100 --json-out /tmp/report.json

    # Override model path (env var otherwise):
    YOLO_MODEL_PATH=user/repo python scripts/eval_detector.py --data data/eval_la/data.yaml

Exit codes (D-18):
    0 = OK
    1 = Other error
    2 = Below --min-precision or --min-recall floor
    3 = Missing dataset (data.yaml path does not exist)

Security note: `--model` / `YOLO_MODEL_PATH` values feed into
`YOLO(model_path)`, which deserializes a PyTorch .pt file. Loading an
untrusted .pt is ACE-equivalent (pickle). The factory defaults to a
well-known HF repo; opt into other sources deliberately (T-02-11 mitigation).

Requires: ultralytics>=8.3, huggingface_hub>=0.24, scipy>=1.13, numpy>=2.2
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Ensure project root is importable (scripts/ runs from either project root or
# within an installer-built package; this mirrors scripts/ingest_iri.py).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_pipeline.eval import bootstrap_ci, per_severity_breakdown

# Module-top env read (matches backend/app/db.py convention).
YOLO_MODEL_PATH = os.environ.get("YOLO_MODEL_PATH")  # None = factory default

logger = logging.getLogger(__name__)

# D-18 exit codes.
EXIT_OK = 0
EXIT_OTHER = 1
EXIT_BELOW_FLOOR = 2
EXIT_MISSING_DATA = 3


def _collect_per_image_counts(
    results,
    iou_threshold: float = 0.5,
) -> list[dict[str, int]]:
    """Extract per-image TP/FP/FN from ultralytics validation results.

    Ultralytics' metrics object exposes per-prediction arrays (``box.tp``,
    ``box.fp``) whose grouping back to per-image varies across versions. We
    try the ``stats`` dict first and fall back to a single aggregate bucket
    so bootstrap still runs (the CI will be near-degenerate in that case).

    Args:
        results: DetMetrics-like object returned by ``YOLO.val()``.
        iou_threshold: IoU threshold (unused here; ultralytics has already
            applied it inside ``val()``). Parameter kept for forward
            compatibility.

    Returns:
        List of ``{"tp": int, "fp": int, "fn": int}``, one entry per image
        when available, otherwise a single aggregated entry.
    """
    del iou_threshold  # ultralytics already applied the threshold
    per_image: list[dict[str, int]] = []
    if hasattr(results, "stats") and results.stats is not None:
        stats = results.stats
        # If stats is a dict of arrays keyed by image index:
        if isinstance(stats, dict) and "tp" in stats:
            for i in range(len(stats["tp"])):
                per_image.append({
                    "tp": int(stats["tp"][i]),
                    "fp": int(stats["fp"][i]),
                    "fn": int(stats["fn"][i]),
                })
            return per_image
    # Fallback: derive approximate per-image from aggregate (single bucket).
    box = results.box
    tp_total = int(box.tp.sum()) if hasattr(box, "tp") and box.tp is not None else 0
    fp_total = int(box.fp.sum()) if hasattr(box, "fp") and box.fp is not None else 0
    fn_total = max(0, int(box.nl) - tp_total) if hasattr(box, "nl") else 0
    per_image.append({"tp": tp_total, "fp": fp_total, "fn": fn_total})
    return per_image


def _print_human_summary(report: dict) -> None:
    print("\n--- Detector Evaluation Summary ---")
    print(f"  Model:      {report['model_path']}")
    print(f"  Split:      {report['split']}")
    print(
        f"  Precision:  {report['precision']:.3f}  "
        f"[95% CI: {report['precision_ci_95'][0]:.3f}, "
        f"{report['precision_ci_95'][2]:.3f}]"
    )
    print(
        f"  Recall:     {report['recall']:.3f}  "
        f"[95% CI: {report['recall_ci_95'][0]:.3f}, "
        f"{report['recall_ci_95'][2]:.3f}]"
    )
    print(f"  mAP@0.5:    {report['map50']:.3f}")
    print(
        "  By severity: "
        f"moderate={report['per_severity']['moderate']['count']}  "
        f"severe={report['per_severity']['severe']['count']}  "
        f"dropped={report['per_severity']['dropped']['count']}"
    )
    print(f"  IoU:        {report['eval_config']['iou']}")
    print(f"  Bootstrap:  {report['eval_config']['bootstrap_resamples']} resamples")
    print("-----------------------------------\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate YOLOv8 detector against a labelled eval set.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=Path("data/eval_la/data.yaml"),
        help="Path to YOLO data.yaml (defaults to data/eval_la/data.yaml)",
    )
    parser.add_argument(
        "--split",
        choices=["val", "test"],
        default="test",
        help="Which split to evaluate (default: test per D-09)",
    )
    parser.add_argument(
        "--iou",
        type=float,
        default=0.5,
        help="IoU threshold (D-07 = 0.5)",
    )
    parser.add_argument(
        "--bootstrap-resamples",
        type=int,
        default=1000,
        help="D-08 = 1000",
    )
    parser.add_argument(
        "--ci-level",
        type=float,
        default=0.95,
        help="D-08 = 0.95",
    )
    parser.add_argument(
        "--min-precision",
        type=float,
        default=None,
        help="Exit 2 if measured precision < this floor",
    )
    parser.add_argument(
        "--min-recall",
        type=float,
        default=None,
        help="Exit 2 if measured recall < this floor",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Write metrics JSON (for docs/DETECTOR_EVAL.md pipeline)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Override YOLO_MODEL_PATH (HF repo id or local .pt path)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # D-17: missing dataset -> exit 3 with fetch hint.
    if not args.data.exists():
        print(
            f"Eval set not found at {args.data}. "
            f"Run: python scripts/fetch_eval_data.py",
            file=sys.stderr,
        )
        return EXIT_MISSING_DATA

    try:
        from data_pipeline.detector_factory import _resolve_model_path
        from ultralytics import YOLO
    except ImportError as e:
        print(
            f"ERROR: missing dependency ({e}). "
            "Install: pip install -r data_pipeline/requirements.txt",
            file=sys.stderr,
        )
        return EXIT_OTHER

    try:
        explicit = args.model if args.model is not None else YOLO_MODEL_PATH
        model_path = _resolve_model_path(explicit)
        logger.info("Loading model: %s", model_path)
        model = YOLO(model_path)

        results = model.val(
            data=str(args.data),
            split=args.split,
            iou=args.iou,
            verbose=False,
        )

        per_image = _collect_per_image_counts(results, iou_threshold=args.iou)
        precision_ci = bootstrap_ci(
            per_image,
            metric="precision",
            n_resamples=args.bootstrap_resamples,
            ci_level=args.ci_level,
        )
        recall_ci = bootstrap_ci(
            per_image,
            metric="recall",
            n_resamples=args.bootstrap_resamples,
            ci_level=args.ci_level,
        )

        # Per-severity breakdown pulled from aggregate predictions when
        # available. One bucket for all predictions is acceptable — the
        # severity rule is per-detection, not per-image.
        per_image_dets: list[list[tuple[float, str]]] = []
        if (
            hasattr(results, "box")
            and hasattr(results.box, "conf")
            and results.box.conf is not None
        ):
            names = getattr(results, "names", {0: "pothole"})
            dets: list[tuple[float, str]] = []
            for i in range(len(results.box.conf)):
                conf = float(results.box.conf[i])
                cls_id = (
                    int(results.box.cls[i]) if hasattr(results.box, "cls") else 0
                )
                cls_name = names.get(cls_id, "pothole")
                dets.append((conf, cls_name))
            per_image_dets = [dets]
        severity = per_severity_breakdown(per_image_dets)

        report = {
            "model_path": model_path,
            "split": args.split,
            "precision": float(results.box.mp) if hasattr(results.box, "mp") else 0.0,
            "recall": float(results.box.mr) if hasattr(results.box, "mr") else 0.0,
            "map50": float(results.box.map50) if hasattr(results.box, "map50") else 0.0,
            "precision_ci_95": list(precision_ci),
            "recall_ci_95": list(recall_ci),
            "per_severity": severity,
            "eval_config": {
                "iou": args.iou,
                "bootstrap_resamples": args.bootstrap_resamples,
                "ci_level": args.ci_level,
                "num_images": len(per_image),
            },
        }

        _print_human_summary(report)

        if args.json_out:
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(json.dumps(report, indent=2))
            logger.info("Wrote JSON report to %s", args.json_out)

        # D-18 floor checks.
        if args.min_precision is not None and report["precision"] < args.min_precision:
            print(
                f"FAIL: precision {report['precision']:.3f} < floor {args.min_precision}",
                file=sys.stderr,
            )
            return EXIT_BELOW_FLOOR
        if args.min_recall is not None and report["recall"] < args.min_recall:
            print(
                f"FAIL: recall {report['recall']:.3f} < floor {args.min_recall}",
                file=sys.stderr,
            )
            return EXIT_BELOW_FLOOR

        return EXIT_OK

    except FileNotFoundError as e:
        print(f"Missing file: {e}", file=sys.stderr)
        return EXIT_MISSING_DATA
    except Exception:
        import traceback

        traceback.print_exc()
        return EXIT_OTHER


if __name__ == "__main__":
    sys.exit(main())
