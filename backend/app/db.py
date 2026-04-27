"""Module-level psycopg2 connection pool for the FastAPI backend.

Phase 5 SC #6: connections are pooled.
Phase 5 SC #9: the pool wrapper's try/finally putconn guarantees that the
slot releases on every exit path — including exceptions raised inside a
`with get_connection() as conn:` block. This means routing.py's existing
calls (lines 59, 73) become automatically leak-safe; no per-call-site
contextlib.closing wrap is needed (RESEARCH §3 Pattern 4 compatibility table).

ThreadedConnectionPool is required (the single-thread variant in psycopg2.pool
is documented as not shareable across threads). FastAPI runs sync `def`
handlers via anyio's threadpool (40 workers default). Two concurrent requests
will hit getconn from different threads. The single-thread pool's internal
_pool list and _used dict are mutated without a lock — race conditions,
deadlocks, double-handed connections. ThreadedConnectionPool wraps both
methods in a threading.Lock. This corrects CONTEXT D-07's incorrect default
per RESEARCH Correction A / Pitfall 1. Anti-pattern guard: the plan's verify
gate explicitly bans the single-thread class name from this file via grep.

Pool sizing (minconn=2, maxconn=12):
  - minconn=2: keep 2 warm connections (tests, /health probe, demo traffic)
  - maxconn=12: bounded by FastAPI's anyio threadpool (40 workers) AND PG's
    default max_connections=100 (leaves headroom for psql sessions, the seed
    script, in-machine tooling). Burst above 12 will block on getconn —
    that's correct: graceful backpressure, not a 500.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

import psycopg2
import psycopg2.extensions
from psycopg2 import pool as _pool
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://rq:rqpass@localhost:5432/roadquality"
)

# Module-level pool — cached after first init via _get_pool(). Lazy because
# tests may set DATABASE_URL via fixture BEFORE the pool tries to open
# connections. Eager init at import time would race the fixture.
_connection_pool: "_pool.ThreadedConnectionPool | None" = None


def _get_pool() -> "_pool.ThreadedConnectionPool":
    """Lazy-initialize the module-level pool on first use.

    Returns the same pool instance on every subsequent call. Tests that
    need to reset the pool (e.g., to apply a different DATABASE_URL) can
    call close_pool() to clear the cached instance.
    """
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = _pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=12,
            dsn=DATABASE_URL,
            cursor_factory=RealDictCursor,
        )
    return _connection_pool


@contextmanager
def get_connection() -> Iterator[psycopg2.extensions.connection]:
    """Borrow a pooled connection. The pool slot ALWAYS releases on exit,
    even if the caller raised — guards against the SC #9 leak pattern.

    Usage (unchanged from the pre-pool single-connection API — minimal-diff
    migration; existing call sites in segments.py, routing.py, auth.py keep
    working with NO syntax changes):

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(...)

    For transaction management, combine with psycopg2's connection-level
    context manager (commit on success, rollback on exception):

        with get_connection() as conn, conn:
            with conn.cursor() as cur:
                cur.execute("INSERT ...")

    Note: putconn does NOT auto-rollback. Callers that mutate state must
    use the `with conn:` inner context to commit/rollback explicitly, or
    call conn.commit() / conn.rollback() before the outer context exits.
    The pool wrapper just guarantees the slot is released.
    """
    p = _get_pool()
    conn = p.getconn()
    try:
        yield conn
    finally:
        p.putconn(conn)


def close_pool() -> None:
    """Optional teardown for tests / shutdown.

    Production code rarely needs this — the OS reclaims sockets when the
    process exits. Tests use it to reset the cached pool between fixtures
    that set different DATABASE_URLs.
    """
    global _connection_pool
    if _connection_pool is not None:
        _connection_pool.closeall()
        _connection_pool = None
