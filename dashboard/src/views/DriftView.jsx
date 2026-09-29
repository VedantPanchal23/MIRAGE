import React, { useEffect, useState, useCallback } from "react";
import {
  Activity,
  AlertTriangle,
  AlertCircle,
  ShieldCheck,
  Layers,
  RefreshCw,
  Database,
  Scale,
} from "lucide-react";
import { getDriftReport } from "../api";
import { MetricCard } from "../components/MetricCard";
import { DriftDistributionChart } from "../components/DriftDistributionChart";
import { DriftChart } from "../components/DriftChart";

/**
 * Longitudinal Drift View.
 *
 * Implements PRD FR-DFT-01, Technical Architecture §8.2, and P2.6 requirements:
 * - Uses authoritative centralized API client `getDriftReport({ days })`.
 * - Strictly respects the `/v1/drift` backend contract without client-supplied tenant override.
 * - Displays Population Stability Index (PSI), Two-Sample Kolmogorov-Smirnov (KS) telemetry,
 *   10-bin baseline vs current probability distribution comparison, and longitudinal time-series.
 * - Handles Loading, Error, Empty, and Success states with accessible ARIA semantics.
 *
 * @param {object} props
 * @param {boolean} [props.isRefreshing=false] - Global refresh signal from dashboard header
 * @param {Function} [props.onDataLoaded] - Callback with timestamp when data successfully loaded
 */
