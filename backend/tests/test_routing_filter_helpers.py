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


# ---------------------------------------------------------------------------
# Phase 8 Plan 08-03 -- find_k_shortest_via_dijkstra unit tests
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock


def _make_cursor(fetchall_side_effect: list[list[dict]]) -> MagicMock:
    """Build a MagicMock cursor whose fetchall() consumes the provided list.

    Each call to .fetchall() returns the next item from the side_effect list.
    cur.execute() is a no-op (returns MagicMock) -- it does NOT consume from
    side_effect. This mirrors the pattern from test_route.py:_setup_mock_conn.
    """
    cur = MagicMock()
    cur.fetchall.side_effect = fetchall_side_effect
    return cur


def test_dijkstra_helper_k_equals_1():
    """k=1: helper issues 1 execute, returns rows tagged path_id=1 only."""
    cur = _make_cursor([
        [{"seq": 1, "edge": 10, "cost": 5.0},
         {"seq": 2, "edge": 11, "cost": 5.0}],
    ])
    rows = routing.find_k_shortest_via_dijkstra(cur, 100, 200, k=1)
    assert len(rows) == 2
    assert all(r["path_id"] == 1 for r in rows)
    assert [r["edge"] for r in rows] == [10, 11]
    # Exactly 1 execute call (no further iterations).
    assert cur.execute.call_count == 1


def test_dijkstra_helper_k_equals_3_full():
    """k=3 with all-non-empty iterations: 3 path_ids, total 6 rows."""
    cur = _make_cursor([
        [{"seq": 1, "edge": 10, "cost": 5.0},
         {"seq": 2, "edge": 11, "cost": 5.0}],
        [{"seq": 1, "edge": 20, "cost": 6.0},
         {"seq": 2, "edge": 21, "cost": 6.0}],
        [{"seq": 1, "edge": 30, "cost": 7.0},
         {"seq": 2, "edge": 31, "cost": 7.0}],
    ])
    rows = routing.find_k_shortest_via_dijkstra(cur, 100, 200, k=3)
    assert len(rows) == 6
    assert sorted({r["path_id"] for r in rows}) == [1, 2, 3]
    assert cur.execute.call_count == 3


def test_dijkstra_helper_early_break_on_empty_later_iteration():
    """When iteration 2 returns [], helper breaks early -- only path 1 returned."""
    cur = _make_cursor([
        [{"seq": 1, "edge": 10, "cost": 5.0},
         {"seq": 2, "edge": 11, "cost": 5.0}],
        [],  # iteration 2 -> no more distinct paths
    ])
    rows = routing.find_k_shortest_via_dijkstra(cur, 100, 200, k=5)
    assert len(rows) == 2
    assert {r["path_id"] for r in rows} == {1}
    # Helper stopped after the empty iteration -- 2 executes, not 5.
    assert cur.execute.call_count == 2


def test_dijkstra_helper_returns_empty_on_first_iteration_empty():
    """When iteration 1 returns [], helper returns [] for caller fallback."""
    cur = _make_cursor([[]])
    rows = routing.find_k_shortest_via_dijkstra(cur, 100, 200, k=5)
    assert rows == []
    assert cur.execute.call_count == 1


def test_dijkstra_helper_blocked_edges_grow_across_iterations():
    """Inner SQL passed to pgr_dijkstra includes ARRAY of prior-path edges.

    Iteration 1: ARRAY[] (nothing blocked yet).
    Iteration 2: ARRAY[10,11] (path 1's edges blocked).
    Pins the perturbation behavior -- without growing the blocked set,
    pgr_dijkstra would just return path 1 again on every iteration.
    """
    cur = _make_cursor([
        [{"seq": 1, "edge": 10, "cost": 5.0},
         {"seq": 2, "edge": 11, "cost": 5.0}],
        [{"seq": 1, "edge": 20, "cost": 6.0}],
    ])
    routing.find_k_shortest_via_dijkstra(cur, 100, 200, k=2)

    # Inspect the two execute calls. cur.execute(sql, params_dict) -- params
    # is a dict whose "inner_sql" key is the per-iteration inner SQL string.
    call_1_args = cur.execute.call_args_list[0]
    call_2_args = cur.execute.call_args_list[1]
    inner_1 = call_1_args[0][1]["inner_sql"]
    inner_2 = call_2_args[0][1]["inner_sql"]

    # Iteration 1: no edges blocked yet -> ARRAY[] (empty).
    assert "ARRAY[]::bigint[]" in inner_1
    # Iteration 2: path 1's edges 10 and 11 are blocked.
    assert "ARRAY[10,11]::bigint[]" in inner_2


def test_dijkstra_helper_weight_penalty_override_propagates_to_sql():
    """weight_penalty kwarg overrides the module-default DIJKSTRA_BLOCKED_EDGE_PENALTY.

    The penalty value appears in the inner_sql's CASE WHEN ... THEN cost * <penalty>
    clause. This matters operationally: an operator can tighten or loosen
    path-diversity by tuning the penalty without redeploying.
    """
    cur = _make_cursor([
        [{"seq": 1, "edge": 10, "cost": 5.0}],
        [{"seq": 1, "edge": 20, "cost": 6.0}],
    ])
    routing.find_k_shortest_via_dijkstra(
        cur, 100, 200, k=2, weight_penalty=42.5,
    )
    inner_2 = cur.execute.call_args_list[1][0][1]["inner_sql"]
    # The penalty literal appears in the CASE WHEN clause. float(42.5) -> "42.5".
    assert "cost * 42.5" in inner_2
