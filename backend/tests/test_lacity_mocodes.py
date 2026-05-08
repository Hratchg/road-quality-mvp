"""Unit tests for data_pipeline.lacity_mocodes.map_mocodes_to_severity.

Wave-0 RED tests pin the contracts before downstream code (ingest_crashes.py)
depends on the mapper:
  - Multi-severity-code rows resolve to the highest tier (Pitfall A).
  - Zero-severity-code rows raise ValueError (D-09-14 RED — Pitfall 2 / KEY LESSON 2).
  - Defensive separator handles both space and comma separators (D-09-13 REVISED).
  - Non-KABCO codes are silently ignored — they're expected (charitable read of D-09-13).

These are pure-function tests with no DB / network / filesystem dependencies.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make data_pipeline importable when running pytest from repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_pipeline.lacity_mocodes import (
    MOCODE_SEVERITY_MAP,
    map_mocodes_to_severity,
)


def test_every_kabco_code_maps():
    """Each of the 5 KABCO codes in isolation maps to the expected severity."""
    assert map_mocodes_to_severity("3027") == "fatal"
    assert map_mocodes_to_severity("3024") == "injury"
    assert map_mocodes_to_severity("3025") == "injury"
    assert map_mocodes_to_severity("3026") == "injury"
    assert map_mocodes_to_severity("3028") == "pdo"


def test_multi_severity_resolves_to_highest():
    """Pitfall A: multi-victim crash with both 3024 (Severe) and 3027 (Fatal)
    must resolve to 'fatal'. fatal > injury > pdo.
    """
    assert map_mocodes_to_severity("3024 3027") == "fatal"
    assert map_mocodes_to_severity("3027 3024") == "fatal"  # order-insensitive
    assert map_mocodes_to_severity("3026 3024") == "injury"  # both injury → injury
    assert map_mocodes_to_severity("3028 3025") == "injury"  # pdo + injury → injury


def test_no_severity_code_raises_value_error():
    """D-09-14 RED test: a row carrying ONLY non-severity codes (3401 weather,
    3701 road condition) must raise ValueError — fail-loud on the SEVERITY scale,
    not on benign codes (Pitfall 2 / KEY LESSON 2 charitable read).
    """
    with pytest.raises(ValueError, match="no KABCO severity"):
        map_mocodes_to_severity("3401 3701")


def test_separator_robustness():
    """D-09-13 REVISED: the defensive split handles space, comma, and mixed
    whitespace. Live data is space-separated, but future schema drift to
    comma-separated must not break the mapper.
    """
    assert map_mocodes_to_severity("3027") == "fatal"
    assert map_mocodes_to_severity("3024 3027") == "fatal"     # space
    assert map_mocodes_to_severity("3024,3027") == "fatal"     # comma
    assert map_mocodes_to_severity("3024,  3027") == "fatal"   # mixed
    assert map_mocodes_to_severity(" 3027 ") == "fatal"        # leading/trailing space
    assert map_mocodes_to_severity("3024\t3027") == "fatal"    # tab (whitespace)


def test_non_severity_codes_ignored():
    """Charitable read of D-09-13 (per 09-RESEARCH.md Pattern 3 commentary):
    non-KABCO codes (3001-3023 vehicle, 3101-3104 PCF, 4001-4027 location,
    3401/3701 weather/road) are EXPECTED and IGNORED. Only zero-severity-codes
    triggers loud failure.

    Real Socrata sample (2026-05-08): "3004 3027 3034 4027 3036 3101 3401 3701"
    → 8 codes, only 3027 is a severity code → 'fatal'.
    """
    real_sample = "3004 3027 3034 4027 3036 3101 3401 3701"
    assert map_mocodes_to_severity(real_sample) == "fatal"


def test_empty_string_raises():
    """Empty string contains zero severity codes → ValueError."""
    with pytest.raises(ValueError, match="no KABCO severity"):
        map_mocodes_to_severity("")


def test_mocode_severity_map_has_exactly_five_entries():
    """Schema invariant: the catalog is exactly the 5 KABCO codes 3024-3028.
    If a future PR adds a 6th 'unknown' or removes one, this test fires.
    """
    assert MOCODE_SEVERITY_MAP == {
        "3027": "fatal",
        "3024": "injury",
        "3025": "injury",
        "3026": "injury",
        "3028": "pdo",
    }
