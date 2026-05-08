import { render } from '@testing-library/react';
import { vi, beforeEach, test, expect } from 'vitest';
import MapView from '../pages/MapView';

const CAPTION = 'Crash data: LA City open-data through March 2024. Single-segment attribution; intersection distribution to be added in a future release.';

beforeEach(() => {
  // Stub fetch so MapView's useEffect-driven segments fetch returns an empty FC and component mounts cleanly.
  globalThis.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ type: 'FeatureCollection', features: [] }),
  } as Response);
});

test('MapView renders the EXACT-LOCKED data-vintage caption (D-11-06)', () => {
  render(<MapView />);
  expect(document.body).toHaveTextContent(CAPTION);
});
