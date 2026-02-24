"""YOLOv8-based pothole detector for road quality analysis.

Requires:
    ultralytics >= 8.1
    opencv-python-headless >= 4.8

Place your trained model at models/pothole_yolov8.pt (relative to project root)
or pass a custom path via the model_path parameter.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from data_pipeline.detector import Detection

logger = logging.getLogger(__name__)

# Class name mappings for severity assignment
_SEVERE_CLASSES = {"severe_pothole", "severe"}
_MODERATE_CLASSES = {"moderate_pothole", "moderate"}
_GENERIC_CLASSES = {"pothole"}


class YOLOv8Detector:
    """Real YOLOv8 pothole detector satisfying the PotholeDetector protocol.

    Supports two model variants:
    1. Two-class model with "severe_pothole" and "moderate_pothole" classes
       -> Maps class names directly to severity.
    2. Single-class model with a "pothole" class
       -> Assigns severity based on confidence thresholds:
          confidence >= 0.7  -> "severe"
          confidence >= 0.4  -> "moderate"
          below 0.4          -> not reported
    """

    def __init__(
        self,
        model_path: str = "models/pothole_yolov8.pt",
        conf_threshold: float = 0.25,
    ) -> None:
        self.model_path = model_path
        self.conf_threshold = conf_threshold
        self._model = None

    def _load_model(self):
        """Lazy-load the YOLO model on first inference call."""
        if self._model is not None:
            return self._model

        from ultralytics import YOLO  # noqa: F811

        if not Path(self.model_path).exists():
            raise FileNotFoundError(
                f"Model file not found: {self.model_path}"
            )

        self._model = YOLO(self.model_path)
        logger.info("Loaded YOLOv8 model from %s", self.model_path)
        return self._model

    def detect(self, image_path: str) -> list[Detection]:
        """Run YOLOv8 inference on an image and return pothole detections.

        Args:
            image_path: Path to the image file to analyze.

        Returns:
            List of Detection objects with severity and confidence.
            Returns an empty list if the image is missing or inference fails.
        """
        # Validate image exists
        if not os.path.isfile(image_path):
            logger.warning("Image not found: %s — returning empty detections", image_path)
            return []

        # Attempt model load and inference
        try:
            model = self._load_model()
        except FileNotFoundError:
            logger.warning(
                "Model file not found at %s — returning empty detections",
                self.model_path,
            )
            return []
        except Exception:
            logger.exception(
                "Failed to load YOLOv8 model from %s", self.model_path
            )
            return []

        try:
            results = model(image_path, conf=self.conf_threshold, verbose=False)
        except Exception:
            logger.exception("YOLOv8 inference failed on %s", image_path)
            return []

        # Parse results
        detections: list[Detection] = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue

            class_names = result.names  # dict {class_id: class_name}

            for i in range(len(boxes)):
                confidence = float(boxes.conf[i])
                class_id = int(boxes.cls[i])
                class_name = class_names.get(class_id, "").lower().strip()

                severity = self._map_severity(class_name, confidence)
                if severity is None:
                    continue

                detections.append(
                    Detection(
                        severity=severity,
                        confidence=round(confidence, 3),
                    )
                )

        return detections

    @staticmethod
    def _map_severity(class_name: str, confidence: float) -> str | None:
        """Map a YOLO class name and confidence to a severity string.

        Two-class model logic:
            "severe_pothole" / "severe"     -> "severe"
            "moderate_pothole" / "moderate"  -> "moderate"

        Single-class ("pothole") logic:
            confidence >= 0.7  -> "severe"
            confidence >= 0.4  -> "moderate"
            below 0.4         -> None (not reported)

        Returns:
            "severe", "moderate", or None if the detection should be dropped.
        """
        if class_name in _SEVERE_CLASSES:
            return "severe"
        if class_name in _MODERATE_CLASSES:
            return "moderate"
        if class_name in _GENERIC_CLASSES:
            if confidence >= 0.7:
                return "severe"
            if confidence >= 0.4:
                return "moderate"
            return None  # Below threshold — not reported

        # Unknown class — log and skip
        logger.debug("Ignoring unknown class: %s", class_name)
        return None


if __name__ == "__main__":
    import sys

    image = sys.argv[1] if len(sys.argv) > 1 else "sample.jpg"
    print(f"Running YOLOv8 pothole detection on: {image}")

    detector = YOLOv8Detector()
    results = detector.detect(image)

    if not results:
        print("No detections (or model/image not available).")
    else:
        for det in results:
            print(f"  {det.severity:>10s}  confidence={det.confidence:.3f}")
