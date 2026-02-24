import { useEffect, useState, useCallback } from "react";
import { MapContainer, TileLayer, GeoJSON, useMapEvents } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import ControlPanel, { ControlState } from "../components/ControlPanel";
import Legend from "../components/Legend";
import { fetchSegments } from "../api";

const LA_CENTER: [number, number] = [34.0522, -118.2437];

function scoreForFeature(
  props: any,
  controls: ControlState
): number {
  const { includeIri, includePotholes, weightIri, weightPotholes } = controls;
  if (!includeIri && !includePotholes) return 0;

  let wIri = 0, wPot = 0;
  if (includeIri && includePotholes) {
    const total = weightIri + weightPotholes || 1;
    wIri = weightIri / total;
    wPot = weightPotholes / total;
  } else if (includeIri) {
    wIri = 1;
  } else {
    wPot = 1;
  }

  return wIri * (props.iri_norm || 0) + wPot * (props.pothole_score_total || 0);
}

function scoreToColor(score: number): string {
  const clamped = Math.min(score, 1);
  if (clamped < 0.5) {
    const t = clamped / 0.5;
    const r = Math.round(34 + t * (234 - 34));
    const g = Math.round(197 + t * (179 - 197));
    const b = Math.round(94 + t * (8 - 94));
    return `rgb(${r},${g},${b})`;
  }
  const t = (clamped - 0.5) / 0.5;
  const r = Math.round(234 + t * (239 - 234));
  const g = Math.round(179 - t * 179);
  const b = Math.round(8 + t * (68 - 8));
  return `rgb(${r},${g},${b})`;
}

function MapEvents({ onBoundsChange }: { onBoundsChange: (bbox: string) => void }) {
  useMapEvents({
    moveend(e) {
      const b = e.target.getBounds();
      onBoundsChange(`${b.getWest()},${b.getSouth()},${b.getEast()},${b.getNorth()}`);
    },
  });
  return null;
}

export default function MapView() {
  const [controls, setControls] = useState<ControlState>({
    includeIri: true,
    includePotholes: true,
    weightIri: 50,
    weightPotholes: 50,
  });
  const [geojson, setGeojson] = useState<any>(null);
  const [bbox, setBbox] = useState("");

  const loadSegments = useCallback(async (b: string) => {
    if (!b) return;
    try {
      const data = await fetchSegments(b);
      setGeojson(data);
    } catch (err) {
      console.error("Failed to fetch segments", err);
    }
  }, []);

  useEffect(() => {
    if (bbox) loadSegments(bbox);
  }, [bbox, loadSegments]);

  return (
    <div className="relative h-[calc(100vh-52px)]">
      <MapContainer center={LA_CENTER} zoom={13} className="h-full w-full">
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <MapEvents onBoundsChange={setBbox} />
        {geojson && (
          <GeoJSON
            key={JSON.stringify(controls)}
            data={geojson}
            style={(feature) => {
              const score = scoreForFeature(feature?.properties, controls);
              return {
                color: scoreToColor(score),
                weight: 3,
                opacity: 0.8,
              };
            }}
          />
        )}
      </MapContainer>
      <div className="absolute top-4 right-4 z-[1000] space-y-2">
        <ControlPanel state={controls} onChange={setControls} />
        <Legend />
      </div>
    </div>
  );
}
