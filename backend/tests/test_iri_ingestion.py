"""Tests for IRI data ingestion module.

These tests do NOT require a running database -- all DB interactions are mocked.
Run with: python -m pytest tests/test_iri_ingestion.py -v
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import numpy as np
import pytest

# Add the scripts directory to the Python path so we can import iri_sources
SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts",
)
sys.path.insert(0, SCRIPTS_DIR)

from iri_sources import (
    load_iri_from_csv,
    normalize_iri,
    generate_improved_synthetic_iri,
    IRI_DISTRIBUTIONS,
    _classify_highway,
)


# ---------------------------------------------------------------------------
# Sample CSV path (relative to project root)
# ---------------------------------------------------------------------------
SAMPLE_CSV = os.path.join(SCRIPTS_DIR, "sample_iri_data.csv")


class TestLoadCsvParsesCorrectly:
    """test_load_csv_parses_correctly -- load the sample CSV, verify row count and data types."""

    def test_loads_correct_number_of_rows(self):
        records = load_iri_from_csv(SAMPLE_CSV)
        assert len(records) == 20, f"Expected 20 rows, got {len(records)}"

    def test_records_have_required_keys(self):
        records = load_iri_from_csv(SAMPLE_CSV)
        for rec in records:
            assert "latitude" in rec
            assert "longitude" in rec
            assert "iri_value" in rec

    def test_latitude_is_float_and_in_range(self):
        records = load_iri_from_csv(SAMPLE_CSV)
        for rec in records:
            assert isinstance(rec["latitude"], float)
            assert -90 <= rec["latitude"] <= 90

    def test_longitude_is_float_and_in_range(self):
        records = load_iri_from_csv(SAMPLE_CSV)
        for rec in records:
            assert isinstance(rec["longitude"], float)
            assert -180 <= rec["longitude"] <= 180

    def test_iri_value_is_positive_float(self):
        records = load_iri_from_csv(SAMPLE_CSV)
        for rec in records:
            assert isinstance(rec["iri_value"], float)
            assert rec["iri_value"] > 0

    def test_optional_road_name_present(self):
        records = load_iri_from_csv(SAMPLE_CSV)
        # All rows in sample have road_name
        for rec in records:
            assert "road_name" in rec
            assert isinstance(rec["road_name"], str)
            assert len(rec["road_name"]) > 0

    def test_iri_values_in_realistic_range(self):
        records = load_iri_from_csv(SAMPLE_CSV)
        iri_values = [r["iri_value"] for r in records]
        assert min(iri_values) >= 1.0, "IRI values should be >= 1.0 m/km"
        assert max(iri_values) <= 10.0, "Sample IRI values should be <= 10.0 m/km"


class TestLoadCsvMissingFile:
    """test_load_csv_missing_file -- graceful error on nonexistent file."""

    def test_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_iri_from_csv("/nonexistent/path/fake_iri_data.csv")

    def test_raises_file_not_found_with_meaningful_message(self):
        fake_path = "/tmp/does_not_exist_iri.csv"
        with pytest.raises(FileNotFoundError, match="CSV file not found"):
            load_iri_from_csv(fake_path)

    def test_missing_required_columns(self):
        """CSV exists but lacks required columns."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as f:
            f.write("name,value\n")
            f.write("foo,42\n")
            tmp_path = f.name

        try:
            with pytest.raises(ValueError, match="missing required columns"):
                load_iri_from_csv(tmp_path)
        finally:
            os.unlink(tmp_path)

    def test_empty_csv_returns_empty_list(self):
        """CSV with header but no data rows returns empty list."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as f:
            f.write("latitude,longitude,iri_value\n")
            tmp_path = f.name

        try:
            records = load_iri_from_csv(tmp_path)
            assert records == []
        finally:
            os.unlink(tmp_path)


class TestImprovedSyntheticDistribution:
    """test_improved_synthetic_distribution -- verify realistic mean/std (mocked DB)."""

    def _make_mock_conn(self, n_segments: int = 1000, highway_type: str = "residential"):
        """Create a mock DB connection that returns n_segments rows."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        # Simulate column check query
        column_rows = [("id",), ("highway",), ("length_m",), ("geom",), ("iri_value",)]
        # Simulate segment data query
        rng = np.random.default_rng(99)
        segment_rows = [
            (
                i + 1,                           # id
                highway_type,                    # highway
                float(rng.uniform(50, 500)),     # length_m
                float(rng.uniform(-118.3, -118.2)),  # cx
                float(rng.uniform(34.0, 34.1)),      # cy
            )
            for i in range(n_segments)
        ]
        # Simulate neighbor query returning no neighbors (for speed)
        neighbor_rows = []

        # Track call count to return different results per execute
        call_count = {"n": 0}

        def mock_fetchall():
            call_count["n"] += 1
            if call_count["n"] == 1:
                return column_rows
            elif call_count["n"] == 2:
                return segment_rows
            else:
                return neighbor_rows

        mock_cur.fetchall.side_effect = mock_fetchall

        return mock_conn

    @patch("iri_sources.execute_values")
    def test_residential_mean_near_5(self, mock_exec_values):
        """Residential roads should have mean IRI near 5.0 m/km."""
        mock_conn = self._make_mock_conn(n_segments=2000, highway_type="residential")
        stats = generate_improved_synthetic_iri(mock_conn, seed=42)

        expected_mean = IRI_DISTRIBUTIONS["residential"]["mean"]
        assert abs(stats["mean"] - expected_mean) < 1.0, (
            f"Mean IRI {stats['mean']} too far from expected {expected_mean}"
        )

    @patch("iri_sources.execute_values")
    def test_motorway_mean_near_2(self, mock_exec_values):
        """Motorway roads should have mean IRI near 2.0 m/km."""
        mock_conn = self._make_mock_conn(n_segments=2000, highway_type="motorway")
        stats = generate_improved_synthetic_iri(mock_conn, seed=42)

        expected_mean = IRI_DISTRIBUTIONS["motorway"]["mean"]
        assert abs(stats["mean"] - expected_mean) < 1.0, (
            f"Mean IRI {stats['mean']} too far from expected {expected_mean}"
        )

    @patch("iri_sources.execute_values")
    def test_std_is_positive_and_reasonable(self, mock_exec_values):
        """Standard deviation should be positive and within realistic range."""
        mock_conn = self._make_mock_conn(n_segments=2000, highway_type="secondary")
        stats = generate_improved_synthetic_iri(mock_conn, seed=42)

        assert stats["std"] > 0.1, "Std should be positive"
        assert stats["std"] < 5.0, "Std should not be extreme"

    @patch("iri_sources.execute_values")
    def test_values_clamped_to_physical_bounds(self, mock_exec_values):
        """All IRI values should be within [0.5, 15.0] m/km."""
        mock_conn = self._make_mock_conn(n_segments=5000, highway_type="unclassified")
        stats = generate_improved_synthetic_iri(mock_conn, seed=42)

        assert stats["min"] >= 0.5, f"Min IRI {stats['min']} below 0.5"
        assert stats["max"] <= 15.0, f"Max IRI {stats['max']} above 15.0"

    @patch("iri_sources.execute_values")
    def test_count_matches_input(self, mock_exec_values):
        """Number of updated segments should match input count."""
        mock_conn = self._make_mock_conn(n_segments=500, highway_type="primary")
        stats = generate_improved_synthetic_iri(mock_conn, seed=42)
        assert stats["count"] == 500

    @patch("iri_sources.execute_values")
    def test_seed_produces_reproducible_results(self, mock_exec_values):
        """Same seed should produce same statistics."""
        mock_conn_a = self._make_mock_conn(n_segments=1000, highway_type="tertiary")
        mock_conn_b = self._make_mock_conn(n_segments=1000, highway_type="tertiary")
        stats_a = generate_improved_synthetic_iri(mock_conn_a, seed=77)
        stats_b = generate_improved_synthetic_iri(mock_conn_b, seed=77)
        assert stats_a["mean"] == stats_b["mean"]
        assert stats_a["std"] == stats_b["std"]


