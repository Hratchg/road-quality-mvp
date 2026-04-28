---
phase: 05-cloud-deployment
created: 2026-04-28
source: 05-HUMAN-UAT.md walkthrough 2026-04-27 → 2026-04-28
---

# Phase 5 — Lessons Learned (Defects 8–16)

The Phase 5 live-deploy UAT walkthrough surfaced 9 defects beyond the
original 7 plan/CONTEXT issues that landed in commits `bca06a6` + `fdd8fd4`
+ `766c2fe`. All 9 were fixed inline (commits `b4e2cd5` → `64ad2d4`). This
doc codifies them so a future operator (or Phase 5.1 polish plan) doesn't
have to re-discover them.

## BLOCKING anti-pattern — `pgr_createTopology` via `flyctl proxy`

**Never run `pgr_createTopology` (or any long DDL) through `flyctl proxy`.**

Why: the wireguard tunnel can't sustain multi-minute queries. When the
proxy connection dies mid-query, postgres aborts → rollback writes WAL →
small volume hits "No space left on device" writing pg_wal/xlogtemp →
recovery crash loop. Cost when this happened: ~30 min of debugging plus
a memory scale and volume extend.

How to apply: always use direct on-machine execution for long DDL.

```
flyctl ssh console -a road-quality-db -C \
  "psql -U rq -d roadquality -c \"SELECT pgr_createTopology(...)\""
```

## Production infra sizing baseline (defects #8 + #9)

The Phase 5 RESEARCH/CONTEXT sized infra against an empty schema. After
seeding 209k segments + 125k defects + scores + topology, both ran out
simultaneously.

| Resource | Phase 5 plan | Phase 5 actual (after UAT) | Notes |
|---|---|---|---|
| `road-quality-db` machine memory | `shared-cpu-1x:512MB` | `shared-cpu-1x:2048MB` | 512 MB OOMed during pgr_createTopology on 200k segments |
| `rq_db` volume size | `1 GB` | `5 GB` | 1 GB filled with segments + indexes + WAL during recovery from the OOM |

Phase 6 (Public Demo Launch) and any future cloud-deploy phase should
size against a real LA seed, not an empty schema. The sizing above is
comfortable for the demo; bump again if seg count > 500k.

## CI test job — collect-time deps (#11)

`backend/tests/` collect-time-imports from `scripts/` and `data_pipeline/`.
The Phase 5 deploy.yml only installed `backend/requirements.txt`, so
collection failed on `requests`, `numpy`, `huggingface_hub`. Targeted
install added (commit `ec0fa67`). The heavier ML deps (ultralytics+torch
~3GB, opencv, scipy) intentionally NOT installed — runtime-only and the
tests that exercise them now skip cleanly via the `db_has_topology`
fixture or osmnx import guards.

## CI test fixtures — `db_has_topology` (#15)

Six integration tests require a fully-seeded DB with topology built.
CI's lightweight postgres service container has migrations only.
Solution: a session fixture in `conftest.py` that checks for
`road_segments_vertices_pgr` and skips with a clear message if missing.
Local dev with seeded DB still runs them; CI cleanly skips.

This pattern should be reused for any future test that depends on
seeded data — don't let CI silently pass with skipped failures.

## Stale assertion — `test_health_remains_public` (#13)

Phase 5 enhanced `/health` to include `db: reachable` for LB-probe
parity. The auth-routes test wasn't updated. Fixed inline. Lesson:
when a route's response shape changes, grep the test suite for the
old shape and update assertions in the same PR.

## Silent decorator — `pytest-timeout` (#12)

`@pytest.mark.timeout(N)` was used on 4 tests but `pytest-timeout`
was never declared as a dep. Decorators registered as unknown marks
(visible only as warnings) and provided zero timeout enforcement.
Fixed by adding to `backend/requirements.txt`. Lesson: any
`@pytest.mark.X` that isn't a built-in mark must come with its
plugin in requirements, OR pytest will silently no-op it.

## Heavy test skip-guard — `test_seed_topology` (#14)

The SC #7 regression gate subprocess-launches `seed_data.py` which
needs osmnx (heavy, ~5min download). Added an `import osmnx` guard
that skips when unavailable so CI without `scripts/requirements.txt`
doesn't fail on the OSMnx weight. Local dev with `/tmp/rq-venv` runs
the full path.

## flyctl `[build].dockerfile` path resolution (#16)

In CI (both 0.4.40 and 0.4.41), flyctl computed the
`[build].dockerfile` path from a wrong anchor and produced
"dockerfile not found" against the doubled-name GH-Actions checkout
root. Workaround: in `deploy.yml`, invoke flyctl with
`working-directory: backend` + relative `--config ../deploy/backend/fly.toml`
+ context `.`. flyctl auto-discovers `Dockerfile` in CWD without
cross-directory path resolution. Same shape verified via local
manual deploy (image rebuild + rolling deploy successful).

The toml's `[build].dockerfile` was also dropped (commit `5f5eea2`)
to remove the failure mode entirely. The frontend toml + db toml
keep their explicit `dockerfile = "Dockerfile"` since their
positional-arg context (`.` = repo root) makes auto-discovery
ambiguous (no `Dockerfile` at repo root).

## Cross-references

- `05-HUMAN-UAT.md` — full UAT result narrative with the 16 defects
  itemized in context
- `~/.claude/projects/-Users-hratchghanime/memory/road-quality-mvp_fly_deploy.md`
  — cross-session memory snapshot of Fly state + anti-patterns
- Commits: `b4e2cd5`, `2720a37`, `df65509`, `ec0fa67`, `9c852e9`,
  `a29601f`, `5f5eea2`, `a55d6b5`, `75f38f0`, `64ad2d4`
