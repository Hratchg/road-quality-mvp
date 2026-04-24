"""Fetch or verify the LA pothole eval dataset.

Modes:
    --verify-only (default): hash-check every file in data/eval_la/
                             against manifest.json. Exits 3 if manifest or
                             any file missing / corrupt.

    --build:                 Fresh pull from Mapillary across configurable
                             LA bboxes, writes YOLO layout + regenerates
                             manifest.json. Requires MAPILLARY_ACCESS_TOKEN.
                             OVERWRITES existing data/eval_la/ contents.

Usage:
    # Verify (default, safe):
    python scripts/fetch_eval_data.py
    python scripts/fetch_eval_data.py --verify-only

    # Build fresh (requires env token, long-running, network-heavy):
    MAPILLARY_ACCESS_TOKEN=... python scripts/fetch_eval_data.py --build --count 100

Exit codes (D-18):
    0 = OK
    1 = Other error (API failure, token missing in --build mode)
    3 = Missing dataset (manifest missing OR any file missing/corrupt)

Licensing:
    Mapillary imagery is CC-BY-SA 4.0. Each downloaded file is recorded in
    manifest.json with its source_mapillary_id for attribution.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
from pathlib import Path

# Ensure project root is importable (so data_pipeline.* resolves when this
# script is run directly from the repo root)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_pipeline.mapillary import (  # noqa: E402
    MAPILLARY_TOKEN,
    download_image,
    search_images,
    validate_bbox,
    verify_manifest,
    write_manifest,
)

logger = logging.getLogger(__name__)

# D-18 exit codes
EXIT_OK = 0
EXIT_OTHER = 1
EXIT_MISSING_DATA = 3

# Default LA bboxes for --build mode. Each is <= 0.01 deg2 per Pitfall 3.
# Three zones sampled to balance geographic diversity per CONTEXT.md Claude
# discretion: downtown, residential (west LA), and freeway-adjacent (Hollywood).
# Format: (min_lon, min_lat, max_lon, max_lat) -- longitude-first per
# Mapillary API v4 convention.
_DEFAULT_LA_BBOXES: dict[str, tuple[float, float, float, float]] = {
    "downtown":    (-118.258, 34.043, -118.248, 34.053),  # DTLA
    "residential": (-118.400, 34.050, -118.390, 34.060),  # West LA residential
    "freeway":     (-118.340, 34.060, -118.330, 34.070),  # Hollywood / adj freeway
}


def _build_fresh(
    out_root: Path,
    count_per_bbox: int,
    splits: tuple[float, float, float],
) -> int:
    """Fresh pull: search each default LA bbox, download, split, write manifest."""
    if not MAPILLARY_TOKEN:
        print(
            "ERROR: --build requires MAPILLARY_ACCESS_TOKEN. "
            "Get a token at https://www.mapillary.com/dashboard/developers",
            file=sys.stderr,
        )
        return EXIT_OTHER

    train_pct, val_pct, test_pct = splits
    if abs(sum(splits) - 1.0) > 1e-6:
        print(
            f"ERROR: split fractions must sum to 1.0, got {splits} "
            f"(sum={sum(splits)})",
            file=sys.stderr,
        )
        return EXIT_OTHER

    # Pitfall 3 pre-flight -- fail loudly before any network I/O
    for name, bbox in _DEFAULT_LA_BBOXES.items():
        validate_bbox(bbox)

    all_fetched: list[dict] = []
    for zone, bbox in _DEFAULT_LA_BBOXES.items():
        logger.info("Searching Mapillary in zone=%s bbox=%s", zone, bbox)
        results = search_images(bbox, limit=count_per_bbox)
        logger.info("  got %d results", len(results))
        all_fetched.extend([{**r, "_zone": zone} for r in results])

    if not all_fetched:
        print(
            "ERROR: Mapillary returned zero images across all bboxes.",
            file=sys.stderr,
        )
        return EXIT_OTHER

    # Split by sequence_id to avoid test contamination (Pitfall 7).
    # Project seed convention (SEED = 42, matches scripts/seed_data.py).
    rng = random.Random(42)
    sequences: dict[str, list[dict]] = {}
    for img in all_fetched:
        seq = str(img.get("sequence_id", f"no_seq_{img['id']}"))
        sequences.setdefault(seq, []).append(img)
    seq_ids = list(sequences.keys())
    rng.shuffle(seq_ids)
    n_total = len(seq_ids)
    n_train = int(n_total * train_pct)
    n_val = int(n_total * val_pct)
    split_assignment: dict[str, str] = {}
    for i, seq in enumerate(seq_ids):
        if i < n_train:
            split_assignment[seq] = "train"
        elif i < n_train + n_val:
            split_assignment[seq] = "val"
        else:
            split_assignment[seq] = "test"

    manifest_entries: list[dict] = []
    # Download in the same pass as metadata (Pitfall 5: URL TTL).
    for img in all_fetched:
        seq = str(img.get("sequence_id", f"no_seq_{img['id']}"))
        split = split_assignment[seq]
        out_dir = out_root / "images" / split
        try:
            written = download_image(img, out_dir)
        except Exception as exc:  # noqa: BLE001
            logger.warning("  download failed for %s: %s", img.get("id"), exc)
            continue
        rel = str(written.relative_to(out_root))
        manifest_entries.append(
            {
                "path": rel,
                "source_mapillary_id": str(img["id"]),
                "sequence_id": seq,
                "split": split,
            }
        )
        # Stub empty label file (operator hand-labels later with CVAT / LabelStudio).
        # Empty .txt = no pothole; operator replaces with YOLO-format labels.
        label_path = out_root / "labels" / split / f"{img['id']}.txt"
        label_path.parent.mkdir(parents=True, exist_ok=True)
        if not label_path.exists():
            label_path.write_text("")
        manifest_entries.append(
            {
                "path": str(label_path.relative_to(out_root)),
                "source_mapillary_id": str(img["id"]),
                "sequence_id": seq,
                "split": split,
            }
        )

    # Write manifest + data.yaml
    manifest_path = out_root / "manifest.json"
    write_manifest(
        manifest_path,
        manifest_entries,
        source_bucket=f"mapillary:bboxes={list(_DEFAULT_LA_BBOXES.keys())}",
        license_str=(
            "CC-BY-SA 4.0 (Mapillary open imagery -- "
            "attribution via source_mapillary_id)"
        ),
    )
    data_yaml = out_root / "data.yaml"
    data_yaml.write_text(
        "# Auto-generated by scripts/fetch_eval_data.py --build\n"
        "path: data/eval_la\n"
        "train: images/train\n"
        "val: images/val\n"
        "test: images/test\n"
        "\n"
        "nc: 1\n"
        "names:\n"
        "  0: pothole\n"
    )
    logger.info(
        "Build complete: %d files manifested, %d sequences split",
        len(manifest_entries),
        n_total,
    )
    print(
        f"\nBuilt dataset at {out_root}.\n"
        f"  Sequences: {n_total} "
        f"(train={n_train}, val={n_val}, test={n_total - n_train - n_val})\n"
        f"  Files: {len(manifest_entries)}\n"
        f"  NEXT: hand-label images under {out_root}/images/ using a "
        f"YOLO-compatible tool\n"
        f"  (CVAT recommended). Labels go under "
        f"{out_root}/labels/<split>/<image_id>.txt\n"
        f"  Re-run with --verify-only after labeling to confirm manifest.\n"
    )
    return EXIT_OK


def _verify(manifest_path: Path, data_root: Path) -> int:
    """Verify mode: hash-check every file listed in the manifest."""
    if not manifest_path.exists():
        print(
            f"Manifest not found at {manifest_path}.\n"
            f"  Run: python scripts/fetch_eval_data.py --build",
            file=sys.stderr,
        )
        return EXIT_MISSING_DATA
    missing, corrupt = verify_manifest(manifest_path, data_root)
    if missing:
        print(f"Missing files ({len(missing)}):", file=sys.stderr)
        for p in missing[:10]:
            print(f"  {p}", file=sys.stderr)
        if len(missing) > 10:
            print(f"  ... and {len(missing) - 10} more", file=sys.stderr)
    if corrupt:
        print(
            f"Corrupt files (SHA256 mismatch, {len(corrupt)}):",
            file=sys.stderr,
        )
        for p in corrupt[:10]:
            print(f"  {p}", file=sys.stderr)
    if missing or corrupt:
        print(
            "\n  Dataset integrity check FAILED.\n"
            "  Re-run: python scripts/fetch_eval_data.py --build",
            file=sys.stderr,
        )
        return EXIT_MISSING_DATA
    total = len(json.loads(manifest_path.read_text())["files"])
    print(f"Dataset OK: all {total} files match manifest.")
    return EXIT_OK


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch or verify the LA pothole eval dataset.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--verify-only",
        action="store_true",
        default=True,
        help="Hash-check existing dataset (default mode)",
    )
    group.add_argument(
        "--build",
        action="store_true",
        help="Fresh pull from Mapillary (requires MAPILLARY_ACCESS_TOKEN)",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("data/eval_la"),
        help="Dataset root (default: data/eval_la)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Manifest path (default: <root>/manifest.json)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=100,
        help="Images per bbox in --build mode (default 100 * 3 zones = 300 target)",
    )
    parser.add_argument(
        "--split-train",
        type=float,
        default=0.7,
        help="Train fraction (D-09 = 0.7)",
    )
    parser.add_argument(
        "--split-val",
        type=float,
        default=0.2,
        help="Val fraction (D-09 = 0.2)",
    )
    parser.add_argument(
        "--split-test",
        type=float,
        default=0.1,
        help="Test fraction (D-09 = 0.1)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    manifest_path = args.manifest or (args.root / "manifest.json")

    try:
        if args.build:
            args.root.mkdir(parents=True, exist_ok=True)
            return _build_fresh(
                args.root,
                count_per_bbox=args.count,
                splits=(args.split_train, args.split_val, args.split_test),
            )
        return _verify(manifest_path, args.root)
    except FileNotFoundError as e:
        print(f"Missing file: {e}", file=sys.stderr)
        return EXIT_MISSING_DATA
    except Exception:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        return EXIT_OTHER


if __name__ == "__main__":
    sys.exit(main())
