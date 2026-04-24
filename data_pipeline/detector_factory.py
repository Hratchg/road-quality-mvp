"""Factory for creating the appropriate PotholeDetector implementation.

Usage:
    from data_pipeline.detector_factory import get_detector

    # MVP / testing — deterministic stub
    detector = get_detector(use_yolo=False)

    # Production — real YOLOv8 model (falls back to stub if ultralytics missing)
    detector = get_detector(use_yolo=True, model_path="models/pothole_yolov8.pt")

    # HuggingFace — resolved via hf_hub_download, then passed to YOLOv8Detector
    detector = get_detector(use_yolo=True, model_path="user/repo")

The factory reads the ``YOLO_MODEL_PATH`` env var at module top (matches
``backend/app/db.py`` convention). Precedence: explicit ``model_path`` arg >
``YOLO_MODEL_PATH`` env > ``_DEFAULT_HF_REPO``.

Phase 2 D-14 correction: ultralytics' ``YOLO()`` does NOT auto-resolve HF repo
names. The factory performs the HF download explicitly via
``huggingface_hub.hf_hub_download`` and passes the resolved local path to
``YOLOv8Detector``.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from data_pipeline.detector import PotholeDetector, StubDetector

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Default HF repo to fall back to if YOLO_MODEL_PATH is unset AND use_yolo=True.
# Bumped explicitly when a new fine-tune is published (see Pitfall 8 in
# .planning/phases/02-real-data-detector-accuracy/02-RESEARCH.md).
_DEFAULT_HF_REPO = "keremberke/yolov8s-pothole-segmentation"
_DEFAULT_HF_FILENAME = "best.pt"

# Matches "user/repo" or "user/repo@revision" — NOT "./path" or "/abs/path".
_HF_REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(@[A-Za-z0-9_.-]+)?$")

YOLO_MODEL_PATH_ENV = os.environ.get("YOLO_MODEL_PATH")  # None = factory default


def _resolve_model_path(value: str | None) -> str:
    """Turn a YOLO_MODEL_PATH value into an on-disk .pt file path.

    Accepts:
        "user/repo"              -> hf_hub_download from that repo (best.pt by convention)
        "user/repo:filename.pt"  -> specific file inside the repo
        "user/repo@revision"     -> pinned revision (passed through to hf_hub_download)
        "/abs/path.pt"           -> used as-is
        "./relative/path.pt"     -> used as-is (existence checked lazily by YOLOv8Detector)
        None                     -> falls back to _DEFAULT_HF_REPO
    """
    target = value or _DEFAULT_HF_REPO

    # Explicit local path: starts with ./ or / or ../, or is an existing .pt file
    if target.startswith(("./", "/", "../")) or (
        target.endswith(".pt") and Path(target).exists()
    ):
        return target

    # HF repo id (optional :filename suffix, optional @revision)
    repo_with_rev, _, filename = target.partition(":")
    repo_id, _, revision = repo_with_rev.partition("@")
    # WR-06: reject repo ids whose second segment ends in ``.pt``. The regex
    # matches "foo/bar.pt" because ``.`` is in the character class, but no
    # legitimate HF repo is named ``*.pt`` — it is almost certainly a typo'd
    # local path, and handing it to hf_hub_download opens a remote-pickle
    # (T-02-01 ACE) vector if an attacker has registered that name. Treat as
    # local; YOLOv8Detector will raise FileNotFoundError with a clear message.
    if not _HF_REPO_PATTERN.match(repo_with_rev) or repo_id.endswith(".pt"):
        # Not a recognizable HF id; treat as local path, let YOLOv8Detector raise on load
        return target

    from huggingface_hub import hf_hub_download  # lazy import

    kwargs: dict = {"repo_id": repo_id, "filename": filename or _DEFAULT_HF_FILENAME}
    if revision:
        kwargs["revision"] = revision
    return hf_hub_download(**kwargs)


def get_detector(
    use_yolo: bool = False,
    model_path: str | None = None,
) -> PotholeDetector:
    """Return the appropriate pothole detector.

    Args:
        use_yolo: If True, attempt to create a YOLOv8Detector.
                  Falls back to StubDetector if ultralytics is not installed.
        model_path: Optional override for the model path. May be an HF repo id
                    ("user/repo", "user/repo:file.pt", "user/repo@revision") or
                    a local .pt file path. If None, falls back to the
                    ``YOLO_MODEL_PATH`` env var; if that is also unset, falls
                    back to ``_DEFAULT_HF_REPO``.

    Returns:
        An object satisfying the PotholeDetector protocol.
    """
    if not use_yolo:
        logger.info("Using StubDetector (use_yolo=False)")
        return StubDetector()

    # Attempt to import the YOLO detector adapter
    try:
        from data_pipeline.yolo_detector import YOLOv8Detector
    except ImportError:
        logger.warning(
            "ultralytics is not installed — falling back to StubDetector. "
            "Install with: pip install ultralytics>=8.1"
        )
        return StubDetector()

    # Precedence: explicit model_path arg > YOLO_MODEL_PATH env > _DEFAULT_HF_REPO
    explicit_value = model_path if model_path is not None else YOLO_MODEL_PATH_ENV
    resolved = _resolve_model_path(explicit_value)
    logger.info("Using YOLOv8Detector (resolved_model_path=%s)", resolved)
    return YOLOv8Detector(model_path=resolved)
