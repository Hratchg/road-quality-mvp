"""SC #7 regression gate: scripts/seed_data.py builds a routable topology.

Phase 5 SC #7: 'Fresh deploy initializes a routable graph: seed_data.py
populates road_segments_vertices_pgr via pgr_createTopology so the first
POST /route after deploy succeeds without a manual SQL step.'

Per RESEARCH Correction B + Assumption A1, scripts/seed_data.py:151 already
calls `SELECT pgr_createTopology('road_segments', 0.0001, 'geom', 'id',
clean := true)`. This test is the regression gate that locks the existing
behavior — if a future refactor removes or moves the pgr_createTopology call
without updating the deploy-time bootstrap, this test fails LOUD in CI.

The test is HEAVY: a full seed_data.py run downloads OSMnx data (~5 MB for
LA bbox) and inserts ~10k segments. Expect ~3-5 minutes on a CI runner with
network access. Auto-skips when DB is unreachable via the standard
db_available fixture chain.

Marker rationale: integration. The test makes real DB writes, network
requests (OSMnx), and runs a child process. Not appropriate for the unit
test sub-suite.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_SCRIPT = REPO_ROOT / "scripts" / "seed_data.py"


def test_seed_data_builds_routable_topology(db_conn):
    """Full SC #7 regression gate.

    Runs scripts/seed_data.py against the existing CI/dev DB (which already
    has the schema applied via docker-compose's init flow OR the GH Actions
    test job's psql-loop). After the script completes, asserts that:

    1. road_segments has rows (the seed populated segments)
    2. road_segments_vertices_pgr has rows (pgr_createTopology built the topology)
    3. Every road_segments row has non-NULL source AND target (the topology
       linkage that pgr_ksp depends on)

    If any of these fails, the deploy-time POST /route would 500 because
    pgr_ksp can't build a route on a non-existent or unlinked topology.
    This is the EXACT bug Phase 4's UAT exposed (the manual SQL step
    requirement) and Phase 5 SC #7 closes.
    """
    if not SEED_SCRIPT.exists():
        pytest.fail(f"scripts/seed_data.py not found at {SEED_SCRIPT}")

    # Construct DATABASE_URL from the existing db_conn for the child process.
    # The child needs to write to the SAME DB the test reads from.
    dsn = db_conn.dsn  # e.g., "host=localhost port=5432 dbname=... user=rq password=rqpass"
    # psycopg2.connect accepts both DSN keyword string AND postgresql:// URL;
    # we normalize to URL format because seed_data.py reads DATABASE_URL as URL.
    # Parse the dsn keyword string into a URL.
    dsn_kv = dict(token.split("=", 1) for token in dsn.split() if "=" in token)
    db_url = (
        f"postgresql://{dsn_kv.get('user', 'rq')}:{dsn_kv.get('password', 'rqpass')}@"
        f"{dsn_kv.get('host', 'localhost')}:{dsn_kv.get('port', '5432')}/"
        f"{dsn_kv.get('dbname', 'roadquality')}"
    )

    env = os.environ.copy()
    env["DATABASE_URL"] = db_url

    # Clean slate: truncate road_segments first so the assertion is meaningful
    # regardless of prior test state. The seed script ON CONFLICT-merges so
    # without truncate we couldn't tell if pgr_createTopology re-ran or not.
    with db_conn.cursor() as cur:
        cur.execute("TRUNCATE road_segments CASCADE")
        # CASCADE handles the route_requests / segment_defects / segment_scores FKs
        # if they exist; if not, this is a no-op for those tables.
    db_conn.commit()

    # Run the seed script. Heavy: ~3-5 minutes on a CI runner with network access.
    result = subprocess.run(
        [sys.executable, str(SEED_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=600,  # 10 minutes hard timeout
    )

    if result.returncode != 0:
        pytest.fail(
            f"scripts/seed_data.py failed with code {result.returncode}\n"
            f"STDOUT: {result.stdout[-2000:]}\n"
            f"STDERR: {result.stderr[-2000:]}"
        )

    # Re-acquire a cursor on the test connection (the seed script committed
    # via its own connection; our connection sees the new state on next query).
    with db_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM road_segments")
        seg_count = cur.fetchone()["c"]
        assert seg_count > 0, (
            f"SC #7 regression: road_segments has 0 rows after seed_data.py — "
            f"the seed didn't populate segments. Check the script's INSERT loop."
        )

        cur.execute("SELECT COUNT(*) AS c FROM road_segments_vertices_pgr")
        vertex_count = cur.fetchone()["c"]
        assert vertex_count > 0, (
            f"SC #7 regression: road_segments_vertices_pgr has 0 rows after "
            f"seed_data.py — pgr_createTopology was NOT called or failed silently. "
            f"Verify scripts/seed_data.py:151 still has the SELECT pgr_createTopology(...) "
            f"line. road_segments has {seg_count} rows."
        )

        cur.execute(
            "SELECT COUNT(*) AS c FROM road_segments WHERE source IS NULL OR target IS NULL"
        )
        unlinked_count = cur.fetchone()["c"]
        assert unlinked_count == 0, (
            f"SC #7 regression: {unlinked_count} of {seg_count} road_segments have "
            f"NULL source or target — pgr_createTopology partially failed. "
            f"pgr_ksp will not be able to route across these edges."
        )


def test_pgr_create_topology_call_present_in_seed_script():
    """Static guard: scripts/seed_data.py must contain the pgr_createTopology call.

    Faster than the integration test (no DB roundtrip, no OSMnx download). Runs
    even when DB is unreachable. Catches refactor-removal of the line at the
    source level, before the integration test would even attempt to run.

    Per RESEARCH A1: the line is at scripts/seed_data.py:148-152 as of 2026-04-27.
    """
    seed_text = SEED_SCRIPT.read_text()
    assert "pgr_createTopology" in seed_text, (
        f"scripts/seed_data.py must contain a pgr_createTopology call "
        f"(SC #7 invariant). If you removed it, the deploy-time topology "
        f"bootstrap is broken. See RESEARCH Pattern 5 + the test_seed_data_builds_routable_topology "
        f"integration test."
    )
    assert "clean := true" in seed_text, (
        f"scripts/seed_data.py's pgr_createTopology call must include "
        f"`clean := true` for idempotency on re-runs (RESEARCH Pitfall 3)."
    )
