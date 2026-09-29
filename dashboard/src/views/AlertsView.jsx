import React, { useState, useEffect, useCallback } from "react";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Clock,
  ShieldAlert,
  ShieldCheck,
  RefreshCw,
  Check,
  XCircle,
  Filter,
  Eye,
} from "lucide-react";
import { useAuth, PERMISSIONS } from "../context/AuthContext";
import { getAlerts, acknowledgeAlert } from "../api";

const STATUS_FILTERS = ["ALL", "ACTIVE", "ACKNOWLEDGED", "RESOLVED"];

/**
 * Format timestamp safely for presentation.
 */
function formatTimestamp(isoStr) {
  if (!isoStr) return "N/A";
  try {
    const d = new Date(isoStr);
    return isNaN(d.getTime()) ? isoStr : d.toLocaleString();
  } catch {
    return isoStr;
  }
}

/**
 * Severity badge styling helper.
 */
function getSeverityBadge(severity = "") {
  const sev = severity.toLowerCase();
  switch (sev) {
    case "critical":
      return "text-purple-400 bg-purple-950/80 border-purple-800";
    case "high":
      return "text-rose-400 bg-rose-950/80 border-rose-800";
    case "medium":
      return "text-amber-400 bg-amber-950/80 border-amber-800";
    case "low":
    default:
      return "text-sky-400 bg-sky-950/80 border-sky-800";
  }
}

/**
 * Lifecycle status badge styling helper.
 */
function getStatusBadge(status = "") {
  const st = status.toLowerCase();
  switch (st) {
    case "active":
      return "text-rose-400 bg-rose-950/80 border-rose-800";
    case "acknowledged":
      return "text-emerald-400 bg-emerald-950/80 border-emerald-800";
    case "resolved":
      return "text-slate-400 bg-slate-800 border-slate-700";
    default:
      return "text-slate-400 bg-slate-800 border-slate-700";
  }
}

/**
 * AlertsView Component (P2.8)
 *
 * Persisted Operator Alerts Console.
 *
 * Requirements:
 * - Consumes GET /v1/alerts and POST /v1/alerts/{alert_id}/acknowledge.
 * - Displays alert identity, status, severity, timestamps, and trigger metrics.
 * - Preserves backend-provided values without inventing classifications.
 * - Loading, error, and empty states.
 * - Gated by authoritative Permission.ALERTS_ACKNOWLEDGE for acknowledgement.
 * - Read-only users (possessing DASHBOARD_READ but lacking ALERTS_ACKNOWLEDGE)
 *   may inspect alerts without seeing acknowledgement controls.
 * - Prevents duplicate acknowledgement submissions while pending.
 * - Strict tenant isolation via centralized API client (no client-controlled tenant parameter).
 *
 * @param {object} props
 * @param {boolean} [props.isRefreshing=false] - Parent-triggered refresh status
 * @param {function} [props.onDataLoaded] - Callback with loaded timestamp string
 */
