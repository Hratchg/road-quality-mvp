import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from data_pipeline.detector import StubDetector, Detection


def test_stub_detector_returns_detections():
    detector = StubDetector(seed=42)
    results = detector.detect("test_image.jpg")
    assert isinstance(results, list)
    for d in results:
        assert isinstance(d, Detection)
        assert d.severity in ("moderate", "severe")
        assert 0.0 <= d.confidence <= 1.0


def test_stub_detector_is_deterministic():
    d1 = StubDetector(seed=42).detect("test_image.jpg")
    d2 = StubDetector(seed=42).detect("test_image.jpg")
    assert len(d1) == len(d2)
    for a, b in zip(d1, d2):
        assert a.severity == b.severity
        assert a.confidence == b.confidence
