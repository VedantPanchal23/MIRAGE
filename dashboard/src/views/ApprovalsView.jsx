import React, { useState, useEffect } from "react";
import {
  CheckSquare,
  AlertTriangle,
  AlertCircle,
  CheckCircle,
  XCircle,
  Shield,
  Clock,
  UserCheck,
  Search,
} from "lucide-react";
import { api } from "../api";
import { useAuth } from "../context/AuthContext";

export function ApprovalsView() {
  const { tenantId } = useAuth();
  const [approvals, setApprovals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeApproval, setActiveApproval] = useState(null);
  const [decisionReason, setDecisionReason] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [successMessage, setSuccessMessage] = useState(null);
  const [errorMessage, setErrorMessage] = useState(null);

  useEffect(() => {
    let mounted = true;
    async function loadData() {
      try {
        const res = await api.getPendingApprovals();
        if (mounted && Array.isArray(res) && res.length > 0) {
          setApprovals(res);
          setActiveApproval(res[0]);
        } else if (mounted) {
          setApprovals([]);
          setActiveApproval(null);
        }
      } catch (err) {
        if (mounted) {
          setApprovals([]);
          setActiveApproval(null);
        }
      } finally {
        if (mounted) setLoading(false);
      }
    }
    loadData();
    return () => {
      mounted = false;
    };
  }, [tenantId]);

  const handleGrant = async () => {
    if (!activeApproval) return;
    setIsSubmitting(true);
    setErrorMessage(null);
    try {
      await api.grantApproval(activeApproval.id, decisionReason || "Approved via Operator Dashboard");
      setSuccessMessage(`Approval granted for ${activeApproval.action_id}. Action authorized.`);
      setApprovals((prev) => prev.filter((a) => a.id !== activeApproval.id));
      setActiveApproval(null);
    } catch (err) {
      setErrorMessage(err.message || `Failed to grant approval for ${activeApproval.action_id}`);
    } finally {
      setIsSubmitting(false);
      setDecisionReason("");
    }
  };

  const handleDeny = async () => {
    if (!activeApproval) return;
    setIsSubmitting(true);
    setErrorMessage(null);
    try {
      await api.denyApproval(activeApproval.id, decisionReason || "Denied via Operator Dashboard");
      setSuccessMessage(`Action ${activeApproval.action_id} denied and terminated.`);
      setApprovals((prev) => prev.filter((a) => a.id !== activeApproval.id));
      setActiveApproval(null);
    } catch (err) {
      setErrorMessage(err.message || `Failed to deny approval for ${activeApproval.action_id}`);
    } finally {
      setIsSubmitting(false);
      setDecisionReason("");
    }
  };

  return (
    <div className="space-y-8 pb-12">
      <div>
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-apple-text">
          Human-in-the-Loop (HITL) Queue
        </h1>
        <p className="text-apple-secondary text-sm mt-1">
          Gate 3 Action Assurance escalation: Inspect and decide high-risk mutations, external API calls, and elevated blast-radius actions before execution.
        </p>
      </div>

      {successMessage && (
        <div className="p-4 rounded-2xl bg-apple-green/10 border border-apple-green/20 text-xs sm:text-sm text-apple-green flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <CheckCircle className="w-4 h-4" />
            <span>{successMessage}</span>
          </div>
          <button
            type="button"
            onClick={() => setSuccessMessage(null)}
            className="text-apple-secondary hover:text-apple-text text-xs"
          >
            Dismiss
          </button>
        </div>
      )}

      {errorMessage && (
        <div className="p-4 rounded-2xl bg-apple-red/10 border border-apple-red/20 text-xs sm:text-sm text-apple-red flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <AlertCircle className="w-4 h-4" />
            <span>{errorMessage}</span>
          </div>
          <button
            type="button"
            onClick={() => setErrorMessage(null)}
            className="text-apple-secondary hover:text-apple-text text-xs"
          >
            Dismiss
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Pending List */}
        <div className="lg:col-span-5 space-y-3">
          <div className="flex items-center justify-between px-1">
            <span className="text-xs font-semibold text-apple-secondary uppercase tracking-wider">
              Pending Tickets ({approvals.length})
            </span>
            <span className="text-xs text-apple-muted">L4 Escalation</span>
          </div>

          {approvals.length === 0 ? (
            <div className="bg-apple-surface rounded-2xl p-8 border border-apple-border text-center">
              <CheckCircle className="w-8 h-8 text-apple-green mx-auto mb-2" />
              <h4 className="text-sm font-semibold text-apple-text">Queue Clear</h4>
              <p className="text-xs text-apple-secondary mt-1">
                Zero actions pending human approval. Automated Gate 3 policy controls are active.
              </p>
            </div>
          ) : (
            <div className="space-y-2.5">
              {approvals.map((a) => {
                const isSelected = activeApproval?.id === a.id;
                return (
                  <div
                    key={a.id}
                    onClick={() => setActiveApproval(a)}
                    className={`p-4 rounded-2xl border transition cursor-pointer ${
                      isSelected
                        ? "bg-apple-surface border-apple-blue shadow-apple-card ring-1 ring-apple-blue/20"
                        : "bg-apple-surface hover:bg-apple-subtle/50 border-apple-border"
                    }`}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-mono text-xs font-semibold text-apple-text">
                        {a.tool_name}
                      </span>
                      <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-apple-red/10 text-apple-red border border-apple-red/20">
                        Risk: {a.risk_score.toFixed(2)}
                      </span>
                    </div>

                    <p className="text-xs text-apple-secondary font-mono truncate">
                      Target: {a.target_resource}
                    </p>

                    <div className="flex items-center justify-between text-[11px] text-apple-muted mt-3 pt-2 border-t border-apple-border/50">
                      <span>{a.blast_radius}</span>
                      <span className="font-mono">{a.id}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Right Column: Detailed Ticket Inspection & Decision */}
        <div className="lg:col-span-7">
          {activeApproval ? (
            <div className="bg-apple-surface rounded-3xl p-6 border border-apple-border shadow-apple-card space-y-5">
              <div className="flex items-start justify-between pb-4 border-b border-apple-border">
                <div>
                  <div className="text-xs font-mono text-apple-secondary">
                    Ticket ID: {activeApproval.id}
                  </div>
                  <h3 className="text-lg font-bold text-apple-text mt-0.5">
                    {activeApproval.tool_name}
                  </h3>
                  <div className="text-xs font-mono text-apple-muted mt-0.5">
                    Transaction: {activeApproval.transaction_id}
                  </div>
                </div>

                <div className="text-right">
                  <div className="text-xs font-bold text-apple-red">
                    Risk Score: {activeApproval.risk_score.toFixed(2)}
                  </div>
                  <div className="text-[11px] text-apple-secondary mt-0.5">
                    {activeApproval.blast_radius}
                  </div>
                </div>
              </div>

              {/* Reason for Escalation */}
              <div className="p-3.5 rounded-2xl bg-apple-orange/10 border border-apple-orange/20 text-xs text-apple-orange space-y-1">
                <div className="font-semibold flex items-center space-x-1.5">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  <span>Escalation Rule Triggered</span>
                </div>
                <p className="text-apple-text leading-relaxed">
                  {activeApproval.reason_for_escalation}
                </p>
              </div>

              {/* Parameters JSON Inspector */}
              <div>
                <label className="block text-xs font-semibold text-apple-text mb-1.5">
                  Proposed Action Parameters (Target State Transition)
                </label>
                <pre className="p-3.5 rounded-2xl bg-apple-subtle border border-apple-border text-xs font-mono text-apple-text overflow-x-auto leading-relaxed">
                  {JSON.stringify(activeApproval.parameters, null, 2)}
                </pre>
              </div>

              {/* Decision Input & Action Buttons */}
              <div className="pt-2 border-t border-apple-border space-y-3">
                <label className="block text-xs font-semibold text-apple-text">
                  Decision Notes (Recorded in Cryptographic Audit Ledger)
                </label>
                <input
                  type="text"
                  value={decisionReason}
                  onChange={(e) => setDecisionReason(e.target.value)}
                  placeholder="e.g., Verified authorized vendor invoice #INV-2026-99"
                  className="w-full text-xs p-2.5 rounded-xl bg-apple-subtle border border-apple-border focus:outline-none focus:border-apple-blue font-sans"
                />

                <div className="grid grid-cols-2 gap-3 pt-2">
                  <button
                    type="button"
                    disabled={isSubmitting}
                    onClick={handleDeny}
                    className="flex items-center justify-center space-x-2 py-2.5 rounded-xl border border-apple-red/30 bg-apple-red/10 text-apple-red text-xs font-semibold hover:bg-apple-red/20 transition disabled:opacity-50"
                  >
                    <XCircle className="w-4 h-4" />
                    <span>Deny Action</span>
                  </button>

                  <button
                    type="button"
                    disabled={isSubmitting}
                    onClick={handleGrant}
                    className="flex items-center justify-center space-x-2 py-2.5 rounded-xl bg-apple-blue hover:bg-apple-blueHover text-white text-xs font-semibold shadow-apple-sm transition disabled:opacity-50"
                  >
                    <CheckCircle className="w-4 h-4" />
                    <span>Grant & Dispatch (Gate 3 Lease)</span>
                  </button>
                </div>
              </div>
            </div>
          ) : (
            <div className="h-full min-h-[320px] flex flex-col items-center justify-center rounded-3xl border border-dashed border-apple-border p-8 text-center text-apple-secondary text-xs space-y-2">
              <Shield className="w-8 h-8 text-apple-muted mx-auto" />
              <div className="font-semibold text-apple-text">No Action Selected</div>
              <p className="max-w-xs text-apple-muted">
                Proposed actions requiring elevated capabilities or human-in-the-loop review will appear here for parameter inspection.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
