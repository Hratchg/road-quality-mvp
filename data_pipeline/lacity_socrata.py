"""LA City Socrata SoQL client for d5tf-ez2w (Traffic Collision Data 2010-Present).

Mirrors data_pipeline/mapillary.py shape: framework-agnostic (no argparse, no
sys.exit), module-top env-var read, paged generator, requests-only HTTP. CLI
lives in scripts/ingest_crashes.py.

Dataset:
    https://data.lacity.org/resource/d5tf-ez2w.json
    Frozen at 2025-03-11 (response header X-SODA2-Truth-Last-Modified).
    Schema (verified via X-SODA2-Fields header on 2026-05-08):
      dr_no, date_rptd, date_occ, time_occ, area, area_name, rpt_dist_no,
      crm_cd, crm_cd_desc, mocodes (SPACE-separated), vict_age, vict_sex,
      vict_descent, premis_cd, premis_desc, location, cross_street,
      location_1 ({"latitude": str, "longitude": str, "human_address": ...}),
      ...

App token (D-09-20):
    Optional. With token: 1000 req/hr per registered app.
    Without: shared-IP throttling (~lower).
    Header: X-App-Token: <token>
    [VERIFIED dev.socrata.com/docs/app-tokens]
    Token is NEVER logged or echoed by this module — the operator is
    responsible for getting it into the env via the project's Python
    `.env` parser (memory pin: tokens contain pipes; never `source .env`).

D-09-01 time window default: 2019-03-01 → 2024-03-01 (5 full pre-freeze years).
The driver in scripts/ingest_crashes.py owns the argparse defaults; this module
takes the dates as required parameters.
"""

from __future__ import annotations

import logging
import os
from typing import Iterator

import requests

logger = logging.getLogger(__name__)

# Module-top env read (matches data_pipeline/mapillary.py:48-49 pattern).
LACITY_APP_TOKEN = os.environ.get("LACITY_APP_TOKEN")  # optional per D-09-20

_API_URL = "https://data.lacity.org/resource/d5tf-ez2w.json"
DEFAULT_PAGE_SIZE = 1000


def iter_crashes(
    start_date: str,
    end_date: str,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    token: str | None = None,
    timeout_s: float = 60.0,
) -> Iterator[dict]:
    """Yield one dict per row across the date window, paging by $offset.

    Args:
        start_date: ISO date string, e.g. "2019-03-01". Mapped to the date_occ
            BETWEEN filter at midnight UTC.
        end_date: ISO date string, e.g. "2024-03-01". Exclusive upper bound.
        bbox: Optional (ymin, xmin, ymax, xmax) — uses Socrata
            within_box(location_1, ymin, xmin, ymax, xmax). Lat-first per
            Socrata docs https://dev.socrata.com/docs/functions/within_box.html.
            For LA City the typical full-LA bbox is (33.7, -118.7, 34.4, -118.0).
        page_size: Rows per HTTP request; 1000 is the SoQL default + sweet spot.
        token: LACITY_APP_TOKEN override; falls back to env var. Optional.
        timeout_s: HTTP timeout per page.

    Yields:
        dict per row with at minimum keys: dr_no (str, the LA City record id),
        date_occ (ISO timestamp string), mocodes (space-separated str),
        location_1 ({"latitude": str, "longitude": str, ...}).
        Other Socrata fields are passed through but unused by Phase 9.

    Raises:
        requests.HTTPError on non-2xx responses (caller may wrap in retry).
    """
    where_parts = [
        f"date_occ between '{start_date}T00:00:00' and '{end_date}T00:00:00'"
    ]
    if bbox is not None:
        ymin, xmin, ymax, xmax = (float(c) for c in bbox)
        # within_box uses LAT-FIRST argument order per Socrata docs.
        where_parts.append(
            f"within_box(location_1, {ymin}, {xmin}, {ymax}, {xmax})"
        )
    where = " AND ".join(where_parts)

    headers: dict[str, str] = {}
    tok = token or LACITY_APP_TOKEN
    if tok:
        headers["X-App-Token"] = tok
        # Note: NEVER log the token. The operator is responsible for getting
        # it into the env via the project's Python .env parser (memory pin).

    offset = 0
    while True:
        params = {
            "$where": where,
            "$select": "dr_no,date_occ,mocodes,location_1",
            "$order": ":id",     # stable pagination per dev.socrata.com/docs/paging
            "$limit": page_size,
            "$offset": offset,
        }
        r = requests.get(
            _API_URL, params=params, headers=headers, timeout=timeout_s,
        )
        r.raise_for_status()
        rows = r.json()
        if not rows:
            return
        for row in rows:
            yield row
        if len(rows) < page_size:
            return
        offset += page_size
        logger.info("lacity_socrata: paged offset=%d page_size=%d", offset, page_size)
