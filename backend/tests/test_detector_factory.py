"""Tests for detector_factory env-var + HF resolution.

These tests do NOT require ultralytics or huggingface_hub to be installed —
all external calls are mocked. Extends the existing factory coverage in
test_yolo_detector.py with env-driven path resolution (Phase 2 SC #2, SC #3).
"""

import importlib
import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# Ensure the project root is on sys.path so data_pipeline is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from data_pipeline.detector import StubDetector


def _make_mock_ultralytics():
    """Create a mock ultralytics module with a YOLO class."""
    mock_mod = types.ModuleType("ultralytics")
    mock_mod.YOLO = MagicMock  # type: ignore[attr-defined]
    return mock_mod


def _reload_factory():
    """Reload detector_factory so YOLO_MODEL_PATH_ENV re-reads from env."""
    from data_pipeline import detector_factory
    importlib.reload(detector_factory)
    return detector_factory


class TestResolveModelPath:
    def test_none_returns_default_hf_repo_via_hf_hub_download(self, monkeypatch):
        monkeypatch.delenv("YOLO_MODEL_PATH", raising=False)
        factory = _reload_factory()
        with patch("huggingface_hub.hf_hub_download", return_value="/tmp/sentinel/best.pt") as mock_dl:
            resolved = factory._resolve_model_path(None)
            assert resolved == "/tmp/sentinel/best.pt"
            mock_dl.assert_called_once()
            call_kwargs = mock_dl.call_args.kwargs
            assert call_kwargs["repo_id"] == "keremberke/yolov8s-pothole-segmentation"
            assert call_kwargs["filename"] == "best.pt"

    def test_hf_repo_id_calls_hf_hub_download(self):
        factory = _reload_factory()
        with patch("huggingface_hub.hf_hub_download", return_value="/tmp/sentinel/best.pt") as mock_dl:
            resolved = factory._resolve_model_path("user/repo")
            assert resolved == "/tmp/sentinel/best.pt"
            assert mock_dl.call_args.kwargs["repo_id"] == "user/repo"
            assert mock_dl.call_args.kwargs["filename"] == "best.pt"

    def test_hf_repo_with_filename_suffix(self):
        factory = _reload_factory()
        with patch("huggingface_hub.hf_hub_download", return_value="/tmp/custom.pt") as mock_dl:
            resolved = factory._resolve_model_path("user/repo:custom.pt")
            assert resolved == "/tmp/custom.pt"
            assert mock_dl.call_args.kwargs["filename"] == "custom.pt"

    def test_hf_repo_with_revision_pin(self):
        factory = _reload_factory()
        with patch("huggingface_hub.hf_hub_download", return_value="/tmp/pinned.pt") as mock_dl:
            resolved = factory._resolve_model_path("user/repo@abc123")
            assert resolved == "/tmp/pinned.pt"
            assert mock_dl.call_args.kwargs["revision"] == "abc123"
            assert mock_dl.call_args.kwargs["repo_id"] == "user/repo"

    def test_absolute_local_path_passthrough(self):
        factory = _reload_factory()
        with patch("huggingface_hub.hf_hub_download") as mock_dl:
            resolved = factory._resolve_model_path("/abs/path/to/model.pt")
            assert resolved == "/abs/path/to/model.pt"
            mock_dl.assert_not_called()

    def test_relative_local_path_passthrough(self):
        factory = _reload_factory()
        with patch("huggingface_hub.hf_hub_download") as mock_dl:
            resolved = factory._resolve_model_path("./models/my.pt")
            assert resolved == "./models/my.pt"
            mock_dl.assert_not_called()

    def test_parent_relative_local_path_passthrough(self):
        factory = _reload_factory()
        with patch("huggingface_hub.hf_hub_download") as mock_dl:
            resolved = factory._resolve_model_path("../models/my.pt")
            assert resolved == "../models/my.pt"
            mock_dl.assert_not_called()


class TestGetDetectorEnvVar:
    def test_env_var_is_used_when_model_path_arg_none(self, monkeypatch):
        monkeypatch.setenv("YOLO_MODEL_PATH", "./local/envtest.pt")
        factory = _reload_factory()
        mock_ul = _make_mock_ultralytics()
        with patch.dict(sys.modules, {"ultralytics": mock_ul}):
            detector = factory.get_detector(use_yolo=True)
            assert not isinstance(detector, StubDetector)
            assert detector.model_path == "./local/envtest.pt"

    def test_explicit_arg_overrides_env_var(self, monkeypatch):
        monkeypatch.setenv("YOLO_MODEL_PATH", "./should-not-be-used.pt")
        factory = _reload_factory()
        mock_ul = _make_mock_ultralytics()
        with patch.dict(sys.modules, {"ultralytics": mock_ul}):
            detector = factory.get_detector(use_yolo=True, model_path="./explicit.pt")
            assert detector.model_path == "./explicit.pt"

    def test_use_yolo_false_always_returns_stub(self, monkeypatch):
        monkeypatch.setenv("YOLO_MODEL_PATH", "./anything.pt")
        factory = _reload_factory()
        detector = factory.get_detector(use_yolo=False)
        assert isinstance(detector, StubDetector)

    def test_unset_env_falls_back_to_default_hf(self, monkeypatch):
        monkeypatch.delenv("YOLO_MODEL_PATH", raising=False)
        factory = _reload_factory()
        mock_ul = _make_mock_ultralytics()
        with patch.dict(sys.modules, {"ultralytics": mock_ul}), \
             patch("huggingface_hub.hf_hub_download", return_value="/tmp/default.pt") as mock_dl:
            detector = factory.get_detector(use_yolo=True)
            assert detector.model_path == "/tmp/default.pt"
            mock_dl.assert_called_once()
