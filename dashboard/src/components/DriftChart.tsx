import React from "react";
import { DriftReport } from "../types";

interface DriftChartProps {
  drift: DriftReport;
}

export const DriftChart: React.FC<DriftChartProps> = ({ drift }) => {
  const points = drift.timeseries || [];
  const maxScore = 0.50; // max Y on scale
  const height = 140;
  const width = 500;
  const padding = 20;

  const getCoordinates = () => {
    if (points.length < 2) return "";
    return points
      .map((p, i) => {
        const x = padding + (i / (points.length - 1)) * (width - 2 * padding);
        const y = height - padding - (p.mean_hrs / maxScore) * (height - 2 * padding);
        return `${x},${y}`;
      })
      .join(" ");
  };

  const getAreaCoordinates = () => {
    if (points.length < 2) return "";
    const coords = points.map((p, i) => {
      const x = padding + (i / (points.length - 1)) * (width - 2 * padding);
      const y = height - padding - (p.mean_hrs / maxScore) * (height - 2 * padding);
      return `${x},${y}`;
    });
    const firstX = padding;
    const lastX = width - padding;
    const bottomY = height - padding;
    return `${coords.join(" ")} ${lastX},${bottomY} ${firstX},${bottomY}`;
  };

  const statusColors = {
    STABLE: { badge: "bg-emerald-950 text-emerald-400 border-emerald-800", text: "text-emerald-400" },
    MODERATE_DRIFT: { badge: "bg-amber-950 text-amber-400 border-amber-800", text: "text-amber-400" },
    SIGNIFICANT_DRIFT: { badge: "bg-rose-950 text-rose-400 border-rose-800", text: "text-rose-400" },
  }[drift.psi_status] || { badge: "bg-emerald-950 text-emerald-400 border-emerald-800", text: "text-emerald-400" };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-lg">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold text-slate-200">Longitudinal Distribution Drift (PSI)</h3>
          <p className="text-xs text-slate-400 mt-0.5">
            Population Stability Index tracking 30-day baseline vs current window
          </p>
        </div>

        <div className="flex items-center space-x-3">
          <div className="text-right">
            <div className="text-xs font-mono font-bold text-slate-200">
              PSI = {drift.psi.toFixed(4)}
            </div>
            <div className="text-[10px] text-slate-400">KS p = {drift.ks_p_value.toFixed(3)}</div>
          </div>
          <span className={`text-xs px-2.5 py-1 rounded-md font-semibold border ${statusColors.badge}`}>
            {drift.psi_status}
          </span>
        </div>
      </div>

      <div className="mt-4 bg-slate-950 rounded-lg p-4 border border-slate-800/80">
        <div className="flex justify-between text-[11px] text-slate-400 font-mono mb-2">
          <span>Daily Mean Calibrated HRS (Past 30 Days)</span>
          <span>Baseline Reference: 0.12 HRS</span>
        </div>

        <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-36 overflow-visible">
          <defs>
            <linearGradient id="driftAreaGrad" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.3" />
              <stop offset="100%" stopColor="#38bdf8" stopOpacity="0.0" />
            </linearGradient>
          </defs>

          {/* Grid lines */}
          <line x1={padding} y1={padding} x2={width - padding} y2={padding} stroke="#334155" strokeDasharray="3 3" />
          <line x1={padding} y1={height / 2} x2={width - padding} y2={height / 2} stroke="#334155" strokeDasharray="3 3" />
          <line x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} stroke="#475569" />

          {/* Area Fill */}
          {points.length >= 2 && (
            <polygon points={getAreaCoordinates()} fill="url(#driftAreaGrad)" />
          )}

          {/* Data Polyline */}
          {points.length >= 2 && (
            <polyline
              fill="none"
              stroke="#38bdf8"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              points={getCoordinates()}
            />
          )}

          {/* Points */}
          {points.map((p, i) => {
            const x = padding + (i / (points.length - 1)) * (width - 2 * padding);
            const y = height - padding - (p.mean_hrs / maxScore) * (height - 2 * padding);
            return (
              <circle
                key={p.date}
                cx={x}
                cy={y}
                r="3"
                className="fill-sky-400 stroke-slate-950 stroke-2 hover:r-5 transition-all"
              >
                <title>{`${p.date}: ${p.mean_hrs.toFixed(3)} HRS (${p.sample_count} reqs)`}</title>
              </circle>
            );
          })}
        </svg>

        <div className="flex justify-between text-[10px] text-slate-500 mt-2 font-mono">
          <span>{points[0]?.date || "Day -30"}</span>
          <span>{points[Math.floor(points.length / 2)]?.date || "Day -15"}</span>
          <span>{points[points.length - 1]?.date || "Today"}</span>
        </div>
      </div>
    </div>
  );
};
