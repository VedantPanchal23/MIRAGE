import React, { useState, useEffect, useCallback, useContext } from "react";
import {
  ShieldCheck,
  ShieldAlert,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Activity,
  Send,
  Lock,
  RefreshCw,
  Sliders,
  DollarSign,
  Clock,
  Layers,
  Sparkles,
} from "lucide-react";
import { assureOutput } from "../api/output";
import { AuthContext } from "../context/AuthContext";

/**
 * Gate 4 Output Assurance & Modernized Verification Engine View.
 *
 * Implements MIRAGE 3.0 Gate 4 Output Assurance:
 * - Factual consistency verification via multi-signal verification engine (RAV, SCS, NLI, ICS, VGS).
 * - Holistic Reliability Scoring (HRS) with calibrated Isotonic regression probability.
 * - Mondrian group-conditional conformal prediction intervals.
 * - TreeSHAP feature attribution breakdown.
 * - DLP and safety scanning (secrets, PII, injection leakage, auto-redaction).
 * - Adaptive verification ladder and strict budget enforcement.
 * - LangGraph autonomous correction loop integration for contradicted claims.
 */
export function OutputAssuranceView({ isRefreshing, onDataLoaded }) {
  const { tenantId } = useContext(AuthContext);

  const [prompt, setPrompt] = useState(
    "Who discovered penicillin and where was it discovered?"
  );
  const [responseText, setResponseText] = useState(
    "Alexander Fleming discovered penicillin in 1928 at St. Mary's Hospital in London."
  );
  const [transactionId, setTransactionId] = useState("txn_demo_default");
  const [modelId, setModelId] = useState("allam-2-7b");
  const [autoCorrect, setAutoCorrect] = useState(true);
  const [maxLatencyMs, setMaxLatencyMs] = useState(5000);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [assuranceResult, setAssuranceResult] = useState(null);

  const handleAssureOutput = async (e) => {
    if (e) e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const payload = {
        transaction_id: transactionId,
        model_id: modelId,
        model_version: "1.0.0",
        response_text: responseText,
        prompt: prompt,
        auto_correct: autoCorrect,
        budget: {
          max_cost_dollars: 0.1,
          max_tokens: 4000,
          max_latency_ms: Number(maxLatencyMs),
          max_model_calls: 10,
        },
      };

      const result = await assureOutput(payload);
      setAssuranceResult(result);
      if (onDataLoaded) onDataLoaded(new Date().toLocaleTimeString());
    } catch (err) {
      console.error("Output assurance failed:", err);
      setError(
        err.response?.data?.detail ||
          err.message ||
          "Output assurance evaluation failed"
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isRefreshing) {
      handleAssureOutput();
    }
  }, [isRefreshing]);

  const getTierBadge = (tier) => {
    switch (tier) {
      case "LOW":
        return "bg-emerald-500/20 text-emerald-400 border-emerald-500/30";
      case "MEDIUM":
        return "bg-amber-500/20 text-amber-400 border-amber-500/30";
      case "HIGH":
        return "bg-orange-500/20 text-orange-400 border-orange-500/30";
      case "CRITICAL":
        return "bg-rose-500/20 text-rose-400 border-rose-500/30";
      default:
        return "bg-slate-500/20 text-slate-400 border-slate-500/30";
    }
  };

  const getDecisionBadge = (decision) => {
    switch (decision) {
      case "ALLOW":
        return "bg-emerald-500/20 text-emerald-300 border-emerald-500/40";
      case "ALLOW_WITH_UNCERTAINTY":
        return "bg-blue-500/20 text-blue-300 border-blue-500/40";
      case "REDACT_TRANSFORM":
        return "bg-amber-500/20 text-amber-300 border-amber-500/40";
      case "REQUIRE_HUMAN_REVIEW":
        return "bg-orange-500/20 text-orange-300 border-orange-500/40";
      case "BLOCK":
        return "bg-rose-500/20 text-rose-300 border-rose-500/40";
      default:
        return "bg-slate-500/20 text-slate-300 border-slate-500/40";
    }
  };

  const getStatusBadge = (status) => {
    switch (status) {
      case "VERIFIED":
        return "bg-emerald-500/20 text-emerald-300 border-emerald-500/40";
      case "PARTIALLY_VERIFIED":
        return "bg-amber-500/20 text-amber-300 border-amber-500/40";
      case "UNVERIFIED":
        return "bg-slate-500/20 text-slate-300 border-slate-500/40";
      case "CONTRADICTED":
        return "bg-rose-500/20 text-rose-300 border-rose-500/40";
      case "BLOCKED":
        return "bg-red-600/20 text-red-300 border-red-500/40";
      case "DEGRADED":
        return "bg-purple-500/20 text-purple-300 border-purple-500/40";
      default:
        return "bg-slate-500/20 text-slate-300 border-slate-500/40";
    }
  };

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 relative overflow-hidden">
        <div className="absolute top-0 right-0 w-96 h-96 bg-cyan-500/5 rounded-full blur-3xl -mr-20 -mt-20 pointer-events-none" />
        <div className="relative z-10 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
                Gate 4 Execution Barrier
              </span>
              <span className="text-xs text-slate-400">
                Adaptive Verification Ladder & Output Policy
              </span>
            </div>
            <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-2">
              <ShieldCheck className="w-6 h-6 text-cyan-400" />
              Output Assurance & Verification Engine
            </h1>
            <p className="text-slate-400 text-sm mt-1 max-w-3xl">
              Evaluates AI-generated responses before delivery to users.
              Integrates atomic claim decomposition, DeBERTa NLI grounding,
              Holistic Reliability Scoring (HRS), conformal bounds, and DLP
              scanners.
            </p>
          </div>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-rose-500/10 border border-rose-500/30 rounded-lg text-rose-300 text-sm flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Main Grid: Input Form & Results Panel */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Evaluation Controls */}
        <div className="lg:col-span-5 space-y-6">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <h2 className="text-sm font-semibold text-slate-200 mb-4 flex items-center gap-2">
              <Sliders className="w-4 h-4 text-cyan-400" />
              Assurance Request Parameters
            </h2>

            <form onSubmit={handleAssureOutput} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">
                  Parent Transaction ID
                </label>
                <input
                  type="text"
                  value={transactionId}
                  onChange={(e) => setTransactionId(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-cyan-500"
                  required
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">
                  Model Identifier
                </label>
                <input
                  type="text"
                  value={modelId}
                  onChange={(e) => setModelId(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-cyan-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">
                  Original User Prompt
                </label>
                <textarea
                  rows={2}
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-cyan-500 font-sans"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">
                  Candidate Generated Response
                </label>
                <textarea
                  rows={4}
                  value={responseText}
                  onChange={(e) => setResponseText(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-cyan-500 font-sans"
                  required
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-slate-400 mb-1">
                    Max Latency (ms)
                  </label>
                  <input
                    type="number"
                    value={maxLatencyMs}
                    onChange={(e) => setMaxLatencyMs(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-cyan-500"
                  />
                </div>
                <div className="flex items-center pt-5">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={autoCorrect}
                      onChange={(e) => setAutoCorrect(e.target.checked)}
                      className="rounded bg-slate-950 border-slate-700 text-cyan-500 focus:ring-0"
                    />
                    <span className="text-xs text-slate-300 font-medium">
                      Auto-Correct (LangGraph)
                    </span>
                  </label>
                </div>
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full bg-cyan-600 hover:bg-cyan-500 text-white font-medium py-2.5 px-4 rounded-lg flex items-center justify-center gap-2 transition-colors disabled:opacity-50"
              >
                {loading ? (
                  <RefreshCw className="w-4 h-4 animate-spin" />
                ) : (
                  <Send className="w-4 h-4" />
                )}
                <span>Evaluate Gate 4 Output Assurance</span>
              </button>
            </form>
          </div>
        </div>

        {/* Right Column: Assurance Contract Inspection */}
        <div className="lg:col-span-7 space-y-6">
          {assuranceResult ? (
            <div className="space-y-6">
              {/* Disposition Bar */}
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
                <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
                  <div>
                    <span className="text-xs text-slate-400 uppercase tracking-wider block">
                      Gate 4 Decision
                    </span>
                    <span
                      className={`inline-block px-3 py-1 rounded-full text-sm font-semibold border mt-1 ${getDecisionBadge(
                        assuranceResult.final_decision
                      )}`}
                    >
                      {assuranceResult.final_decision}
                    </span>
                  </div>

                  <div>
                    <span className="text-xs text-slate-400 uppercase tracking-wider block">
                      Verification Status
                    </span>
                    <span
                      className={`inline-block px-3 py-1 rounded-full text-sm font-semibold border mt-1 ${getStatusBadge(
                        assuranceResult.verification_status
                      )}`}
                    >
                      {assuranceResult.verification_status}
                    </span>
                  </div>

                  <div>
                    <span className="text-xs text-slate-400 uppercase tracking-wider block">
                      Risk Tier
                    </span>
                    <span
                      className={`inline-block px-3 py-1 rounded-full text-sm font-semibold border mt-1 ${getTierBadge(
                        assuranceResult.risk_classification
                      )}`}
                    >
                      {assuranceResult.risk_classification} (HRS:{" "}
                      {(assuranceResult.risk_score * 100).toFixed(1)}%)
                    </span>
                  </div>
                </div>

                {/* Conformal Prediction & Attributions */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 pt-3 border-t border-slate-800">
                  <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                    <span className="text-xs text-slate-400 block">
                      Conformal 95% Bound
                    </span>
                    <span className="text-sm font-mono text-cyan-400 font-semibold">
                      [{assuranceResult.conformal_interval.lower.toFixed(3)},{" "}
                      {assuranceResult.conformal_interval.upper.toFixed(3)}]
                    </span>
                  </div>

                  <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                    <span className="text-xs text-slate-400 block">
                      Factual Grounding
                    </span>
                    <span className="text-sm font-mono text-emerald-400 font-semibold">
                      {(
                        assuranceResult.factual_result
                          .factual_consistency_score * 100
                      ).toFixed(1)}
                      %
                    </span>
                  </div>

                  <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                    <span className="text-xs text-slate-400 block">
                      Verification Latency
                    </span>
                    <span className="text-sm font-mono text-slate-200 font-semibold flex items-center gap-1">
                      <Clock className="w-3.5 h-3.5 text-slate-400" />
                      {assuranceResult.budget_consumed.latency_ms.toFixed(1)}ms
                    </span>
                  </div>

                  <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                    <span className="text-xs text-slate-400 block">
                      Assurance Cost
                    </span>
                    <span className="text-sm font-mono text-emerald-400 font-semibold flex items-center gap-1">
                      <DollarSign className="w-3.5 h-3.5" />$
                      {assuranceResult.budget_consumed.cost_dollars.toFixed(4)}
                    </span>
                  </div>
                </div>
              </div>

              {/* Verified Final Text Payload */}
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-semibold text-slate-200 flex items-center gap-2">
                    <Sparkles className="w-4 h-4 text-cyan-400" />
                    Assured Output Payload
                  </h3>
                  {assuranceResult.was_corrected && (
                    <span className="px-2 py-0.5 rounded text-xs bg-amber-500/20 text-amber-300 border border-amber-500/30">
                      Corrected by LangGraph Loop
                    </span>
                  )}
                </div>
                <div className="p-4 bg-slate-950 rounded-lg border border-slate-800 text-sm text-slate-200 font-sans whitespace-pre-wrap leading-relaxed">
                  {assuranceResult.final_output}
                </div>
                <div className="mt-2 text-xs text-slate-500 font-mono flex items-center gap-1">
                  <span>SHA-256 Fingerprint:</span>
                  <span className="text-slate-400 truncate">
                    {assuranceResult.output_hash}
                  </span>
                </div>
              </div>

              {/* Atomic Claims Decomposition */}
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
                <h3 className="text-sm font-semibold text-slate-200 mb-3 flex items-center gap-2">
                  <Layers className="w-4 h-4 text-cyan-400" />
                  Decomposed Atomic Claims ({assuranceResult.claims.length})
                </h3>
                <div className="space-y-3">
                  {assuranceResult.claims.map((cr, idx) => (
                    <div
                      key={idx}
                      className="p-3 bg-slate-950 rounded-lg border border-slate-800 text-xs space-y-2"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-cyan-400 font-semibold">
                          {cr.claim.claim_id} [{cr.claim.claim_type}]
                        </span>
                        <span
                          className={`px-2 py-0.5 rounded text-[11px] font-semibold border ${
                            cr.status === "SUPPORTED"
                              ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30"
                              : cr.status === "CONTRADICTED"
                              ? "bg-rose-500/20 text-rose-400 border-rose-500/30"
                              : "bg-slate-500/20 text-slate-400 border-slate-500/30"
                          }`}
                        >
                          {cr.status}
                        </span>
                      </div>
                      <p className="text-slate-300 font-sans">{cr.claim.text}</p>
                      <div className="flex items-center gap-4 text-slate-400 font-mono text-[11px] pt-1 border-t border-slate-900">
                        <span>Risk: {(cr.risk_score * 100).toFixed(1)}%</span>
                        <span>Weight: {cr.claim.criticality_weight}</span>
                        {cr.evidence_chunks?.length > 0 && (
                          <span className="text-emerald-400">
                            {cr.evidence_chunks.length} evidence chunks
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Adaptive Ladder Path & Safety Scanner Findings */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
                  <h3 className="text-sm font-semibold text-slate-200 mb-3 flex items-center gap-2">
                    <Activity className="w-4 h-4 text-cyan-400" />
                    Adaptive Verification Path
                  </h3>
                  <div className="space-y-2 text-xs font-mono">
                    {assuranceResult.verification_tier_path.map((tier, idx) => (
                      <div
                        key={idx}
                        className="flex items-center gap-2 text-slate-300 bg-slate-950 p-2 rounded border border-slate-800"
                      >
                        <span className="text-cyan-400 font-bold">
                          Step {idx + 1}:
                        </span>
                        <span>{tier}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
                  <h3 className="text-sm font-semibold text-slate-200 mb-3 flex items-center gap-2">
                    <ShieldAlert className="w-4 h-4 text-cyan-400" />
                    DLP & Safety Checks
                  </h3>
                  <div className="space-y-2 text-xs">
                    <div className="flex items-center justify-between p-2 bg-slate-950 rounded border border-slate-800">
                      <span className="text-slate-400">Cryptographic Secrets:</span>
                      <span
                        className={
                          assuranceResult.safety_result.secrets_detected
                            ? "text-rose-400 font-semibold"
                            : "text-emerald-400"
                        }
                      >
                        {assuranceResult.safety_result.secrets_detected
                          ? "DETECTED"
                          : "CLEAN"}
                      </span>
                    </div>

                    <div className="flex items-center justify-between p-2 bg-slate-950 rounded border border-slate-800">
                      <span className="text-slate-400">PII Tokens:</span>
                      <span
                        className={
                          assuranceResult.safety_result.pii_detected
                            ? "text-amber-400 font-semibold"
                            : "text-emerald-400"
                        }
                      >
                        {assuranceResult.safety_result.pii_detected
                          ? "DETECTED"
                          : "CLEAN"}
                      </span>
                    </div>

                    <div className="flex items-center justify-between p-2 bg-slate-950 rounded border border-slate-800">
                      <span className="text-slate-400">Injection Leakage:</span>
                      <span
                        className={
                          assuranceResult.safety_result.prompt_injection_leakage
                            ? "text-rose-400 font-semibold"
                            : "text-emerald-400"
                        }
                      >
                        {assuranceResult.safety_result.prompt_injection_leakage
                          ? "DETECTED"
                          : "CLEAN"}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-12 text-center text-slate-400 flex flex-col items-center justify-center">
              <ShieldCheck className="w-12 h-12 text-slate-600 mb-4" />
              <h3 className="text-lg font-semibold text-slate-300">
                Awaiting Gate 4 Evaluation
              </h3>
              <p className="text-xs text-slate-500 mt-1 max-w-sm">
                Submit an AI completion using the parameters on the left to
                execute the adaptive verification ladder.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
