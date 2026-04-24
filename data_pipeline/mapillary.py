"""Mapillary API v4 client: search images by bbox, download for offline use.

Shared by Phase 2 (fetch_eval_data.py -- one-shot 300-image pull for eval set)
and Phase 3 (ingest_mapillary.py -- ongoing detection pipeline). Keeps the
API surface framework-agnostic (no argparse, no sys.exit) per the
scripts/iri_sources.py convention.

Mapillary API reference:
    https://www.mapillary.com/developer/api-documentation

Token acquisition:
    https://www.mapillary.com/dashboard/developers  (free, OAuth bearer)

Licensing:
    Mapillary open imagery is CC-BY-SA 4.0. Downstream datasets MUST
    preserve per-image attribution via source_mapillary_id.
    https://help.mapillary.com/hc/en-us/articles/115001770409

Pitfalls honored:
    - Pitfall 3: bbox must be <= 0.01 deg2 (validate_bbox guards this).
      The Mapillary v4 images endpoint expects bbox=min_lon,min_lat,max_lon,max_lat
      (longitude-first, NOT latitude-first).
    - Pitfall 5: thumb_2048_url TTL -- download immediately in same pass as search
    - Security V6: SHA256 compare uses hmac.compare_digest (constant-time)
    - Security V5: manifest path entries rejected if they contain ".."

Cross-phase reuse:
    Phase 3's scripts/ingest_mapillary.py imports from this module. Keep
    everything framework-agnostic (no argparse, no sys.exit); the CLI
    layer lives in scripts/fetch_eval_data.py.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

# Module-top env read (matches backend/app/db.py:5-7 pattern)
MAPILLARY_TOKEN = os.environ.get("MAPILLARY_ACCESS_TOKEN")

# Pitfall 3 DoS guard: Mapillary recommends <= 0.01 deg2 per direct bbox request.
# Larger areas require spatial tiling (mapillary-python-sdk does this automatically);
# for Phase 2 we use a fixed list of small bboxes and rely on this guard to fail
# loudly if an operator tries to pass something larger.
MAX_BBOX_AREA_DEG2 = 0.01

# IEEE 754 tolerance (unit: deg^2): (0.1 - 0.0) * (0.1 - 0.0) evaluates to
# 0.010000000000000002, an artifact of order 2e-18. We allow a tiny epsilon
# over MAX_BBOX_AREA_DEG2 to avoid rejecting perfectly valid lat/lon corners
# whose computed area hits that floating-point artifact.
#
# WR-05: the previous value 1e-9 was ~1e9x the demonstrated artifact and
# ~1e-5x MAX_BBOX_AREA_DEG2 itself, meaning a bbox whose intended area was
# 0.010000001 deg^2 (a genuinely-oversized request, not a float artifact)
# would slip past the DoS guard. Tighten to 1e-15 which is comfortably
# above 2e-18 (the real artifact) and safely below any meaningfully-larger
# bbox area. Regression tests in backend/tests/test_mapillary.py pin the
# ceiling and floor.
_BBOX_AREA_TOLERANCE = 1e-15

# Security V5: SHA256 hex must be 64 lowercase hex chars (defensive parse)
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

_API_BASE = "https://graph.mapillary.com"


def validate_bbox(bbox: tuple[float, float, float, float]) -> None:
    """Pitfall 3 guard: reject bboxes above Mapillary's direct-query limit.

    Args:
        bbox: (min_lon, min_lat, max_lon, max_lat) -- longitude-first per
            Mapillary v4 convention.

    Raises:
        ValueError: if bbox malformed or area exceeds MAX_BBOX_AREA_DEG2.
    """
    if len(bbox) != 4:
        raise ValueError(f"bbox must have 4 elements, got {len(bbox)}")
    min_lon, min_lat, max_lon, max_lat = bbox
    if max_lon <= min_lon or max_lat <= min_lat:
        raise ValueError(f"bbox corners out of order: {bbox}")
    area = (max_lon - min_lon) * (max_lat - min_lat)
    if area > MAX_BBOX_AREA_DEG2 + _BBOX_AREA_TOLERANCE:
        raise ValueError(
            f"bbox area {area:.4f} deg2 exceeds Mapillary direct-query limit "
            f"{MAX_BBOX_AREA_DEG2} deg2 (Pitfall 3). Split into smaller bboxes."
        )


def search_images(
    bbox: tuple[float, float, float, float],
    limit: int = 100,
    token: str | None = None,
    timeout_s: float = 30.0,
) -> list[dict[str, Any]]:
    """Search Mapillary for images inside a bbox.

    Args:
        bbox: (min_lon, min_lat, max_lon, max_lat) -- must be <= 0.01 deg2.
        limit: max images per request (Mapillary default 2000).
        token: Mapillary access token (falls back to MAPILLARY_ACCESS_TOKEN env).
        timeout_s: HTTP timeout.

    Returns:
        List of image metadata dicts (keys: id, thumb_2048_url,
        computed_geometry, captured_at, sequence_id).

    Raises:
        ValueError: bbox too large or malformed.
        RuntimeError: token missing.
        requests.HTTPError: API error.
    """
    validate_bbox(bbox)
    tok = token or MAPILLARY_TOKEN
    if not tok:
        raise RuntimeError(
            "MAPILLARY_ACCESS_TOKEN not set. Get one at "
            "https://www.mapillary.com/dashboard/developers"
        )
    params = {
        "bbox": ",".join(str(c) for c in bbox),
        "fields": "id,thumb_2048_url,computed_geometry,captured_at,sequence_id",
        "limit": limit,
    }
    headers = {"Authorization": f"OAuth {tok}"}
    r = requests.get(
        f"{_API_BASE}/images", params=params, headers=headers, timeout=timeout_s
    )
    r.raise_for_status()
    data = r.json().get("data", [])
    logger.info("Mapillary search bbox=%s returned %d images", bbox, len(data))
    return data


def download_image(
    image_meta: dict[str, Any],
    out_dir: Path,
    timeout_s: float = 60.0,
) -> Path:
    """Download a single Mapillary image.

    URLs expire (Pitfall 5) -- callers MUST fetch metadata + download in the
    same pass; do NOT batch-fetch all URLs then batch-download.

    Args:
        image_meta: dict from search_images (must have 'id' and 'thumb_2048_url').
        out_dir: directory to write <image_id>.jpg into (created if missing).
        timeout_s: HTTP timeout.

    Returns:
        Path to the written file.

    Raises:
        ValueError: if meta is missing required fields or image id is malformed
            (T-02-20: only digits permitted to prevent path-injection via filename).
        requests.HTTPError: download failure (including expired URL 403/404).
    """
    url = image_meta.get("thumb_2048_url")
    if not url:
        raise ValueError(f"image_meta missing thumb_2048_url: {image_meta}")
    image_id = str(image_meta["id"])
    # T-02-20: validate image id is digits-only before using it as a filename
    if not re.fullmatch(r"[0-9]+", image_id):
        raise ValueError(f"unexpected image id format: {image_id!r}")
    out_dir.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, timeout=timeout_s)
    r.raise_for_status()
    out_path = out_dir / f"{image_id}.jpg"
    out_path.write_bytes(r.content)
    logger.debug(
        "Downloaded %s -> %s (%d bytes)", image_id, out_path, len(r.content)
    )
    return out_path


def _sha256_of_file(path: Path) -> str:
    """Compute SHA256 hex digest of a file, streaming 64KiB chunks."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _validate_manifest_path(rel: str) -> None:
    """Security V5: reject path-traversal attempts in manifest entries.

    Manifest `path` fields are relative to the dataset root. Any `..`
    component or absolute-path marker indicates either a malformed manifest
    or a tampering attempt (T-02-14).
    """
    if ".." in Path(rel).parts or rel.startswith(("/", "\\")):
        raise ValueError(f"manifest path entry rejected (traversal): {rel!r}")


