"""Phase 8 — unit tests for routing.py SQL constants and env-var config.

These do not need a live DB. They lock the contract of the constants added
in Plan 08-02 so that the wiring in Plan 08-03 has a stable foundation.
"""
import importlib
import os

import pytest

from app.routes import routing


def test_default_buffer_is_0_03():
    """ROUTE_FILTER_BUFFER_DEG defaults to 0.03 when env unset (RESEARCH §9)."""
    # Conftest does not set ROUTE_FILTER_BUFFER_DEG, so importing routing
    # under the default test env should yield 0.03.
    assert routing.ROUTE_FILTER_BUFFER_DEG == 0.03


def test_widen_factor_default_is_2():
    """ROUTE_FILTER_WIDEN_FACTOR defaults to 2.0 when env unset."""
    assert routing.ROUTE_FILTER_WIDEN_FACTOR == 2.0


def test_buffer_env_override_applies_after_reload(monkeypatch):
    """Setting the env var + reloading the module bumps the buffer.

    Module-level constant is read at import time; ops change requires a
    process restart in production. The reload here simulates that.
    """
    monkeypatch.setenv("ROUTE_FILTER_BUFFER_DEG", "0.05")
    try:
        reloaded = importlib.reload(routing)
        assert reloaded.ROUTE_FILTER_BUFFER_DEG == 0.05
    finally:
        # Reload again under the original (unset) env so subsequent tests
        # in the suite see the default. monkeypatch.delenv is auto-undone
        # at test end, but the module-level constant needs a fresh reload.
        monkeypatch.delenv("ROUTE_FILTER_BUFFER_DEG", raising=False)
        importlib.reload(routing)


def test_temp_table_sql_has_btree_indexes():
    """Pitfall G — pgr_ksp inner Dijkstra needs btree on source/target.

    Without these the temp table degrades back to seq scan inside Yen's
    inner loop and the perf target slips by a factor of 5+.
    """
    assert "CREATE INDEX ON rq_filtered_edges (source)" in routing.INDEX_FILTERED_EDGES_SQL
    assert "CREATE INDEX ON rq_filtered_edges (target)" in routing.INDEX_FILTERED_EDGES_SQL


def test_filtered_ksp_reads_from_temp_table():
    """KSP_FILTERED_SQL points pgr_ksp's inner edges_sql at rq_filtered_edges.

    This is the structural fix — the inner SQL must NOT scan road_segments
    directly (Pitfall A from RESEARCH §1).
    """
    assert "FROM rq_filtered_edges" in routing.KSP_FILTERED_SQL
    # The full table name must NOT appear in the FILTERED variant's inner SQL
    # (the outer SELECT in KSP_FILTERED_SQL legitimately wraps pgr_ksp; we
    # only forbid 'FROM road_segments' inside the literal).
    assert "FROM road_segments" not in routing.KSP_FILTERED_SQL


def test_create_filtered_uses_named_params():
    """SQL-injection mitigation — origin/destination/buffer are bound, not interpolated.

    Threat T-08-02-01 in the threat model. Any string-formatted lat/lon in
    this SQL would let a malicious request inject through the request body.
    """
    sql = routing.CREATE_FILTERED_EDGES_SQL
    assert "%(o_lon)s" in sql
    assert "%(o_lat)s" in sql
    assert "%(d_lon)s" in sql
    assert "%(d_lat)s" in sql
    assert "%(buf)s" in sql


def test_full_ksp_sql_preserved_for_fallback():
    """Plan 08-03's 3-attempt fallback chain ends at KSP_FULL_SQL; the constant must exist."""
    assert hasattr(routing, "KSP_FULL_SQL")
    assert "FROM road_segments" in routing.KSP_FULL_SQL
    assert "pgr_ksp" in routing.KSP_FULL_SQL
