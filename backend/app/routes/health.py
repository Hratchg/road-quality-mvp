"""GET /health endpoint - Phase 5 SC #5: DB-reachability probe for LB checks.

200 + {status:"ok", db:"reachable"} on success (PRD M0 contract preserved
via the {status:"ok"} key; the {db:"reachable"} field is additive).
503 + {detail:{status:"unhealthy", db:"unreachable"}} on any DB failure.

Fly's HTTP health check treats non-2xx as unhealthy and DEPOOLS the machine
(does NOT restart it - see RESEARCH Pitfall 5). So 503 is the right code:
the LB stops sending traffic until the next probe succeeds, which gives the
DB a chance to recover from a transient hiccup without Fly tearing down the
machine and reseating it.

Threat T-05-07: psycopg2 error messages may include host:port and (rarely)
password fragments. The except clause catches Exception broadly and surfaces
ONLY the static "unreachable" string - never the underlying message. Operator
visibility comes from Fly's stderr logs, not from this public endpoint.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.db import get_connection

router = APIRouter()


@router.get("/health")
def health():
    """LB-probe-friendly health check.

    Returns 200 with {status:"ok", db:"reachable"} on success.
    Returns 503 with {detail:{status:"unhealthy", db:"unreachable"}} on
    any DB failure - Fly's HTTP health check treats non-2xx as unhealthy
    and depools the machine.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return {"status": "ok", "db": "reachable"}
    except Exception:
        # Threat T-05-07: don't leak DB details (host, password fragment in
        # error message) to public probes. The static string is what the LB
        # needs; operator debugging comes from Fly's process logs, not from
        # this endpoint's response body.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "unhealthy", "db": "unreachable"},
        )
