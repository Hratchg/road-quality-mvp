import { Routes, Route, Link } from "react-router-dom";
import MapView from "./pages/MapView";
import RouteFinder from "./pages/RouteFinder";

export default function App() {
  return (
    <div className="min-h-screen bg-gray-100">
      <nav className="bg-white shadow px-6 py-3 flex gap-6">
        <Link to="/" className="font-semibold text-blue-600 hover:underline">
          Map View
        </Link>
        <Link to="/route" className="font-semibold text-blue-600 hover:underline">
          Route Finder
        </Link>
      </nav>
      <Routes>
        <Route path="/" element={<MapView />} />
        <Route path="/route" element={<RouteFinder />} />
      </Routes>
    </div>
  );
}
