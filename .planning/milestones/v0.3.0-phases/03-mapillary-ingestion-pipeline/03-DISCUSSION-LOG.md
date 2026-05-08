# Phase 3: Mapillary Ingestion Pipeline - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in `03-CONTEXT.md` — this log preserves the alternatives considered.

**Date:** 2026-04-25
**Phase:** 03-mapillary-ingestion-pipeline
**Areas discussed:** Image-to-segment matching, Idempotency strategy, Tiling & operator scope, Synthetic-data coexistence

---

## Gray Area Selection

| Option | Description | Selected |
|--------|-------------|----------|
| Image-to-segment matching | Snap radius + PostGIS approach + drop policy | ✓ |
| Idempotency strategy | Schema migration vs bookkeeping vs composite-key upsert | ✓ |
| Tiling & operator scope | One-tile vs auto-tile vs segment-targeted; CLI shape | ✓ |
| Synthetic-data coexistence | Wipe vs tag vs leave alone; SC #4 implications | ✓ |

**User selected all four areas.**

---

## Image-to-Segment Matching

### Q1: How should we associate each Mapillary image (lon,lat) to a road segment?

| Option | Description | Selected |
|--------|-------------|----------|
| Simple PostGIS | `ST_DWithin` + ORDER BY distance LIMIT 1. One query per image. Fast (~5ms with GIST index), debuggable. | ✓ (Recommended) |
| Geometrically pickier | `ST_LineLocatePoint` perpendicular-distance. Better on curvy roads. More code. |  |
| Batched CTE | Match all images in a tile in one big SQL. Faster for huge batches, loses per-image visibility. |  |

**User's choice:** Simple PostGIS (Recommended)
**Notes:** User asked for clarification first; explanation walked through the point-to-line matching problem, end results, and project effects before re-presenting options. Selected after that.

### Q2: How far from a road can an image still be considered "on" that road?

| Option | Description | Selected |
|--------|-------------|----------|
| 25 m, configurable | `--snap-meters` flag, default 25. Covers Mapillary GPS error without bridging parallel streets. | ✓ (Recommended) |
| Fixed 10 m (strict) | Higher precision, lower recall. Demo could look sparse. |  |
| Fixed 50 m (permissive) | Risk of cross-attribution between adjacent streets. |  |

**User's choice:** 25 m, configurable (Recommended)
**Notes:** Same Q&A turn as Q1 after the clarification.

---

## Idempotency Strategy

### Q3: How should we prevent double-counting on rerun, and where does Mapillary provenance live?

| Option | Description | Selected |
|--------|-------------|----------|
| Schema migration: `source_mapillary_id` + UNIQUE | New column on `segment_defects` + UNIQUE(segment_id, source_mapillary_id, severity) + ON CONFLICT DO NOTHING. Provenance per row. | ✓ (Recommended, confirmed in follow-up) |
| Separate `ingested_images` bookkeeping table | Track processed image IDs separately. Migration cost without provenance value. |  |
| Composite-key upsert, no schema change | `(segment_id, severity)` dedupe. Breaks existing multi-row pattern. Don't recommend. |  |

**User's choice:** Schema migration (Option A)
**Notes:** User asked "What's recommended?" after first presentation. Re-confirmed via follow-up question with five reasons (provenance, rollback, manifest alignment, accumulation, one-migration-cost). User confirmed "Yes, lock it in."

---

## Tiling & Operator Scope

### Q4: How should the ingest CLI handle the bbox when an operator wants more than one tile?

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-tile | `--bbox <any size> --tile-size 0.01` splits into chunks, processes sequentially. | (Recommended, not chosen) |
| One tile at a time | Operator passes only ≤0.01 deg² bboxes; manual orchestration. |  |
| Segment-targeted | Operator picks segment IDs/filter; CLI generates per-segment bboxes. | ✓ |

**User's choice:** Segment-targeted (over the recommended Auto-tile)
**Notes:** User chose directed segment-by-segment ingestion over the broader auto-tile sweep. Drove D-09/D-10 in CONTEXT.md.

### Q5: After detection completes for an image, what do we do with the downloaded JPEG?

| Option | Description | Selected |
|--------|-------------|----------|
| Keep + manifest | Persist with manifest.json (CC-BY-SA audit, re-detection support). | ✓ (Recommended) |
| Delete after detect | Save disk; re-runs require re-download. |  |
| Tempdir, never persist | No audit trail. |  |

