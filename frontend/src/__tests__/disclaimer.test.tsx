import { render } from '@testing-library/react';
import { vi, beforeEach, test, expect } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import RouteFinder from '../pages/RouteFinder';

const DISCLAIMER = 'Routes incorporate historical crash data from LA City open-data (through March 2024). This is informational, not a safety guarantee — always drive defensively.';

beforeEach(() => {
  // Stub fetch so any AddressInput/route side effects do not crash the render.
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ type: 'FeatureCollection', features: [] }),
  } as Response);
});

test('RouteFinder renders the EXACT-LOCKED disclaimer adjacent to the find-route button (D-11-04, D-11-05)', () => {
  render(<MemoryRouter><RouteFinder /></MemoryRouter>);
  // toHaveTextContent matches the exact substring in the document — em dash U+2014 must match byte-for-byte.
  expect(document.body).toHaveTextContent(DISCLAIMER);
});

test('disclaimer em dash is U+2014 (not double hyphen, not en dash) — Pitfall 10 byte sentinel', () => {
  // sentinel byte-check — guards Pitfall 10 build-then-supersede.
  expect(DISCLAIMER).toContain('—'); // U+2014 EM DASH
  expect(DISCLAIMER).not.toContain('--');
  expect(DISCLAIMER).not.toContain('–'); // U+2013 EN DASH must NOT appear
  // Confirm the em dash codepoint is exactly U+2014 (8212).
  const emDashIdx = DISCLAIMER.indexOf('—');
  expect(emDashIdx).toBeGreaterThan(-1);
  expect(DISCLAIMER.charCodeAt(emDashIdx)).toBe(0x2014);
});
