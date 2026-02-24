import { useState } from "react";

export interface ControlState {
  includeIri: boolean;
  includePotholes: boolean;
  weightIri: number;
  weightPotholes: number;
}

interface Props {
  state: ControlState;
  onChange: (state: ControlState) => void;
}

export default function ControlPanel({ state, onChange }: Props) {
  const update = (patch: Partial<ControlState>) =>
    onChange({ ...state, ...patch });

  return (
    <div className="bg-white rounded-lg shadow p-4 space-y-3 w-64">
      <h3 className="font-bold text-sm uppercase text-gray-500">Layers</h3>

      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={state.includeIri}
          onChange={(e) => update({ includeIri: e.target.checked })}
        />
        <span>Show IRI</span>
      </label>
      {state.includeIri && (
        <label className="flex items-center gap-2 pl-6">
          <span className="text-sm text-gray-600 w-16">Weight</span>
          <input
            type="range"
            min={0}
            max={100}
            value={state.weightIri}
            onChange={(e) => update({ weightIri: Number(e.target.value) })}
            className="flex-1"
          />
          <span className="text-sm w-8">{state.weightIri}</span>
        </label>
      )}

      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={state.includePotholes}
          onChange={(e) => update({ includePotholes: e.target.checked })}
        />
        <span>Show Potholes</span>
      </label>
      {state.includePotholes && (
        <label className="flex items-center gap-2 pl-6">
          <span className="text-sm text-gray-600 w-16">Weight</span>
          <input
            type="range"
            min={0}
            max={100}
            value={state.weightPotholes}
            onChange={(e) => update({ weightPotholes: Number(e.target.value) })}
            className="flex-1"
          />
          <span className="text-sm w-8">{state.weightPotholes}</span>
        </label>
      )}
    </div>
  );
}
