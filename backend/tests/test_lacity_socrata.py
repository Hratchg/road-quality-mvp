"""Unit tests for data_pipeline.lacity_socrata.iter_crashes.

Uses unittest.mock.patch against requests.get to verify URL composition,
pagination, header handling, and the token-not-logged contract. Per D-09-06,
no live LA City API hit in CI (manual smoke is operator runbook in Phase 12).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_pipeline import lacity_socrata


def _mock_response(rows: list[dict]) -> MagicMock:
    r = MagicMock()
    r.json.return_value = rows
    r.raise_for_status = MagicMock()
    return r


def test_iter_crashes_pages():
    """Three HTTP calls when the third page is partial."""
    page_size = 1000
    page1 = [{"dr_no": str(i)} for i in range(page_size)]
    page2 = [{"dr_no": str(page_size + i)} for i in range(page_size)]
    page3 = [{"dr_no": str(2 * page_size + i)} for i in range(500)]
    with patch.object(lacity_socrata.requests, "get") as mg:
        mg.side_effect = [
            _mock_response(page1),
            _mock_response(page2),
            _mock_response(page3),
        ]
        rows = list(lacity_socrata.iter_crashes(
            "2019-03-01", "2024-03-01", page_size=page_size,
        ))
    assert len(rows) == 2500
    assert mg.call_count == 3
    # Third call: $offset should be 2 * page_size
    third_call_kwargs = mg.call_args_list[2].kwargs
    assert third_call_kwargs["params"]["$offset"] == 2 * page_size


def test_iter_crashes_stops_on_partial_page():
    """When the second page is partial (< page_size), iteration stops."""
    with patch.object(lacity_socrata.requests, "get") as mg:
        mg.side_effect = [
            _mock_response([{"dr_no": str(i)} for i in range(1000)]),
            _mock_response([{"dr_no": str(1000 + i)} for i in range(500)]),
        ]
        rows = list(lacity_socrata.iter_crashes("2019-03-01", "2024-03-01"))
    assert len(rows) == 1500
    assert mg.call_count == 2


def test_iter_crashes_stops_on_empty_response():
    """Empty first response → zero rows yielded, single HTTP call."""
    with patch.object(lacity_socrata.requests, "get") as mg:
        mg.side_effect = [_mock_response([])]
        rows = list(lacity_socrata.iter_crashes("2019-03-01", "2024-03-01"))
    assert rows == []
    assert mg.call_count == 1


def test_where_clause_composition_with_bbox():
    """$where must contain date_occ BETWEEN and within_box(location_1, ...);
    $order must be :id; $select must list the four fields the driver needs.
    """
    with patch.object(lacity_socrata.requests, "get") as mg:
        mg.return_value = _mock_response([])
        list(lacity_socrata.iter_crashes(
            "2019-03-01", "2024-03-01",
            bbox=(33.7, -118.7, 34.4, -118.0),
        ))
    params = mg.call_args.kwargs["params"]
    where = params["$where"]
    assert "date_occ between '2019-03-01T00:00:00' and '2024-03-01T00:00:00'" in where
    assert "within_box(location_1, 33.7, -118.7, 34.4, -118.0)" in where
    assert params["$order"] == ":id"
    assert params["$select"] == "dr_no,date_occ,mocodes,location_1"
    assert params["$limit"] == 1000


def test_iter_crashes_no_bbox_clause_when_unset():
    """When bbox=None, $where contains only the date filter — no within_box."""
    with patch.object(lacity_socrata.requests, "get") as mg:
        mg.return_value = _mock_response([])
        list(lacity_socrata.iter_crashes("2019-03-01", "2024-03-01", bbox=None))
    params = mg.call_args.kwargs["params"]
    assert "within_box" not in params["$where"]
    assert "date_occ between" in params["$where"]


def test_token_header_added_when_set():
    """Explicit token arg → X-App-Token header is present."""
    with patch.object(lacity_socrata.requests, "get") as mg:
        mg.return_value = _mock_response([])
        list(lacity_socrata.iter_crashes(
            "2019-03-01", "2024-03-01", token="abc123",
        ))
    headers = mg.call_args.kwargs["headers"]
    assert headers.get("X-App-Token") == "abc123"


def test_token_header_absent_when_unset(monkeypatch):
    """No explicit token + no LACITY_APP_TOKEN env → no X-App-Token header."""
    monkeypatch.delenv("LACITY_APP_TOKEN", raising=False)
    monkeypatch.setattr(lacity_socrata, "LACITY_APP_TOKEN", None)
    with patch.object(lacity_socrata.requests, "get") as mg:
        mg.return_value = _mock_response([])
        list(lacity_socrata.iter_crashes("2019-03-01", "2024-03-01"))
    headers = mg.call_args.kwargs["headers"]
    assert "X-App-Token" not in headers


def test_token_never_logged_or_printed():
    """Static analysis: the module source must not contain logger/print of the token.
    T-9-03 mitigation: token is sensitive, must not leak into logs.
    """
    src = (REPO_ROOT / "data_pipeline" / "lacity_socrata.py").read_text()
    # Forbidden substrings — case-insensitive.
    forbidden = [
        "logger.debug(token",
        "logger.info(token",
        "logger.warning(token",
        "logger.error(token",
        "print(token",
        "logger.debug(headers",   # would log the X-App-Token header
        "logger.info(headers",
        "print(headers",
    ]
    src_lower = src.lower()
    for pat in forbidden:
        assert pat not in src_lower, f"forbidden token-leak pattern in module: {pat}"


def test_offset_increments_by_page_size():
    """Each call's $offset should be N * page_size, starting at 0."""
    page_size = 100
    page1 = [{"dr_no": str(i)} for i in range(page_size)]
    page2 = [{"dr_no": str(i)} for i in range(page_size, 150)]
    with patch.object(lacity_socrata.requests, "get") as mg:
        mg.side_effect = [_mock_response(page1), _mock_response(page2)]
        list(lacity_socrata.iter_crashes(
            "2019-03-01", "2024-03-01", page_size=page_size,
        ))
    assert mg.call_args_list[0].kwargs["params"]["$offset"] == 0
    assert mg.call_args_list[1].kwargs["params"]["$offset"] == page_size
