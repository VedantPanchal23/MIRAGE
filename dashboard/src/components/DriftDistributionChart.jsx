import React, { useState } from "react";
import { BarChart2, Table, Eye, EyeOff } from "lucide-react";

/**
 * 10 Uniform probability bins across [0.0, 1.0] for HRS distribution comparison.
 */
const BINS = [
  { index: 0, label: "0.0 - 0.1", min: 0.0, max: 0.1 },
  { index: 1, label: "0.1 - 0.2", min: 0.1, max: 0.2 },
  { index: 2, label: "0.2 - 0.3", min: 0.2, max: 0.3 },
  { index: 3, label: "0.3 - 0.4", min: 0.3, max: 0.4 },
  { index: 4, label: "0.4 - 0.5", min: 0.4, max: 0.5 },
  { index: 5, label: "0.5 - 0.6", min: 0.5, max: 0.6 },
  { index: 6, label: "0.6 - 0.7", min: 0.6, max: 0.7 },
  { index: 7, label: "0.7 - 0.8", min: 0.7, max: 0.8 },
  { index: 8, label: "0.8 - 0.9", min: 0.8, max: 0.9 },
  { index: 9, label: "0.9 - 1.0", min: 0.9, max: 1.0 },
];

/**
 * DriftDistributionChart Component
 *
 * Visualizes 10-bin probability distribution comparison between baseline reference
 * and current production samples. Includes paired visual bars with accessible styling
 * (not relying solely on color) and a semantic HTML data table.
 *
 * @param {object} props
 * @param {number[]} [props.baselineProportions=[]] - Array of 10 baseline bin proportions (sums to 1.0)
 * @param {number[]} [props.currentProportions=[]] - Array of 10 current bin proportions (sums to 1.0)
 */
