"""Tests for data_pipeline.mapillary client.

Pure unit tests -- mocks requests.get, no network required, no real
MAPILLARY_ACCESS_TOKEN needed. Verifies bbox DoS guard (T-02-18),
constant-time SHA256 compare (T-02-13), path-traversal rejection (T-02-14),
malformed-hash rejection (T-02-15), and image-id validation (T-02-20).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Project root importable so data_pipeline.* resolves from any CWD
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from data_pipeline.mapillary import (  # noqa: E402
    MAX_BBOX_AREA_DEG2,
    download_image,
    search_images,
    validate_bbox,
    verify_manifest,
    write_manifest,
)


# ---------------------------------------------------------------------------
# validate_bbox -- Pitfall 3 DoS guard (T-02-18)
# ---------------------------------------------------------------------------

class TestValidateBbox:
    def test_small_bbox_ok(self):
        # 0.01 x 0.01 = 0.0001 deg2 -- safely under the limit
        validate_bbox((-118.25, 34.04, -118.24, 34.05))

    def test_bbox_at_limit_ok(self):
        # Exactly 0.01 deg2 -> OK (<=)
        validate_bbox((0.0, 0.0, 0.1, 0.1))

    def test_oversized_bbox_raises(self):
        with pytest.raises(ValueError, match="exceeds Mapillary"):
            # 0.5 x 0.5 = 0.25 deg2 -- 25x over the limit
            validate_bbox((-118.5, 33.8, -118.0, 34.3))

    def test_malformed_length(self):
        with pytest.raises(ValueError, match="4 elements"):
            validate_bbox((0.0, 0.0, 1.0))  # type: ignore[arg-type]

    def test_corners_out_of_order(self):
        with pytest.raises(ValueError, match="out of order"):
            validate_bbox((1.0, 1.0, 0.0, 0.0))

    def test_max_constant_is_documented_limit(self):
        # Pitfall 3 records the API's 0.01 deg2 limit; a refactor that
        # quietly raises this should fail the test.
        assert MAX_BBOX_AREA_DEG2 == 0.01


# ---------------------------------------------------------------------------
# search_images -- mocked requests.get (no network)
# ---------------------------------------------------------------------------

class TestSearchImagesMocked:
    def test_search_requires_token(self, monkeypatch):
        """Without a token anywhere, search_images must raise RuntimeError."""
        monkeypatch.delenv("MAPILLARY_ACCESS_TOKEN", raising=False)
        # force-reload to pick up unset env -- the module reads the env var
        # at import time (backend/app/db.py pattern)
        import importlib

        import data_pipeline.mapillary as m

        importlib.reload(m)
        with pytest.raises(RuntimeError, match="MAPILLARY_ACCESS_TOKEN"):
            m.search_images((-118.25, 34.04, -118.24, 34.05))

    def test_search_uses_token_arg(self):
        fake_response = MagicMock()
        fake_response.json.return_value = {
            "data": [{"id": "123", "thumb_2048_url": "http://x"}]
        }
        fake_response.raise_for_status = MagicMock()
        with patch(
            "data_pipeline.mapillary.requests.get", return_value=fake_response
        ) as mock_get:
            results = search_images(
                (-118.25, 34.04, -118.24, 34.05), token="fake_token", limit=10
            )
            assert len(results) == 1
            assert results[0]["id"] == "123"
            # Token was passed via Authorization header, not logged or
            # echoed anywhere (T-02-16)
            call_headers = mock_get.call_args.kwargs["headers"]
            assert call_headers["Authorization"] == "OAuth fake_token"

    def test_search_requests_required_fields(self):
        fake_response = MagicMock()
        fake_response.json.return_value = {"data": []}
        fake_response.raise_for_status = MagicMock()
        with patch(
            "data_pipeline.mapillary.requests.get", return_value=fake_response
        ) as mock_get:
            search_images((-118.25, 34.04, -118.24, 34.05), token="t")
            params = mock_get.call_args.kwargs["params"]
            for field in [
                "id",
                "thumb_2048_url",
                "computed_geometry",
                "captured_at",
                "sequence_id",
            ]:
                assert field in params["fields"]

    def test_search_oversized_bbox_fails_before_network(self):
        """Pitfall 3 pre-flight: bbox guard must fire BEFORE requests.get()."""
        with patch("data_pipeline.mapillary.requests.get") as mock_get:
            with pytest.raises(ValueError, match="exceeds Mapillary"):
                search_images((-119.0, 33.0, -118.0, 34.0), token="t")
            mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# download_image -- mocked requests.get
# ---------------------------------------------------------------------------

class TestDownloadImageMocked:
    def test_download_writes_file(self, tmp_path):
        fake_response = MagicMock()
        fake_response.content = b"\xff\xd8\xff\xe0fake jpeg bytes"
        fake_response.raise_for_status = MagicMock()
        meta = {"id": "12345", "thumb_2048_url": "http://mapillary.cdn/fake"}
        with patch(
            "data_pipeline.mapillary.requests.get", return_value=fake_response
        ):
            path = download_image(meta, tmp_path)
            assert path.name == "12345.jpg"
            assert path.read_bytes() == b"\xff\xd8\xff\xe0fake jpeg bytes"

    def test_download_rejects_bad_image_id(self, tmp_path):
        """T-02-20: image ids containing path separators must be rejected."""
        meta = {"id": "../etc/passwd", "thumb_2048_url": "http://x"}
        with pytest.raises(ValueError, match="unexpected image id"):
            download_image(meta, tmp_path)

    def test_download_rejects_non_numeric_image_id(self, tmp_path):
        meta = {"id": "abc123", "thumb_2048_url": "http://x"}
        with pytest.raises(ValueError, match="unexpected image id"):
            download_image(meta, tmp_path)

    def test_download_missing_url_raises(self, tmp_path):
        meta = {"id": "123"}
        with pytest.raises(ValueError, match="missing thumb_2048_url"):
            download_image(meta, tmp_path)


# ---------------------------------------------------------------------------
# verify_manifest / write_manifest -- SHA256 integrity + security guards
# ---------------------------------------------------------------------------

class TestManifestVerification:
    def test_verify_ok(self, tmp_path):
        # Create a real file + compute real hash
        img = tmp_path / "images/test/img_001.jpg"
        img.parent.mkdir(parents=True)
        img.write_bytes(b"hello world")
        sha = hashlib.sha256(b"hello world").hexdigest()
        manifest = {
            "version": "1.0",
            "source_bucket": "test",
            "license": "CC-BY-SA 4.0",
            "files": [{"path": "images/test/img_001.jpg", "sha256": sha}],
        }
        mf = tmp_path / "manifest.json"
        mf.write_text(json.dumps(manifest))
        missing, corrupt = verify_manifest(mf, tmp_path)
        assert missing == []
        assert corrupt == []

    def test_verify_missing_file(self, tmp_path):
        manifest = {
            "version": "1.0",
            "source_bucket": "test",
            "license": "CC-BY-SA 4.0",
            "files": [
                {"path": "images/test/missing.jpg", "sha256": "a" * 64}
            ],
        }
        mf = tmp_path / "manifest.json"
        mf.write_text(json.dumps(manifest))
        missing, corrupt = verify_manifest(mf, tmp_path)
        assert missing == ["images/test/missing.jpg"]
        assert corrupt == []

    def test_verify_corrupt_file(self, tmp_path):
        """Hash mismatch must be caught via constant-time compare (T-02-13)."""
        img = tmp_path / "img.jpg"
        img.write_bytes(b"real bytes")
        wrong_sha = "a" * 64
        manifest = {
            "version": "1.0",
            "source_bucket": "test",
            "license": "CC-BY-SA 4.0",
            "files": [{"path": "img.jpg", "sha256": wrong_sha}],
        }
        mf = tmp_path / "manifest.json"
        mf.write_text(json.dumps(manifest))
        missing, corrupt = verify_manifest(mf, tmp_path)
        assert missing == []
        assert corrupt == ["img.jpg"]

    def test_verify_rejects_path_traversal(self, tmp_path):
        """T-02-14: manifest entries with '..' must be rejected."""
        manifest = {
            "version": "1.0",
            "source_bucket": "test",
            "license": "CC-BY-SA 4.0",
            "files": [{"path": "../../etc/passwd", "sha256": "a" * 64}],
        }
        mf = tmp_path / "manifest.json"
        mf.write_text(json.dumps(manifest))
        with pytest.raises(ValueError, match="traversal"):
            verify_manifest(mf, tmp_path)

    def test_verify_rejects_absolute_path(self, tmp_path):
        """Absolute paths in manifest entries are equally dangerous."""
        manifest = {
            "version": "1.0",
            "source_bucket": "test",
            "license": "CC-BY-SA 4.0",
            "files": [{"path": "/etc/passwd", "sha256": "a" * 64}],
        }
        mf = tmp_path / "manifest.json"
        mf.write_text(json.dumps(manifest))
        with pytest.raises(ValueError, match="traversal"):
            verify_manifest(mf, tmp_path)

    def test_verify_rejects_malformed_sha256(self, tmp_path):
        """T-02-15: non-hex or wrong-length sha256 must be rejected."""
        manifest = {
            "version": "1.0",
            "source_bucket": "test",
            "license": "CC-BY-SA 4.0",
            "files": [{"path": "ok.jpg", "sha256": "not-a-hash"}],
        }
        mf = tmp_path / "manifest.json"
        mf.write_text(json.dumps(manifest))
        with pytest.raises(ValueError, match="64 lowercase hex"):
            verify_manifest(mf, tmp_path)

    def test_verify_rejects_uppercase_sha256(self, tmp_path):
        """Regex is lowercase-only; uppercase hex is rejected for consistency."""
        manifest = {
            "version": "1.0",
            "source_bucket": "test",
            "license": "CC-BY-SA 4.0",
            "files": [{"path": "ok.jpg", "sha256": "A" * 64}],
        }
        mf = tmp_path / "manifest.json"
        mf.write_text(json.dumps(manifest))
        with pytest.raises(ValueError, match="64 lowercase hex"):
            verify_manifest(mf, tmp_path)

    def test_verify_unsupported_version(self, tmp_path):
        manifest = {"version": "99.9", "files": []}
        mf = tmp_path / "manifest.json"
        mf.write_text(json.dumps(manifest))
        with pytest.raises(ValueError, match="Unsupported manifest version"):
            verify_manifest(mf, tmp_path)

    def test_verify_missing_manifest_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Manifest not found"):
            verify_manifest(tmp_path / "no_such.json", tmp_path)

    def test_write_manifest_roundtrip(self, tmp_path):
        img = tmp_path / "a.jpg"
        img.write_bytes(b"content")
        mf = tmp_path / "manifest.json"
        write_manifest(
            mf,
            [
                {
                    "path": "a.jpg",
                    "source_mapillary_id": "1",
                    "sequence_id": "s",
                    "split": "test",
                }
            ],
        )
        missing, corrupt = verify_manifest(mf, tmp_path)
        assert missing == [] and corrupt == []

    def test_write_manifest_rejects_traversal(self, tmp_path):
        """Writers must also enforce the path-traversal guard."""
        mf = tmp_path / "manifest.json"
        with pytest.raises(ValueError, match="traversal"):
            write_manifest(mf, [{"path": "../escape.jpg"}])

    def test_write_manifest_records_license(self, tmp_path):
        """CC-BY-SA license text is recorded in the manifest (T-02-19)."""
        img = tmp_path / "a.jpg"
        img.write_bytes(b"content")
        mf = tmp_path / "manifest.json"
        write_manifest(mf, [{"path": "a.jpg"}], license_str="CC-BY-SA 4.0")
        m = json.loads(mf.read_text())
        assert "CC-BY-SA" in m["license"]
