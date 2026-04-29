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
    @pytest.mark.skip(reason="Phase 7 RED test scaffold (Plan 07-01 → 07-07): turns GREEN when Plan 07-07 swaps _DEFAULT_HF_REPO to Hratchg/road-quality-la-yolov8@<sha-from-Plan-07-05-HF-push>. Skipped in CI until that lands so the gate doesn't block unrelated deploys.")
    def test_none_returns_default_hf_repo_via_hf_hub_download(self, monkeypatch):
        monkeypatch.delenv("YOLO_MODEL_PATH", raising=False)
        factory = _reload_factory()
        with patch("huggingface_hub.hf_hub_download", return_value="/tmp/sentinel/best.pt") as mock_dl:
            resolved = factory._resolve_model_path(None)
            assert resolved == "/tmp/sentinel/best.pt"
            mock_dl.assert_called_once()
            call_kwargs = mock_dl.call_args.kwargs
            # Phase 7: _DEFAULT_HF_REPO points at Hratchg/road-quality-la-yolov8 (Plan 07-07 lands the constant swap; SHA pinned by Plan 07-07 after HF push completes).
            assert call_kwargs["repo_id"] == "Hratchg/road-quality-la-yolov8"
            assert call_kwargs["filename"] == "best.pt"
            assert "revision" in call_kwargs, (
                "_DEFAULT_HF_REPO must include @<sha> (T-07-01 pickle-ACE mitigation)"
            )
            assert call_kwargs["revision"], "revision must be non-empty"

    @pytest.mark.skip(reason="Phase 7 RED test scaffold (Plan 07-01 → 07-07): turns GREEN when Plan 07-07 swaps _DEFAULT_HF_REPO to Hratchg/road-quality-la-yolov8@<sha-from-Plan-07-05-HF-push>. Skipped in CI until that lands so the gate doesn't block unrelated deploys.")
    def test_default_hf_repo_pin_contains_sha(self, monkeypatch):
        """SC #4 + Pitfall 8 (pickle-ACE mitigation): _DEFAULT_HF_REPO must
        contain `@<sha>` so a compromised HF token cannot replace best.pt
        and have it loaded by an unsuspecting `hf_hub_download` of HEAD.
        Phase 7 swaps the constant from keremberke@d6d5df4 to
        Hratchg/road-quality-la-yolov8@<sha-from-Plan-07-07>."""
        monkeypatch.delenv("YOLO_MODEL_PATH", raising=False)
        factory = _reload_factory()
        repo = factory._DEFAULT_HF_REPO
        assert isinstance(repo, str), f"_DEFAULT_HF_REPO not a str: {type(repo)}"
        assert repo.startswith("Hratchg/road-quality-la-yolov8@"), (
            f"_DEFAULT_HF_REPO must start with 'Hratchg/road-quality-la-yolov8@', "
            f"got: {repo!r}"
        )
        # SHA must be non-empty (the part after @)
        sha = repo.split("@", 1)[1] if "@" in repo else ""
        assert sha, f"_DEFAULT_HF_REPO missing SHA after @: {repo!r}"
        # Forbid the token literal '<sha>' (Plan 07-07 must replace it with a real SHA)
        assert sha != "<sha>", (
            "_DEFAULT_HF_REPO still has placeholder <sha>; Plan 07-07 must "
            "substitute the real HF commit SHA captured via "
            "HfApi().model_info('Hratchg/road-quality-la-yolov8').sha"
        )

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

    def test_local_path_without_prefix_not_treated_as_hf(self):
        """WR-06: a typo'd local path like ``models/latest.pt`` must NOT be
        handed to hf_hub_download — that would open an ACE vector (T-02-01)
        if an attacker registered a same-named HF repo. Treat as local path
        so YOLOv8Detector raises a clear FileNotFoundError instead.
        """
        factory = _reload_factory()
        with patch("huggingface_hub.hf_hub_download") as mock_dl:
            assert (
                factory._resolve_model_path("models/latest.pt")
                == "models/latest.pt"
            )
            mock_dl.assert_not_called()

    def test_any_repo_id_ending_pt_is_rejected_as_hf(self):
        """WR-06 corollary: ``user/weights.pt`` (even a real repo name) is
        refused as an HF identifier to remove the .pt ambiguity entirely.
        """
        factory = _reload_factory()
        with patch("huggingface_hub.hf_hub_download") as mock_dl:
            assert (
                factory._resolve_model_path("user/weights.pt")
                == "user/weights.pt"
            )
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
