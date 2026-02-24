"""Tests for YOLOv8Detector and detector_factory.

These tests do NOT require ultralytics to be installed and do NOT require
a real model file. All YOLO internals are mocked.
"""

import sys
import os
import types
from unittest.mock import MagicMock, patch

import pytest

# Ensure the project root is on sys.path so data_pipeline is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from data_pipeline.detector import Detection, StubDetector


# ---------------------------------------------------------------------------
# Helpers — build a mock ultralytics module so imports succeed even without
# the real package installed.
# ---------------------------------------------------------------------------


def _make_mock_ultralytics():
    """Create a mock ultralytics module with a YOLO class."""
    mock_mod = types.ModuleType("ultralytics")
    mock_mod.YOLO = MagicMock  # type: ignore[attr-defined]
    return mock_mod


# ---------------------------------------------------------------------------
# 1. Protocol conformance
# ---------------------------------------------------------------------------


def test_yolo_detector_protocol():
    """YOLOv8Detector has the correct detect(image_path) -> list[Detection] signature."""
    # Patch ultralytics into sys.modules so the import inside yolo_detector succeeds
    mock_ul = _make_mock_ultralytics()
    with patch.dict(sys.modules, {"ultralytics": mock_ul}):
        from data_pipeline.yolo_detector import YOLOv8Detector

        detector = YOLOv8Detector(model_path="fake.pt")

        # Verify the instance has a callable detect method
        assert hasattr(detector, "detect")
        assert callable(detector.detect)

        # Verify detect accepts image_path and the return annotation is list[Detection]
        import inspect

        sig = inspect.signature(detector.detect)
        params = list(sig.parameters.keys())
        assert "image_path" in params


# ---------------------------------------------------------------------------
# 2. Factory — stub path
# ---------------------------------------------------------------------------


def test_detector_factory_stub():
    """get_detector(use_yolo=False) returns a StubDetector."""
    from data_pipeline.detector_factory import get_detector

    detector = get_detector(use_yolo=False)
    assert isinstance(detector, StubDetector)


# ---------------------------------------------------------------------------
# 3. Factory — YOLO fallback when ultralytics is NOT installed
# ---------------------------------------------------------------------------


def test_detector_factory_yolo_fallback():
    """get_detector(use_yolo=True) falls back to StubDetector when
    ultralytics is not importable."""
    # Temporarily make yolo_detector's import of ultralytics fail
    # by hiding the yolo_detector module itself (it tries to import ultralytics
    # at class-level lazy load, but the factory imports the module).
    # The easiest approach: make `from data_pipeline.yolo_detector import ...`
    # raise ImportError.
    original = sys.modules.get("data_pipeline.yolo_detector")
    original_ul = sys.modules.get("ultralytics")
    try:
        # Remove cached modules so factory re-imports
        sys.modules.pop("data_pipeline.yolo_detector", None)
        sys.modules.pop("ultralytics", None)
        # Force the import inside the factory to fail
        sys.modules["data_pipeline.yolo_detector"] = None  # type: ignore[assignment]

        # Re-import factory to test fresh
        import importlib
        from data_pipeline import detector_factory

        importlib.reload(detector_factory)

        detector = detector_factory.get_detector(use_yolo=True)
        assert isinstance(detector, StubDetector)
    finally:
        # Restore
        sys.modules.pop("data_pipeline.yolo_detector", None)
        if original is not None:
            sys.modules["data_pipeline.yolo_detector"] = original
        if original_ul is not None:
            sys.modules["ultralytics"] = original_ul


# ---------------------------------------------------------------------------
# 4. Missing image returns empty list
# ---------------------------------------------------------------------------


def test_yolo_detector_missing_image():
    """detect() on a nonexistent image path returns an empty list."""
    mock_ul = _make_mock_ultralytics()
    with patch.dict(sys.modules, {"ultralytics": mock_ul}):
        from data_pipeline.yolo_detector import YOLOv8Detector

        detector = YOLOv8Detector(model_path="fake.pt")
        result = detector.detect("/nonexistent/path/to/image.jpg")
        assert result == []


# ---------------------------------------------------------------------------
# 5. Severity mapping — two-class model
# ---------------------------------------------------------------------------


def test_severity_mapping_two_class():
    """_map_severity correctly maps severe_pothole / moderate_pothole classes."""
    mock_ul = _make_mock_ultralytics()
    with patch.dict(sys.modules, {"ultralytics": mock_ul}):
        from data_pipeline.yolo_detector import YOLOv8Detector

        assert YOLOv8Detector._map_severity("severe_pothole", 0.9) == "severe"
        assert YOLOv8Detector._map_severity("severe_pothole", 0.3) == "severe"
        assert YOLOv8Detector._map_severity("moderate_pothole", 0.8) == "moderate"
        assert YOLOv8Detector._map_severity("moderate_pothole", 0.2) == "moderate"


# ---------------------------------------------------------------------------
# 6. Severity mapping — single-class model
# ---------------------------------------------------------------------------


def test_severity_mapping_single_class():
    """_map_severity assigns severity by confidence for the generic 'pothole' class."""
    mock_ul = _make_mock_ultralytics()
    with patch.dict(sys.modules, {"ultralytics": mock_ul}):
        from data_pipeline.yolo_detector import YOLOv8Detector

        # High confidence -> severe
        assert YOLOv8Detector._map_severity("pothole", 0.85) == "severe"
        assert YOLOv8Detector._map_severity("pothole", 0.70) == "severe"

        # Medium confidence -> moderate
        assert YOLOv8Detector._map_severity("pothole", 0.55) == "moderate"
        assert YOLOv8Detector._map_severity("pothole", 0.40) == "moderate"

        # Low confidence -> not reported
        assert YOLOv8Detector._map_severity("pothole", 0.39) is None
        assert YOLOv8Detector._map_severity("pothole", 0.1) is None


# ---------------------------------------------------------------------------
# 7. Unknown class is ignored
# ---------------------------------------------------------------------------


def test_severity_mapping_unknown_class():
    """_map_severity returns None for classes that are not pothole-related."""
    mock_ul = _make_mock_ultralytics()
    with patch.dict(sys.modules, {"ultralytics": mock_ul}):
        from data_pipeline.yolo_detector import YOLOv8Detector

        assert YOLOv8Detector._map_severity("car", 0.95) is None
        assert YOLOv8Detector._map_severity("crack", 0.80) is None
