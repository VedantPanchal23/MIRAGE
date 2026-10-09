import React, { useState, useContext } from "react";
import {
  CheckCircle,
  XCircle,
  AlertTriangle,
  Activity,
  ShieldCheck,
  Send,
  Eye,
  Clock,
  Database,
  Globe,
  Radio,
  FileCheck,
  Layers,
  Sparkles,
} from "lucide-react";
import { verifyActionOutcome, reconcileOutputAndOutcome } from "../api/outcomes";
import { AuthContext } from "../context/AuthContext";

/**
 * Gate 5 Outcome Assurance & Reality Verification View.
 *
 * Implements MIRAGE 3.0 Gate 5 Reality Verification:
 * - Direct state inspection across 4 epistemic observability classes (OBS_DIRECT, OBS_EVENTUAL, OBS_INFERRED, OBS_BLIND).
 * - Canonical 7 outcome statuses (SUCCESS_CONFIRMED, SUCCESS_EVENTUALLY_OBSERVED, ACKNOWLEDGED_UNVERIFIED, etc.).
 * - Epistemic Invariant enforcement: Request accepted != Tool acknowledged != Final state verified.
 * - Cryptographic SHA-256 tamper-evident verification hashing.
 * - Output <-> Outcome consistency reconciliation.
 */