class TestIriNormalization:
    """test_iri_normalization -- verify normalize function maps min->0, max->1 correctly."""

    def test_normalize_maps_min_to_zero_and_max_to_one(self):
        """After normalization, the SQL should set iri_norm = (val - min) / range."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        # Simulate: min=2.0, max=10.0
        mock_cur.fetchone.return_value = (2.0, 10.0)

        iri_min, iri_max = normalize_iri(mock_conn)

        assert iri_min == 2.0
        assert iri_max == 10.0

        # Verify the UPDATE was called with correct parameters
        update_call = mock_cur.execute.call_args_list[-1]
        sql = update_call[0][0]
        params = update_call[0][1]
        assert "iri_norm" in sql
        assert "iri_value" in sql
        # Params should be (min, range) = (2.0, 8.0)
        assert params == (2.0, 8.0)

    def test_normalize_handles_equal_min_max(self):
        """When all IRI values are identical, range=1.0 to avoid division by zero."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        # All segments have IRI = 5.0
        mock_cur.fetchone.return_value = (5.0, 5.0)

        iri_min, iri_max = normalize_iri(mock_conn)

        assert iri_min == 5.0
        assert iri_max == 5.0

        # Range should be 1.0 (fallback), so all iri_norm = 0.0
        update_call = mock_cur.execute.call_args_list[-1]
        params = update_call[0][1]
        assert params == (5.0, 1.0)

    def test_normalize_handles_no_data(self):
        """When no IRI values exist, returns (0, 0) without updating."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        mock_cur.fetchone.return_value = (None, None)

        iri_min, iri_max = normalize_iri(mock_conn)

        assert iri_min == 0.0
        assert iri_max == 0.0

        # Should NOT have called UPDATE (only the SELECT)
        assert mock_cur.execute.call_count == 1

    def test_normalize_commits_transaction(self):
        """Normalization should commit after UPDATE."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_cur.fetchone.return_value = (1.0, 9.0)

        normalize_iri(mock_conn)

        mock_conn.commit.assert_called()


class TestClassifyHighway:
    """Test the highway tag classification helper."""

    def test_known_types(self):
        assert _classify_highway("motorway") == "motorway"
        assert _classify_highway("residential") == "residential"
        assert _classify_highway("primary") == "primary"

    def test_link_roads_mapped_to_parent(self):
        assert _classify_highway("motorway_link") == "motorway"
        assert _classify_highway("primary_link") == "primary"
        assert _classify_highway("trunk_link") == "trunk"

    def test_none_returns_default(self):
        assert _classify_highway(None) == "default"

    def test_unknown_returns_default(self):
        assert _classify_highway("footway") == "default"
        assert _classify_highway("cycleway") == "default"