export function DriftDistributionChart({
  baselineProportions = [],
  currentProportions = [],
}) {
  const [showTable, setShowTable] = useState(true);

  // Compute maximum proportion across both distributions for visual scale normalization
  const maxProportion = Math.max(
    ...(baselineProportions.length ? baselineProportions : [0]),
    ...(currentProportions.length ? currentProportions : [0]),
    0.05
  );

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-lg space-y-5">
      {/* Header with Title and Table Toggle */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center space-x-2.5">
          <div className="p-2 rounded-lg bg-sky-500/10 border border-sky-500/20 text-sky-400">
            <BarChart2 className="w-4 h-4" aria-hidden="true" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white">
              Baseline vs. Current HRS Distribution
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              10-bin probability density comparison across [0.0, 1.0] risk range
            </p>
          </div>
        </div>

        {/* Legend & Toggle Button */}
        <div className="flex items-center space-x-4">
          <div className="flex items-center space-x-3 text-xs">
            <div className="flex items-center space-x-1.5">
              <span
                className="w-3 h-3 rounded-sm bg-indigo-950 border border-indigo-500/60"
                aria-hidden="true"
              />
              <span className="text-slate-300 font-medium">Baseline (Ref)</span>
            </div>
            <div className="flex items-center space-x-1.5">
              <span
                className="w-3 h-3 rounded-sm bg-sky-500 border border-sky-400"
                aria-hidden="true"
              />
              <span className="text-slate-300 font-medium">Current (Observed)</span>
            </div>
          </div>

          <button
            type="button"
            onClick={() => setShowTable((prev) => !prev)}
            aria-expanded={showTable}
            aria-controls="distribution-table-section"
            className="flex items-center space-x-1 px-2.5 py-1 text-xs font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 rounded-md border border-slate-700 transition focus:outline-none focus:ring-2 focus:ring-sky-500"
          >
            <Table className="w-3.5 h-3.5" aria-hidden="true" />
            <span>{showTable ? "Hide Table" : "Show Table"}</span>
          </button>
        </div>
      </div>

      {/* Visual Dual-Bar Histogram */}
      <div
        className="space-y-3 pt-2"
        role="region"
        aria-label="Distribution comparison visual bars"
      >
        {BINS.map((bin) => {
          const baseProp = baselineProportions[bin.index] ?? 0;
          const currProp = currentProportions[bin.index] ?? 0;
          const basePct = (baseProp * 100).toFixed(1);
          const currPct = (currProp * 100).toFixed(1);
          const delta = currProp - baseProp;
          const deltaPct = (delta * 100).toFixed(1);

          const baseBarWidth = `${Math.max(2, (baseProp / maxProportion) * 100)}%`;
          const currBarWidth = `${Math.max(2, (currProp / maxProportion) * 100)}%`;

          return (
            <div
              key={bin.index}
              className="bg-slate-950/60 border border-slate-800/80 rounded-lg p-3 hover:border-slate-700 transition"
            >
              <div className="flex items-center justify-between text-xs mb-2">
                <span className="font-mono font-semibold text-slate-200">
                  Bin [{bin.label}]
                </span>
                <div className="flex items-center space-x-3 text-[11px] font-mono">
                  <span className="text-indigo-300">Base: {basePct}%</span>
                  <span className="text-sky-300">Curr: {currPct}%</span>
                  <span
                    className={`px-1.5 py-0.2 rounded font-semibold ${
                      Math.abs(delta) < 0.005
                        ? "text-slate-400 bg-slate-800"
                        : delta > 0
                        ? "text-amber-400 bg-amber-950/80 border border-amber-800/60"
                        : "text-emerald-400 bg-emerald-950/80 border border-emerald-800/60"
                    }`}
                  >
                    {delta > 0 ? `+${deltaPct}%` : `${deltaPct}%`}
                  </span>
                </div>
              </div>

              {/* Paired Visual Bars */}
              <div className="space-y-1.5">
                {/* Baseline Bar (Patterned / Outlined Indigo) */}
                <div className="h-2 w-full bg-slate-900 rounded-full overflow-hidden">
                  <div
                    style={{ width: baseBarWidth }}
                    className="h-full bg-indigo-600/80 border-r-2 border-indigo-400 rounded-full transition-all duration-300"
                    title={`Baseline: ${basePct}%`}
                  />
                </div>

                {/* Current Bar (Solid Sky Blue) */}
                <div className="h-2 w-full bg-slate-900 rounded-full overflow-hidden">
                  <div
                    style={{ width: currBarWidth }}
                    className="h-full bg-sky-500 border-r-2 border-sky-300 rounded-full transition-all duration-300 shadow-sm"
                    title={`Current: ${currPct}%`}
                  />
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Accessible Data Table */}
      {showTable && (
        <div
          id="distribution-table-section"
          className="mt-4 pt-4 border-t border-slate-800 overflow-x-auto"
        >
          <table className="w-full text-left text-xs text-slate-300 font-sans border-collapse">
            <caption className="text-left text-xs font-semibold text-slate-400 mb-2 sr-only">
              Baseline vs Current Probability Distribution by Bins
            </caption>
            <thead>
              <tr className="border-b border-slate-800 text-[11px] font-mono text-slate-400 uppercase tracking-wider bg-slate-950/80">
                <th scope="col" className="py-2.5 px-3">
                  HRS Bin Range
                </th>
                <th scope="col" className="py-2.5 px-3 text-right">
                  Baseline Proportion
                </th>
                <th scope="col" className="py-2.5 px-3 text-right">
                  Current Proportion
                </th>
                <th scope="col" className="py-2.5 px-3 text-right">
                  Shift Delta (Obs - Ref)
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-mono">
              {BINS.map((bin) => {
                const baseProp = baselineProportions[bin.index] ?? 0;
                const currProp = currentProportions[bin.index] ?? 0;
                const delta = currProp - baseProp;

                return (
                  <tr key={bin.index} className="hover:bg-slate-800/30 transition">
                    <td className="py-2 px-3 font-semibold text-slate-200">
                      [{bin.label}]
                    </td>
                    <td className="py-2 px-3 text-right text-indigo-300">
                      {(baseProp * 100).toFixed(2)}%
                    </td>
                    <td className="py-2 px-3 text-right text-sky-300 font-bold">
                      {(currProp * 100).toFixed(2)}%
                    </td>
                    <td
                      className={`py-2 px-3 text-right font-semibold ${
                        Math.abs(delta) < 0.005
                          ? "text-slate-400"
                          : delta > 0
                          ? "text-amber-400"
                          : "text-emerald-400"
                      }`}
                    >
                      {delta > 0
                        ? `+${(delta * 100).toFixed(2)}%`
                        : `${(delta * 100).toFixed(2)}%`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default DriftDistributionChart;
