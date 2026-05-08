---
phase: 11-frontend-slider-removal-liability-disclaimer-data-vintage-caption
reviewed: 2026-05-07T00:00:00Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - frontend/src/components/ControlPanel.tsx
  - frontend/src/pages/RouteFinder.tsx
  - frontend/src/pages/MapView.tsx
  - frontend/src/api.ts
  - frontend/src/__tests__/disclaimer.test.tsx
  - frontend/src/__tests__/mapViewCaption.test.tsx
  - frontend/src/__tests__/controlPanel.test.tsx
  - frontend/src/__tests__/routeFinderPost.test.tsx
  - frontend/src/test/setup.ts
  - frontend/vitest.config.ts
  - frontend/package.json
findings:
  critical: 0
  warning: 1
  info: 4
  total: 5
status: issues_found
---

# Phase 11: Code Review Report

**Reviewed:** 2026-05-07
**Depth:** standard
**Files Reviewed:** 11
**Status:** issues_found

## Summary

Phase 11 implements REQ-frontend-slider-removal cleanly and meets every load-bearing
must-have. All four high-leverage checks pass:

1. **Exact-string locks (Pitfall 10):** Both the RouteFinder disclaimer and the MapView
   caption are byte-equal to the requirement spec, including em dash U+2014 (verified
   via UTF-8 byte search: `\xe2\x80\x94` present in source, en dash `\xe2\x80\x93`
   absent, double-hyphen `--` absent).
2. **Anti-features locked OUT:** Grep across `frontend/src/` for `heatmap`, `safer
   route`, `crash.layer`, `crash.toggle`, `CrashHeat`, `crash_marker` returns zero
   matches. No new Leaflet layers, no toggles, no markers.
3. **POST body shape:** `RouteFinder.handleSearch()` sends only `{origin, destination,
   max_extra_minutes}`. `RouteRequestBody` in `api.ts` matches Phase 10 contract
   (`docs/API.md:20`). No occurrences of `weight_iri`, `weight_potholes`,
   `include_iri`, or `include_potholes` in production source — only the negative test
   assertions in `routeFinderPost.test.tsx` reference them.
4. **crash_norm type-through:** `SegmentProperties.crash_norm: number` is exported
   from `api.ts:21` and consumed in `MapView.tsx:81` (via the `feature.properties`
   cast) but is intentionally not read by `scoreForFeature()` — exactly the
   D-11-07 / D-11-09 contract.

The `scoreForFeature()` math is sensible: `0.40/0.75 + 0.35/0.75 = 1.0`, so a
worst-case (iri=1, pot=1) feature scores 1.0 and clamps cleanly to red in
`scoreToColor()`. The visual blend ratio is also documented in the file comment.

Pitfall 9 placement is correct — the disclaimer sits 2 lines below the
"Find Best Route" button (`RouteFinder.tsx:130-139`), in the same visual cluster
as the action moment, not in a hamburger menu, footer, or sidebar.

Issues below are quality / minor robustness — none block merge.

## Warnings

### WR-01: routeFinderPost.test.tsx does not exercise the production `RouteFinder` code path