export function AlertsView({ isRefreshing = false, onDataLoaded }) {
  const { hasPermission } = useAuth();
  const canAcknowledge = hasPermission(PERMISSIONS.ALERTS_ACKNOWLEDGE);

  const [alerts, setAlerts] = useState([]);
  const [totalAlerts, setTotalAlerts] = useState(0);
  const [activeAlerts, setActiveAlerts] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [statusFilter, setStatusFilter] = useState("ALL");

  // Track pending acknowledgements to prevent duplicate submissions
  const [pendingAckIds, setPendingAckIds] = useState([]);
  // Track per-alert acknowledgement errors
  const [ackErrors, setAckErrors] = useState({});

  // 1. Fetch Alerts List
  const fetchAlertsList = useCallback(async () => {
    setLoading(true);
    setError(null);

    const params = {};
    if (statusFilter !== "ALL") {
      params.status = statusFilter.toLowerCase();
    }

    try {
      const data = await getAlerts(params);
      const items = Array.isArray(data.alerts) ? data.alerts : [];
      setAlerts(items);
      setTotalAlerts(typeof data.total_alerts === "number" ? data.total_alerts : items.length);
      setActiveAlerts(
        typeof data.active_alerts === "number"
          ? data.active_alerts
          : items.filter((a) => (a.status || "").toLowerCase() === "active").length
      );

      if (onDataLoaded) {
        onDataLoaded(new Date().toLocaleTimeString());
      }
    } catch (err) {
      setError({
        message: err.message || "Failed to load operator alerts.",
        code: err.code || "LOAD_ERROR",
        traceId: err.traceId || null,
        status: err.status || 500,
      });
    } finally {
      setLoading(false);
    }
  }, [statusFilter, onDataLoaded]);

  // Initial fetch and on statusFilter change
  useEffect(() => {
    fetchAlertsList();
  }, [fetchAlertsList]);

  // Synchronize when parent triggers refresh
  useEffect(() => {
    if (isRefreshing) {
      fetchAlertsList();
    }
  }, [isRefreshing, fetchAlertsList]);

  // 2. Handle Alert Acknowledgement
  const handleAcknowledge = async (alertId) => {
    if (!canAcknowledge || pendingAckIds.includes(alertId)) {
      return;
    }

    // Set pending
    setPendingAckIds((prev) => [...prev, alertId]);
    // Clear previous error for this alert
    setAckErrors((prev) => {
      const next = { ...prev };
      delete next[alertId];
      return next;
    });

    try {
      const updatedAlert = await acknowledgeAlert(alertId);

      // Update local state with acknowledged alert returned by backend
      setAlerts((prevAlerts) =>
        prevAlerts.map((a) => {
          if (a.alert_id === alertId) {
            return {
              ...a,
              status: updatedAlert.status || "acknowledged",
              acknowledged_at: updatedAlert.acknowledged_at || new Date().toISOString(),
              acknowledged_by: updatedAlert.acknowledged_by || a.acknowledged_by || "current_user",
            };
          }
          return a;
        })
      );

      // Decrement active count if it was active
      setActiveAlerts((prev) => Math.max(0, prev - 1));
    } catch (err) {
      setAckErrors((prev) => ({
        ...prev,
        [alertId]: {
          message: err.message || "Acknowledgement failed.",
          code: err.code || "ACK_FAILED",
          status: err.status || 500,
          traceId: err.traceId || null,
        },
      }));
    } finally {
      setPendingAckIds((prev) => prev.filter((id) => id !== alertId));
    }
  };

  // 1. LOADING STATE
  if (loading && alerts.length === 0) {
    return (
      <section
        role="status"
        aria-live="polite"
        aria-label="Loading operator alerts"
        className="space-y-6"
      >
        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-6 h-28 animate-pulse flex items-center justify-between" />
        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-8 h-80 animate-pulse flex items-center justify-center text-slate-500 text-xs">
          Loading operator alerts and telemetry events...
        </div>
      </section>
    );
  }

  // 2. ERROR STATE
  if (error) {
    return (
      <section
        role="alert"
        aria-labelledby="alerts-error-title"
        className="bg-slate-900 border border-rose-900/60 rounded-xl p-6 shadow-lg space-y-4"
      >
        <div className="flex items-start space-x-3">
          <div className="w-10 h-10 rounded-lg bg-rose-500/10 border border-rose-500/30 flex items-center justify-center text-rose-400 flex-shrink-0">
            <AlertCircle className="w-5 h-5" aria-hidden="true" />
          </div>
          <div className="space-y-1">
            <h3 id="alerts-error-title" className="text-sm font-bold text-white">
              Unable to Load Operator Alerts
            </h3>
            <p className="text-xs text-rose-300">{error.message}</p>
            <div className="flex flex-wrap items-center gap-3 text-[11px] font-mono text-slate-400 pt-1">
              <span>Code: {error.code}</span>
              {error.traceId && <span>Trace: {error.traceId}</span>}
              <span>Status: {error.status}</span>
            </div>
          </div>
        </div>

        <div className="flex justify-end pt-2 border-t border-slate-800">
          <button
            type="button"
            onClick={fetchAlertsList}
            aria-label="Retry loading alerts"
            className="flex items-center space-x-1.5 px-3 py-1.5 text-xs font-semibold text-white bg-slate-800 hover:bg-slate-700 rounded-lg border border-slate-700 transition focus:outline-none focus:ring-2 focus:ring-sky-500"
          >
            <RefreshCw className="w-3.5 h-3.5" aria-hidden="true" />
            <span>Retry</span>
          </button>
        </div>
      </section>
    );
  }

  return (
    <section aria-labelledby="alerts-title" className="space-y-6">
      {/* Title & Filter Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 id="alerts-title" className="text-base font-bold text-white tracking-tight">
            Operator Alerts & Operational Events
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Audit persisted operational anomalies, threshold breaches, and acknowledge alerts directly.
          </p>
        </div>

        {/* Status Filter Buttons */}
        <div
          role="group"
          aria-label="Filter alerts by status"
          className="flex items-center bg-slate-900 p-1 rounded-lg border border-slate-800"
        >
          <span className="text-[11px] font-mono text-slate-400 px-2 hidden sm:inline">
            Status:
          </span>
          {STATUS_FILTERS.map((st) => (
            <button
              key={st}
              type="button"
              onClick={() => setStatusFilter(st)}
              aria-pressed={statusFilter === st}
              className={`px-2.5 py-1 text-xs rounded-md font-medium transition ${
                statusFilter === st
                  ? "bg-sky-600 text-white font-semibold shadow-sm"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-800"
              }`}
            >
              {st}
            </button>
          ))}
        </div>
      </div>

      {/* Summary Metrics Bar */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-sm">
          <span className="text-[11px] font-mono text-slate-400 uppercase block">Total Alerts</span>
          <span className="text-xl font-bold text-white mt-1 block font-mono">
            {totalAlerts}
          </span>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-sm">
          <span className="text-[11px] font-mono text-slate-400 uppercase block">Active Alerts</span>
          <span
            className={`text-xl font-bold mt-1 block font-mono ${
              activeAlerts > 0 ? "text-rose-400" : "text-emerald-400"
            }`}
          >
            {activeAlerts}
          </span>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-sm">
          <span className="text-[11px] font-mono text-slate-400 uppercase block">Permission Mode</span>
          <span className="text-xs font-semibold mt-1.5 block">
            {canAcknowledge ? (
              <span className="text-emerald-400 inline-flex items-center space-x-1">
                <ShieldCheck className="w-3.5 h-3.5" aria-hidden="true" />
                <span>Operator (Ack Enabled)</span>
              </span>
            ) : (
              <span className="text-slate-400 inline-flex items-center space-x-1">
                <Eye className="w-3.5 h-3.5" aria-hidden="true" />
                <span>Read-Only Viewer</span>
              </span>
            )}
          </span>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-sm flex items-center justify-between">
          <div>
            <span className="text-[11px] font-mono text-slate-400 uppercase block">Telemetry</span>
            <span className="text-xs text-slate-300 font-mono mt-1 block">PostgreSQL</span>
          </div>
          <button
            type="button"
            onClick={fetchAlertsList}
            aria-label="Refresh alerts"
            className="p-2 text-slate-400 hover:text-slate-200 bg-slate-800 hover:bg-slate-700 rounded-lg border border-slate-700 transition"
          >
            <RefreshCw className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>
      </div>

      {/* 3. EMPTY STATE */}
      {!loading && alerts.length === 0 ? (
        <div
          aria-labelledby="alerts-empty-title"
          className="bg-slate-900 border border-slate-800 rounded-xl p-10 text-center shadow-lg space-y-4"
        >
          <div className="w-12 h-12 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center mx-auto text-slate-400">
            <ShieldCheck className="w-6 h-6 text-emerald-400" aria-hidden="true" />
          </div>
          <div>
            <h3 id="alerts-empty-title" className="text-base font-bold text-white">
              No Persisted Alerts Available
            </h3>
            <p className="text-xs text-slate-400 mt-1 max-w-md mx-auto leading-relaxed">
              {statusFilter !== "ALL"
                ? `No alerts found with status '${statusFilter}'. Try selecting 'ALL' or check back later.`
                : "No operational alerts recorded for the authenticated tenant. All verification pipelines, drift tolerances, and circuit breakers are healthy."}
            </p>
          </div>
          <div className="pt-2">
            {statusFilter !== "ALL" ? (
              <button
                type="button"
                onClick={() => setStatusFilter("ALL")}
                className="inline-flex items-center space-x-1.5 px-3.5 py-1.5 text-xs font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 rounded-lg border border-slate-700 transition"
              >
                <span>Clear Status Filter</span>
              </button>
            ) : (
              <button
                type="button"
                onClick={fetchAlertsList}
                className="inline-flex items-center space-x-1.5 px-3.5 py-1.5 text-xs font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 rounded-lg border border-slate-700 transition"
              >
                <RefreshCw className="w-3.5 h-3.5" aria-hidden="true" />
                <span>Check for Updates</span>
              </button>
            )}
          </div>
        </div>
      ) : (
        /* Alerts List */
        <div className="space-y-4" role="feed" aria-label="Persisted alerts list">
          {alerts.map((alert) => {
            const rawStatus = (alert.status || "active").toLowerCase();
            const isActive = rawStatus === "active";
            const isAcknowledged = rawStatus === "acknowledged";
            const isPending = pendingAckIds.includes(alert.alert_id);
            const ackErr = ackErrors[alert.alert_id];

            return (
              <article
                key={alert.alert_id}
                aria-label={`Alert ${alert.alert_id}`}
                className={`bg-slate-900 border rounded-xl p-5 shadow-lg space-y-4 transition ${
                  isActive
                    ? "border-rose-900/60 bg-gradient-to-r from-rose-950/10 to-transparent"
                    : "border-slate-800 hover:border-slate-700"
                }`}
              >
                {/* Header row: ID, Severity, Status, Type, and Timestamp */}
                <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-slate-800/80">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs font-bold text-white bg-slate-950 px-2.5 py-0.5 rounded border border-slate-800">
                      {alert.alert_id}
                    </span>

                    <span
                      className={`text-[11px] font-bold uppercase font-mono px-2 py-0.5 rounded border ${getSeverityBadge(
                        alert.severity
                      )}`}
                    >
                      {(alert.severity || "NORMAL").toUpperCase()}
                    </span>

                    <span
                      className={`text-[11px] font-bold uppercase font-mono px-2 py-0.5 rounded border ${getStatusBadge(
                        alert.status
                      )}`}
                    >
                      {(alert.status || "ACTIVE").toUpperCase()}
                    </span>

                    {alert.alert_type && (
                      <span className="text-[10px] font-mono text-slate-400 bg-slate-800 px-2 py-0.5 rounded">
                        {alert.alert_type}
                      </span>
                    )}
                  </div>

                  <div className="flex items-center space-x-1.5 text-[11px] font-mono text-slate-400">
                    <Clock className="w-3.5 h-3.5" aria-hidden="true" />
                    <span>Created: {formatTimestamp(alert.created_at)}</span>
                  </div>
                </div>

                {/* Content: Title & Description */}
                <div className="space-y-1.5">
                  <h3 className="text-sm font-bold text-white leading-snug">
                    {alert.title}
                  </h3>
                  <p className="text-xs text-slate-300 leading-relaxed">
                    {alert.description}
                  </p>
                </div>

                {/* Metrics / Trigger threshold information */}
                {(alert.threshold !== null && alert.threshold !== undefined ||
                  alert.current_value !== null && alert.current_value !== undefined) && (
                  <div className="bg-slate-950/70 border border-slate-800/80 rounded-lg p-3 flex flex-wrap items-center gap-4 text-xs font-mono text-slate-300">
                    {alert.current_value !== null && alert.current_value !== undefined && (
                      <div>
                        <span className="text-[10px] text-slate-500 uppercase block">Observed Value</span>
                        <span className="font-bold text-rose-400">
                          {typeof alert.current_value === "number"
                            ? alert.current_value.toFixed(4)
                            : alert.current_value}
                        </span>
                      </div>
                    )}

                    {alert.threshold !== null && alert.threshold !== undefined && (
                      <div>
                        <span className="text-[10px] text-slate-500 uppercase block">Trigger Threshold</span>
                        <span className="font-bold text-amber-400">
                          {typeof alert.threshold === "number"
                            ? alert.threshold.toFixed(4)
                            : alert.threshold}
                        </span>
                      </div>
                    )}
                  </div>
                )}

                {/* Footer: Acknowledgement Metadata or Action Control */}
                <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
                  <div className="text-[11px] font-mono text-slate-400">
                    {alert.acknowledged_at && (
                      <span className="inline-flex items-center space-x-1 text-emerald-400">
                        <Check className="w-3.5 h-3.5" aria-hidden="true" />
                        <span>
                          Acknowledged at {formatTimestamp(alert.acknowledged_at)}
                          {alert.acknowledged_by ? ` by ${alert.acknowledged_by}` : ""}
                        </span>
                      </span>
                    )}
                  </div>

                  {/* Action Control: Only rendered if canAcknowledge (RBAC UX Gating) */}
                  <div>
                    {canAcknowledge ? (
                      isActive ? (
                        <div className="flex items-center space-x-2">
                          <button
                            type="button"
                            onClick={() => handleAcknowledge(alert.alert_id)}
                            disabled={isPending}
                            aria-label={`Acknowledge alert ${alert.alert_id}`}
                            className={`inline-flex items-center space-x-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-lg transition ${
                              isPending
                                ? "bg-slate-800 text-slate-500 cursor-not-allowed border border-slate-700"
                                : "bg-sky-600 hover:bg-sky-500 text-white shadow-sm focus:outline-none focus:ring-2 focus:ring-sky-500"
                            }`}
                          >
                            {isPending ? (
                              <>
                                <RefreshCw className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
                                <span>Acknowledging...</span>
                              </>
                            ) : (
                              <>
                                <Check className="w-3.5 h-3.5" aria-hidden="true" />
                                <span>Acknowledge</span>
                              </>
                            )}
                          </button>
                        </div>
                      ) : (
                        <span className="text-xs font-mono text-emerald-400 font-semibold inline-flex items-center space-x-1">
                          <CheckCircle2 className="w-4 h-4" aria-hidden="true" />
                          <span>Acknowledged</span>
                        </span>
                      )
                    ) : (
                      /* Read-only users without ALERTS_ACKNOWLEDGE */
                      <span
                        className="text-[11px] font-mono text-slate-500 px-2 py-1 rounded bg-slate-950 border border-slate-800"
                        title="Acknowledgement requires ALERTS_ACKNOWLEDGE permission"
                      >
                        Read-Only Inspection
                      </span>
                    )}
                  </div>
                </div>

                {/* Per-Alert Acknowledgement Error Message */}
                {ackErr && (
                  <div
                    role="alert"
                    className="bg-rose-950/40 border border-rose-800/80 rounded-lg p-3 text-xs text-rose-300 flex items-start space-x-2"
                  >
                    <AlertTriangle className="w-4 h-4 text-rose-400 flex-shrink-0 mt-0.5" aria-hidden="true" />
                    <div className="space-y-0.5">
                      <p className="font-semibold">Acknowledgement Failed: {ackErr.message}</p>
                      <div className="text-[10px] font-mono text-slate-400">
                        <span>Code: {ackErr.code}</span>
                        {ackErr.traceId && <span className="ml-2">Trace: {ackErr.traceId}</span>}
                      </div>
                    </div>
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}

export default AlertsView;
