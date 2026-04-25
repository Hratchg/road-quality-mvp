"""Mapillary->YOLO->segment_defects ingestion pipeline (Phase 3, REQ-mapillary-pipeline).

Operator-facing CLI:
    python scripts/ingest_mapillary.py --segment-ids 1,2,3
    python scripts/ingest_mapillary.py --segment-ids-file priority.txt
    python scripts/ingest_mapillary.py --where "iri_norm > 0.5 ORDER BY iri_norm DESC LIMIT 50"

Workflow per target segment:
    1. Compute padded bbox via ST_Buffer(geom::geography, pad_m)::geometry -> ST_Envelope.
    2. If envelope area > 0.01 deg^2, subdivide into 4 quadrants (Pitfall 2).
    3. For each (sub-)bbox, call data_pipeline.mapillary.search_images(bbox, limit=N).
    4. For each image meta:
        - download via data_pipeline.mapillary.download_image (validates image_id is digits-only).
        - run detector via data_pipeline.detector_factory.get_detector(use_yolo=True).detect.
        - snap-match the image's lon/lat to the nearest segment (D-01: ST_DWithin + <->).
        - if matched within snap_m: aggregate detections by severity, queue for insert.
        - if outside snap radius: drop, increment "dropped_outside_snap" counter (D-03).
    5. Flush queued rows via execute_values + ON CONFLICT
       (segment_id, source_mapillary_id, severity) DO NOTHING (D-08: idempotent resume).
    6. Append manifest entries; write manifest BEFORE any --no-keep unlinks
       (Pattern 5 caveat).

Token & client reuse:
    - MAPILLARY_ACCESS_TOKEN read at module-top via data_pipeline.mapillary import (D-19).
    - data_pipeline/mapillary.py is NOT modified (D-20). All Mapillary HTTP, bbox guards,
      SHA256 verification, image_id validation, path-traversal rejection inherit from Phase 2.

Exit codes (D-18 inherited):
    0 OK
    1 generic error (token missing, DB connection failed)
    2 validation error (--where rejected, --segment-ids invalid, no targets matched)
    3 missing resource (segment id not found)

NOTE: --wipe-synthetic, --no-recompute, and structured JSON run-summary land in plan 03-04.
This plan ships the core; plan 04 extends.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import psycopg2
import requests
from psycopg2 import sql as psql
from psycopg2.extras import execute_values

# Pattern S-3: project-root importable so data_pipeline.* resolves
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_pipeline.mapillary import (  # noqa: E402
    MAPILLARY_TOKEN,
    download_image,
    search_images,
    validate_bbox,
    write_manifest,
)
from data_pipeline.detector_factory import get_detector  # noqa: E402

logger = logging.getLogger(__name__)

# Pattern S-1: module-top env-var read (matches backend/app/db.py:5-7)
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://rq:rqpass@localhost:5432/roadquality"
)

# Pattern S-2: D-18 exit codes (inherited)
EXIT_OK = 0
EXIT_OTHER = 1
EXIT_VALIDATION = 2
EXIT_MISSING_RESOURCE = 3

# CONTEXT.md D-02 / D-10 / D-12 defaults
DEFAULT_SNAP_METERS = 25.0
DEFAULT_PAD_METERS = 50.0
DEFAULT_LIMIT_PER_SEGMENT = 20
MAX_SEGMENTS_FROM_WHERE = 1000  # Pattern 6 cap
MAX_BBOX_AREA_DEG2 = 0.01  # mirrors data_pipeline.mapillary.MAX_BBOX_AREA_DEG2

# Pattern 6: forbidden-token regex for --where defense.
# Case-insensitive; matched against the operator-supplied predicate.
_FORBIDDEN_RE = re.compile(
    r"\b(DELETE|UPDATE|INSERT|DROP|ALTER|CREATE|GRANT|REVOKE|EXECUTE|"
    r"TRUNCATE|COPY|EXEC|pg_\w+|information_schema)\b",
    re.IGNORECASE,
)


# ---------- Target resolution (D-09) ----------

def parse_segment_ids_csv(value: str) -> list[int]:
    """Parse '--segment-ids 1,2,3' into [1, 2, 3]. Raises ValueError on bad item."""
    out: list[int] = []
    for raw in value.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(int(raw))
        except ValueError as e:
            raise ValueError(
                f"--segment-ids contains non-integer item: {raw!r}"
            ) from e
    if not out:
        raise ValueError("--segment-ids contained no integers")
    return out


def parse_segment_ids_file(path: Path) -> list[int]:
    """One id per line, skip blank lines and `#` comments."""
    if not path.exists():
        raise FileNotFoundError(f"--segment-ids-file not found: {path}")
    out: list[int] = []
    for lineno, raw in enumerate(path.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            out.append(int(line))
        except ValueError as e:
            raise ValueError(
                f"{path}:{lineno}: non-integer id {line!r}"
            ) from e
    if not out:
        raise ValueError(f"--segment-ids-file {path} contained 0 ids")
    return out


def validate_where_predicate(predicate: str) -> str:
    """Pattern 6 defense-in-depth.

    Reject predicates with comment markers, semicolons, or DDL/DML tokens.
    Returns the cleaned predicate. Raises ValueError on rejection.
    The actual SQL composition uses psycopg2.sql.SQL -- this regex is the
    documentation of the trust model.
    """
    if "--" in predicate or "/*" in predicate or "*/" in predicate:
        raise ValueError(
            "comment markers (`--`, `/*`, `*/`) not allowed in --where"
        )
    if ";" in predicate:
        raise ValueError("`;` not allowed in --where predicate")
    if _FORBIDDEN_RE.search(predicate):
        raise ValueError(
            f"forbidden token in --where predicate: {predicate!r}. "
            "DDL/DML and pg_*/information_schema references are blocked."
        )
    return predicate.strip()


def resolve_where_targets(
    cur,
    predicate: str,
    max_segments: int = MAX_SEGMENTS_FROM_WHERE,
) -> list[int]:
    """Resolve --where predicate to a list of segment ids.

    Uses psycopg2.sql.SQL composition; the predicate itself is validated by
    `validate_where_predicate` before being wrapped. The max_segments cap
    bounds the explosion radius for typo'd predicates (Pitfall 9 + DoS guard).
    """
    cleaned = validate_where_predicate(predicate)
    # Apply a statement timeout to bound bad predicates (Anti-Pattern reminder).
    cur.execute("SET statement_timeout = '30s'")
    query = psql.SQL("SELECT id FROM road_segments WHERE {predicate}").format(
        predicate=psql.SQL(cleaned),
    )
    cur.execute(query)
    rows = cur.fetchmany(max_segments + 1)
    ids = [row[0] if not isinstance(row, dict) else row["id"] for row in rows]
    if len(ids) > max_segments:
        raise ValueError(
            f"--where predicate matched > {max_segments} segments; "
            f"add an explicit LIMIT clause to your --where"
        )
    return ids


def resolve_targets(cur, args: argparse.Namespace) -> list[int]:
    """Dispatch to one of the three target modes (mutex enforced by argparse)."""
    if args.segment_ids:
        return parse_segment_ids_csv(args.segment_ids)
    if args.segment_ids_file:
        return parse_segment_ids_file(args.segment_ids_file)
    if args.where:
        return resolve_where_targets(cur, args.where)
    raise ValueError("no target mode specified (argparse should have caught this)")


# ---------- Bbox + spatial helpers (D-01, D-10, RESEARCH Pattern 2/3) ----------

def compute_padded_bbox(
    cur, segment_id: int, pad_meters: float
) -> tuple[float, float, float, float]:
    """Pattern S-7: ST_Buffer on geography, then envelope.

    Returns (min_lon, min_lat, max_lon, max_lat).
    """
    cur.execute(
        """
        SELECT ST_XMin(env), ST_YMin(env), ST_XMax(env), ST_YMax(env)
        FROM (
            SELECT ST_Envelope(ST_Buffer(geom::geography, %s)::geometry) AS env
            FROM road_segments WHERE id = %s
        ) e
        """,
        (pad_meters, segment_id),
    )
    row = cur.fetchone()
    if not row:
        raise ValueError(f"segment_id {segment_id} not found")
    if isinstance(row, dict):
        # RealDictCursor returns dict — extract by ST_* alias keys (lowercased)
        keys = list(row.keys())
        vals = [row[k] for k in keys]
    else:
        vals = list(row)
    if vals[0] is None:
        raise ValueError(f"segment_id {segment_id} not found")
    return (float(vals[0]), float(vals[1]), float(vals[2]), float(vals[3]))


def maybe_subdivide(
    bbox: tuple[float, float, float, float],
) -> list[tuple[float, float, float, float]]:
    """If bbox area > MAX_BBOX_AREA_DEG2, split into 4 quadrants. Else single-element list."""
    min_lon, min_lat, max_lon, max_lat = bbox
    area = (max_lon - min_lon) * (max_lat - min_lat)
    if area <= MAX_BBOX_AREA_DEG2:
        return [bbox]
    mid_lon = (min_lon + max_lon) / 2
    mid_lat = (min_lat + max_lat) / 2
    return [
        (min_lon, min_lat, mid_lon, mid_lat),
        (mid_lon, min_lat, max_lon, mid_lat),
        (min_lon, mid_lat, mid_lon, max_lat),
        (mid_lon, mid_lat, max_lon, max_lat),
    ]


def snap_match_image(
    cur, lon: float, lat: float, snap_meters: float
) -> int | None:
    """D-01 + RESEARCH Pattern 3: nearest segment within snap_meters, or None.

    Uses ST_DWithin (radius filter, GIST-indexed) + ORDER BY <-> (KNN distance,
    GIST-indexed) + LIMIT 1 for the nearest-within-radius query.
    """
    cur.execute(
        """
        SELECT id FROM road_segments
        WHERE ST_DWithin(
            geom::geography,
            ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
            %s
        )
        ORDER BY geom <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326)
        LIMIT 1
        """,
        (lon, lat, snap_meters, lon, lat),
    )
    row = cur.fetchone()
    if not row:
        return None
    if isinstance(row, dict):
        return int(row["id"])
    return int(row[0])


# ---------- Detection aggregation (RESEARCH Standard Stack: one row per (seg, src_mly, severity)) ----------

def aggregate_detections(
    detections: list, image_id: str
) -> list[tuple[str, str, int, float]]:
    """Group detections by severity. Returns list of (image_id, severity, count, conf_sum).

    The UNIQUE constraint includes severity, so per (segment, image, severity)
    triple at most one row is allowed. Pre-aggregating per image at this layer
    matches the schema contract.
    """
    by_sev: dict[str, list[float]] = {}
    for det in detections:
        by_sev.setdefault(det.severity, []).append(det.confidence)
    return [
        (image_id, sev, len(confs), round(sum(confs), 3))
        for sev, confs in by_sev.items()
    ]


# ---------- HTTP retry (RESEARCH Code Example 5; no tenacity dep) ----------

def with_retry(fn, *args, max_attempts: int = 3, base_delay: float = 1.0, **kwargs):
    """Hand-rolled exponential backoff for 429 + 5xx. Raises immediately on 4xx."""
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return fn(*args, **kwargs)
        except requests.HTTPError as e:
            last_exc = e
            status = getattr(e.response, "status_code", 0) if e.response is not None else 0
            if (status == 429 or 500 <= status < 600) and attempt < max_attempts - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "Mapillary HTTP %d on attempt %d/%d; sleeping %.1fs",
                    status, attempt + 1, max_attempts, delay,
                )
                time.sleep(delay)
                continue
            raise
    # Defensive: should be unreachable because we always either return or raise.
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("with_retry: no attempts executed")


# ---------- Per-segment workflow (D-10, RESEARCH Pattern 2) ----------

def ingest_segment(
    *,
    cur,
    detector,
    segment_id: int,
    cache_root: Path,
    snap_meters: float,
    pad_meters: float,
    limit: int,
    no_keep: bool,
    counters: dict,
    manifest_entries: list,
) -> list[tuple[int, str, int, float, str, str]]:
    """Run the per-segment pipeline. Returns rows ready for INSERT."""
    rows: list[tuple[int, str, int, float, str, str]] = []
    bbox = compute_padded_bbox(cur, segment_id, pad_meters)
    sub_bboxes = maybe_subdivide(bbox)

    seg_dir = cache_root / str(segment_id)
    seg_dir.mkdir(parents=True, exist_ok=True)

    images: list[dict] = []
    for sb in sub_bboxes:
        try:
            validate_bbox(sb)  # extra sanity (subdivide should already satisfy)
        except ValueError as e:
            logger.warning(
                "seg %s: bbox %s rejected by validate_bbox: %s",
                segment_id, sb, e,
            )
            counters["bbox_rejected"] = counters.get("bbox_rejected", 0) + 1
            continue
        try:
            sub_images = with_retry(search_images, sb, limit=limit)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "seg %s: search_images failed for %s: %s",
                segment_id, sb, e,
            )
            counters["search_failed"] = counters.get("search_failed", 0) + 1
            continue
        images.extend(sub_images)

    counters["images_found"] = counters.get("images_found", 0) + len(images)

    for meta in images:
        image_id = str(meta.get("id", ""))
        if not image_id:
            counters["bad_meta"] = counters.get("bad_meta", 0) + 1
            continue
        # Pitfall 3: download immediately in same pass as search (URL TTL).
        try:
            local_path = with_retry(download_image, meta, seg_dir)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "seg %s: download failed for %s: %s",
                segment_id, image_id, e,
            )
            counters["download_failed"] = counters.get("download_failed", 0) + 1
            continue

        try:
            detections = detector.detect(str(local_path))
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "seg %s: detect failed for %s: %s",
                segment_id, image_id, e,
            )
            counters["detect_failed"] = counters.get("detect_failed", 0) + 1
            continue

        # Snap-match using the image's reported coordinates (D-01).
        coords = (
            (meta.get("computed_geometry") or meta.get("geometry") or {})
            .get("coordinates")
        )
        if not coords or len(coords) != 2:
            counters["no_coords"] = counters.get("no_coords", 0) + 1
            continue
        lon, lat = float(coords[0]), float(coords[1])
        matched_seg = snap_match_image(cur, lon, lat, snap_meters)
        if matched_seg is None:
            # D-03: drop images outside snap radius.
            counters["dropped_outside_snap"] = counters.get(
                "dropped_outside_snap", 0
            ) + 1
            continue

        if matched_seg != segment_id:
            counters["matched_to_neighbor"] = counters.get(
                "matched_to_neighbor", 0
            ) + 1

        groups = aggregate_detections(detections, image_id)
        for img_id, sev, count, conf_sum in groups:
            rows.append((matched_seg, sev, count, conf_sum, img_id, "mapillary"))

        # Manifest entry (Pattern 5).
        manifest_entries.append({
            "path": str(local_path.relative_to(cache_root)),
            "source_mapillary_id": image_id,
            "matched_segment_id": matched_seg,
            "snap_meters": snap_meters,
        })

    return rows


# ---------- Main ----------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pull Mapillary imagery for target segments, run YOLO, write detections.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument(
        "--segment-ids", type=str,
        help="Comma-separated segment ids: '1,2,3'",
    )
    target_group.add_argument(
        "--segment-ids-file", type=Path,
        help="Path to file with one segment id per line",
    )
    target_group.add_argument(
        "--where", type=str,
        help='SQL predicate against road_segments, e.g. '
             '"iri_norm > 0.5 ORDER BY iri_norm DESC LIMIT 50"',
    )

    parser.add_argument("--snap-meters", type=float, default=DEFAULT_SNAP_METERS)
    parser.add_argument("--pad-meters", type=float, default=DEFAULT_PAD_METERS)
    parser.add_argument(
        "--limit-per-segment", type=int, default=DEFAULT_LIMIT_PER_SEGMENT,
    )
    parser.add_argument(
        "--cache-root", type=Path, default=Path("data/ingest_la"),
        help="Image cache root for downloaded Mapillary imagery (D-11)",
    )
    parser.add_argument(
        "--no-keep", action="store_true",
        help="Delete images after detection (D-11; manifest is still written first)",
    )
    parser.add_argument(
        "--json-out", type=Path, default=None,
        help="Write run summary JSON to this path",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # D-19: token must be set.
    if not MAPILLARY_TOKEN:
        print(
            "ERROR: ingest_mapillary requires MAPILLARY_ACCESS_TOKEN. "
            "Get a token at https://www.mapillary.com/dashboard/developers",
            file=sys.stderr,
        )
        return EXIT_OTHER

    # DB connect (mirror ingest_iri.py:231-253).
    try:
        conn = psycopg2.connect(DATABASE_URL)
    except psycopg2.OperationalError as e:
        print(f"ERROR: cannot connect to database: {e}", file=sys.stderr)
        return EXIT_OTHER

    try:
        with conn.cursor() as cur:
            # Resolve targets (one of three modes).
            try:
                segment_ids = resolve_targets(cur, args)
            except (FileNotFoundError, ValueError) as e:
                print(f"ERROR: {e}", file=sys.stderr)
                return EXIT_VALIDATION
            if not segment_ids:
                # Pitfall 9: empty match exits 2.
                print(
                    "ERROR: --where matched 0 segments; "
                    "refine --segment-ids / --where",
                    file=sys.stderr,
                )
                return EXIT_VALIDATION
            logger.info("Resolved %d target segment(s)", len(segment_ids))

            # Detector single-load (Pattern S-10).
            detector = get_detector(use_yolo=True)

            args.cache_root.mkdir(parents=True, exist_ok=True)
            counters: dict[str, int] = {
                "segments_processed": 0,
                "rows_inserted": 0,
            }
            manifest_entries: list[dict[str, Any]] = []
            all_rows: list[tuple[int, str, int, float, str, str]] = []

            for seg_id in segment_ids:
                logger.info("--- segment %s ---", seg_id)
                try:
                    rows = ingest_segment(
                        cur=cur,
                        detector=detector,
                        segment_id=seg_id,
                        cache_root=args.cache_root,
                        snap_meters=args.snap_meters,
                        pad_meters=args.pad_meters,
                        limit=args.limit_per_segment,
                        no_keep=args.no_keep,
                        counters=counters,
                        manifest_entries=manifest_entries,
                    )
                except ValueError as e:
                    # Missing segment id, etc. Continue with the rest.
                    logger.warning("segment %s skipped: %s", seg_id, e)
                    counters["segment_errors"] = counters.get(
                        "segment_errors", 0
                    ) + 1
                    continue
                counters["segments_processed"] += 1
                all_rows.extend(rows)

            # Idempotent batch INSERT (Pattern 4).
            if all_rows:
                execute_values(
                    cur,
                    """
                    INSERT INTO segment_defects
                        (segment_id, severity, count, confidence_sum,
                         source_mapillary_id, source)
                    VALUES %s
                    ON CONFLICT (segment_id, source_mapillary_id, severity)
                    DO NOTHING
                    """,
                    all_rows,
                    page_size=500,
                )
                conn.commit()
                counters["rows_inserted"] = cur.rowcount or 0
            else:
                counters["rows_inserted"] = 0

            # Manifest write BEFORE --no-keep unlinks (Pattern 5 caveat).
            if manifest_entries:
                run_id = int(time.time())
                manifest_path = args.cache_root / f"manifest-{run_id}.json"
                write_manifest(
                    manifest_path,
                    manifest_entries,
                    source_bucket="mapillary:per-segment-targeted-ingest",
                    license_str=(
                        "CC-BY-SA 4.0 (Mapillary -- attribution via "
                        "source_mapillary_id)"
                    ),
                )
                counters["manifest_path"] = str(manifest_path)

            # Now safe to unlink images if --no-keep.
            if args.no_keep and manifest_entries:
                for entry in manifest_entries:
                    p = args.cache_root / entry["path"]
                    p.unlink(missing_ok=True)

            # Run summary.
            summary = {"counters": counters, "segments": segment_ids[:50]}
            if args.json_out:
                args.json_out.write_text(json.dumps(summary, indent=2))
            print(json.dumps(summary, indent=2))
    except Exception:
        conn.rollback()
        logger.exception("ingest aborted")
        return EXIT_OTHER
    finally:
        conn.close()

    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