**File:** `frontend/src/__tests__/routeFinderPost.test.tsx:21-43`
**Issue:** The test imports and calls `fetchRoute()` directly from `api.ts`. This pins
the **API helper's** body shape, not the **page's** body shape. If a future regression
adds `weight_iri` back to `RouteFinder.handleSearch()`'s `body` literal at line 54-58
(while leaving `RouteRequestBody`'s type clean), this test would still pass because
it never invokes `RouteFinder`. The plan text explicitly says (line 58 of
`11-01-PLAN.md`): "performs origin+dest selection + click find-route; asserts request
body (parsed JSON)..." — the actual test takes a unit-test shortcut that loses
the page-level coverage.

The disclaimer test does mount `RouteFinder` (which exercises the render path), but
it doesn't click the button or assert on fetch — so today no test actually verifies
the `body` literal at `RouteFinder.tsx:54-58`. The TS type system makes this safe
in practice (extra keys would fail `RouteRequestBody`), but Pitfall 10 says
"belt and suspenders," not "trust the type checker."

**Fix:** Either keep the api-level test as the contract pin (it's a defensible
stance — the type forces the shape) and update the plan text to match, or add a
second test that mounts `RouteFinder`, drives the inputs, clicks "Find Best Route",
and asserts `globalThis.fetch.mock.calls[0][1].body` parsed JSON has the expected
keys. Suggested addition:

```tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import RouteFinder from '../pages/RouteFinder';

test('RouteFinder click sends body with no legacy keys', async () => {
  render(<MemoryRouter><RouteFinder /></MemoryRouter>);
  // ... drive AddressInput selections via test-only props or window state ...
  fireEvent.click(screen.getByRole('button', { name: /find best route/i }));
  await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
  const body = JSON.parse((globalThis.fetch as any).mock.calls.at(-1)[1].body);
  expect(body).not.toHaveProperty('weight_iri');
});
```

## Info

### IN-01: `geoJsonToLatLngs` parameter typed `any` (pre-existing, not introduced by Phase 11)

**File:** `frontend/src/pages/RouteFinder.tsx:25`
**Issue:** `function geoJsonToLatLngs(geojson: any): [number, number][]`. The Phase 11
must-have "no `any` introduced" appears satisfied — this `any` predates Phase 11
(it's not in the diff). Flagged as info because the file was modified in this phase
and the linter did not catch it.

**Fix:** When you next touch this function, narrow to `GeoJSON.LineString | undefined`
or a minimal local interface:

```ts
function geoJsonToLatLngs(geojson: { coordinates?: [number, number][] } | undefined): [number, number][] {
  if (!geojson?.coordinates) return [];
  return geojson.coordinates.map(([lon, lat]) => [lat, lon]);
}
```

### IN-02: `result` and `err` typed `any` in RouteFinder

**File:** `frontend/src/pages/RouteFinder.tsx:38, 71`
**Issue:** `useState<any>(null)` for `result` and `catch (err: any)`. These are both
pre-existing patterns; `result` is structurally tied to the `/route` response which
isn't yet typed in `api.ts` (`fetchRoute` returns `Promise<any>` implicitly via
`res.json()`).

**Fix:** Add a `RouteResponse` interface to `api.ts` mirroring the Phase 10 backend
shape (`fastest_route`, `best_route`, `warning`), and `catch (err: unknown)` with a
narrowing check. Out of scope for this phase but worth a Phase 12+ ticket.

### IN-03: ControlPanel `Props` interface is unused after refactor

**File:** `frontend/src/components/ControlPanel.tsx:6-13`
**Issue:** `ControlState = Record<string, never>` and the `Props` interface is
preserved so callers (`MapView.tsx:92`) keep their existing `state={controls}
onChange={setControls}` wiring without churn. The component body ignores both
(`function ControlPanel(_: Props)`). This is intentional per the file comment
("kept as a named export so future debug overlays slot in") and the plan
(`D-11-02 last-line discretion`). No action — flagged purely so the next reader
doesn't try to "clean it up."

**Fix:** None. Comment in source already explains the rationale; reviewers can
verify D-11-02 intent.

### IN-04: ControlPanel test passes `{} as any` instead of leaning on the typed shape

**File:** `frontend/src/__tests__/controlPanel.test.tsx:8`
**Issue:** `render(<ControlPanel state={{} as any} onChange={() => {}} />)`. Since
`ControlState` is `Record<string, never>`, `state={{}}` (without `as any`) would
type-check cleanly. The `as any` is a small noise item and slightly weakens what
the test demonstrates (that the production shape is empty).

**Fix:**

```tsx
render(<ControlPanel state={{}} onChange={() => {}} />);
```

The TS compiler accepts this because `Record<string, never>` matches the empty
object literal.

---

_Reviewed: 2026-05-07_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
