interface RouteInfo {
  total_time_s: number;
  total_cost: number;
  avg_iri_norm?: number;
  total_moderate_score?: number;
  total_severe_score?: number;
}

interface Props {
  fastest: RouteInfo;
  best: RouteInfo;
  warning?: string | null;
}

export default function RouteResults({ fastest, best, warning }: Props) {
  const fmt = (s: number) => `${Math.round(s / 60)} min`;

  return (
    <div className="bg-white rounded-lg shadow p-4 space-y-3">
      {warning && (
        <div className="bg-yellow-100 border-l-4 border-yellow-500 text-yellow-700 p-2 text-sm">
          {warning}
        </div>
      )}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <h4 className="font-bold text-blue-600 text-sm">Fastest Route</h4>
          <p className="text-sm">Time: {fmt(fastest.total_time_s)}</p>
          <p className="text-sm">Cost: {fastest.total_cost.toFixed(1)}</p>
        </div>
        <div>
          <h4 className="font-bold text-green-600 text-sm">Best Route</h4>
          <p className="text-sm">Time: {fmt(best.total_time_s)}</p>
          <p className="text-sm">Cost: {best.total_cost.toFixed(1)}</p>
          {best.avg_iri_norm != null && (
            <p className="text-sm">Avg IRI: {best.avg_iri_norm.toFixed(2)}</p>
          )}
          {best.total_moderate_score != null && (
            <p className="text-sm">Moderate: {best.total_moderate_score.toFixed(1)}</p>
          )}
          {best.total_severe_score != null && (
            <p className="text-sm">Severe: {best.total_severe_score.toFixed(1)}</p>
          )}
        </div>
      </div>
    </div>
  );
}
