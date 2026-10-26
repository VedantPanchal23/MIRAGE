import React, { useEffect, useState, useCallback, useContext } from "react";
import {
  Activity,
  ShieldCheck,
  AlertTriangle,
  RotateCcw,
  AlertCircle,
  Database,
  BarChart2,
  RefreshCw,
} from "lucide-react";
import { getDashboardStats, getHealth } from "../api";
import { MetricCard } from "../components/MetricCard";
import { CircuitBreakerStatus } from "../components/CircuitBreakerStatus";
import { AuthContext } from "../context/AuthContext";

/**
 * Overview View for Executive & Operational Telemetry.
 *
 * Implements PRD FR-DFT-01 and Technical Architecture §8.2:
 * - Uses the authoritative centralized API client (`getDashboardStats`, `getHealth`).
 * - Strictly respects the `/v1/dashboard/stats` backend schema.
 * - Handles Loading, Error, Empty, and Success states cleanly with accessible ARIA semantics.
 */
export function OverviewView({ isRefreshing, onDataLoaded }) {
  const auth = useContext(AuthContext);
  const [stats, setStats] = useState(null);
  const [circuits, setCircuits] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchOverviewData = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      // 1. Fetch dashboard stats from centralized API client
      const statsData = await getDashboardStats();
      setStats(statsData);

      // 2. Fetch health & circuit breaker status
      try {
        const healthData = await getHealth();
        if (healthData && (healthData.circuits || healthData.circuit_breakers)) {
          setCircuits(healthData.circuits || healthData.circuit_breakers);
        }
      } catch {
        // Circuit breaker data is secondary; do not fail the overview view if health probe fails
      }

      if (onDataLoaded) {
        onDataLoaded(new Date().toLocaleTimeString());
      }
    } catch (err) {
      setError({
        message: err.message || "Failed to load dashboard overview data.",
        code: err.code || "LOAD_ERROR",
        traceId: err.traceId || null,
        status: err.status || 500,
      });
    } finally {
      setLoading(false);
    }
  }, [onDataLoaded]);

  useEffect(() => {
    if (auth?.isAuthenticated) {
      fetchOverviewData();
    }
  }, [auth?.isAuthenticated, fetchOverviewData]);

  // Synchronize when parent triggers a global refresh
  useEffect(() => {
    if (isRefreshing && auth?.isAuthenticated) {
      fetchOverviewData();
    }
  }, [isRefreshing, auth?.isAuthenticated, fetchOverviewData]);

  // 1. LOADING STATE
  if (loading && !stats) {
    return (
      <section
        role="status"
        aria-live="polite"
        aria-label="Loading overview statistics"
        className="space-y-6"
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <div
              key={i}
              className="bg-white border border-slate-200 rounded-xl p-5 h-32 animate-pulse flex flex-col justify-between shadow-xs"
            >
              <div className="h-3 bg-slate-200 rounded w-1/3"></div>
              <div className="h-8 bg-slate-200 rounded w-1/2"></div>
              <div className="h-3 bg-slate-200 rounded w-2/3"></div>
            </div>
          ))}
        </div>
        <div className="bg-white border border-slate-200 rounded-xl p-8 h-48 animate-pulse flex items-center justify-center text-slate-500 text-xs shadow-xs">
          Loading system telemetry...
        </div>
      </section>
    );
  }

  // 2. ERROR STATE
  if (error) {
    return (
      <section
        role="alert"
        aria-labelledby="overview-error-title"
        className="bg-white border border-rose-200 rounded-xl p-6 shadow-xs space-y-4"
      >
        <div className="flex items-start space-x-3">
          <div className="w-10 h-10 rounded-lg bg-rose-50 border border-rose-200 flex items-center justify-center text-rose-600 flex-shrink-0">
            <AlertCircle className="w-5 h-5" aria-hidden="true" />
          </div>
          <div className="flex-1">
            <h2 id="overview-error-title" className="text-sm font-bold text-slate-900">
              Unable to Load Overview Telemetry
            </h2>
            <p className="text-xs text-slate-600 mt-1 leading-relaxed">{error.message}</p>
            <div className="flex flex-wrap items-center gap-3 mt-3 text-[11px] font-mono text-slate-600">
              <span className="bg-slate-100 px-2 py-0.5 rounded border border-slate-200">
                Code: {error.code}
              </span>
              {error.traceId && (
                <span className="bg-slate-100 px-2 py-0.5 rounded border border-slate-200">
                  Trace: {error.traceId}
                </span>
              )}
            </div>
          </div>
        </div>

        {(error.status === 401 || error.code === "UNAUTHORIZED" || error.code === "HTTP_401") && (
          <div className="mt-4 pt-3 border-t border-slate-200 bg-slate-50 rounded-lg p-4 space-y-2">
            <div className="flex items-center space-x-2">
              <ShieldCheck className="w-4 h-4 text-sky-600" />
              <span className="text-xs font-semibold text-slate-800">
                Authentication Required
              </span>
            </div>
            <p className="text-[11px] text-slate-500">
              Please authenticate using your authoritative Bearer JWT token via the Login button in the top navigation bar.
            </p>
          </div>
        )}

        <div className="flex justify-end pt-2 border-t border-slate-200">
          <button
            onClick={fetchOverviewData}
            aria-label="Retry loading overview statistics"
            className="flex items-center space-x-1.5 px-3.5 py-1.5 text-xs font-semibold text-slate-700 bg-white hover:bg-slate-50 rounded-lg border border-slate-200 shadow-xs transition focus:outline-none focus:ring-2 focus:ring-sky-500"
          >
            <RefreshCw className="w-3.5 h-3.5" aria-hidden="true" />
            <span>Retry</span>
          </button>
        </div>
      </section>
    );
  }

  // Extract stats values normalized from /v1/dashboard/stats contract
  const totalRequests = stats?.total_requests ?? stats?.total_verifications ?? 0;
  const avgHrs = typeof stats?.average_hrs === "number" ? stats.average_hrs : 0.0;
  const correctionRate = typeof stats?.correction_rate === "number" ? stats.correction_rate : 0.0;
  const tierCounts = stats?.tier_counts || stats?.tier_distribution || {
    LOW: 0,
    MEDIUM: 0,
    HIGH: 0,
    CRITICAL: 0,
  };
  const driftReport = stats?.drift_report || null;

  // 3. EMPTY STATE
  if (totalRequests === 0) {
    return (
      <section
        aria-labelledby="overview-empty-title"
        className="bg-white border border-slate-200 rounded-xl p-10 text-center shadow-xs space-y-4"
      >
        <div className="w-12 h-12 rounded-full bg-slate-100 border border-slate-200 flex items-center justify-center mx-auto text-slate-500">
          <Database className="w-6 h-6" aria-hidden="true" />
        </div>
        <div>
          <h2 id="overview-empty-title" className="text-base font-bold text-slate-900">
            No Verification Telemetry Available
          </h2>
          <p className="text-xs text-slate-500 mt-1 max-w-md mx-auto leading-relaxed">
            There are no recorded verification sessions for the authenticated tenant yet. Once requests are
            processed by the MIRAGE Gateway, longitudinal risk scores and distributions will appear here.
          </p>
        </div>
        <div className="pt-2">
          <button
            onClick={fetchOverviewData}
            className="inline-flex items-center space-x-1.5 px-3.5 py-1.5 text-xs font-medium text-slate-700 bg-white hover:bg-slate-50 rounded-lg border border-slate-200 shadow-xs transition focus:outline-none focus:ring-2 focus:ring-sky-500"
          >
            <RefreshCw className="w-3.5 h-3.5" aria-hidden="true" />
            <span>Check for Updates</span>
          </button>
        </div>
      </section>
    );
  }

  // Calculate tier percentages
  const lowCount = tierCounts.LOW || 0;
  const medCount = tierCounts.MEDIUM || 0;
  const highCount = tierCounts.HIGH || 0;
  const critCount = tierCounts.CRITICAL || 0;
  const critRate = totalRequests > 0 ? (critCount / totalRequests) * 100 : 0.0;

  // 4. SUCCESS DATA STATE
  return (
    <section aria-labelledby="overview-title" className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 id="overview-title" className="text-sm font-semibold uppercase tracking-wider text-slate-500">
          System Overview & Telemetry
        </h2>
        <span className="text-[11px] font-mono text-slate-500">
          Status: Operational
        </span>
      </div>

      {/* KPI Metrics Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          title="Total Verified Requests"
          value={totalRequests.toLocaleString()}
          subtitle="Processed via gateway"
          badge="Active"
          badgeColor="green"
          icon={<Activity className="w-4 h-4" />}
        />
        <MetricCard
          title="Calibrated Mean HRS"
          value={avgHrs.toFixed(3)}
          subtitle="Isotonic calibrated risk"
          badge={avgHrs < 0.1 ? "Low Risk" : avgHrs < 0.3 ? "Moderate" : "Elevated"}
          badgeColor={avgHrs < 0.1 ? "green" : avgHrs < 0.3 ? "yellow" : "red"}
          icon={<ShieldCheck className="w-4 h-4" />}
        />
        <MetricCard
          title="Critical Risk Rate"
          value={`${critRate.toFixed(1)}%`}
          subtitle={`${critCount.toLocaleString()} critical tier requests`}
          badge={critRate < 2.0 ? "Normal" : "Warning"}
          badgeColor={critRate < 2.0 ? "green" : "red"}
          icon={<AlertTriangle className="w-4 h-4" />}
        />
        <MetricCard
          title="Correction Loop Rate"
          value={`${(correctionRate * 100).toFixed(1)}%`}
          subtitle="Autonomous rewrites applied"
          badge="Adaptive"
          badgeColor="blue"
          icon={<RotateCcw className="w-4 h-4" />}
        />
      </div>

      {/* Risk Tier Distribution Card */}
      <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-xs space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <BarChart2 className="w-4 h-4 text-sky-600" aria-hidden="true" />
            <h3 className="text-sm font-bold text-slate-900">Risk Tier Distribution</h3>
          </div>
          <span className="text-xs text-slate-500 font-mono">
            {totalRequests.toLocaleString()} Total
          </span>
        </div>

        {/* Visual Multi-Segment Bar */}
        <div
          role="progressbar"
          aria-valuenow={totalRequests}
          aria-valuemin={0}
          aria-valuemax={totalRequests}
          aria-label="Risk tier proportions"
          className="h-3 w-full bg-slate-100 rounded-full overflow-hidden flex"
        >
          {lowCount > 0 && (
            <div
              style={{ width: `${(lowCount / totalRequests) * 100}%` }}
              className="bg-emerald-500 h-full"
              title={`LOW: ${lowCount} (${((lowCount / totalRequests) * 100).toFixed(1)}%)`}
            />
          )}
          {medCount > 0 && (
            <div
              style={{ width: `${(medCount / totalRequests) * 100}%` }}
              className="bg-amber-500 h-full"
              title={`MEDIUM: ${medCount} (${((medCount / totalRequests) * 100).toFixed(1)}%)`}
            />
          )}
          {highCount > 0 && (
            <div
              style={{ width: `${(highCount / totalRequests) * 100}%` }}
              className="bg-rose-500 h-full"
              title={`HIGH: ${highCount} (${((highCount / totalRequests) * 100).toFixed(1)}%)`}
            />
          )}
          {critCount > 0 && (
            <div
              style={{ width: `${(critCount / totalRequests) * 100}%` }}
              className="bg-purple-500 h-full"
              title={`CRITICAL: ${critCount} (${((critCount / totalRequests) * 100).toFixed(1)}%)`}
            />
          )}
        </div>

        {/* Tier Grid Breakdown */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2">
          <div className="bg-slate-50 border border-slate-200 rounded-lg p-3">
            <div className="flex items-center space-x-2">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500"></span>
              <span className="text-xs font-semibold text-slate-700">LOW</span>
            </div>
            <div className="text-lg font-bold text-slate-900 mt-1 font-mono">{lowCount.toLocaleString()}</div>
            <div className="text-[11px] text-slate-500">
              {totalRequests > 0 ? ((lowCount / totalRequests) * 100).toFixed(1) : 0}%
            </div>
          </div>

          <div className="bg-slate-50 border border-slate-200 rounded-lg p-3">
            <div className="flex items-center space-x-2">
              <span className="w-2.5 h-2.5 rounded-full bg-amber-500"></span>
              <span className="text-xs font-semibold text-slate-700">MEDIUM</span>
            </div>
            <div className="text-lg font-bold text-slate-900 mt-1 font-mono">{medCount.toLocaleString()}</div>
            <div className="text-[11px] text-slate-500">
              {totalRequests > 0 ? ((medCount / totalRequests) * 100).toFixed(1) : 0}%
            </div>
          </div>

          <div className="bg-slate-50 border border-slate-200 rounded-lg p-3">
            <div className="flex items-center space-x-2">
              <span className="w-2.5 h-2.5 rounded-full bg-rose-500"></span>
              <span className="text-xs font-semibold text-slate-700">HIGH</span>
            </div>
            <div className="text-lg font-bold text-slate-900 mt-1 font-mono">{highCount.toLocaleString()}</div>
            <div className="text-[11px] text-slate-500">
              {totalRequests > 0 ? ((highCount / totalRequests) * 100).toFixed(1) : 0}%
            </div>
          </div>

          <div className="bg-slate-50 border border-slate-200 rounded-lg p-3">
            <div className="flex items-center space-x-2">
              <span className="w-2.5 h-2.5 rounded-full bg-purple-500"></span>
              <span className="text-xs font-semibold text-slate-700">CRITICAL</span>
            </div>
            <div className="text-lg font-bold text-slate-900 mt-1 font-mono">{critCount.toLocaleString()}</div>
            <div className="text-[11px] text-slate-500">
              {totalRequests > 0 ? ((critCount / totalRequests) * 100).toFixed(1) : 0}%
            </div>
          </div>
        </div>
      </div>

      {/* Drift Status Banner if available */}
      {driftReport && (
        <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="flex items-center space-x-2">
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                Longitudinal Drift Status
              </span>
              <span
                className={`text-[10px] font-mono px-2 py-0.5 rounded-full border font-bold ${
                  driftReport.status === "STABLE"
                    ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                    : "bg-amber-50 text-amber-800 border-amber-200"
                }`}
              >
                {driftReport.status || "STABLE"}
              </span>
            </div>
            <p className="text-xs text-slate-700 mt-1">
              Population Stability Index: <span className="font-mono font-bold text-slate-900">{typeof driftReport.psi === "number" ? driftReport.psi.toFixed(4) : "0.0000"}</span>
              {typeof driftReport.ks_pvalue === "number" && (
                <span className="text-slate-500 ml-3">
                  (KS p-value: {driftReport.ks_pvalue.toFixed(3)})
                </span>
              )}
            </p>
          </div>

          {driftReport.alert_triggered && (
            <div className="flex items-center space-x-1.5 text-xs text-rose-700 bg-rose-50 border border-rose-200 px-3 py-1.5 rounded-lg">
              <AlertTriangle className="w-4 h-4 text-rose-600" aria-hidden="true" />
              <span>{driftReport.alert_reason || "Drift alert threshold exceeded"}</span>
            </div>
          )}
        </div>
      )}

      {/* Circuit Breakers Health Grid (if available) */}
      {circuits && Object.keys(circuits).length > 0 && (
        <CircuitBreakerStatus circuits={circuits} />
      )}
    </section>
  );
}

export default OverviewView;
