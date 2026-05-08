# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v0.3.0 — Post-MVP + Public Demo

**Shipped:** 2026-05-08
**Phases:** 8 | **Plans:** 41 | **Tasks:** 73
**Timeline:** 2026-04-22 → 2026-05-07 (16 days)
**Commits:** 296 | **Files changed:** 2,877 (+72,985 / -82) | **LOC at close:** 11,583 (Py+TS+SQL)

### What Was Built

- **Real-data pipeline end-to-end:** `scripts/ingest_mapillary.py` pulls Mapillary v4 imagery → ST_Buffer→subdivide→YOLO→snap-match → idempotent `ON CONFLICT DO NOTHING` upsert into `segment_defects`. Migration 002 added `(source_mapillary_id, source)` UNIQUE for dedup. ~125k real LA detections in production.
- **Fly.io tri-app deploy:** db (custom PostGIS+pgRouting 3.8 image, internal-only) + backend (with `/health` DB-reachability LB probe + ThreadedConnectionPool wrapper) + frontend (build-time-baked `VITE_API_URL`, nginx:alpine, 92 MB image). GH Actions deploy.yml. Live at `https://road-quality-frontend.fly.dev/`.
- **Detector evaluation harness:** Deterministic seed=42 bootstrap CIs, `bootstrap_ci_map50` for image-level P-R AUC CI, `scripts/eval_detector.py` runnable on real eval set. `docs/DETECTOR_EVAL.md` (291 lines) is the citation source.
- **Authentication then deliberate removal:** Phase 4 shipped JWT (HS256) + pwdlib argon2id + sign-in modal + demo account, validated 8-scenario curl UAT against live Docker. Commit `d0ef452` then unmounted everything for the public-demo target. Auth modules retained as dormant code.
- **Routing perf fix:** pgr_ksp K=5 (super-linear, 20-90s on cross-LA) replaced with pre-filter temp table + pgr_dijkstra×K with edge-weight perturbation (Yen's-style, linear in K, OSRM/Valhalla pattern). 3-attempt fallback chain (filter → wide → full) catches BOTH `psycopg2.errors.QueryCanceled` AND empty-result conditions. Cross-LA: 2.47s. DTLA: 0.385s.
- **Phase 7 documented negative:** Hand-labeled 171 positive bboxes across 12 LA zones, fine-tuned on 1322 images, two iterations published to HF. Both failed D-11 win-check on test split — iter-1 collapsed (0 predictions everywhere), iter-2 had val P=0.184 R=0.071 but 0 predictions on test (operator labeling-style drift across CVAT splits). D-13 contingency: production retains keremberke baseline. Honest disclosure in DETECTOR_EVAL.md v0.3.0.

### What Worked

- **Plan-checker / replan loops upstream of execute.** Phase 7 plan-revision cycle caught 6 blockers + warnings before any code was written. Phase 8 had a similar cycle that caught the SQL-shape-vs-control-flow split. Cheaper to fail in markdown than in code.
- **Wave-0 RED gates per phase.** Tests written first, intentionally failing, then turned GREEN by implementation. Phase 7 (07-01) and Phase 8 (08-01) both used this. The RED→GREEN pin made plan reviews concrete.
- **Decision contingencies baked into plans (D-XX).** Phase 7 D-13 (skip prod cutover on negative win-check) was written into the plan, not improvised when the negative landed. That preserved the demo and forced honest negative documentation.
- **Operator gates inside plans (GATE A, GATE B).** Phase 7 paused at hand-labeling (GATE A) and HF SHA capture (GATE B) — explicit halt-points for human work, then resume. Avoided pretending operator work was code work.
- **Live-DB perf measurement, not synthetic benchmarks.** Phase 8's `08-PERF-NUMBERS.md` captured numbers against the seeded local DB (209,856 segments / 74,270 vertices / 125,632 defects). README cross-links to it as source-of-truth for the perf claim.
- **Inline-comment-as-anti-pattern-pin.** `routing.py:272-298` cites RESEARCH §8 Pitfalls A and G to prevent re-introducing the 2026-04-29 pgr_ksp-on-temp-table disaster. The post-mortem lives in the code that would be edited next time.
- **`docs(NN-MM):` commit prefix per plan.** Made `git log --grep` slicing trivial for milestone close stats.

### What Was Inefficient

- **Phase 4 re-litigation.** Phase 4 shipped fully-functional auth, then commit `d0ef452` ripped it out two days later for a public-demo-friction reason that could have been decided in a 30-second conversation before Phase 4 started. ~5 plans of work landed and unlanded.
- **Doc drift surfaced only at audit.** `REQ-user-auth` traceability stayed marked "Pending" through milestone close audit even though Phase 4 had shipped + been superseded weeks earlier. The audit caught it (verdict flipped from `tech_debt` → `passed` after fixing), but a checklist that asks "does any superseding commit reference a REQ?" would have caught it earlier.
- **Phase 7 labeling-style drift wasn't caught at GATE A.** Test split was labeled first with least operator experience, train labeled last with most. The labeling-style split contributed to iter-2's 0-test-predictions failure mode. A "label all splits in one pass with the same operator + style" check would have surfaced this before training.
- **`02-HUMAN-UAT.md`, `03-HUMAN-UAT.md`, `05-HUMAN-UAT.md` carry-forward.** Multiple phases shipped with operator-runbook walkthroughs deferred. They're acknowledged at milestone close, but the next milestone inherits them as drag.
- **One-liner extraction junk.** Plan SUMMARY.md format wasn't consistent — some had literal `One-liner:` placeholder, some had file-path-only, some had `None for Tasks 1-4.`. Auto-extraction shipped junk into the initial MILESTONES.md draft. A SUMMARY template lint (`gsd-sdk` could enforce one_liner is a non-trivial sentence) would help next time.

### Patterns Established

- **Decimal-phase insertion convention.** Phase 8 was added 2026-04-29 mid-milestone after the routing perf disaster surfaced; ROADMAP.md noted insertion explicitly.
- **D-XX-NEGATIVE contingency clauses.** Phase 7's D-13 ("if win-check fails, skip prod cutover") proved its weight — plan continued cleanly through a negative result without improvisation.
- **GATE A/B operator pauses inside execution.** Use them whenever a plan has a human-in-the-loop step (CVAT labeling, EC2 training, HF SHA capture) so the plan doesn't pretend to autorun.
- **Anti-pattern pinning in code comments + RESEARCH.md citation.** When a non-obvious approach failed, the post-mortem lives where the next maintainer will edit (Phase 8 routing.py header).
- **`flyctl ssh console -C` over `flyctl proxy` for long DDL.** Locked anti-pattern in 05-LESSONS-LEARNED.md.

### Key Lessons

1. **Auth-or-no-auth is a product decision, not a phase decision.** Decide before scoping the phase, or accept that Phase X may need to be unwound.
2. **Audit-time doc drift detection isn't enough.** Whenever a commit message says "remove" or "supersede", scan for REQ-IDs in the diff and propose `REQUIREMENTS.md` updates in the same commit.
3. **Label all eval splits in one pass with the same operator.** Splitting label work across sessions/operators introduces a style drift that is invisible in train metrics but kills test generalization.
4. **pgRouting's `pgr_ksp` evaluates inner SQL via SPI, which doesn't use GiST.** A bbox WHERE inside the pgr_ksp SQL string is a full sequential scan. Use a pre-filter into a temp table + btree on source/target (Pitfalls A and G).
5. **Long DDL on Fly DB must use `flyctl ssh console -C`, not `flyctl proxy`.** The wireguard tunnel times out on multi-minute queries and triggers a postgres recovery crash loop.
6. **Phase 7 negative was a feature, not a bug.** Documenting "we tried, here's what failed, here's why" beats a hand-wavy "future work" claim. The honest disclosure is the portfolio asset.

### Cost Observations

- Sessions: ~30+ across the milestone
- Notable: Phase 7 ate ~12 hours operator time + ~3 hours model time, returned a documented negative. Phase 8 ate ~1 hour model time, returned a 10-30× perf win. Investment-to-payoff ratio varies wildly per phase; plan-checker upstream is what made the high-payoff phases land cleanly.

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Key Change |
|-----------|--------|-------|------------|
| v0.2.0 | 7 (M0) | — | Initial MVP, pre-`.planning/` |
| v0.3.0 | 8 (M1) | 41 | Adopted GSD `.planning/` workflow; introduced Wave-0 RED tests, D-XX contingencies, GATE A/B operator pauses, plan-checker / replan loops |

### Cumulative Quality

| Milestone | LOC | Tests | Notable |
|-----------|-----|-------|---------|
| v0.2.0 | ~2,900 (est.) | 6 integration tests | Local Docker stack working end-to-end |
| v0.3.0 | 11,583 | 73 tasks across 41 plans (~150+ tests) | Live Fly deploy, real Mapillary data, cross-LA routing under 5s |

### Top Lessons (verified once; revisit at v0.4.0)

1. **Plan-checker / replan loops upstream of execute is the highest-leverage pattern.** Catches blockers in markdown (cheap) instead of code (expensive). Verified across Phases 7 and 8.
2. **Wave-0 RED gates make plan reviews concrete.** Tests written first define the contract; implementation just turns them GREEN.
3. **Document negative results honestly.** The Phase 7 negative is a portfolio asset, not a failure to hide.
