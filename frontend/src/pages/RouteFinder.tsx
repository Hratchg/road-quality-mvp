import { useState } from "react";
import { MapContainer, TileLayer, Polyline, Marker } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import ControlPanel, { ControlState } from "../components/ControlPanel";
import RouteResults from "../components/RouteResults";
import AddressInput from "../components/AddressInput";
import { fetchRoute, RouteRequestBody } from "../api";

const LA_CENTER: [number, number] = [34.0522, -118.2437];

function makeCircleIcon(color: string) {
  return L.divIcon({
    className: "",
    iconSize: [18, 18],
    iconAnchor: [9, 9],
    html: `<svg width="18" height="18" viewBox="0 0 18 18" xmlns="http://www.w3.org/2000/svg">
      <circle cx="9" cy="9" r="8" fill="${color}" stroke="white" stroke-width="2"/>
    </svg>`,
  });
}

const originIcon = makeCircleIcon("#22c55e");
const destIcon = makeCircleIcon("#ef4444");

function geoJsonToLatLngs(geojson: any): [number, number][] {
  if (!geojson?.coordinates) return [];
  return geojson.coordinates.map(
    ([lon, lat]: [number, number]) => [lat, lon] as [number, number],
  );
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
  const [originText, setOriginText] = useState("");
  const [destText, setDestText] = useState("");
  const [maxExtra, setMaxExtra] = useState(5);
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSwap = () => {
    setOrigin(destination);
    setDestination(origin);
    setOriginText(destText);
    setDestText(originText);
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

      // Snap markers to the route's actual start/end on the road network
      const routeGeojson = data?.best_route?.geojson ?? data?.fastest_route?.geojson;
      if (routeGeojson?.coordinates?.length) {
        const coords = routeGeojson.coordinates;
        const [startLon, startLat] = coords[0];
        const [endLon, endLat] = coords[coords.length - 1];
        setOrigin({ lat: startLat, lon: startLon });
        setDestination({ lat: endLat, lon: endLon });
      }
    } catch (err: any) {
      setError(err.message || "Route request failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-[calc(100vh-52px)]">
      <div className="w-80 p-4 space-y-3 overflow-y-auto bg-gray-50 border-r">
        <h2 className="font-bold text-lg">Route Finder</h2>

        <AddressInput
          label="From"
          placeholder="Search origin address..."
          markerColor="#22c55e"
          value={originText}
          onSelect={(lat, lon, name) => {
            setOrigin({ lat, lon });
            setOriginText(name);
          }}
        />

        <div className="flex justify-center">
          <button
            onClick={handleSwap}
            disabled={!origin && !destination}
            title="Swap origin and destination"
            className="text-gray-500 hover:text-blue-600 disabled:opacity-30 transition-colors"
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M6 4L6 16M6 16L3 13M6 16L9 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M14 16L14 4M14 4L11 7M14 4L17 7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </button>
        </div>

        <AddressInput
          label="To"
          placeholder="Search destination address..."
          markerColor="#ef4444"
          value={destText}
          onSelect={(lat, lon, name) => {
            setDestination({ lat, lon });
            setDestText(name);
          }}
        />

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
        {origin && <Marker position={[origin.lat, origin.lon]} icon={originIcon} />}
        {destination && <Marker position={[destination.lat, destination.lon]} icon={destIcon} />}
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
