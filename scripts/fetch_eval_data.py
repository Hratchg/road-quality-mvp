"""Fetch or verify the LA pothole eval dataset.

Modes:
    --verify-only (default): hash-check every file in data/eval_la/
                             against manifest.json. Exits 3 if manifest or
                             any file missing / corrupt.

    --build:                 Fresh pull from Mapillary across configurable
                             LA bboxes. Writes new images into
                             data/eval_la/images/<split>/, regenerates
                             manifest.json (overwriting), and creates empty
                             stub label files only where none exist. Existing
                             hand-labels under data/eval_la/labels/ are
                             PRESERVED so annotation work is not lost across
                             re-runs; pass --clean to wipe images/ and labels/
                             before downloading. Stale files whose image_id
                             does not reappear in the new query will remain
                             on disk unless --clean is passed. Requires
                             MAPILLARY_ACCESS_TOKEN.

    --clean:                 Only meaningful with --build. rmtree's
                             <root>/images/ and <root>/labels/ before the
                             fresh pull so the resulting dataset is a
                             bit-for-bit fresh state (WR-02 contract).

Usage:
    # Verify (default, safe):
    python scripts/fetch_eval_data.py
    python scripts/fetch_eval_data.py --verify-only

    # Build fresh (requires env token, long-running, network-heavy):
    MAPILLARY_ACCESS_TOKEN=... python scripts/fetch_eval_data.py --build --count 100

    # Build fresh, wiping any prior images/labels first:
    MAPILLARY_ACCESS_TOKEN=... python scripts/fetch_eval_data.py --build --clean

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
import shutil
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

# Default LA bboxes for --build mode. Phase 7 D-02 / D-04 expansion to
# 12 zones × 4 sub-tiles = 48 entries (~960 images at --count 20,
# ~1500 at --count 32).
# Each is 0.005 deg per side (~550m), subdivided 2x2 from a 0.01-deg
# parent zone (Phase 6 D-03 fix: Mapillary 500 errors above 0.01 deg^2
# for dense imagery — RESEARCH §2.1 Pitfall 4).
#
# Format: (min_lon, min_lat, max_lon, max_lat) -- longitude-first per
# Mapillary API v4 convention.
#
# Zone groups:
# - Phase 6 carry-forward (D-06): downtown, residential (West LA), freeway (Hollywood)
#   --> existing 17 hand-labels in data/eval_la/labels/ are preserved across --build
#       runs IF --clean is not passed
# - Phase 7 spread (D-02): echopark, koreatown, inglewood, eaglerock, venice, culvercity
# - Phase 7 known-bad-pavement (D-04): midcity (east of La Brea),
#   boyleheights, southla (Vermont Square)
_DEFAULT_LA_BBOXES: dict[str, tuple[float, float, float, float]] = {
    # ----- Phase 6 carry-forward zones (D-06: keep so existing 17 hand-labels merge in via --build without --clean) -----
    # Downtown LA (DTLA): 2x2 subdivision of (-118.258, 34.043, -118.248, 34.053)
    "downtown_sw":    (-118.258, 34.043, -118.253, 34.048),
    "downtown_se":    (-118.253, 34.043, -118.248, 34.048),
    "downtown_nw":    (-118.258, 34.048, -118.253, 34.053),
    "downtown_ne":    (-118.253, 34.048, -118.248, 34.053),
    # West LA residential: 2x2 subdivision of (-118.400, 34.050, -118.390, 34.060)
    "residential_sw": (-118.400, 34.050, -118.395, 34.055),
    "residential_se": (-118.395, 34.050, -118.390, 34.055),
    "residential_nw": (-118.400, 34.055, -118.395, 34.060),
    "residential_ne": (-118.395, 34.055, -118.390, 34.060),
    # Hollywood / adj freeway: 2x2 subdivision of (-118.340, 34.060, -118.330, 34.070)
    "freeway_sw":     (-118.340, 34.060, -118.335, 34.065),
    "freeway_se":     (-118.335, 34.060, -118.330, 34.065),
    "freeway_nw":     (-118.340, 34.065, -118.335, 34.070),
    "freeway_ne":     (-118.335, 34.065, -118.330, 34.070),
    # ----- Phase 7 D-02: spread zones (north / south / east / west LA coverage) -----
    # Echo Park / Silver Lake (north central): subdivision of (-118.265, 34.075, -118.255, 34.085)
    "echopark_sw":    (-118.265, 34.075, -118.260, 34.080),
    "echopark_se":    (-118.260, 34.075, -118.255, 34.080),
    "echopark_nw":    (-118.265, 34.080, -118.260, 34.085),
    "echopark_ne":    (-118.260, 34.080, -118.255, 34.085),
    # Koreatown (central): subdivision of (-118.305, 34.058, -118.295, 34.068)
    "koreatown_sw":   (-118.305, 34.058, -118.300, 34.063),
    "koreatown_se":   (-118.300, 34.058, -118.295, 34.063),
    "koreatown_nw":   (-118.305, 34.063, -118.300, 34.068),
    "koreatown_ne":   (-118.300, 34.063, -118.295, 34.068),
    # Inglewood / Westchester (south west): subdivision of (-118.380, 33.960, -118.370, 33.970)
    "inglewood_sw":   (-118.380, 33.960, -118.375, 33.965),
    "inglewood_se":   (-118.375, 33.960, -118.370, 33.965),
    "inglewood_nw":   (-118.380, 33.965, -118.375, 33.970),
    "inglewood_ne":   (-118.375, 33.965, -118.370, 33.970),
    # Eagle Rock (north east): subdivision of (-118.215, 34.135, -118.205, 34.145)
    "eaglerock_sw":   (-118.215, 34.135, -118.210, 34.140),
    "eaglerock_se":   (-118.210, 34.135, -118.205, 34.140),
    "eaglerock_nw":   (-118.215, 34.140, -118.210, 34.145),
    "eaglerock_ne":   (-118.210, 34.140, -118.205, 34.145),
    # Venice (west): subdivision of (-118.475, 33.985, -118.465, 33.995)
    "venice_sw":      (-118.475, 33.985, -118.470, 33.990),
    "venice_se":      (-118.470, 33.985, -118.465, 33.990),
    "venice_nw":      (-118.475, 33.990, -118.470, 33.995),
    "venice_ne":      (-118.470, 33.990, -118.465, 33.995),
    # Culver City (south central, adjacent West LA): subdivision of (-118.405, 34.015, -118.395, 34.025)
    "culvercity_sw":  (-118.405, 34.015, -118.400, 34.020),
    "culvercity_se":  (-118.400, 34.015, -118.395, 34.020),
    "culvercity_nw":  (-118.405, 34.020, -118.400, 34.025),
    "culvercity_ne":  (-118.400, 34.020, -118.395, 34.025),
    # ----- Phase 7 D-04: known-bad-pavement zones (operator-supplied) -----
    # Mid-City east of La Brea: subdivision of (-118.345, 34.045, -118.335, 34.055)
    "midcity_sw":     (-118.345, 34.045, -118.340, 34.050),
    "midcity_se":     (-118.340, 34.045, -118.335, 34.050),
    "midcity_nw":     (-118.345, 34.050, -118.340, 34.055),
    "midcity_ne":     (-118.340, 34.050, -118.335, 34.055),
    # Boyle Heights (east of DTLA): subdivision of (-118.215, 34.030, -118.205, 34.040)
    "boyleheights_sw":(-118.215, 34.030, -118.210, 34.035),
    "boyleheights_se":(-118.210, 34.030, -118.205, 34.035),
    "boyleheights_nw":(-118.215, 34.035, -118.210, 34.040),
    "boyleheights_ne":(-118.210, 34.035, -118.205, 34.040),
    # South LA (Vermont Square area): subdivision of (-118.295, 34.000, -118.285, 34.010)
    "southla_sw":     (-118.295, 34.000, -118.290, 34.005),
    "southla_se":     (-118.290, 34.000, -118.285, 34.005),
    "southla_nw":     (-118.295, 34.005, -118.290, 34.010),
    "southla_ne":     (-118.290, 34.005, -118.285, 34.010),
}


def _build_fresh(
    out_root: Path,
    count_per_bbox: int,
    splits: tuple[float, float, float],
    clean: bool = False,
) -> int:
    """Fresh pull: search each default LA bbox, download, split, write manifest.

    When ``clean`` is True, ``<out_root>/images/`` and ``<out_root>/labels/``
    are ``shutil.rmtree``-d before any download so the resulting tree is a
    genuine fresh state (WR-02 contract). Otherwise, existing hand-labels are
    preserved and stale files whose image_id does not reappear in the new
    query will remain on disk.
    """
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

    # WR-02: when --clean is set, wipe images/ and labels/ so the fresh pull
    # starts from an empty tree. Without this flag, stale files whose image_id
    # does not reappear in the new query remain on disk (documented contract).
    if clean:
        for sub in ("images", "labels"):
            d = out_root / sub
            if d.exists():
                shutil.rmtree(d)
                logger.info("--clean: removed %s", d)

    import requests as _requests  # local import to avoid module-level clash

    all_fetched: list[dict] = []
    skipped_zones: list[str] = []
    for zone, bbox in _DEFAULT_LA_BBOXES.items():
        logger.info("Searching Mapillary in zone=%s bbox=%s", zone, bbox)
        # D-05 (Phase 7): recency filter to >= 2023 imagery. quality_score
        # is NOT available via Mapillary v4 search API (RESEARCH §2.1) so
        # operator judgment during CVAT labeling handles per-image quality.
        # Rule 1 (Bug): Mapillary v4 intermittently returns HTTP 500 on specific
        # sub-tile bboxes (Pitfall 4). Catch per-bbox so a single zone failure
        # does not abort the entire build (remaining zones may succeed fine).
        try:
            results = search_images(
                bbox,
                limit=count_per_bbox,
                start_captured_at="2023-01-01T00:00:00Z",
            )
        except _requests.HTTPError as exc:
            logger.warning(
                "  zone=%s: Mapillary returned %s -- skipping zone "
                "(Pitfall 4: transient 500 on dense-imagery bbox)",
                zone,
                exc.response.status_code if exc.response is not None else "?",
            )
            skipped_zones.append(zone)
            continue
        logger.info("  got %d results", len(results))
        all_fetched.extend([{**r, "_zone": zone} for r in results])
    if skipped_zones:
        logger.warning(
            "Skipped %d zone(s) due to Mapillary API errors: %s",
            len(skipped_zones),
            skipped_zones,
        )

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
        # Intentionally do NOT overwrite an existing label file: hand-annotation
        # work is preserved across `--build` re-runs. Operators who need a
        # fresh state should pass `--clean`, which wipes the labels/ tree
        # before this loop (see WR-02 in 02-REVIEW.md).
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

    # WR-03: reject a silently-zero build. If every download failed (Pitfall 5
    # URL TTL, rate limits, transient network) we must NOT exit 0 with an empty
    # manifest — a CI job on the next step would then "verify OK" a 0-file
    # dataset. Fail loudly so the operator investigates.
    if not manifest_entries:
        print(
            "ERROR: no files survived download. Check Mapillary rate limits "
            "and URL TTL (Pitfall 5 in 02-RESEARCH.md).",
            file=sys.stderr,
        )
        return EXIT_OTHER
    # And guard against a degenerate split (e.g. --count 1 per bbox) that
    # produces a zero-image test or val split — a training dead end.
    if n_total < 3:
        print(
            f"ERROR: only {n_total} sequence(s) available; need >=3 to split "
            "into train/val/test (D-09). Pass a larger --count or widen bboxes.",
            file=sys.stderr,
        )
        return EXIT_OTHER

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
    # WR-04: argparse's add_mutually_exclusive_group only blocks BOTH flags
    # being passed on the same line. With default=True on --verify-only, the
    # mutex was silently always-True regardless of --build, giving readers a
    # false sense that "exactly one mode" is enforced. Drop default=True and
    # resolve the mode explicitly below.
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--verify-only",
        action="store_true",
        default=False,
        help="Hash-check existing dataset (default mode when neither flag set)",
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
        default=25,
        help="Images per bbox in --build mode (default 25 * 12 sub-tiles = 300 target)",
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
    parser.add_argument(
        "--clean",
        action="store_true",
        help=(
            "With --build only: shutil.rmtree <root>/images/ and <root>/labels/ "
            "before downloading, for a genuinely fresh state. Without this flag, "
            "existing hand-labels are preserved and stale images may remain on "
            "disk (WR-02 contract)."
        ),
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
                clean=args.clean,
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
