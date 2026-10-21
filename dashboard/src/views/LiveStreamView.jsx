import React, { useState } from "react";
import {
  Radio,
  Play,
  RotateCcw,
  Wifi,
  WifiOff,
  CheckCircle2,
  AlertCircle,
  AlertTriangle,
  Layers,
  Activity,
  ShieldCheck,
  Cpu,
  Clock,
  Send,
  Sparkles,
} from "lucide-react";
import { useAuth, PERMISSIONS } from "../context/AuthContext";
import { AccessDenied } from "../components/AccessDenied";
import { useWebSocketStream, STREAM_STATUS } from "../hooks/useWebSocketStream";

/**
 * Format timestamp safely for log display.
 */
function formatEventTime(isoStr) {
  if (!isoStr) return "";
  try {
    const d = new Date(isoStr);
    return isNaN(d.getTime()) ? isoStr : d.toLocaleTimeString();
  } catch {
    return isoStr;
  }
}

/**
 * Risk tier badge styling helper.
 */
function getRiskTierBadge(tier = "") {
  const t = tier.toUpperCase();
  switch (t) {
    case "CRITICAL":
      return "text-purple-700 bg-purple-50 border-purple-200";
    case "HIGH":
      return "text-rose-700 bg-rose-50 border-rose-200";
    case "MEDIUM":
      return "text-amber-700 bg-amber-50 border-amber-200";
    case "LOW":
    default:
      return "text-emerald-700 bg-emerald-50 border-emerald-200";
  }
}

/**
 * Live WebSocket Verification Stream Console.
 *
 * Implements Technical Architecture §3.4 & §7, and Security & Access §4.4:
 * - Two-step first-message JWT authentication over WebSocket transport.
 * - RBAC UX gating strictly derived from PERMISSIONS.VERIFY_WRITE.
 * - Real-time progressive stream event presentation (decomposition -> multi-signal -> HRS verdict).
 * - Authoritative JWT-derived tenant display (strictly prevents client tenant spoofing).
 * - Accessible states for all phases of connection and stream lifecycle.
 */
