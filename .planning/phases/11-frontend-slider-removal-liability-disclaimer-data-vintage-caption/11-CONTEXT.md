# Phase 11: Frontend Slider Removal + Liability Disclaimer + Data-Vintage Caption - Context

**Gathered:** 2026-05-08
**Status:** Ready for planning
**Mode:** Auto-generated via /gsd-discuss-phase 11 --auto (decisions sourced from REQUIREMENTS.md REQ-frontend-slider-removal — every string and anti-feature is exact-locked at the milestone level; no implementation gray areas remain).

<domain>
## Phase Boundary

Strip the IRI weight slider and pothole weight slider from `ControlPanel.tsx`; keep only the `max_extra_minutes` slider. `RouteFinder.tsx` POSTs to `/route` without `weight_iri` / `weight_potholes` (silently accepted by Phase 10 backend via `extra='ignore'`, but the frontend should not send them). `MapView.tsx` carries a static one-line crash-data-vintage caption (NOT a new map layer) and consumes `crash_norm` from the `/segments` response (added in Phase 10) for any future debugging — no new visual layer is introduced. `RouteFinder.tsx` shows the locked liability disclaimer copy adjacent to the "find route" button (NOT in a hamburger menu — Pitfall 9: moment-of-decision placement).

This phase does NOT:
- Add a crash heatmap, per-segment crash markers, or a crash-data toggle (locked anti-features per PROJECT.md)
- Touch any backend code (Phase 10 already shipped silent-ignore + crash_norm exposure)
- Run a Fly.io deploy (Phase 12)

</domain>

<decisions>
## Implementation Decisions

### ControlPanel.tsx (REQ-frontend-slider-removal AC #1)
- **D-11-01:** Remove the `<input type="range">` for `weightIri` and `weightPotholes` and their labels. Remove the `includeIri` / `includePotholes` checkboxes too (their backend purpose was gating the unused weights; with locked weights they are dead UI). Keep the `max_extra_minutes` slider.
- **D-11-02:** Update `ControlState` interface in `ControlPanel.tsx`: drop `includeIri`, `includePotholes`, `weightIri`, `weightPotholes`. The component's only output state is now whatever `max_extra_minutes` lives in (likely lifted to the parent `RouteFinder.tsx`). If the file shrinks to <30 lines after this, that's expected — keep the file rather than collapsing into RouteFinder, so future debug overlays have a home.

### RouteFinder.tsx (REQ-frontend-slider-removal AC #2 + AC disclaimer)
- **D-11-03:** POST body to `/route` no longer includes `weight_iri` or `weight_potholes`. Remove from the JSON object literal at lines 66-67. `max_extra_minutes` stays (line 68).
- **D-11-04:** Render the EXACT-LOCKED disclaimer string adjacent to the "find route" button (NOT inside a hamburger menu, NOT in a footer — Pitfall 9 moment-of-decision placement):
  ```
  Routes incorporate historical crash data from LA City open-data (through March 2024). This is informational, not a safety guarantee — always drive defensively.
  ```
  Use a `<p>` or `<small>` adjacent to the action button. Tailwind classes appropriate for compact secondary text (e.g., `text-xs text-gray-500 mt-2`).
- **D-11-05:** Disclaimer copy is exact-string locked. Tests must `toEqual` not `toContain`. Do NOT paraphrase, do NOT split, do NOT translate. Pitfall 10 build-then-supersede risk applies.

### MapView.tsx (REQ-frontend-slider-removal AC vintage-caption + crash_norm consumption)
- **D-11-06:** Render the EXACT-LOCKED static caption (NOT a new map layer, NOT a heatmap, NOT per-segment markers — locked anti-features):
  ```
  Crash data: LA City open-data through March 2024. Single-segment attribution; intersection distribution to be added in a future release.
  ```
  Place as a small text element somewhere unobtrusive on the Map View page (corner overlay, header strip, or footer). Tailwind: `text-xs text-gray-500`.
- **D-11-07:** When MapView consumes the `/segments` response, capture `crash_norm` into the in-memory feature data (already exposed by Phase 10, default 0.0). Do NOT visualize it (anti-feature). Just typing it through enables future debug overlays / dev console inspection. If the existing code uses a typed `Segment` interface, add `crash_norm: number` to it.

### api.ts (Type contract sync with Phase 10 backend)
- **D-11-08:** Update `RouteRequest` type: remove `weight_iri` and `weight_potholes`. Keep `max_extra_minutes`. The Phase 10 backend silently ignores extra fields (`extra='ignore'`), but frontend types should match what the frontend actually sends.
- **D-11-09:** Update `Segment` (or whatever the typed shape is for `/segments` features) to include `crash_norm: number`. Default 0.0; non-null per D-10-18.

### Anti-features (locked OUT — do NOT add)
- **D-11-10:** No crash heatmap.
- **D-11-11:** No per-segment crash markers / pins.
- **D-11-12:** No new map layer toggle.
- **D-11-13:** No "safer route" copy. Use the exact disclaimer string only.

