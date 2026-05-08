// Empty for now — kept as a named export so future debug overlays slot in (D-11-02).
// IRI / pothole sliders + checkboxes were removed in Phase 11 because the v0.4.0 routing
// formula uses locked weights (W_IRI=0.40, W_POT=0.35, W_CRASH=0.25) — see backend/app/scoring.py.
// This file is intentionally retained as a near-empty card so Phase 12+ debug overlays
// (e.g. crash_norm inspectors, perf counters) have a typed home.
export type ControlState = Record<string, never>;

interface Props {
  state: ControlState;
  onChange: (state: ControlState) => void;
}

export default function ControlPanel(_: Props) {
  return (
    <div className="bg-white rounded-lg shadow p-4 space-y-3 w-64">
      <h3 className="font-bold text-sm uppercase text-gray-500">Layers</h3>
    </div>
  );
}
