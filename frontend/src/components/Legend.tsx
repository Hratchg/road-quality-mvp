export default function Legend() {
  return (
    <div className="bg-white rounded-lg shadow p-3 w-48">
      <h4 className="font-bold text-xs uppercase text-gray-500 mb-2">Road Quality</h4>
      <div className="flex items-center gap-2 text-sm">
        <div className="w-4 h-3 rounded" style={{ background: "#22c55e" }} />
        <span>Good</span>
      </div>
      <div className="flex items-center gap-2 text-sm">
        <div className="w-4 h-3 rounded" style={{ background: "#eab308" }} />
        <span>Fair</span>
      </div>
      <div className="flex items-center gap-2 text-sm">
        <div className="w-4 h-3 rounded" style={{ background: "#ef4444" }} />
        <span>Poor</span>
      </div>
    </div>
  );
}