**User's choice:** Keep + manifest (Recommended)
**Notes:** Mirrors Phase 2's manifest format.

### Q6: How does the operator specify which segments to ingest imagery for?

| Option | Description | Selected |
|--------|-------------|----------|
| Multi-mode flags | `--segment-ids`, `--segment-ids-file`, `--where`. Covers ad-hoc, scripted, exploratory. | ✓ (Recommended) |
| Just `--segment-ids` list | Simplest, least flexible. |  |
| Just `--where` SQL filter | Powerful but always requires SQL. |  |
| Named target sets | Curated UX, every new target needs code change. |  |

**User's choice:** Multi-mode flags (Recommended)
**Notes:** Drove D-09. Planner must defend `--where` against SQL injection (whitelist or parameterized predicates).

### Q7: Match drift — when imagery fetched 'for segment X' snaps closer to neighboring Y, what happens?

| Option | Description | Selected |
|--------|-------------|----------|
| Attribute to closest | Trust the 25m PostGIS match. "Free coverage" of adjacent segments. | ✓ (Recommended) |
| Force-attribute to target X | Predictable but produces wrong attributions near boundaries. |  |
| Drop images that don't match the target | Clean per-segment semantics, lower yield. |  |

**User's choice:** Attribute to closest (Recommended)
**Notes:** Drove D-04.

---

## Synthetic-Data Coexistence

### Q8: How should real (Mapillary) and synthetic defects coexist in segment_defects?

| Option | Description | Selected |
|--------|-------------|----------|
| Tag with source column | `source TEXT` ('synthetic'\|'mapillary') + compute_scores `--source` filter. SC #4 demonstrable in dev. | (Initial recommendation) |
| Wipe synthetic before first real ingest | Clean final state, SC #4 requires regenerating. |  |
| Mixed, no distinction | Don't recommend. |  |
| **Other (user note)** | "I don't want synthetic data when the project is finished." | ✓ |

**User's choice:** Other (free-text note)
**Notes:** User's intent was a final-state requirement, not a single option. Reflected back as a hybrid (tag + wipe path + Phase 6 procedure) and confirmed in Q9.

### Q9: Lock in the hybrid — source column + `--wipe-synthetic` flag + public demo runs wiped?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, hybrid as proposed | Tag + `--wipe-synthetic` flag + Phase 6 procedure wipes. | ✓ |
| Stricter — always wipe synthetic on every ingest | No flag needed, synthetic is dev-only. |  |
| Tag-only, no wipe path | Filter at query time via WHERE source = 'mapillary'. |  |

**User's choice:** Yes, hybrid as proposed
**Notes:** Drove D-13/D-14/D-15/D-16 in CONTEXT.md.

---

## Final Confirmation

### Q10: Ready to write CONTEXT.md, or explore more gray areas first?

| Option | Description | Selected |
|--------|-------------|----------|
| Ready for context | Write CONTEXT.md now; remaining items as Claude's discretion. | ✓ |
| Explore more gray areas | Lock confidence threshold / detection-row shape / rate-limit handling now. |  |
| Revisit one of the four areas |  |  |

**User's choice:** Ready for context

---

## Claude's Discretion

These came up during discussion but were left for downstream agents (researcher/planner) to decide:

- Confidence threshold for filtering low-confidence YOLO detections (~0.25–0.5; tuned after seeing real model output)
- Detection-row aggregation policy (one row per detection vs grouped by image+severity)
- Mapillary heading/orientation filter (not in Phase 2 either; defer)
- Mapillary rate-limit / retry / exponential backoff details
- Bbox padding amount around target segments (default 50 m suggested in D-10)
- Run-summary format (probably mirror Phase 2's `eval_detector.py` exit codes)
- Whether `--where` SQL uses parameterized queries or column whitelisting (planner picks the safer one)
- Optional `--no-defects` flag on `seed_data.py` for clean dev starts (low-priority polish)

## Deferred Ideas

Captured in CONTEXT.md `<deferred>` section. Notable:

- Auto-tile sweep mode (`--bbox` operator entrypoint) — could be added later atop segment-targeted
- Named target sets — over-engineered for MVP
- Confidence calibration / temperature scaling
- CI gate on ingestion correctness
- Soft-delete (`deleted_at`) for run-level rollback