export function OutcomeAssuranceView({ isRefreshing, onDataLoaded }) {
  const { tenantId } = useContext(AuthContext);

  // Form state
  const [transactionId, setTransactionId] = useState("txn_demo_default");
  const [actionId, setActionId] = useState("act_demo_default");
  const [observabilityClass, setObservabilityClass] = useState("OBS_DIRECT");
  const [verifierType, setVerifierType] = useState("SIMULATED");
  const [expectedPostconditions, setExpectedPostconditions] = useState(
    JSON.stringify({ status: "ACTIVE", updated: true }, null, 2)
  );
  const [adapterConfig, setAdapterConfig] = useState(
    JSON.stringify({ simulated_state: { status: "ACTIVE", updated: true } }, null, 2)
  );

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [verificationResult, setVerificationResult] = useState(null);

  // Reconciliation state
  const [reconcileOutcomeId, setReconcileOutcomeId] = useState("");
  const [reconcileText, setReconcileText] = useState(
    "The funds have reached the recipient and the wire transfer has been processed."
  );
  const [reconcileLoading, setReconcileLoading] = useState(false);
  const [reconcileResult, setReconcileResult] = useState(null);

  const handleVerify = async (e) => {
    if (e) e.preventDefault();
    setLoading(true);
    setError(null);
    setVerificationResult(null);

    try {
      let parsedPostconditions = {};
      let parsedConfig = {};

      try {
        parsedPostconditions = JSON.parse(expectedPostconditions);
      } catch (err) {
        throw new Error("Invalid JSON in Expected Postconditions");
      }

      try {
        parsedConfig = JSON.parse(adapterConfig);
      } catch (err) {
        throw new Error("Invalid JSON in Adapter Config");
      }

      const payload = {
        transaction_id: transactionId,
        action_id: actionId,
        observability_class: observabilityClass,
        verifier_type: verifierType,
        expected_postconditions: parsedPostconditions,
        adapter_config: parsedConfig,
      };

      const res = await verifyActionOutcome(payload);
      setVerificationResult(res);
      setReconcileOutcomeId(res.outcome_id);
    } catch (err) {
      setError(err.message || "Failed to execute reality verification");
    } finally {
      setLoading(false);
    }
  };

  const handleReconcile = async (e) => {
    if (e) e.preventDefault();
    if (!reconcileOutcomeId) {
      setError("Please run a verification probe or enter an Outcome ID first");
      return;
    }

    setReconcileLoading(true);
    setError(null);
    try {
      const res = await reconcileOutputAndOutcome({
        outcome_id: reconcileOutcomeId,
        response_text: reconcileText,
      });
      setReconcileResult(res);
    } catch (err) {
      setError(err.message || "Reconciliation failed");
    } finally {
      setReconcileLoading(false);
    }
  };

  const getStatusBadge = (status) => {
    switch (status) {
      case "SUCCESS_CONFIRMED":
      case "SUCCESS_EVENTUALLY_OBSERVED":
        return {
          bg: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
          icon: <CheckCircle className="w-4 h-4 mr-1.5" />,
          label: status,
        };
      case "ACKNOWLEDGED_UNVERIFIED":
        return {
          bg: "bg-amber-500/10 text-amber-400 border-amber-500/30",
          icon: <Clock className="w-4 h-4 mr-1.5" />,
          label: "ACKNOWLEDGED_UNVERIFIED (Transport ACK Only)",
        };
      case "UNOBSERVABLE":
        return {
          bg: "bg-zinc-500/10 text-zinc-400 border-zinc-500/30",
          icon: <Eye className="w-4 h-4 mr-1.5" />,
          label: "UNOBSERVABLE (Write-Only Sink)",
        };
      case "FAILED":
        return {
          bg: "bg-rose-500/10 text-rose-400 border-rose-500/30",
          icon: <XCircle className="w-4 h-4 mr-1.5" />,
          label: status,
        };
      default:
        return {
          bg: "bg-blue-500/10 text-blue-400 border-blue-500/30",
          icon: <Activity className="w-4 h-4 mr-1.5" />,
          label: status,
        };
    }
  };

  return (
    <div className="space-y-6">
      {/* Top Banner */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 p-6 rounded-2xl bg-zinc-900/60 border border-zinc-800 shadow-xl backdrop-blur-sm">
        <div>
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-purple-500/10 border border-purple-500/20 text-purple-400">
              <Eye className="w-6 h-6" />
            </div>
            <div>
              <h1 className="text-xl font-semibold text-zinc-100 flex items-center gap-2">
                Gate 5 — Outcome Assurance & Reality Verification
                <span className="text-xs px-2.5 py-0.5 rounded-full font-medium bg-purple-500/10 text-purple-400 border border-purple-500/20">
                  Execution Plane
                </span>
              </h1>
              <p className="text-sm text-zinc-400 mt-0.5">
                Verify actual state changes in real systems. Distinguish transport acknowledgment from verified reality.
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2 text-xs font-mono text-zinc-400 bg-zinc-950/60 px-3 py-2 rounded-xl border border-zinc-800">
          <ShieldCheck className="w-4 h-4 text-emerald-400" />
          <span>Tenant: {tenantId || "default"}</span>
        </div>
      </div>

      {/* Epistemic Model Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="p-4 rounded-xl bg-zinc-900/40 border border-zinc-800/80">
          <div className="flex items-center gap-2 text-emerald-400 text-sm font-medium mb-1">
            <Database className="w-4 h-4" />
            <span>OBS_DIRECT</span>
          </div>
          <p className="text-xs text-zinc-400">Synchronous direct read (SQL ACID, consistent REST GET). Confidence: 0.95 - 1.00</p>
        </div>

        <div className="p-4 rounded-xl bg-zinc-900/40 border border-zinc-800/80">
          <div className="flex items-center gap-2 text-cyan-400 text-sm font-medium mb-1">
            <Radio className="w-4 h-4" />
            <span>OBS_EVENTUAL</span>
          </div>
          <p className="text-xs text-zinc-400">Asynchronously observable with lag (S3, queues, indexers). Bounded polling with backoff.</p>
        </div>

        <div className="p-4 rounded-xl bg-zinc-900/40 border border-zinc-800/80">
          <div className="flex items-center gap-2 text-amber-400 text-sm font-medium mb-1">
            <Globe className="w-4 h-4" />
            <span>OBS_INFERRED</span>
          </div>
          <p className="text-xs text-zinc-400">Transport-acknowledged only (HTTP 200, Stripe intent, Jira webhook). Confidence: 0.40 - 0.60</p>
        </div>

        <div className="p-4 rounded-xl bg-zinc-900/40 border border-zinc-800/80">
          <div className="flex items-center gap-2 text-zinc-400 text-sm font-medium mb-1">
            <Eye className="w-4 h-4" />
            <span>OBS_BLIND</span>
          </div>
          <p className="text-xs text-zinc-500">Write-only sink with zero readback (UDP syslog, unmonitored SMTP). Confidence: strictly 0.0</p>
        </div>
      </div>

      {/* Main Grid: Probe Form + Live Results */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left: Reality Verification Probe */}
        <div className="lg:col-span-6 space-y-6">
          <div className="p-6 rounded-2xl bg-zinc-900/50 border border-zinc-800 shadow-lg space-y-5">
            <div className="flex items-center justify-between border-b border-zinc-800/80 pb-4">
              <div className="flex items-center gap-2 text-zinc-200 font-medium text-sm">
                <FileCheck className="w-4 h-4 text-purple-400" />
                <span>Reality Verification Probe</span>
              </div>
              <span className="text-xs text-zinc-500 font-mono">Gate 5 Engine</span>
            </div>

            {error && (
              <div className="p-3.5 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400 text-xs flex items-start gap-2">
                <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                <span>{error}</span>
              </div>
            )}

            <form onSubmit={handleVerify} className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-zinc-400 mb-1">Transaction ID</label>
                  <input
                    type="text"
                    value={transactionId}
                    onChange={(e) => setTransactionId(e.target.value)}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-xl px-3 py-2 text-xs text-zinc-200 focus:outline-none focus:border-purple-500"
                    required
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-zinc-400 mb-1">Action ID</label>
                  <input
                    type="text"
                    value={actionId}
                    onChange={(e) => setActionId(e.target.value)}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-xl px-3 py-2 text-xs text-zinc-200 focus:outline-none focus:border-purple-500"
                    required
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-zinc-400 mb-1">Observability Class</label>
                  <select
                    value={observabilityClass}
                    onChange={(e) => setObservabilityClass(e.target.value)}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-xl px-3 py-2 text-xs text-zinc-200 focus:outline-none focus:border-purple-500"
                  >
                    <option value="OBS_DIRECT">OBS_DIRECT (Direct Read)</option>
                    <option value="OBS_EVENTUAL">OBS_EVENTUAL (Async Polling)</option>
                    <option value="OBS_INFERRED">OBS_INFERRED (Transport ACK)</option>
                    <option value="OBS_BLIND">OBS_BLIND (Write-Only)</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-zinc-400 mb-1">Verifier Adapter</label>
                  <select
                    value={verifierType}
                    onChange={(e) => setVerifierType(e.target.value)}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-xl px-3 py-2 text-xs text-zinc-200 focus:outline-none focus:border-purple-500"
                  >
                    <option value="SIMULATED">SIMULATED (Testbed)</option>
                    <option value="DATABASE">DATABASE (PostgreSQL State)</option>
                    <option value="HTTP_RESOURCE">HTTP_RESOURCE (REST GET)</option>
                    <option value="ASYNC_EVENT">ASYNC_EVENT (Backoff Poller)</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-zinc-400 mb-1">Expected Postconditions (JSON)</label>
                <textarea
                  value={expectedPostconditions}
                  onChange={(e) => setExpectedPostconditions(e.target.value)}
                  rows={3}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-xl p-3 text-xs font-mono text-zinc-300 focus:outline-none focus:border-purple-500"
                  required
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-zinc-400 mb-1">Adapter Configuration (JSON)</label>
                <textarea
                  value={adapterConfig}
                  onChange={(e) => setAdapterConfig(e.target.value)}
                  rows={3}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-xl p-3 text-xs font-mono text-zinc-300 focus:outline-none focus:border-purple-500"
                  required
                />
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full py-2.5 px-4 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white rounded-xl text-xs font-medium transition-colors flex items-center justify-center gap-2 shadow-lg shadow-purple-600/20"
              >
                {loading ? (
                  <>
                    <Activity className="w-4 h-4 animate-spin" />
                    <span>Executing Reality Probe...</span>
                  </>
                ) : (
                  <>
                    <Send className="w-4 h-4" />
                    <span>Execute Reality Verification Probe</span>
                  </>
                )}
              </button>
            </form>
          </div>

          {/* Output <-> Outcome Reconciliation Test */}
          <div className="p-6 rounded-2xl bg-zinc-900/50 border border-zinc-800 shadow-lg space-y-4">
            <div className="flex items-center justify-between border-b border-zinc-800/80 pb-3">
              <div className="flex items-center gap-2 text-zinc-200 font-medium text-sm">
                <Sparkles className="w-4 h-4 text-cyan-400" />
                <span>Output ↔ Outcome Consistency Interlock</span>
              </div>
              <span className="text-xs text-zinc-500">Epistemic Check</span>
            </div>

            <p className="text-xs text-zinc-400">
              Validates whether AI generated output honestly reflects verified reality or makes ungrounded claims of external success.
            </p>

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-zinc-400 mb-1">Outcome ID to Reconcile</label>
                <input
                  type="text"
                  value={reconcileOutcomeId}
                  onChange={(e) => setReconcileOutcomeId(e.target.value)}
                  placeholder="outc_..."
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-xl px-3 py-2 text-xs text-zinc-200 focus:outline-none focus:border-cyan-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-zinc-400 mb-1">Model Response Text</label>
                <textarea
                  value={reconcileText}
                  onChange={(e) => setReconcileText(e.target.value)}
                  rows={2}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-xl p-3 text-xs text-zinc-300 focus:outline-none focus:border-cyan-500"
                />
              </div>

              <button
                onClick={handleReconcile}
                disabled={reconcileLoading}
                className="w-full py-2 px-4 bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-white rounded-xl text-xs font-medium transition-colors flex items-center justify-center gap-2"
              >
                {reconcileLoading ? "Evaluating Consistency..." : "Check Output Consistency Against Reality"}
              </button>

              {reconcileResult && (
                <div
                  className={`p-4 rounded-xl border text-xs space-y-2 ${
                    reconcileResult.is_consistent
                      ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-300"
                      : "bg-rose-500/10 border-rose-500/30 text-rose-300"
                  }`}
                >
                  <div className="flex items-center justify-between font-semibold">
                    <span className="flex items-center gap-1.5">
                      {reconcileResult.is_consistent ? (
                        <CheckCircle className="w-4 h-4 text-emerald-400" />
                      ) : (
                        <XCircle className="w-4 h-4 text-rose-400" />
                      )}
                      {reconcileResult.is_consistent
                        ? "Claims Grounded in Reality"
                        : "Epistemic Conflict Detected"}
                    </span>
                    <span className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full bg-zinc-950/40 border">
                      Disposition: {reconcileResult.recommended_disposition}
                    </span>
                  </div>

                  {reconcileResult.conflict_reasons?.map((reason, idx) => (
                    <p key={idx} className="text-xs text-rose-200 mt-1">
                      {reason}
                    </p>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Right: Live Reality Verification Contract */}
        <div className="lg:col-span-6 space-y-6">
          <div className="p-6 rounded-2xl bg-zinc-900/50 border border-zinc-800 shadow-lg min-h-[500px]">
            <div className="flex items-center justify-between border-b border-zinc-800/80 pb-4 mb-5">
              <div className="flex items-center gap-2 text-zinc-200 font-medium text-sm">
                <ShieldCheck className="w-4 h-4 text-emerald-400" />
                <span>Gate 5 Outcome Assurance Contract</span>
              </div>
              <span className="text-xs text-zinc-500 font-mono">Authoritative Ledger</span>
            </div>

            {!verificationResult ? (
              <div className="flex flex-col items-center justify-center h-80 text-center text-zinc-500 space-y-3">
                <Layers className="w-12 h-12 stroke-[1.5] text-zinc-600" />
                <div>
                  <p className="text-sm font-medium text-zinc-400">No Outcome Verification Executed Yet</p>
                  <p className="text-xs text-zinc-500 mt-1 max-w-sm">
                    Submit the reality verification probe to test direct state inspection, eventual consistency, or transport acknowledgment.
                  </p>
                </div>
              </div>
            ) : (
              <div className="space-y-5">
                {/* Status and Confidence */}
                <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 p-4 rounded-xl bg-zinc-950 border border-zinc-800">
                  <div className="flex items-center gap-2">
                    {(() => {
                      const badge = getStatusBadge(verificationResult.outcome_status);
                      return (
                        <div
                          className={`inline-flex items-center text-xs font-semibold px-3 py-1.5 rounded-xl border ${badge.bg}`}
                        >
                          {badge.icon}
                          <span>{badge.label}</span>
                        </div>
                      );
                    })()}
                  </div>

                  <div className="flex items-center gap-4 text-xs">
                    <div>
                      <span className="text-zinc-500">Confidence:</span>{" "}
                      <span className="font-mono font-semibold text-zinc-200">
                        {(verificationResult.epistemic_confidence * 100).toFixed(1)}%
                      </span>
                    </div>
                    {verificationResult.is_simulated && (
                      <span className="px-2 py-0.5 rounded-md bg-amber-500/10 text-amber-400 border border-amber-500/20 text-[10px] font-mono">
                        SIMULATED
                      </span>
                    )}
                  </div>
                </div>

                {/* Metadata Grid */}
                <div className="grid grid-cols-2 gap-3 text-xs bg-zinc-950/60 p-4 rounded-xl border border-zinc-800/80 font-mono">
                  <div>
                    <span className="text-zinc-500">Outcome ID:</span>
                    <p className="text-zinc-300 truncate mt-0.5">{verificationResult.outcome_id}</p>
                  </div>
                  <div>
                    <span className="text-zinc-500">Observability:</span>
                    <p className="text-zinc-300 truncate mt-0.5">{verificationResult.observability_class}</p>
                  </div>
                  <div>
                    <span className="text-zinc-500">Adapter:</span>
                    <p className="text-zinc-300 truncate mt-0.5">{verificationResult.verifier_adapter}</p>
                  </div>
                  <div>
                    <span className="text-zinc-500">Environment:</span>
                    <p className="text-zinc-300 truncate mt-0.5">{verificationResult.target_environment || "DEFAULT"}</p>
                  </div>
                  <div>
                    <span className="text-zinc-500">Idempotency Key:</span>
                    <p className="text-zinc-300 truncate mt-0.5">{verificationResult.idempotency_key || "N/A"}</p>
                  </div>
                  <div>
                    <span className="text-zinc-500">Verified At:</span>
                    <p className="text-zinc-300 truncate mt-0.5">
                      {new Date(verificationResult.verified_at).toLocaleTimeString()}
                    </p>
                  </div>
                </div>

                {/* State Diff / Discrepancies */}
                <div>
                  <h3 className="text-xs font-semibold text-zinc-300 mb-2 flex items-center justify-between">
                    <span>Observed State vs Postconditions</span>
                    <span className="text-[10px] text-zinc-500 font-mono">
                      {verificationResult.discrepancies?.length || 0} Discrepancies
                    </span>
                  </h3>
                  <div className="p-3 bg-zinc-950 rounded-xl border border-zinc-800 font-mono text-[11px] text-zinc-300 max-h-40 overflow-y-auto">
                    <pre>{JSON.stringify(verificationResult.observed_state, null, 2)}</pre>
                  </div>
                </div>

                {/* Caveats and Reconciliation Notes */}
                {verificationResult.reconciliation_notes?.length > 0 && (
                  <div className="p-3.5 rounded-xl bg-zinc-950 border border-zinc-800 text-xs space-y-1.5">
                    <span className="font-semibold text-zinc-400 text-[11px]">Epistemic Invariant Caveats:</span>
                    {verificationResult.reconciliation_notes.map((note, idx) => (
                      <p key={idx} className="text-zinc-400 text-xs flex items-start gap-1.5">
                        <span className="text-purple-400 mt-0.5">•</span>
                        <span>{note}</span>
                      </p>
                    ))}
                  </div>
                )}

                {/* Cryptographic Hash */}
                <div className="p-3 bg-zinc-950 rounded-xl border border-zinc-800 text-xs font-mono">
                  <div className="flex items-center justify-between text-zinc-500 text-[10px] mb-1">
                    <span>Cryptographic Seal (SHA-256):</span>
                    <span>TAMPER-EVIDENT</span>
                  </div>
                  <p className="text-emerald-400 truncate text-[11px]">{verificationResult.verification_hash}</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
export default OutcomeAssuranceView;
