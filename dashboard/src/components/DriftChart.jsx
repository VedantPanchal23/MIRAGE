import React, { useState } from "react";
import { LineChart, Calendar, Table } from "lucide-react";

/**
 * Standard selectable time-series windows in days.
 */
const WINDOW_OPTIONS = [
  { label: "7 Days", value: 7 },
  { label: "30 Days", value: 30 },
  { label: "90 Days", value: 90 },
];

/**
 * DriftChart Component
 *
 * Renders longitudinal daily mean HRS time-series with interactive window selection,
 * lightweight SVG area/line visualization, and an accessible tabular data view.
 *
 * @param {object} props
 * @param {Array<object>} [props.timeSeries=[]] - Array of daily points: { date, mean_hrs/average_hrs, sample_count/request_count, critical_count }
 * @param {number} [props.days=30] - Currently selected day window (7, 30, 90)
 * @param {Function} [props.onDaysChange] - Callback when day window is changed: (days: number) => void
 * @param {number} [props.baselineMean=0.084] - Reference baseline mean HRS
 * @param {object} [props.drift={}] - Optional legacy container for backward compatibility
 */
export function DriftChart({
  timeSeries = [],
  days = 30,
  onDaysChange,
  baselineMean = 0.084,
  drift = {},
}) {
  const [showTable, setShowTable] = useState(false);

  // Normalize points from authoritative time_series or backward-compatible drift.timeseries
  const rawPoints =
    timeSeries && timeSeries.length > 0
      ? timeSeries
      : drift.timeseries || drift.time_series || [];

  const points = rawPoints.map((p) => ({
    date: p.date || p.day || "Unknown",
    hrs:
      typeof p.mean_hrs === "number"
        ? p.mean_hrs
        : typeof p.average_hrs === "number"
        ? p.average_hrs
        : 0.0,
    count: p.sample_count ?? p.request_count ?? 0,
    critical: p.critical_count ?? 0,
  }));

  // Dimensions & coordinate mapping
  const width = 600;
  const height = 160;
  const paddingX = 40;
  const paddingTop = 20;
  const paddingBottom = 30;

  // Determine dynamic max HRS scale
  const maxHrsInPoints = Math.max(...points.map((p) => p.hrs), baselineMean, 0.20);
  const maxScore = Math.min(1.0, Math.ceil(maxHrsInPoints * 10) / 10 + 0.05);

  const getX = (index) => {
    if (points.length <= 1) return width / 2;
    return (
      paddingX + (index / (points.length - 1)) * (width - 2 * paddingX)
    );
  };

  const getY = (val) => {
    const clamped = Math.min(maxScore, Math.max(0, val));
    return (
      height -
      paddingBottom -
      (clamped / maxScore) * (height - paddingTop - paddingBottom)
    );
  };

  const getCoordinates = () => {
    if (points.length < 2) return "";
    return points.map((p, i) => `${getX(i).toFixed(1)},${getY(p.hrs).toFixed(1)}`).join(" ");
  };

  const getAreaCoordinates = () => {
    if (points.length < 2) return "";
    const coords = points.map((p, i) => `${getX(i).toFixed(1)},${getY(p.hrs).toFixed(1)}`);
    const firstX = getX(0).toFixed(1);
    const lastX = getX(points.length - 1).toFixed(1);
    const bottomY = (height - paddingBottom).toFixed(1);
    return `${coords.join(" ")} ${lastX},${bottomY} ${firstX},${bottomY}`;
  };

  const baselineY = getY(baselineMean);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-lg space-y-5">
      {/* Header and Controls */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center space-x-2.5">
          <div className="p-2 rounded-lg bg-sky-500/10 border border-sky-500/20 text-sky-400">
            <LineChart className="w-4 h-4" aria-hidden="true" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white">
              Longitudinal HRS Drift Trend
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              Daily mean calibrated Hallucination Risk Score over rolling time window
            </p>
          </div>
        </div>

        {/* Window Selector & Table Toggle */}
        <div className="flex flex-wrap items-center gap-2">
          {onDaysChange && (
            <div
              role="group"
              aria-label="Time window selection"
              className="flex items-center bg-slate-950 p-1 rounded-lg border border-slate-800"
            >
              {WINDOW_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => onDaysChange(opt.value)}
                  aria-pressed={days === opt.value}
                  className={`px-2.5 py-1 text-xs rounded-md font-medium transition ${
                    days === opt.value
                      ? "bg-sky-600 text-white font-semibold shadow-sm"
                      : "text-slate-400 hover:text-slate-200 hover:bg-slate-900"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          )}

          <button
            type="button"
            onClick={() => setShowTable((prev) => !prev)}
            aria-expanded={showTable}
            aria-controls="timeseries-table-section"
            className="flex items-center space-x-1 px-2.5 py-1 text-xs font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 rounded-md border border-slate-700 transition focus:outline-none focus:ring-2 focus:ring-sky-500"
          >
            <Table className="w-3.5 h-3.5" aria-hidden="true" />
            <span>{showTable ? "Hide Table" : "Show Table"}</span>
          </button>
        </div>
      </div>

      {/* SVG Chart Container */}
      <div className="bg-slate-950 rounded-xl p-4 border border-slate-800/80">
        <div className="flex justify-between items-center text-[11px] text-slate-400 font-mono mb-2 px-1">
          <span>Observed Window: Past {days} Days ({points.length} data points)</span>
          <span className="text-indigo-400 font-semibold">
            Baseline Reference: {baselineMean.toFixed(4)} HRS
          </span>
        </div>

        {points.length === 0 ? (
          <div className="h-40 flex items-center justify-center text-xs text-slate-500 font-mono">
            No time series data points recorded for this window.
          </div>
        ) : (
          <div className="relative w-full overflow-hidden">
            <svg
              viewBox={`0 0 ${width} ${height}`}
              className="w-full h-44 overflow-visible"
              role="img"
              aria-label={`Longitudinal HRS time series graph for past ${days} days`}
            >
              <defs>
                <linearGradient id="driftAreaGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                  <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.35" />
                  <stop offset="100%" stopColor="#38bdf8" stopOpacity="0.0" />
                </linearGradient>
              </defs>

              {/* Grid Lines & Y-Axis Labels */}
              <line
                x1={paddingX}
                y1={paddingTop}
                x2={width - paddingX}
                y2={paddingTop}
                stroke="#334155"
                strokeDasharray="3 3"
              />
              <text
                x={paddingX - 8}
                y={paddingTop + 3}
                fill="#64748b"
                fontSize="9"
                fontFamily="monospace"
                textAnchor="end"
              >
                {maxScore.toFixed(2)}
              </text>

              <line
                x1={paddingX}
                y1={getY(maxScore / 2)}
                x2={width - paddingX}
                y2={getY(maxScore / 2)}
                stroke="#334155"
                strokeDasharray="3 3"
              />
              <text
                x={paddingX - 8}
                y={getY(maxScore / 2) + 3}
                fill="#64748b"
                fontSize="9"
                fontFamily="monospace"
                textAnchor="end"
              >
                {(maxScore / 2).toFixed(2)}
              </text>

              <line
                x1={paddingX}
                y1={height - paddingBottom}
                x2={width - paddingX}
                y2={height - paddingBottom}
                stroke="#475569"
              />
              <text
                x={paddingX - 8}
                y={height - paddingBottom + 3}
                fill="#64748b"
                fontSize="9"
                fontFamily="monospace"
                textAnchor="end"
              >
                0.00
              </text>

              {/* Baseline Reference Horizontal Line */}
              <line
                x1={paddingX}
                y1={baselineY}
                x2={width - paddingX}
                y2={baselineY}
                stroke="#818cf8"
                strokeWidth="1.5"
                strokeDasharray="4 4"
              />

              {/* Area Fill */}
              {points.length >= 2 && (
                <polygon points={getAreaCoordinates()} fill="url(#driftAreaGradient)" />
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

              {/* Data Points (Circles with accessible titles) */}
              {points.map((p, i) => {
                const cx = getX(i);
                const cy = getY(p.hrs);
                return (
                  <circle
                    key={p.date || i}
                    cx={cx}
                    cy={cy}
                    r={points.length > 40 ? 2.5 : 3.5}
                    className="fill-sky-400 stroke-slate-950 stroke-2 hover:r-5 transition-all cursor-pointer"
                  >
                    <title>
                      {`${p.date}: ${p.hrs.toFixed(4)} Mean HRS (${p.count} requests${
                        p.critical > 0 ? `, ${p.critical} critical` : ""
                      })`}
                    </title>
                  </circle>
                );
              })}
            </svg>

            {/* X-Axis Date Labels */}
            <div className="flex justify-between text-[10px] text-slate-500 font-mono mt-1 px-4">
              <span>{points[0]?.date || "Start"}</span>
              {points.length > 2 && (
                <span>{points[Math.floor(points.length / 2)]?.date}</span>
              )}
              <span>{points[points.length - 1]?.date || "Latest"}</span>
            </div>
          </div>
        )}
      </div>

      {/* Accessible Data Table View */}
      {showTable && points.length > 0 && (
        <div
          id="timeseries-table-section"
          className="mt-4 pt-4 border-t border-slate-800 overflow-x-auto max-h-64"
        >
          <table className="w-full text-left text-xs text-slate-300 font-sans border-collapse">
            <caption className="text-left text-xs font-semibold text-slate-400 mb-2 sr-only">
              Daily Longitudinal Hallucination Risk Scores
            </caption>
            <thead className="sticky top-0 bg-slate-950">
              <tr className="border-b border-slate-800 text-[11px] font-mono text-slate-400 uppercase tracking-wider">
                <th scope="col" className="py-2 px-3">
                  Date
                </th>
                <th scope="col" className="py-2 px-3 text-right">
                  Mean HRS
                </th>
                <th scope="col" className="py-2 px-3 text-right">
                  Sample Requests
                </th>
                <th scope="col" className="py-2 px-3 text-right">
                  Critical Count
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-mono">
              {points.map((p) => (
                <tr key={p.date} className="hover:bg-slate-800/30 transition">
                  <td className="py-1.5 px-3 font-semibold text-slate-200">
                    {p.date}
                  </td>
                  <td className="py-1.5 px-3 text-right text-sky-300 font-bold">
                    {p.hrs.toFixed(4)}
                  </td>
                  <td className="py-1.5 px-3 text-right text-slate-300">
                    {p.count.toLocaleString()}
                  </td>
                  <td
                    className={`py-1.5 px-3 text-right font-semibold ${
                      p.critical > 0 ? "text-rose-400" : "text-slate-500"
                    }`}
                  >
                    {p.critical.toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default DriftChart;