export function LiveStreamView() {
  const { isAuthenticated, hasPermission, token, role, tenantId } = useAuth();

  // UX Form inputs
  const [promptInput, setPromptInput] = useState("");
  const [responseInput, setResponseInput] = useState("");
  const [modelIdInput, setModelIdInput] = useState("gpt-4o");
  const [showEventLog, setShowEventLog] = useState(true);

  // Authoritative RBAC UX Gating: Require VERIFY_WRITE
  const isPermitted = isAuthenticated && hasPermission(PERMISSIONS.VERIFY_WRITE);

  // Initialize WebSocket lifecycle hook
  const {
    status,
    isStreaming,
    sessionInfo,
    events,
    claims,
    signals,
    verdict,
    error,
    connect,
    disconnect,
    submitVerification,
    reset,
  } = useWebSocketStream({
    token,
    hasPermission,
    autoConnect: isPermitted,
  });

  if (!isPermitted) {
    return (
      <AccessDenied
        title="Live Stream Access Restricted"
        requiredPermission={PERMISSIONS.VERIFY_WRITE}
        userRole={role}
      />
    );
  }

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!responseInput.trim()) return;

    try {
      submitVerification({
        prompt: promptInput,
        response: responseInput,
        modelId: modelIdInput,
      });
    } catch {
      // errors handled through stream state
    }
  };

  const handleClear = () => {
    reset();
  };

  const isReadyToSubmit =
    (status === STREAM_STATUS.READY || status === STREAM_STATUS.COMPLETED) &&
    !isStreaming &&
    responseInput.trim().length > 0;

  return (
    <div className="space-y-6">
      {/* View Header & Stream Connection Status Bar */}
      <section
        aria-labelledby="stream-heading"
        className="bg-white border border-slate-200 rounded-xl p-6 shadow-xs flex flex-col md:flex-row md:items-center justify-between gap-4"
      >
        <div>
          <div className="flex items-center space-x-3 mb-1">
            <Radio className="w-5 h-5 text-sky-600 animate-pulse" aria-hidden="true" />
            <h1 id="stream-heading" className="text-xl font-bold text-slate-900 tracking-tight">
              Live Verification Stream
            </h1>
          </div>
          <p className="text-xs text-slate-500">
            Real-time WebSocket streaming verification for progressive proposition decomposition and instant HRS scoring.
          </p>
        </div>

        {/* Connection Status Badge & Controls */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Status Badge */}
          <div
            role="status"
            aria-live="polite"
            className="flex items-center space-x-2 px-3 py-1.5 rounded-lg border text-xs font-mono font-medium"
          >
            {status === STREAM_STATUS.READY && (
              <span className="flex items-center space-x-1.5 text-emerald-700 bg-emerald-50 border-emerald-200 px-2 py-0.5 rounded">
                <Wifi className="w-3.5 h-3.5" aria-hidden="true" />
                <span>Ready (Authenticated)</span>
              </span>
            )}
            {status === STREAM_STATUS.STREAMING && (
              <span className="flex items-center space-x-1.5 text-sky-700 bg-sky-50 border-sky-200 px-2 py-0.5 rounded animate-pulse">
                <Activity className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
                <span>Verifying Stream...</span>
              </span>
            )}
            {status === STREAM_STATUS.COMPLETED && (
              <span className="flex items-center space-x-1.5 text-emerald-700 bg-emerald-50 border-emerald-200 px-2 py-0.5 rounded">
                <CheckCircle2 className="w-3.5 h-3.5" aria-hidden="true" />
                <span>Verification Complete</span>
              </span>
            )}
            {status === STREAM_STATUS.CONNECTING && (
              <span className="flex items-center space-x-1.5 text-amber-700 bg-amber-50 border-amber-200 px-2 py-0.5 rounded">
                <Wifi className="w-3.5 h-3.5 animate-pulse" aria-hidden="true" />
                <span>Connecting...</span>
              </span>
            )}
            {status === STREAM_STATUS.AWAITING_AUTH && (
              <span className="flex items-center space-x-1.5 text-sky-700 bg-sky-50 border-sky-200 px-2 py-0.5 rounded">
                <Cpu className="w-3.5 h-3.5 animate-pulse" aria-hidden="true" />
                <span>Authenticating JWT...</span>
              </span>
            )}
            {status === STREAM_STATUS.DISCONNECTED && (
              <span className="flex items-center space-x-1.5 text-slate-600 bg-slate-100 border-slate-200 px-2 py-0.5 rounded">
                <WifiOff className="w-3.5 h-3.5" aria-hidden="true" />
                <span>Disconnected</span>
              </span>
            )}
            {status === STREAM_STATUS.ERROR && (
              <span className="flex items-center space-x-1.5 text-rose-700 bg-rose-50 border-rose-200 px-2 py-0.5 rounded">
                <AlertCircle className="w-3.5 h-3.5" aria-hidden="true" />
                <span>Stream Error</span>
              </span>
            )}
          </div>

          {/* Connection Toggle Button */}
          {status === STREAM_STATUS.DISCONNECTED || status === STREAM_STATUS.ERROR ? (
            <button
              type="button"
              onClick={connect}
              className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-sky-600 hover:bg-sky-700 text-white shadow-xs transition focus:outline-none focus:ring-2 focus:ring-sky-500"
            >
              <Wifi className="w-3.5 h-3.5" aria-hidden="true" />
              <span>Connect</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={disconnect}
              disabled={isStreaming}
              className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-white hover:bg-slate-50 text-slate-700 border border-slate-300 shadow-xs transition disabled:opacity-50"
            >
              <WifiOff className="w-3.5 h-3.5" aria-hidden="true" />
              <span>Disconnect</span>
            </button>
          )}

          {/* Clear Results Button */}
          <button
            type="button"
            onClick={handleClear}
            disabled={!claims.length && !signals && !verdict && !events.length}
            className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-white hover:bg-slate-50 text-slate-700 border border-slate-300 shadow-xs transition disabled:opacity-40"
          >
            <RotateCcw className="w-3.5 h-3.5" aria-hidden="true" />
            <span>Reset</span>
          </button>
        </div>
      </section>

      {/* Authoritative JWT Session Badge */}
      {sessionInfo && (
        <div
          role="region"
          aria-label="Authoritative Session Identity"
          className="bg-white border border-slate-200 rounded-lg px-4 py-2.5 text-xs flex flex-wrap items-center justify-between gap-3 text-slate-600 shadow-xs"
        >
          <div className="flex items-center space-x-4">
            <span>
              Authoritative Tenant:{" "}
              <strong className="text-slate-900 font-mono">{sessionInfo.tenantId || tenantId}</strong>
            </span>
            <span>
              Role:{" "}
              <strong className="text-sky-700 font-mono">{sessionInfo.role || role}</strong>
            </span>
          </div>
          {sessionInfo.traceId && (
            <div className="font-mono text-slate-500 text-[11px]">
              Trace: <span className="text-slate-700">{sessionInfo.traceId.slice(0, 12)}...</span>
            </div>
          )}
        </div>
      )}

      {/* Error Banner */}
      {error && (
        <div
          role="alert"
          className="bg-rose-50 border border-rose-200 rounded-xl p-4 text-xs text-rose-800 flex items-start space-x-3 shadow-xs"
        >
          <AlertCircle className="w-4 h-4 text-rose-600 flex-shrink-0 mt-0.5" aria-hidden="true" />
          <div className="flex-1">
            <strong className="block font-semibold text-rose-900 mb-0.5">Stream Error:</strong>
            <span>{error}</span>
          </div>
        </div>
      )}

      {/* Main Workspace Grid: Input Form vs. Progressive Results */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Verification Submission Form (Left 5 Cols) */}
        <section
          aria-labelledby="submission-heading"
          className="lg:col-span-5 bg-white border border-slate-200 rounded-xl p-5 shadow-xs space-y-4"
        >
          <h2 id="submission-heading" className="text-sm font-bold text-slate-900 flex items-center space-x-2">
            <Send className="w-4 h-4 text-sky-600" aria-hidden="true" />
            <span>Verification Submission</span>
          </h2>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="stream-prompt" className="block text-xs font-medium text-slate-700 mb-1">
                Prompt / Query (Optional context)
              </label>
              <textarea
                id="stream-prompt"
                rows={3}
                value={promptInput}
                onChange={(e) => setPromptInput(e.target.value)}
                placeholder="Enter prompt or query context..."
                disabled={isStreaming}
                className="w-full bg-white border border-slate-300 rounded-lg p-3 text-xs text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-500 disabled:opacity-50"
              />
            </div>

            <div>
              <label htmlFor="stream-response" className="block text-xs font-medium text-slate-700 mb-1">
                LLM Response to Verify <span className="text-rose-600">*</span>
              </label>
              <textarea
                id="stream-response"
                rows={5}
                required
                value={responseInput}
                onChange={(e) => setResponseInput(e.target.value)}
                placeholder="Enter or paste the model output to verify propositions..."
                disabled={isStreaming}
                className="w-full bg-white border border-slate-300 rounded-lg p-3 text-xs text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-500 disabled:opacity-50"
              />
            </div>

            <div>
              <label htmlFor="stream-model" className="block text-xs font-medium text-slate-700 mb-1">
                Originating Model ID
              </label>
              <input
                id="stream-model"
                type="text"
                value={modelIdInput}
                onChange={(e) => setModelIdInput(e.target.value)}
                placeholder="e.g. gpt-4o, claude-3-5-sonnet"
                disabled={isStreaming}
                className="w-full bg-white border border-slate-300 rounded-lg px-3 py-2 text-xs text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-500 disabled:opacity-50 font-mono"
              />
            </div>

            <div className="pt-2">
              <button
                type="submit"
                disabled={!isReadyToSubmit}
                className="w-full py-2.5 px-4 rounded-lg text-xs font-semibold text-white bg-sky-600 hover:bg-sky-700 disabled:bg-slate-100 disabled:text-slate-400 disabled:cursor-not-allowed transition flex items-center justify-center space-x-2 shadow-xs"
              >
                {isStreaming ? (
                  <>
                    <Activity className="w-4 h-4 animate-spin text-white" aria-hidden="true" />
                    <span>Verifying Propositions...</span>
                  </>
                ) : (
                  <>
                    <Play className="w-4 h-4 text-white" aria-hidden="true" />
                    <span>Verify via Stream</span>
                  </>
                )}
              </button>
              {status !== STREAM_STATUS.READY && status !== STREAM_STATUS.COMPLETED && (
                <p className="text-[11px] text-slate-500 mt-2 text-center">
                  Stream connection and authentication required before submission.
                </p>
              )}
            </div>
          </form>
        </section>

        {/* Progressive Real-Time Results (Right 7 Cols) */}
        <section
          aria-labelledby="results-heading"
          className="lg:col-span-7 space-y-6"
        >
          {/* Stage 1: Atomic Claim Decomposition */}
          <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-bold text-slate-900 flex items-center space-x-2 uppercase tracking-wider">
                <Layers className="w-4 h-4 text-sky-600" aria-hidden="true" />
                <span>1. Atomic Claims Decomposition (FLAN-T5)</span>
              </h3>
              {claims.length > 0 && (
                <span className="text-xs font-mono px-2 py-0.5 bg-sky-50 text-sky-700 border border-sky-200 rounded-md">
                  {claims.length} {claims.length === 1 ? "claim" : "claims"}
                </span>
              )}
            </div>

            {claims.length > 0 ? (
              <ul className="space-y-2 max-h-56 overflow-y-auto pr-1">
                {claims.map((claim, idx) => (
                  <li
                    key={claim.claim_id || idx}
                    className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs space-y-1.5"
                  >
                    <div className="flex items-center justify-between text-[11px]">
                      <span className="font-mono text-slate-600 font-semibold">
                        {claim.claim_id || `C-${idx + 1}`}
                      </span>
                      <div className="flex items-center space-x-1.5">
                        <span className="px-1.5 py-0.5 rounded text-[10px] uppercase font-mono bg-white text-slate-700 border border-slate-200">
                          {claim.type || "FACTUAL"}
                        </span>
                        {claim.criticality && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] uppercase font-mono bg-amber-50 text-amber-700 border border-amber-200">
                            {claim.criticality}
                          </span>
                        )}
                      </div>
                    </div>
                    <p className="text-slate-800 leading-relaxed font-sans">{claim.text}</p>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="bg-slate-50 border border-dashed border-slate-300 rounded-lg p-6 text-center text-xs text-slate-500">
                {isStreaming ? (
                  <span className="flex items-center justify-center space-x-2 text-sky-600 animate-pulse">
                    <Activity className="w-4 h-4 animate-spin" />
                    <span>Decomposing response into atomic claims...</span>
                  </span>
                ) : (
                  <span>Awaiting submission to extract atomic claims.</span>
                )}
              </div>
            )}
          </div>

          {/* Stage 2: Multi-Signal Verification Attribution */}
          <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs space-y-3">
            <h3 className="text-xs font-bold text-slate-900 flex items-center space-x-2 uppercase tracking-wider">
              <Activity className="w-4 h-4 text-emerald-600" aria-hidden="true" />
              <span>2. Multi-Signal Verification & Attribution</span>
            </h3>

            {signals ? (
              <div className="space-y-4">
                {/* Signal attribution scores across all active verification signals */}
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
                  {Object.entries(signals.signalAttribution || {})
                    .sort(([a], [b]) => {
                      const order = ["rav", "scs", "nli", "ics", "vgs"];
                      const idxA = order.indexOf(a.toLowerCase());
                      const idxB = order.indexOf(b.toLowerCase());
                      if (idxA !== -1 && idxB !== -1) return idxA - idxB;
                      if (idxA !== -1) return -1;
                      if (idxB !== -1) return 1;
                      return a.localeCompare(b);
                    })
                    .map(([key, val]) => (
                      <div
                        key={key}
                        className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-center"
                      >
                        <span className="block text-[10px] font-mono uppercase text-slate-500 mb-1">
                          {key}
                        </span>
                        <span className="text-base font-bold font-mono text-slate-900">
                          {typeof val === "number"
                            ? val.toFixed(3)
                            : val === null || val === undefined
                            ? "N/A"
                            : String(val)}
                        </span>
                      </div>
                    ))}
                </div>

                {/* Contradicted Claims Alert */}
                {signals.contradictedClaims && signals.contradictedClaims.length > 0 ? (
                  <div
                    role="alert"
                    className="bg-rose-50 border border-rose-200 rounded-lg p-3 text-xs text-rose-800 flex items-center space-x-2"
                  >
                    <AlertTriangle className="w-4 h-4 text-rose-600 flex-shrink-0" />
                    <span>
                      Contradictions detected in claims:{" "}
                      <strong className="font-mono text-rose-900">
                        {signals.contradictedClaims.join(", ")}
                      </strong>
                    </span>
                  </div>
                ) : (
                  <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-2.5 text-xs text-emerald-800 flex items-center space-x-2">
                    <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                    <span>All decomposed claims consistent with retrieved knowledge.</span>
                  </div>
                )}
              </div>
            ) : (
              <div className="bg-slate-50 border border-dashed border-slate-300 rounded-lg p-6 text-center text-xs text-slate-500">
                {isStreaming && claims.length > 0 ? (
                  <span className="flex items-center justify-center space-x-2 text-emerald-600 animate-pulse">
                    <Activity className="w-4 h-4 animate-spin" />
                    <span>Computing RAV, SCS, NLI, ICS, and VGS verification signals...</span>
                  </span>
                ) : (
                  <span>Awaiting signal verification processing.</span>
                )}
              </div>
            )}
          </div>

          {/* Stage 3: Final Verification Verdict */}
          <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs space-y-4">
            <h3 className="text-xs font-bold text-slate-900 flex items-center space-x-2 uppercase tracking-wider">
              <ShieldCheck className="w-4 h-4 text-amber-600" aria-hidden="true" />
              <span>3. Calibrated Risk Verdict (HRS Engine)</span>
            </h3>

            {verdict ? (
              <div className="space-y-4">
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  {/* Calibrated HRS Score */}
                  <div className="bg-slate-50 border border-slate-200 rounded-lg p-4 text-center">
                    <span className="block text-xs font-medium text-slate-500 mb-1">
                      Hallucination Risk Score
                    </span>
                    <span className="text-2xl font-black font-mono text-slate-900">
                      {typeof verdict.hrsScore === "number"
                        ? verdict.hrsScore.toFixed(3)
                        : "N/A"}
                    </span>
                  </div>

                  {/* Risk Tier Badge */}
                  <div className="bg-slate-50 border border-slate-200 rounded-lg p-4 text-center">
                    <span className="block text-xs font-medium text-slate-500 mb-1">
                      Risk Tier
                    </span>
                    <span
                      className={`inline-block px-3 py-1 rounded text-xs font-mono font-bold border ${getRiskTierBadge(
                        verdict.riskTier
                      )}`}
                    >
                      {verdict.riskTier || "UNKNOWN"}
                    </span>
                  </div>

                  {/* Conformal Prediction Interval */}
                  <div className="bg-slate-50 border border-slate-200 rounded-lg p-4 text-center">
                    <span className="block text-xs font-medium text-slate-500 mb-1">
                      Conformal Interval (95%)
                    </span>
                    <span className="text-xs font-mono text-sky-700 font-semibold">
                      {verdict.conformalInterval
                        ? `[${Number(verdict.conformalInterval.lower).toFixed(3)}, ${Number(
                            verdict.conformalInterval.upper
                          ).toFixed(3)}]`
                        : "N/A"}
                    </span>
                  </div>
                </div>

                {/* Correction status & verified response */}
                {verdict.correctionApplied && (
                  <div className="bg-sky-50 border border-sky-200 rounded-lg p-3 text-xs space-y-2">
                    <div className="flex items-center space-x-2 text-sky-800 font-semibold">
                      <Sparkles className="w-4 h-4 text-sky-600" />
                      <span>Correction Loop Applied</span>
                    </div>
                    {verdict.verifiedResponse && (
                      <p className="text-slate-800 font-mono text-xs bg-white p-2.5 rounded border border-slate-200">
                        {verdict.verifiedResponse}
                      </p>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <div className="bg-slate-50 border border-dashed border-slate-300 rounded-lg p-6 text-center text-xs text-slate-500">
                {isStreaming && signals ? (
                  <span className="flex items-center justify-center space-x-2 text-amber-600 animate-pulse">
                    <Activity className="w-4 h-4 animate-spin" />
                    <span>Aggregating signals and calibrating conformal prediction interval...</span>
                  </span>
                ) : (
                  <span>Awaiting final verification complete verdict.</span>
                )}
              </div>
            )}
          </div>
        </section>
      </div>

      {/* Progressive Event Stream Audit Feed */}
      <section
        aria-labelledby="event-log-heading"
        className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs space-y-3"
      >
        <div className="flex items-center justify-between">
          <h2 id="event-log-heading" className="text-xs font-bold text-slate-900 flex items-center space-x-2 uppercase tracking-wider">
            <Clock className="w-4 h-4 text-slate-500" aria-hidden="true" />
            <span>Progressive Event Stream Audit ({events.length})</span>
          </h2>
          <button
            type="button"
            onClick={() => setShowEventLog(!showEventLog)}
            className="text-xs text-slate-500 hover:text-slate-800 underline focus:outline-none"
          >
            {showEventLog ? "Hide Log" : "Show Log"}
          </button>
        </div>

        {showEventLog && (
          <div className="bg-slate-50 border border-slate-200 rounded-lg p-4 max-h-56 overflow-y-auto font-mono text-xs space-y-2">
            {events.length > 0 ? (
              events.map((ev) => (
                <div key={ev.id} className="flex items-start space-x-3 text-slate-600 text-[11px]">
                  <span className="text-slate-500 flex-shrink-0">
                    {formatEventTime(ev.timestamp)}
                  </span>
                  <span className="px-1.5 py-0.5 rounded text-[10px] bg-white text-sky-700 border border-slate-200 flex-shrink-0">
                    {ev.eventType}
                  </span>
                  <span className="text-slate-800 truncate">
                    {JSON.stringify(ev.data)}
                  </span>
                </div>
              ))
            ) : (
              <p className="text-slate-500 text-center py-4">
                No stream events recorded yet. Connect to stream and submit a response.
              </p>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

export default LiveStreamView;
