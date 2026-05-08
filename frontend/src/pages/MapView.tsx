import { useEffect, useState, useCallback } from "react";
import { MapContainer, TileLayer, GeoJSON, useMapEvents } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import ControlPanel, { ControlState } from "../components/ControlPanel";
import Legend from "../components/Legend";
import { fetchSegments, SegmentProperties } from "../api";

const LA_CENTER: [number, number] = [34.0522, -118.2437];

// Locked-weight visual blend mirrors backend W_IRI=0.40 / W_POT=0.35
// normalized within the visual sum (sum=0.75): 0.5333 IRI + 0.4667 pothole.
// crash_norm is typed-through (SegmentProperties below) but NOT visualized
// per anti-features D-11-07, D-11-10, D-11-11, D-11-12 (locked OUT).
const VISUAL_W_IRI = 0.40 / 0.75; // ≈ 0.5333
const VISUAL_W_POT = 0.35 / 0.75; // ≈ 0.4667

function scoreForFeature(props: SegmentProperties | undefined): number {
  const iri = props?.iri_norm ?? 0;
  const pot = props?.pothole_score_total ?? 0;
  return VISUAL_W_IRI * iri + VISUAL_W_POT * pot;
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
  const [controls, setControls] = useState<ControlState>({} as ControlState);
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
            key="segments"
            data={geojson}
            style={(feature) => {
              const score = scoreForFeature(feature?.properties as SegmentProperties | undefined);
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
      <div className="absolute bottom-4 left-4 z-[1000] bg-white/90 rounded px-2 py-1 text-xs text-gray-500 max-w-md leading-snug shadow">
        Crash data: LA City open-data through March 2024. Single-segment attribution; intersection distribution to be added in a future release.
      </div>
    </div>
  );
}
