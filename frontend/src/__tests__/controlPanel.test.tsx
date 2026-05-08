import { render, screen } from '@testing-library/react';
import { test, expect } from 'vitest';
import ControlPanel from '../components/ControlPanel';

test('ControlPanel renders no IRI slider, no pothole slider, no IRI/pothole checkboxes (D-11-01, D-11-02)', () => {
  // Use whatever empty/default state the new ControlState shape allows.
  // After Task 3 ControlState is `Record<string, never>` — pass {} as state.
  render(<ControlPanel state={{} as any} onChange={() => {}} />);
  expect(screen.queryByRole('slider')).toBeNull();
  expect(screen.queryByLabelText(/iri/i)).toBeNull();
  expect(screen.queryByLabelText(/pothole/i)).toBeNull();
  // Defensive: also assert no checkbox has accessible-name matching IRI/pothole.
  const checkboxes = screen.queryAllByRole('checkbox');
  for (const cb of checkboxes) {
    const accessibleName = cb.getAttribute('aria-label') ?? cb.textContent ?? '';
    expect(accessibleName).not.toMatch(/iri|pothole/i);
  }
  // Defensive: no <input type="range"> tags at all.
  const rangeInputs = document.querySelectorAll('input[type="range"]');
  expect(rangeInputs.length).toBe(0);
});
