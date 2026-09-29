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
  ShieldAlert,
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
      return "text-purple-400 bg-purple-950/80 border-purple-800";
    case "HIGH":
      return "text-rose-400 bg-rose-950/80 border-rose-800";
    case "MEDIUM":
      return "text-amber-400 bg-amber-950/80 border-amber-800";
    case "LOW":
    default:
      return "text-emerald-400 bg-emerald-950/80 border-emerald-800";
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
        className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4"
      >
        <div>
          <div className="flex items-center space-x-3 mb-1">
            <Radio className="w-5 h-5 text-sky-400 animate-pulse" aria-hidden="true" />
            <h1 id="stream-heading" className="text-xl font-bold text-white tracking-tight">
              Live Verification Stream
            </h1>
          </div>
          <p className="text-xs text-slate-400">
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
              <span className="flex items-center space-x-1.5 text-emerald-400 bg-emerald-950/40 border-emerald-800/60 px-2 py-0.5 rounded">
                <Wifi className="w-3.5 h-3.5" aria-hidden="true" />
                <span>Ready (Authenticated)</span>
              </span>
            )}
            {status === STREAM_STATUS.STREAMING && (
              <span className="flex items-center space-x-1.5 text-sky-400 bg-sky-950/40 border-sky-800/60 px-2 py-0.5 rounded animate-pulse">
                <Activity className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
                <span>Verifying Stream...</span>
              </span>
            )}
            {status === STREAM_STATUS.COMPLETED && (
              <span className="flex items-center space-x-1.5 text-emerald-300 bg-emerald-950/40 border-emerald-800/60 px-2 py-0.5 rounded">
                <CheckCircle2 className="w-3.5 h-3.5" aria-hidden="true" />
                <span>Verification Complete</span>
              </span>
            )}
            {status === STREAM_STATUS.CONNECTING && (
              <span className="flex items-center space-x-1.5 text-amber-400 bg-amber-950/40 border-amber-800/60 px-2 py-0.5 rounded">
                <Wifi className="w-3.5 h-3.5 animate-pulse" aria-hidden="true" />
                <span>Connecting...</span>
              </span>
            )}
            {status === STREAM_STATUS.AWAITING_AUTH && (
              <span className="flex items-center space-x-1.5 text-sky-400 bg-sky-950/40 border-sky-800/60 px-2 py-0.5 rounded">
                <Cpu className="w-3.5 h-3.5 animate-pulse" aria-hidden="true" />
                <span>Authenticating JWT...</span>
              </span>
            )}
            {status === STREAM_STATUS.DISCONNECTED && (
              <span className="flex items-center space-x-1.5 text-slate-400 bg-slate-800/60 border-slate-700 px-2 py-0.5 rounded">
                <WifiOff className="w-3.5 h-3.5" aria-hidden="true" />
                <span>Disconnected</span>
              </span>
            )}
            {status === STREAM_STATUS.ERROR && (
              <span className="flex items-center space-x-1.5 text-rose-400 bg-rose-950/40 border-rose-800/60 px-2 py-0.5 rounded">
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
              className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-sky-600 hover:bg-sky-500 text-white transition focus:outline-none focus:ring-2 focus:ring-sky-500"
            >
              <Wifi className="w-3.5 h-3.5" aria-hidden="true" />
              <span>Connect</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={disconnect}
              disabled={isStreaming}
              className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition disabled:opacity-50"
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
            className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition disabled:opacity-40"
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
          className="bg-slate-900/60 border border-slate-800 rounded-lg px-4 py-2.5 text-xs flex flex-wrap items-center justify-between gap-3 text-slate-400"
        >
          <div className="flex items-center space-x-4">
            <span>
              Authoritative Tenant:{" "}
              <strong className="text-white font-mono">{sessionInfo.tenantId || tenantId}</strong>
            </span>
            <span>
              Role:{" "}
              <strong className="text-sky-300 font-mono">{sessionInfo.role || role}</strong>
            </span>
          </div>
          {sessionInfo.traceId && (
            <div className="font-mono text-slate-500 text-[11px]">
              Trace: <span className="text-slate-400">{sessionInfo.traceId.slice(0, 12)}...</span>
            </div>
          )}
        </div>
      )}

      {/* Error Banner */}
      {error && (
        <div
          role="alert"
          className="bg-rose-950/60 border border-rose-800/80 rounded-xl p-4 text-xs text-rose-300 flex items-start space-x-3 shadow-md"
        >
          <AlertCircle className="w-4 h-4 text-rose-400 flex-shrink-0 mt-0.5" aria-hidden="true" />
          <div className="flex-1">
            <strong className="block font-semibold text-rose-200 mb-0.5">Stream Error:</strong>
            <span>{error}</span>
          </div>
        </div>
      )}

      {/* Main Workspace Grid: Input Form vs. Progressive Results */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Verification Submission Form (Left 5 Cols) */}
        <section
          aria-labelledby="submission-heading"
          className="lg:col-span-5 bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-4"
        >
          <h2 id="submission-heading" className="text-sm font-bold text-white flex items-center space-x-2">
            <Send className="w-4 h-4 text-sky-400" aria-hidden="true" />
            <span>Verification Submission</span>
          </h2>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="stream-prompt" className="block text-xs font-medium text-slate-300 mb-1">
                Prompt / Query (Optional context)
              </label>
              <textarea
                id="stream-prompt"
                rows={3}
                value={promptInput}
                onChange={(e) => setPromptInput(e.target.value)}
                placeholder="Enter prompt or query context..."
                disabled={isStreaming}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-sky-500 disabled:opacity-50"
              />
            </div>

            <div>
              <label htmlFor="stream-response" className="block text-xs font-medium text-slate-300 mb-1">
                LLM Response to Verify <span className="text-rose-400">*</span>
              </label>
              <textarea
                id="stream-response"
                rows={5}
                required
                value={responseInput}
                onChange={(e) => setResponseInput(e.target.value)}
                placeholder="Enter or paste the model output to verify propositions..."
                disabled={isStreaming}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-sky-500 disabled:opacity-50"
              />
            </div>

            <div>
              <label htmlFor="stream-model" className="block text-xs font-medium text-slate-300 mb-1">
                Originating Model ID
              </label>
              <input
                id="stream-model"
                type="text"
                value={modelIdInput}
                onChange={(e) => setModelIdInput(e.target.value)}
                placeholder="e.g. gpt-4o, claude-3-5-sonnet"
                disabled={isStreaming}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-sky-500 disabled:opacity-50 font-mono"
              />
            </div>

            <div className="pt-2">
              <button
                type="submit"
                disabled={!isReadyToSubmit}
                className="w-full py-2.5 px-4 rounded-lg text-xs font-semibold text-white bg-sky-600 hover:bg-sky-500 disabled:bg-slate-800 disabled:text-slate-500 disabled:cursor-not-allowed transition flex items-center justify-center space-x-2 shadow-sm"
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
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-bold text-white flex items-center space-x-2 uppercase tracking-wider">
                <Layers className="w-4 h-4 text-sky-400" aria-hidden="true" />
                <span>1. Atomic Claims Decomposition (FLAN-T5)</span>
              </h3>
              {claims.length > 0 && (
                <span className="text-xs font-mono px-2 py-0.5 bg-sky-950 text-sky-300 border border-sky-800 rounded-md">
                  {claims.length} {claims.length === 1 ? "claim" : "claims"}
                </span>
              )}
            </div>

            {claims.length > 0 ? (
              <ul className="space-y-2 max-h-56 overflow-y-auto pr-1">
                {claims.map((claim, idx) => (
                  <li
                    key={claim.claim_id || idx}
                    className="bg-slate-950 border border-slate-800/80 rounded-lg p-3 text-xs space-y-1.5"
                  >
                    <div className="flex items-center justify-between text-[11px]">
                      <span className="font-mono text-slate-400 font-semibold">
                        {claim.claim_id || `C-${idx + 1}`}
                      </span>
                      <div className="flex items-center space-x-1.5">
                        <span className="px-1.5 py-0.5 rounded text-[10px] uppercase font-mono bg-slate-800 text-slate-300 border border-slate-700">
                          {claim.type || "FACTUAL"}
                        </span>
                        {claim.criticality && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] uppercase font-mono bg-amber-950/60 text-amber-300 border border-amber-800">
                            {claim.criticality}
                          </span>
                        )}
                      </div>
                    </div>
                    <p className="text-slate-200 leading-relaxed font-sans">{claim.text}</p>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="bg-slate-950/50 border border-dashed border-slate-800 rounded-lg p-6 text-center text-xs text-slate-500">
                {isStreaming ? (
                  <span className="flex items-center justify-center space-x-2 text-sky-400 animate-pulse">
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
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-3">
            <h3 className="text-xs font-bold text-white flex items-center space-x-2 uppercase tracking-wider">
              <Activity className="w-4 h-4 text-emerald-400" aria-hidden="true" />
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
                        className="bg-slate-950 border border-slate-800 rounded-lg p-3 text-center"
                      >
                        <span className="block text-[10px] font-mono uppercase text-slate-400 mb-1">
                          {key}
                        </span>
                        <span className="text-base font-bold font-mono text-white">
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
                    className="bg-rose-950/40 border border-rose-800/80 rounded-lg p-3 text-xs text-rose-300 flex items-center space-x-2"
                  >
                    <AlertTriangle className="w-4 h-4 text-rose-400 flex-shrink-0" />
                    <span>
                      Contradictions detected in claims:{" "}
                      <strong className="font-mono text-rose-200">
                        {signals.contradictedClaims.join(", ")}
                      </strong>
                    </span>
                  </div>
                ) : (
                  <div className="bg-emerald-950/30 border border-emerald-800/60 rounded-lg p-2.5 text-xs text-emerald-300 flex items-center space-x-2">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                    <span>All decomposed claims consistent with retrieved knowledge.</span>
                  </div>
                )}
              </div>
            ) : (
              <div className="bg-slate-950/50 border border-dashed border-slate-800 rounded-lg p-6 text-center text-xs text-slate-500">
                {isStreaming && claims.length > 0 ? (
                  <span className="flex items-center justify-center space-x-2 text-emerald-400 animate-pulse">
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
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-4">
            <h3 className="text-xs font-bold text-white flex items-center space-x-2 uppercase tracking-wider">
              <ShieldCheck className="w-4 h-4 text-amber-400" aria-hidden="true" />
              <span>3. Calibrated Risk Verdict (HRS Engine)</span>
            </h3>

            {verdict ? (
              <div className="space-y-4">
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  {/* Calibrated HRS Score */}
                  <div className="bg-slate-950 border border-slate-800 rounded-lg p-4 text-center">
                    <span className="block text-xs font-medium text-slate-400 mb-1">
                      Hallucination Risk Score
                    </span>
                    <span className="text-2xl font-black font-mono text-white">
                      {typeof verdict.hrsScore === "number"
                        ? verdict.hrsScore.toFixed(3)
                        : "N/A"}
                    </span>
                  </div>

                  {/* Risk Tier Badge */}
                  <div className="bg-slate-950 border border-slate-800 rounded-lg p-4 text-center">
                    <span className="block text-xs font-medium text-slate-400 mb-1">
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
                  <div className="bg-slate-950 border border-slate-800 rounded-lg p-4 text-center">
                    <span className="block text-xs font-medium text-slate-400 mb-1">
                      Conformal Interval (95%)
                    </span>
                    <span className="text-xs font-mono text-sky-400 font-semibold">
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
                  <div className="bg-sky-950/30 border border-sky-800/60 rounded-lg p-3 text-xs space-y-2">
                    <div className="flex items-center space-x-2 text-sky-300 font-semibold">
                      <Sparkles className="w-4 h-4 text-sky-400" />
                      <span>Correction Loop Applied</span>
                    </div>
                    {verdict.verifiedResponse && (
                      <p className="text-slate-200 font-mono text-xs bg-slate-950 p-2.5 rounded border border-slate-800">
                        {verdict.verifiedResponse}
                      </p>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <div className="bg-slate-950/50 border border-dashed border-slate-800 rounded-lg p-6 text-center text-xs text-slate-500">
                {isStreaming && signals ? (
                  <span className="flex items-center justify-center space-x-2 text-amber-400 animate-pulse">
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
        className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-3"
      >
        <div className="flex items-center justify-between">
          <h2 id="event-log-heading" className="text-xs font-bold text-white flex items-center space-x-2 uppercase tracking-wider">
            <Clock className="w-4 h-4 text-slate-400" aria-hidden="true" />
            <span>Progressive Event Stream Audit ({events.length})</span>
          </h2>
          <button
            type="button"
            onClick={() => setShowEventLog(!showEventLog)}
            className="text-xs text-slate-400 hover:text-slate-200 underline focus:outline-none"
          >
            {showEventLog ? "Hide Log" : "Show Log"}
          </button>
        </div>

        {showEventLog && (
          <div className="bg-slate-950 border border-slate-800 rounded-lg p-4 max-h-56 overflow-y-auto font-mono text-xs space-y-2">
            {events.length > 0 ? (
              events.map((ev) => (
                <div key={ev.id} className="flex items-start space-x-3 text-slate-400 text-[11px]">
                  <span className="text-slate-500 flex-shrink-0">
                    {formatEventTime(ev.timestamp)}
                  </span>
                  <span className="px-1.5 py-0.5 rounded text-[10px] bg-slate-800 text-sky-300 flex-shrink-0">
                    {ev.eventType}
                  </span>
                  <span className="text-slate-300 truncate">
                    {JSON.stringify(ev.data)}
                  </span>
                </div>
              ))
            ) : (
              <p className="text-slate-600 text-center py-4">
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