def verify_manifest(
    manifest_path: Path,
    data_root: Path,
) -> tuple[list[str], list[str]]:
    """Verify every file in the manifest matches its recorded SHA256.

    Uses hmac.compare_digest for constant-time compare (Security V6, T-02-13)
    to avoid leaking information about where in the hash comparison an
    attacker-crafted tampered-manifest would diverge from the real file.

    Args:
        manifest_path: path to manifest.json (schema version 1.0).
        data_root: directory the manifest's `path` entries are relative to.

    Returns:
        (missing_files, corrupt_files) -- lists of relative paths.

    Raises:
        FileNotFoundError: manifest.json itself is missing.
        ValueError: manifest malformed, unsupported version, contains
            path-traversal entries (T-02-14), or contains malformed SHA256
            hex (T-02-15).
    """
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("version") != "1.0":
        raise ValueError(
            f"Unsupported manifest version: {manifest.get('version')}"
        )
    missing: list[str] = []
    corrupt: list[str] = []
    for entry in manifest.get("files", []):
        rel = entry["path"]
        _validate_manifest_path(rel)
        expected = entry["sha256"]
        if not _SHA256_HEX_RE.match(expected):
            raise ValueError(
                f"Invalid sha256 in manifest for {rel!r}: "
                "must be 64 lowercase hex chars"
            )
        local = data_root / rel
        if not local.exists():
            missing.append(rel)
            continue
        actual = _sha256_of_file(local)
        # Constant-time compare -- Security V6, T-02-13
        if not hmac.compare_digest(actual, expected):
            corrupt.append(rel)
    return missing, corrupt


def write_manifest(
    manifest_path: Path,
    files: list[dict[str, Any]],
    source_bucket: str = "local",
    license_str: str = "CC-BY-SA 4.0 (Mapillary imagery)",
) -> None:
    """Write a manifest.json with computed SHA256 hashes for each file.

    Args:
        manifest_path: output path (will be overwritten).
        files: list of dicts with keys: "path" (required, relative to
            manifest_path.parent), plus "source_mapillary_id", "sequence_id",
            "split" (all optional but recommended for attribution). The
            "sha256" field is computed here from `manifest_path.parent / path`.
        source_bucket: bucket URI for documentation (e.g., HF datasets URL).
        license_str: license text (CC-BY-SA 4.0 for Mapillary-derived content).

    Raises:
        FileNotFoundError: a listed file does not exist under data_root.
        ValueError: a path entry attempts path traversal.
    """
    data_root = manifest_path.parent
    entries: list[dict[str, Any]] = []
    for entry in files:
        rel = entry["path"]
        _validate_manifest_path(rel)
        local = data_root / rel
        if not local.exists():
            raise FileNotFoundError(
                f"Manifest file missing during write: {local}"
            )
        entries.append(
            {
                **entry,
                "sha256": _sha256_of_file(local),
            }
        )
    manifest = {
        "version": "1.0",
        "source_bucket": source_bucket,
        "license": license_str,
        "files": entries,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    logger.info(
        "Wrote manifest with %d files to %s", len(entries), manifest_path
    )
