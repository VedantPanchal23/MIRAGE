import React, { useEffect, useState, useCallback } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Database,
  AlertCircle,
  RefreshCw,
} from "lucide-react";
import { getDashboardSessions, getSessionById } from "../api";
import { ClaimsTree } from "../components/ClaimsTree";
import { SHAPWaterfall } from "../components/SHAPWaterfall";

const RISK_TIERS = ["ALL", "LOW", "MEDIUM", "HIGH", "CRITICAL"];

/**
 * Sessions & Claims View Console.
 *
 * Implements PRD §FR-AUD-01, Technical Architecture §8.2, and Phase P2.7:
 * - Uses centralized API client `getDashboardSessions` and `getSessionById`.
 * - Backend-authoritative tenant isolation: never injects client-supplied tenant ID.
 * - Supports pagination and risk tier filtering according to backend query contracts.
 * - Renders atomic claim decompositions and TreeSHAP feature attributions.
 * - Handles Loading, Error, Empty, and Success states with accessible ARIA semantics.
 *
 * @param {object} props
 * @param {boolean} [props.isRefreshing=false] - Global refresh trigger from header
 * @param {Function} [props.onDataLoaded] - Timestamp callback when data successfully loaded
 */
export function SessionsView({ isRefreshing, onDataLoaded }) {
  const [sessions, setSessions] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(10);
  const [selectedRiskTier, setSelectedRiskTier] = useState("ALL");

  const [loadingSessions, setLoadingSessions] = useState(true);
  const [sessionsError, setSessionsError] = useState(null);

  const [selectedSessionId, setSelectedSessionId] = useState(null);
  const [sessionDetails, setSessionDetails] = useState(null);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [detailsError, setDetailsError] = useState(null);

  // 1. Fetch Paginated Sessions List
  const fetchSessionsList = useCallback(async () => {
    setLoadingSessions(true);
    setSessionsError(null);

    try {
      const params = {
        page,
        page_size: pageSize,
      };
      if (selectedRiskTier !== "ALL") {
        params.risk_tier = selectedRiskTier;
      }

      // Centralized API client call without client-supplied tenant_id
      const res = await getDashboardSessions(params);
      const items = res?.items || [];
      const totalCount = res?.total ?? items.length;

      setSessions(items);
      setTotal(totalCount);

      // Default selection to first item if current selection is invalid or null
      if (items.length > 0) {
        setSelectedSessionId((prev) => {
          if (prev && items.some((s) => s.session_id === prev)) {
            return prev;
          }
          return items[0].session_id;
        });
      } else {
        setSelectedSessionId(null);
        setSessionDetails(null);
      }

      if (onDataLoaded) {
        onDataLoaded(new Date().toLocaleTimeString());
      }
    } catch (err) {
      setSessionsError({
        message: err.message || "Failed to load verification sessions.",
        code: err.code || "LOAD_ERROR",
        traceId: err.traceId || null,
        status: err.status || 500,
      });
    } finally {
      setLoadingSessions(false);
    }
  }, [page, pageSize, selectedRiskTier, onDataLoaded]);

  // 2. Fetch Detailed Session Record (Claims + Trace + TreeSHAP)
  const fetchSessionDetails = useCallback(async (sessionId) => {
    if (!sessionId) {
      setSessionDetails(null);
      return;
    }

    setLoadingDetails(true);
    setDetailsError(null);

    try {
      const details = await getSessionById(sessionId);
      setSessionDetails(details);
    } catch (err) {
      setDetailsError({
        message: err.message || `Failed to load details for session ${sessionId}.`,
        code: err.code || "LOAD_ERROR",
        traceId: err.traceId || null,
        status: err.status || 500,
      });
    } finally {
      setLoadingDetails(false);
    }
  }, []);

  // Fetch list on mount or filter/page change
  useEffect(() => {
    fetchSessionsList();
  }, [fetchSessionsList]);

  // Synchronize when parent header triggers global refresh
  useEffect(() => {
    if (isRefreshing) {
      fetchSessionsList();
    }
  }, [isRefreshing, fetchSessionsList]);

  // Fetch details whenever selectedSessionId changes
  useEffect(() => {
    if (selectedSessionId) {
      fetchSessionDetails(selectedSessionId);
    }
  }, [selectedSessionId, fetchSessionDetails]);

  const handleFilterChange = (tier) => {
    setSelectedRiskTier(tier);
    setPage(1); // Reset to first page upon filter change
  };

  const totalPages = Math.ceil(total / pageSize) || 1;

  // 1. INITIAL LOADING STATE
  if (loadingSessions && sessions.length === 0) {
    return (
      <section
        role="status"
        aria-live="polite"
        aria-label="Loading verification sessions"
        className="space-y-6"
      >
        <div className="bg-white border border-slate-200 rounded-xl p-6 h-28 animate-pulse flex items-center justify-between shadow-xs" />
        <div className="bg-white border border-slate-200 rounded-xl p-8 h-80 animate-pulse flex items-center justify-center text-slate-500 text-xs shadow-xs">
          Loading verification sessions and claim records...
        </div>
      </section>
    );
  }

  // 2. ERROR STATE
  if (sessionsError) {
    return (
      <section
        role="alert"
        aria-labelledby="sessions-error-title"
        className="bg-white border border-rose-200 rounded-xl p-6 shadow-xs space-y-4"
      >
        <div className="flex items-start space-x-3">
          <div className="w-10 h-10 rounded-lg bg-rose-50 border border-rose-200 flex items-center justify-center text-rose-600 flex-shrink-0">
            <AlertCircle className="w-5 h-5" aria-hidden="true" />
          </div>
          <div className="flex-1">
            <h2 id="sessions-error-title" className="text-sm font-bold text-slate-900">
              Unable to Load Verification Sessions
            </h2>
            <p className="text-xs text-slate-600 mt-1 leading-relaxed">
              {sessionsError.message}
            </p>
            <div className="flex flex-wrap items-center gap-3 mt-3 text-[11px] font-mono text-slate-500">
              <span className="bg-slate-50 px-2 py-0.5 rounded border border-slate-200">
                Code: {sessionsError.code}
              </span>
              {sessionsError.traceId && (
                <span className="bg-slate-50 px-2 py-0.5 rounded border border-slate-200">
                  Trace: {sessionsError.traceId}
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="flex justify-end pt-2 border-t border-slate-100">
          <button
            type="button"
            onClick={fetchSessionsList}
            aria-label="Retry loading sessions"
            className="flex items-center space-x-1.5 px-3 py-1.5 text-xs font-semibold text-slate-700 bg-white hover:bg-slate-50 rounded-lg border border-slate-300 shadow-xs transition focus:outline-none focus:ring-2 focus:ring-sky-500"
          >
            <RefreshCw className="w-3.5 h-3.5" aria-hidden="true" />
            <span>Retry</span>
          </button>
        </div>
      </section>
    );
  }

  // Find summary object of currently selected session from the list
  const selectedSummary =
    sessions.find((s) => s.session_id === selectedSessionId) || null;

  // Determine authoritative TreeSHAP attribution:
  // Prefer detailed session record, fallback to trace.hrs_result, trace, or session summary attribution if available
  const treeShapAttribution =
    sessionDetails?.signal_attribution && Object.keys(sessionDetails.signal_attribution).length > 0
      ? sessionDetails.signal_attribution
      : sessionDetails?.trace?.hrs_result?.signal_attribution &&
        Object.keys(sessionDetails.trace.hrs_result.signal_attribution).length > 0
      ? sessionDetails.trace.hrs_result.signal_attribution
      : sessionDetails?.trace?.signal_attribution && Object.keys(sessionDetails.trace.signal_attribution).length > 0
      ? sessionDetails.trace.signal_attribution
      : selectedSummary?.signal_attribution && Object.keys(selectedSummary.signal_attribution).length > 0
      ? selectedSummary.signal_attribution
      : null;

  // Texts for Claims comparison
  const originalPromptText =
    sessionDetails?.trace?.prompt ||
    sessionDetails?.trace?.original_prompt ||
    selectedSummary?.prompt ||
    (selectedSummary?.prompt_hash ? `Prompt Hash: ${selectedSummary.prompt_hash}` : "");

  const verifiedResponseText =
    sessionDetails?.trace?.verified_response ||
    sessionDetails?.trace?.response ||
    selectedSummary?.response ||
    (selectedSummary?.response_hash ? `Response Hash: ${selectedSummary.response_hash}` : "");

  return (
    <section aria-labelledby="sessions-title" className="space-y-6">
      {/* Title & Filter Bar */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 id="sessions-title" className="text-base font-bold text-slate-900 tracking-tight">
            Sessions Inspector & TreeSHAP Attribution
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Audit verification sessions, propositional claim breakdowns, and model feature attributions.
          </p>
        </div>

        {/* Risk Tier Filter Controls */}
        <div
          role="group"
          aria-label="Filter sessions by risk tier"
          className="flex items-center bg-white p-1 rounded-lg border border-slate-200 shadow-xs"
        >
          <span className="text-[11px] font-mono text-slate-500 px-2 hidden sm:inline">
            Tier:
          </span>
          {RISK_TIERS.map((tier) => (
            <button
              key={tier}
              type="button"
              onClick={() => handleFilterChange(tier)}
              aria-pressed={selectedRiskTier === tier}
              className={`px-2.5 py-1 text-xs rounded-md font-medium transition ${
                selectedRiskTier === tier
                  ? "bg-sky-50 text-sky-700 font-semibold border border-sky-200"
                  : "text-slate-600 hover:text-slate-900 hover:bg-slate-50"
              }`}
            >
              {tier}
            </button>
          ))}
        </div>
      </div>

      {/* 3. EMPTY STATE */}
      {!loadingSessions && sessions.length === 0 ? (
        <div
          aria-labelledby="sessions-empty-title"
          className="bg-white border border-slate-200 rounded-xl p-10 text-center shadow-xs space-y-4"
        >
          <div className="w-12 h-12 rounded-full bg-slate-100 border border-slate-200 flex items-center justify-center mx-auto text-slate-500">
            <Database className="w-6 h-6" aria-hidden="true" />
          </div>
          <div>
            <h3 id="sessions-empty-title" className="text-base font-bold text-slate-900">
              No Verification Sessions Found
            </h3>
            <p className="text-xs text-slate-500 mt-1 max-w-md mx-auto leading-relaxed">
              {selectedRiskTier !== "ALL"
                ? `No sessions recorded with risk tier '${selectedRiskTier}'. Try selecting 'ALL' or check back after new verification requests are processed.`
                : "There are no recorded verification sessions for the authenticated tenant yet. Once requests are processed by the gateway, session logs and claim breakdowns will appear here."}
            </p>
          </div>
          <div className="pt-2">
            {selectedRiskTier !== "ALL" ? (
              <button
                type="button"
                onClick={() => handleFilterChange("ALL")}
                className="inline-flex items-center space-x-1.5 px-3.5 py-1.5 text-xs font-medium text-slate-700 bg-white hover:bg-slate-50 rounded-lg border border-slate-300 shadow-xs transition"
              >
                <span>Clear Tier Filter</span>
              </button>
            ) : (
              <button
                type="button"
                onClick={fetchSessionsList}
                className="inline-flex items-center space-x-1.5 px-3.5 py-1.5 text-xs font-medium text-slate-700 bg-white hover:bg-slate-50 rounded-lg border border-slate-300 shadow-xs transition"
              >
                <RefreshCw className="w-3.5 h-3.5" aria-hidden="true" />
                <span>Check for Updates</span>
              </button>
            )}
          </div>
        </div>
      ) : (
        /* Sessions Table & Master-Detail Inspection View */
        <div className="space-y-6">
          {/* Sessions List Card */}
          <div className="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden">
            <div className="p-4 border-b border-slate-200 flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-900">
                Verification Sessions ({total} total)
              </span>
              <span className="text-xs text-slate-500 font-mono">
                Page {page} of {totalPages}
              </span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs text-slate-700 border-collapse">
                <caption className="sr-only">List of verification sessions</caption>
                <thead>
                  <tr className="border-b border-slate-200 text-[11px] font-mono text-slate-500 uppercase tracking-wider bg-slate-50">
                    <th scope="col" className="py-2.5 px-4">
                      Session ID
                    </th>
                    <th scope="col" className="py-2.5 px-3">
                      Risk Tier
                    </th>
                    <th scope="col" className="py-2.5 px-3 text-right">
                      Calibrated HRS
                    </th>
                    <th scope="col" className="py-2.5 px-3 text-center">
                      Claims
                    </th>
                    <th scope="col" className="py-2.5 px-3">
                      Correction
                    </th>
                    <th scope="col" className="py-2.5 px-4">
                      Timestamp
                    </th>
                    <th scope="col" className="py-2.5 px-4 text-right">
                      Action
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 font-mono">
                  {sessions.map((sess) => {
                    const isSelected = sess.session_id === selectedSessionId;
                    const tier = (sess.risk_tier || "UNKNOWN").toUpperCase();

                    const tierBadgeClass = {
                      LOW: "text-emerald-700 bg-emerald-50 border-emerald-200",
                      MEDIUM: "text-amber-700 bg-amber-50 border-amber-200",
                      HIGH: "text-rose-700 bg-rose-50 border-rose-200",
                      CRITICAL: "text-purple-700 bg-purple-50 border-purple-200",
                    }[tier] || "text-slate-600 bg-slate-100 border-slate-200";

                    return (
                      <tr
                        key={sess.session_id}
                        onClick={() => setSelectedSessionId(sess.session_id)}
                        className={`cursor-pointer transition ${
                          isSelected
                            ? "bg-sky-50/70 border-l-4 border-l-sky-500 font-semibold"
                            : "hover:bg-slate-50"
                        }`}
                      >
                        <td className="py-3 px-4 font-bold text-slate-900">
                          {sess.session_id}
                        </td>
                        <td className="py-3 px-3">
                          <span
                            className={`text-[10px] font-bold px-2 py-0.5 rounded border ${tierBadgeClass}`}
                          >
                            {tier}
                          </span>
                        </td>
                        <td className="py-3 px-3 text-right text-slate-900 font-bold">
                          {typeof sess.hrs_score === "number"
                            ? sess.hrs_score.toFixed(4)
                            : "N/A"}
                          {typeof sess.ci_lower === "number" &&
                            typeof sess.ci_upper === "number" && (
                              <span className="block text-[10px] text-slate-500 font-normal">
                                [{sess.ci_lower.toFixed(3)}, {sess.ci_upper.toFixed(3)}]
                              </span>
                            )}
                        </td>
                        <td className="py-3 px-3 text-center text-slate-600">
                          {sess.claims_count ?? (sess.claims?.length || 0)}
                        </td>
                        <td className="py-3 px-3">
                          {sess.correction_applied ? (
                            <span className="text-[10px] text-emerald-700 bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 rounded">
                              Applied
                            </span>
                          ) : (
                            <span className="text-[10px] text-slate-400">None</span>
                          )}
                        </td>
                        <td className="py-3 px-4 text-slate-500 text-[11px]">
                          {sess.created_at ? sess.created_at.slice(0, 19).replace("T", " ") : "N/A"}
                        </td>
                        <td className="py-3 px-4 text-right">
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedSessionId(sess.session_id);
                            }}
                            className={`text-[11px] px-2.5 py-1 rounded font-medium border transition ${
                              isSelected
                                ? "bg-sky-600 text-white border-sky-500"
                                : "bg-white text-slate-700 border-slate-300 hover:bg-slate-50"
                            }`}
                          >
                            Inspect
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Pagination Bar */}
            <div className="p-3 border-t border-slate-200 bg-slate-50 flex items-center justify-between text-xs text-slate-500">
              <span className="font-mono">
                Showing {Math.min(total, (page - 1) * pageSize + 1)} -{" "}
                {Math.min(total, page * pageSize)} of {total}
              </span>

              <div className="flex items-center space-x-2">
                <button
                  type="button"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  aria-label="Previous page"
                  className="p-1.5 rounded-lg bg-white border border-slate-200 text-slate-700 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-slate-50 transition"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>
                <span className="font-mono px-2 text-slate-700 font-semibold">
                  {page} / {totalPages}
                </span>
                <button
                  type="button"
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  aria-label="Next page"
                  className="p-1.5 rounded-lg bg-white border border-slate-200 text-slate-700 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-slate-50 transition"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>

          {/* Detailed Inspection Pane */}
          {selectedSessionId && (
            <div className="space-y-6 pt-2">
              {loadingDetails && (
                <div
                  role="status"
                  aria-label="Loading session details"
                  className="bg-white border border-slate-200 rounded-xl p-6 text-center text-xs text-slate-500 font-mono animate-pulse shadow-xs"
                >
                  Loading claim breakdown and TreeSHAP attribution for {selectedSessionId}...
                </div>
              )}

              {detailsError && (
                <div
                  role="alert"
                  className="bg-white border border-rose-200 rounded-xl p-4 flex items-start space-x-3 text-rose-800 shadow-xs"
                >
                  <AlertCircle className="w-4 h-4 text-rose-600 flex-shrink-0 mt-0.5" />
                  <div className="flex-1 text-xs">
                    <p className="font-bold">{detailsError.message}</p>
                    <button
                      type="button"
                      onClick={() => fetchSessionDetails(selectedSessionId)}
                      className="mt-2 underline font-semibold text-rose-900 hover:text-rose-950"
                    >
                      Retry loading details
                    </button>
                  </div>
                </div>
              )}

              {/* Session Overview Card */}
              {sessionDetails && (
                <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-xs">
                  <div className="flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-slate-200">
                    <div>
                      <span className="text-[11px] font-mono uppercase tracking-wider text-slate-500">
                        Inspected Session
                      </span>
                      <h3 className="text-base font-bold text-slate-900 font-mono mt-0.5">
                        {sessionDetails.session_id}
                      </h3>
                    </div>

                    <div className="flex items-center space-x-2">
                      <span
                        className={`text-xs px-2.5 py-1 rounded-md font-bold border ${
                          {
                            LOW: "text-emerald-700 bg-emerald-50 border-emerald-200",
                            MEDIUM: "text-amber-700 bg-amber-50 border-amber-200",
                            HIGH: "text-rose-700 bg-rose-50 border-rose-200",
                            CRITICAL: "text-purple-700 bg-purple-50 border-purple-200",
                          }[(sessionDetails.risk_tier || "UNKNOWN").toUpperCase()] ||
                          "text-slate-600 bg-slate-100 border-slate-200"
                        }`}
                      >
                        {(sessionDetails.risk_tier || "UNKNOWN").toUpperCase()} RISK
                      </span>
                    </div>
                  </div>

                  {/* Metadata Grid */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 pt-4 text-xs font-mono">
                    <div className="bg-slate-50 p-3 rounded-lg border border-slate-200">
                      <span className="text-[10px] text-slate-500 uppercase block">Calibrated HRS</span>
                      <span className="text-lg font-bold text-slate-900 block mt-0.5">
                        {typeof sessionDetails.hrs_score === "number"
                          ? sessionDetails.hrs_score.toFixed(4)
                          : "0.0000"}
                      </span>
                      {typeof selectedSummary?.ci_lower === "number" && (
                        <span className="text-[10px] text-sky-700 font-medium">
                          95% CI: [{selectedSummary.ci_lower.toFixed(3)}, {selectedSummary.ci_upper.toFixed(3)}]
                        </span>
                      )}
                    </div>

                    <div className="bg-slate-50 p-3 rounded-lg border border-slate-200">
                      <span className="text-[10px] text-slate-500 uppercase block">Model ID</span>
                      <span className="text-sm font-semibold text-slate-800 block mt-1 truncate" title={sessionDetails.model_id}>
                        {sessionDetails.model_id || "default"}
                      </span>
                    </div>

                    <div className="bg-slate-50 p-3 rounded-lg border border-slate-200">
                      <span className="text-[10px] text-slate-500 uppercase block">Trace ID</span>
                      <span className="text-xs text-slate-700 block mt-1 truncate" title={sessionDetails.trace_id}>
                        {sessionDetails.trace_id || "N/A"}
                      </span>
                    </div>

                    <div className="bg-slate-50 p-3 rounded-lg border border-slate-200">
                      <span className="text-[10px] text-slate-500 uppercase block">Correction Status</span>
                      <span className="text-sm font-semibold block mt-1">
                        {sessionDetails.correction_applied ? (
                          <span className="text-emerald-700">Rewrite Applied</span>
                        ) : (
                          <span className="text-slate-500">Not Triggered</span>
                        )}
                      </span>
                    </div>
                  </div>
                </div>
              )}

              {/* Claims Breakdown Component */}
              <ClaimsTree
                claims={sessionDetails?.claims || selectedSummary?.claims || []}
                originalText={originalPromptText}
                verifiedText={verifiedResponseText}
                correctionApplied={sessionDetails?.correction_applied || selectedSummary?.correction_applied || false}
              />

              {/* TreeSHAP Feature Attribution Component */}
              <SHAPWaterfall
                attribution={treeShapAttribution}
                hrsScore={sessionDetails?.hrs_score ?? selectedSummary?.hrs_score ?? 0.0}
              />
            </div>
          )}
        </div>
      )}
    </section>
  );
}

export default SessionsView;
