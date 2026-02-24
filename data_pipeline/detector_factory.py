"""Factory for creating the appropriate PotholeDetector implementation.

Usage:
    from data_pipeline.detector_factory import get_detector

    # MVP / testing — deterministic stub
    detector = get_detector(use_yolo=False)

    # Production — real YOLOv8 model (falls back to stub if ultralytics missing)
    detector = get_detector(use_yolo=True, model_path="models/pothole_yolov8.pt")
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from data_pipeline.detector import PotholeDetector, StubDetector

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def get_detector(
    use_yolo: bool = False,
    model_path: str | None = None,
) -> PotholeDetector:
    """Return the appropriate pothole detector.

    Args:
        use_yolo: If True, attempt to create a YOLOv8Detector.
                  Falls back to StubDetector if ultralytics is not installed.
        model_path: Optional path to a YOLOv8 .pt model file.
                    Defaults to "models/pothole_yolov8.pt" when use_yolo=True.

    Returns:
        An object satisfying the PotholeDetector protocol.
    """
    if not use_yolo:
        logger.info("Using StubDetector (use_yolo=False)")
        return StubDetector()

    # Attempt to import and instantiate the YOLO detector
    try:
        from data_pipeline.yolo_detector import YOLOv8Detector
    except ImportError:
        logger.warning(
            "ultralytics is not installed — falling back to StubDetector. "
            "Install with: pip install ultralytics>=8.1"
        )
        return StubDetector()

    kwargs: dict = {}
    if model_path is not None:
        kwargs["model_path"] = model_path

    logger.info(
        "Using YOLOv8Detector (model_path=%s)",
        model_path or "models/pothole_yolov8.pt",
    )
    return YOLOv8Detector(**kwargs)
