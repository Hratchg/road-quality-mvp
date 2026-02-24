import { useState } from "react";
import { MapContainer, TileLayer, Polyline, useMapEvents, Marker } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import ControlPanel, { ControlState } from "../components/ControlPanel";
import RouteResults from "../components/RouteResults";
import { fetchRoute, RouteRequestBody } from "../api";

const LA_CENTER: [number, number] = [34.0522, -118.2437];

// Fix default marker icons in react-leaflet
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
});

function ClickHandler({ onSelect }: { onSelect: (lat: number, lon: number) => void }) {
  useMapEvents({
    click(e) {
      onSelect(e.latlng.lat, e.latlng.lng);
    },
  });
  return null;
}

function geoJsonToLatLngs(geojson: any): [number, number][] {
  if (!geojson?.coordinates) return [];
  return geojson.coordinates.map(([lon, lat]: [number, number]) => [lat, lon]);
}

export default function RouteFinder() {
  const [controls, setControls] = useState<ControlState>({
    includeIri: true,
    includePotholes: true,
    weightIri: 50,
    weightPotholes: 50,
  });
  const [origin, setOrigin] = useState<{ lat: number; lon: number } | null>(null);
  const [destination, setDestination] = useState<{ lat: number; lon: number } | null>(null);
  const [selectingOrigin, setSelectingOrigin] = useState(true);
  const [maxExtra, setMaxExtra] = useState(5);
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleMapClick = (lat: number, lon: number) => {
    if (selectingOrigin) {
      setOrigin({ lat, lon });
      setSelectingOrigin(false);
    } else {
      setDestination({ lat, lon });
      setSelectingOrigin(true);
    }
  };

  const handleSearch = async () => {
    if (!origin || !destination) return;
    setLoading(true);
    setError(null);
    try {
      const body: RouteRequestBody = {
        origin,
        destination,
        include_iri: controls.includeIri,
        include_potholes: controls.includePotholes,
        weight_iri: controls.weightIri,
        weight_potholes: controls.weightPotholes,
        max_extra_minutes: maxExtra,
      };
      const data = await fetchRoute(body);
      setResult(data);
    } catch (err: any) {
      setError(err.message || "Route request failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-[calc(100vh-52px)]">
      <div className="w-80 p-4 space-y-4 overflow-y-auto bg-gray-50 border-r">
        <h2 className="font-bold text-lg">Route Finder</h2>

        <p className="text-sm text-gray-500">
          {selectingOrigin
            ? "Click the map to set ORIGIN"
            : "Click the map to set DESTINATION"}
        </p>

        {origin && (
          <p className="text-xs">
            Origin: {origin.lat.toFixed(4)}, {origin.lon.toFixed(4)}
          </p>
        )}
        {destination && (
          <p className="text-xs">
            Dest: {destination.lat.toFixed(4)}, {destination.lon.toFixed(4)}
          </p>
        )}

        <label className="block text-sm">
          Max extra minutes:
          <input
            type="number"
            min={0}
            value={maxExtra}
            onChange={(e) => setMaxExtra(Number(e.target.value))}
            className="ml-2 w-16 border rounded px-1"
          />
        </label>

        <ControlPanel state={controls} onChange={setControls} />

        <button
          onClick={handleSearch}
          disabled={!origin || !destination || loading}
          className="w-full bg-blue-600 text-white rounded py-2 hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? "Searching..." : "Find Best Route"}
        </button>

        {error && <p className="text-red-600 text-sm">{error}</p>}

        {result && (
          <RouteResults
            fastest={result.fastest_route}
            best={result.best_route}
            warning={result.warning}
          />
        )}
      </div>

      <MapContainer center={LA_CENTER} zoom={13} className="flex-1">
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <ClickHandler onSelect={handleMapClick} />
        {origin && <Marker position={[origin.lat, origin.lon]} />}
        {destination && <Marker position={[destination.lat, destination.lon]} />}
        {result?.fastest_route?.geojson && (
          <Polyline
            positions={geoJsonToLatLngs(result.fastest_route.geojson)}
            pathOptions={{ color: "#3b82f6", weight: 4, dashArray: "10 6" }}
          />
        )}
        {result?.best_route?.geojson && (
          <Polyline
            positions={geoJsonToLatLngs(result.best_route.geojson)}
            pathOptions={{ color: "#22c55e", weight: 5 }}
          />
        )}
      </MapContainer>
    </div>
  );
}