export function DriftView({ isRefreshing, onDataLoaded }) {
  const [days, setDays] = useState(30);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchDriftData = useCallback(
    async (daysWindow) => {
      setLoading(true);
      setError(null);

      try {
        // Call centralized API client without injecting tenant_id;
        // backend authoritatively derives tenant context strictly from the validated JWT.
        const result = await getDriftReport({ days: daysWindow });
        setData(result);

        if (onDataLoaded) {
          onDataLoaded(new Date().toLocaleTimeString());
        }
      } catch (err) {
        setError({
          message: err.message || "Failed to load drift analysis telemetry.",
          code: err.code || "LOAD_ERROR",
          traceId: err.traceId || null,
          status: err.status || 500,
        });
      } finally {
        setLoading(false);
      }
    },
    [onDataLoaded]
  );

  // Fetch on mount or when days window changes
  useEffect(() => {
    fetchDriftData(days);
  }, [days, fetchDriftData]);

  // Synchronize when parent header triggers a global refresh
  useEffect(() => {
    if (isRefreshing) {
      fetchDriftData(days);
    }
  }, [isRefreshing, days, fetchDriftData]);

  const handleDaysChange = (newDays) => {
    setDays(newDays);
  };

  // 1. LOADING STATE
  if (loading && !data) {
    return (
      <section
        role="status"
        aria-live="polite"
        aria-label="Loading drift analysis"
        className="space-y-6"
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <div
              key={i}
              className="bg-slate-900/60 border border-slate-800 rounded-xl p-5 h-32 animate-pulse flex flex-col justify-between"
            >
              <div className="h-3 bg-slate-800 rounded w-1/3"></div>
              <div className="h-8 bg-slate-800 rounded w-1/2"></div>
              <div className="h-3 bg-slate-800 rounded w-2/3"></div>
            </div>
          ))}
        </div>
        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-8 h-48 animate-pulse flex items-center justify-center text-slate-500 text-xs">
          Loading longitudinal drift metrics and distribution models...
        </div>
      </section>
    );
  }

  // 2. ERROR STATE
  if (error) {
    return (
      <section
        role="alert"
        aria-labelledby="drift-error-title"
        className="bg-slate-900 border border-rose-900/60 rounded-xl p-6 shadow-lg space-y-4"
      >
        <div className="flex items-start space-x-3">
          <div className="w-10 h-10 rounded-lg bg-rose-500/10 border border-rose-500/30 flex items-center justify-center text-rose-400 flex-shrink-0">
            <AlertCircle className="w-5 h-5" aria-hidden="true" />
          </div>
          <div className="flex-1">
            <h2 id="drift-error-title" className="text-sm font-bold text-white">
              Unable to Load Drift Telemetry
            </h2>
            <p className="text-xs text-slate-300 mt-1 leading-relaxed">
              {error.message}
            </p>
            <div className="flex flex-wrap items-center gap-3 mt-3 text-[11px] font-mono text-slate-400">
              <span className="bg-slate-950 px-2 py-0.5 rounded border border-slate-800">
                Code: {error.code}
              </span>
              {error.traceId && (
                <span className="bg-slate-950 px-2 py-0.5 rounded border border-slate-800">
                  Trace: {error.traceId}
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="flex justify-end pt-2 border-t border-slate-800">
          <button
            type="button"
            onClick={() => fetchDriftData(days)}
            aria-label="Retry loading drift analysis"
            className="flex items-center space-x-1.5 px-3 py-1.5 text-xs font-semibold text-white bg-slate-800 hover:bg-slate-700 rounded-lg border border-slate-700 transition focus:outline-none focus:ring-2 focus:ring-sky-500"
          >
            <RefreshCw className="w-3.5 h-3.5" aria-hidden="true" />
            <span>Retry</span>
          </button>
        </div>
      </section>
    );
  }

  // Extract and normalize values from /v1/drift contract
  const driftReport = data?.drift_report;
  const timeSeries = data?.time_series || [];

  const baselineCount = driftReport?.baseline_sample_count ?? 0;
  const currentCount = driftReport?.current_sample_count ?? 0;
  const baselineMean = driftReport?.baseline_mean_hrs ?? 0.0;
  const currentMean = driftReport?.current_mean_hrs ?? 0.0;
  const rolling7dDelta = driftReport?.rolling_7d_delta;
  const psi = driftReport?.psi ?? 0.0;
  const ksStat = driftReport?.ks_statistic ?? 0.0;
  const ksPval = driftReport?.ks_pvalue ?? 1.0;
  const alertTriggered = driftReport?.alert_triggered ?? false;
  const alertReason = driftReport?.alert_reason ?? null;
  const binBaseline = driftReport?.bin_proportions_baseline || [];
  const binCurrent = driftReport?.bin_proportions_current || [];

  // 3. EMPTY STATE
  if (
    !loading &&
    (!driftReport ||
      (baselineCount === 0 && currentCount === 0 && timeSeries.length === 0))
  ) {
    return (
      <section
        aria-labelledby="drift-empty-title"
        className="bg-slate-900 border border-slate-800 rounded-xl p-10 text-center shadow-lg space-y-4"
      >
        <div className="w-12 h-12 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center mx-auto text-slate-400">
          <Database className="w-6 h-6" aria-hidden="true" />
        </div>
        <div>
          <h2 id="drift-empty-title" className="text-base font-bold text-white">
            No Drift Telemetry Available
          </h2>
          <p className="text-xs text-slate-400 mt-1 max-w-md mx-auto leading-relaxed">
            There are no recorded drift metrics or baseline samples for the authenticated tenant yet. Once requests are processed by the MIRAGE Gateway, Population Stability Index (PSI) and longitudinal distributions will appear here.
          </p>
        </div>
        <div className="pt-2">
          <button
            type="button"
            onClick={() => fetchDriftData(days)}
            className="inline-flex items-center space-x-1.5 px-3.5 py-1.5 text-xs font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 rounded-lg border border-slate-700 transition focus:outline-none focus:ring-2 focus:ring-sky-500"
          >
            <RefreshCw className="w-3.5 h-3.5" aria-hidden="true" />
            <span>Check for Updates</span>
          </button>
        </div>
      </section>
    );
  }

  // Status mapping strictly adhering to backend semantics
  const rawStatus = (driftReport?.status || "stable").toLowerCase();
  const statusConfig = {
    stable: {
      label: "Stable (PSI < 0.10)",
      badge: "bg-emerald-950 text-emerald-400 border-emerald-800",
      cardBadge: "Stable",
      cardColor: "green",
    },
    moderate_drift: {
      label: "Moderate Drift (0.10 ≤ PSI < 0.20)",
      badge: "bg-amber-950 text-amber-400 border-amber-800",
      cardBadge: "Moderate Drift",
      cardColor: "yellow",
    },
    significant_drift: {
      label: "Significant Drift (PSI ≥ 0.20)",
      badge: "bg-rose-950 text-rose-400 border-rose-800",
      cardBadge: "Significant Drift",
      cardColor: "red",
    },
  }[rawStatus] || {
    label: "Stable (PSI < 0.10)",
    badge: "bg-emerald-950 text-emerald-400 border-emerald-800",
    cardBadge: "Stable",
    cardColor: "green",
  };

  // 4. SUCCESS STATE
  return (
    <section aria-labelledby="drift-title" className="space-y-6">
      {/* Title & Status Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2
            id="drift-title"
            className="text-base font-bold text-white tracking-tight"
          >
            Longitudinal Drift & Stability Analysis
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Statistical monitoring of Hallucination Risk Score distributions via Population Stability Index and Two-Sample KS tests.
          </p>
        </div>

        <div className="flex items-center space-x-2">
          <span
            className={`text-xs px-3 py-1 rounded-full font-semibold border ${statusConfig.badge}`}
          >
            {statusConfig.label}
          </span>
        </div>
      </div>

      {/* Active Operational Alert Banner */}
      {alertTriggered && (
        <div
          role="alert"
          aria-label="Active drift alert"
          className="bg-rose-950/60 border border-rose-800 rounded-xl p-4 flex items-start space-x-3 text-rose-300 shadow-md"
        >
          <AlertTriangle
            className="w-5 h-5 text-rose-400 flex-shrink-0 mt-0.5"
            aria-hidden="true"
          />
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider text-rose-300">
              Operational Drift Alert Triggered
            </h3>
            <p className="text-xs mt-1 text-rose-200">
              {alertReason ||
                "Longitudinal distribution shift exceeded predefined operational tolerance."}
            </p>
          </div>
        </div>
      )}

      {/* KPI Cards Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          title="Population Stability Index"
          value={psi.toFixed(4)}
          subtitle="Benchmark: < 0.10 Stable | ≥ 0.20 Significant"
          badge={statusConfig.cardBadge}
          badgeColor={statusConfig.cardColor}
          icon={<Scale className="w-4 h-4" />}
        />

        <MetricCard
          title="Two-Sample KS Test"
          value={`D = ${ksStat.toFixed(4)}`}
          subtitle={`p-value: ${ksPval.toFixed(4)} (${
            ksPval >= 0.05 ? "p ≥ 0.05 Consistent" : "p < 0.05 Shifted"
          })`}
          badge={ksPval >= 0.05 ? "Consistent (p ≥ 0.05)" : "Shifted (p < 0.05)"}
          badgeColor={ksPval >= 0.05 ? "green" : "red"}
          icon={<Activity className="w-4 h-4" />}
        />

        <MetricCard
          title="Calibrated Mean HRS"
          value={currentMean.toFixed(4)}
          subtitle={`Baseline: ${baselineMean.toFixed(4)} | 7d Delta: ${
            typeof rolling7dDelta === "number"
              ? rolling7dDelta >= 0
                ? `+${rolling7dDelta.toFixed(4)}`
                : rolling7dDelta.toFixed(4)
              : "N/A"
          }`}
          badge={
            typeof rolling7dDelta === "number" &&
            Math.abs(rolling7dDelta) >= 0.05
              ? "Elevated Delta"
              : "Within Norm"
          }
          badgeColor={
            typeof rolling7dDelta === "number" &&
            Math.abs(rolling7dDelta) >= 0.05
              ? "yellow"
              : "green"
          }
          icon={<ShieldCheck className="w-4 h-4" />}
        />

        <MetricCard
          title="Observed Production Samples"
          value={currentCount.toLocaleString()}
          subtitle={`Baseline Reference: ${baselineCount.toLocaleString()} samples`}
          badge={currentCount >= 100 ? "Adequate Sample" : "Low Sample"}
          badgeColor={currentCount >= 100 ? "green" : "yellow"}
          icon={<Layers className="w-4 h-4" />}
        />
      </div>

      {/* 10-Bin Distribution Comparison Component */}
      <DriftDistributionChart
        baselineProportions={binBaseline}
        currentProportions={binCurrent}
      />

      {/* Longitudinal Time Series Chart with Window Selector Component */}
      <DriftChart
        timeSeries={timeSeries}
        days={days}
        onDaysChange={handleDaysChange}
        baselineMean={baselineMean}
      />
    </section>
  );
}

export default DriftView;
