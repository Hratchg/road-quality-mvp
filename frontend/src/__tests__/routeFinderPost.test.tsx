import { vi, beforeEach, test, expect } from 'vitest';

beforeEach(() => {
  globalThis.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      fastest_route: {
        total_time_s: 100,
        total_cost: 100,
        geojson: { type: 'LineString', coordinates: [[-118.2, 34.05], [-118.21, 34.06]] },
      },
      best_route: {
        total_time_s: 110,
        total_cost: 105,
        geojson: { type: 'LineString', coordinates: [[-118.2, 34.05], [-118.21, 34.06]] },
      },
    }),
  } as Response);
});

test('POST /route body has only origin/destination/max_extra_minutes (D-11-03, D-11-08)', async () => {
  // Deterministic unit-style entry: invoke fetchRoute() directly with the new typed body shape.
  // The page-level integration is covered by the disclaimer test already mounting RouteFinder;
  // this spec pins the FETCH-CALL-SHAPE contract (the load-bearing assertion).
  const { fetchRoute } = await import('../api');
  await fetchRoute({
    origin: { lat: 34.05, lon: -118.24 },
    destination: { lat: 34.06, lon: -118.25 },
    max_extra_minutes: 5,
  });

  expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  const callArgs = (globalThis.fetch as any).mock.calls[0];
  const url = callArgs[0] as string;
  const init = callArgs[1] as RequestInit;
  expect(url).toMatch(/\/route$/);
  const body = JSON.parse(init.body as string);
  expect(Object.keys(body).sort()).toEqual(['destination', 'max_extra_minutes', 'origin']);
  expect(body).not.toHaveProperty('weight_iri');
  expect(body).not.toHaveProperty('weight_potholes');
  expect(body).not.toHaveProperty('include_iri');
  expect(body).not.toHaveProperty('include_potholes');
});