### Test Coverage
- **D-11-14:** If a test runner exists (look for `frontend/package.json` test script — vitest, jest, RTL), add tests pinning: (a) exact disclaimer string in RouteFinder render, (b) exact caption string in MapView render, (c) /route POST body does NOT contain `weight_iri`/`weight_potholes` keys, (d) ControlPanel does NOT render any IRI/pothole sliders. If no test runner exists, document a manual smoke test in the SUMMARY.
- **D-11-15:** Do NOT add a frontend smoke that requires a running backend — that's Phase 12 territory. Component-level rendering tests with mocked `fetch` are the right scope.

### Documentation
- **D-11-16:** README's frontend-config section (if exists) should note the slider removal; if no such section, no docs change required (the v0.4.0 contract is canonical in `docs/API.md` shipped in Phase 10).

### Claude's Discretion
- Exact placement of the disclaimer DOM node (above vs below the find-route button) — Tailwind class choice — choose what reads most naturally given current layout
- Exact placement of the caption (corner vs header vs footer) — choose lowest-friction position
- Whether to consolidate `ControlState` collapse into RouteFinder.tsx or keep ControlPanel as a near-empty file (default: keep file for future overlays per D-11-02)
- Test framework choice if multiple are available; if no test runner exists, prefer adding vitest with minimal config over leaving untested

### Folded Todos (from STATE.md)
- "Phase 11: Disclaimer text is EXACT-string locked in REQUIREMENTS.md; do NOT paraphrase; verify no new map layer/toggle slips in (Pitfall 10 build-then-supersede risk)" — folded into D-11-04, D-11-05, D-11-06, D-11-10..D-11-13.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Locked Copy + Acceptance Criteria
- `.planning/REQUIREMENTS.md` §REQ-frontend-slider-removal — exact disclaimer + caption strings, locked anti-features
- `.planning/ROADMAP.md` §Phase 11 — 5 success criteria with the exact strings repeated

### Phase 10 Hand-Off (the consumer-side Phase 11 needs)
- `.planning/phases/10-crash-scoring-formula-locked-weight-routing-api/10-VERIFICATION.md` §Hand-offs — confirms /segments crash_norm is exposed and silent-ignore is in place
- `docs/API.md` — Phase 10 v0.4.0 API contract (canonical reference for what the backend now accepts/returns)
- `backend/app/routes/segments.py` — confirms `crash_norm` is in every feature's properties (default 0.0)
- `backend/app/models.py` — RouteRequest with extra='ignore'; frontend types should match

### Existing Frontend Code (touched by Phase 11)
- `frontend/src/components/ControlPanel.tsx` — strip 2 sliders + 2 checkboxes + 4 ControlState fields
- `frontend/src/pages/RouteFinder.tsx` — drop 2 POST body keys, add disclaimer adjacent to button
- `frontend/src/pages/MapView.tsx` — add caption, type-through crash_norm
- `frontend/src/api.ts` — sync RouteRequest type, add crash_norm to Segment type

### Anti-Patterns (load-bearing — do NOT violate)
- `.planning/PROJECT.md` "Frontend anti-features locked OUT: no crash heatmap, no per-segment crash markers, no separate map layer, no severity-tier toggle, no 'safer route' copy" — load-bearing
- Pitfall 9 (moment-of-decision disclaimer placement) — disclaimer adjacent to find-route button, NOT a hamburger menu
- Pitfall 10 (build-then-supersede risk) — exact-string lock; do NOT paraphrase

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- Existing Tailwind classes in ControlPanel.tsx (e.g. `text-sm text-gray-600`, `flex items-center gap-2`) — reuse the typography scale for the new disclaimer + caption
- Existing `Segment` / `RouteRequest` types in `api.ts` — this is where the type-only changes land

### Established Patterns
- One file per page (`frontend/src/pages/RouteFinder.tsx`, `frontend/src/pages/MapView.tsx`); components are reusable and live in `frontend/src/components/`
- API access centralized in `frontend/src/api.ts` (single fetch per endpoint)

### Integration Points
- Phase 11 frontend deploys WITHOUT a coordinated backend redeploy (Phase 10 already shipped silent-ignore + crash_norm exposure). Frontend can ship to Fly.io standalone.
- Phase 12 will redeploy frontend to road-quality-frontend.fly.dev — Phase 11 just needs the build to be green.

</code_context>

<specifics>
## Specific Ideas

- Disclaimer copy: `Routes incorporate historical crash data from LA City open-data (through March 2024). This is informational, not a safety guarantee — always drive defensively.`
- Caption copy: `Crash data: LA City open-data through March 2024. Single-segment attribution; intersection distribution to be added in a future release.`
- Both are exact-string locked. Tests must use `toEqual`/`exact-string` matching.
- Em dash in disclaimer is U+2014 (—), not double hyphen.

</specifics>

<deferred>
## Deferred Ideas

- **Visual rendering of crash_norm on the map** (heatmap, color-coded segments, intensity layer) — explicitly locked OUT for v0.4.0 (PROJECT.md anti-features). Defer to v0.4.1+.
- **Internationalization of the disclaimer** — out of scope; English-only for v0.4.0.
- **A11y audit of the new caption + disclaimer** — basic semantic HTML is fine; full A11y audit deferred.
- **README frontend section update** — D-11-16 says only if a section exists; otherwise the canonical contract is in docs/API.md.

</deferred>

---

*Phase: 11-Frontend Slider Removal + Liability Disclaimer + Data-Vintage Caption*
*Context gathered: 2026-05-08*
