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
  Terminal,
  Cpu,
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
    <div className="space-y-8 pb-16 font-mono">
      {/* Tactical Header */}
      <div className="border-b border-mirage-border pb-5 pt-2">
        <div className="flex items-center space-x-2 text-[10px] text-mirage-amber tracking-widest uppercase mb-1">
          <span className="w-2 h-2 rounded-full bg-mirage-amber animate-pulse" />
          <span>GATE 3 // ACTION ASSURANCE & HITL QUORUM ESCALATIONS</span>
        </div>
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-mirage-text font-display">
          HITL Quorum Escalations
        </h1>
        <p className="text-mirage-subtext text-xs mt-0.5 font-sans">
          Inspect, evaluate, and authorize high-risk autonomous mutations, external tool invocations, and elevated blast-radius operations before dispatch.
        </p>
      </div>

      {successMessage && (
        <div className="p-3.5 rounded bg-mirage-emerald/15 border border-mirage-emerald/40 text-xs text-mirage-emerald flex items-center justify-between shadow-hud-glow-emerald">
          <div className="flex items-center space-x-2">
            <CheckCircle className="w-4 h-4 shrink-0" />
            <span className="font-bold">{successMessage}</span>
          </div>
          <button
            type="button"
            onClick={() => setSuccessMessage(null)}
            className="text-mirage-subtext hover:text-mirage-text text-[11px] uppercase font-bold"
          >
            [DISMISS]
          </button>
        </div>
      )}

      {errorMessage && (
        <div className="p-3.5 rounded bg-mirage-crimson/15 border border-mirage-crimson/40 text-xs text-mirage-crimson flex items-center justify-between shadow-hud-glow-crimson">
          <div className="flex items-center space-x-2">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span className="font-bold">{errorMessage}</span>
          </div>
          <button
            type="button"
            onClick={() => setErrorMessage(null)}
            className="text-mirage-subtext hover:text-mirage-text text-[11px] uppercase font-bold"
          >
            [DISMISS]
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Pending List */}
        <div className="lg:col-span-5 space-y-3">
          <div className="flex items-center justify-between px-1">
            <span className="text-[11px] font-bold text-mirage-subtext uppercase tracking-wider">
              PENDING TICKETS ({approvals.length})
            </span>
            <span className="text-[10px] text-mirage-amber font-mono font-bold">L4_CRITICAL</span>
          </div>

          {approvals.length === 0 ? (
            <div className="bg-mirage-surface/90 rounded border border-mirage-border p-8 text-center shadow-hud-panel">
              <CheckCircle className="w-8 h-8 text-mirage-emerald mx-auto mb-2 opacity-80" />
              <h4 className="text-xs font-bold text-mirage-text uppercase tracking-wider">
                QUEUE CLEAR // ZERO ESCALATIONS
              </h4>
              <p className="text-[11px] text-mirage-muted mt-1 font-sans">
                Zero actions pending human approval. Automated Gate 3 distributed lease fencer and capability filters are guarding the execution boundary.
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
                    className={`p-3.5 rounded border transition cursor-pointer relative ${
                      isSelected
                        ? "bg-mirage-surfaceElevated border-mirage-amber text-mirage-text shadow-hud-glow-amber"
                        : "bg-mirage-surface/80 hover:bg-mirage-surfaceElevated border-mirage-border text-mirage-subtext"
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="font-mono text-xs font-bold text-mirage-cyan">
                        {a.tool_name}
                      </span>
                      <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-mirage-crimson/20 text-mirage-crimson border border-mirage-crimson/40">
                        RISK: {a.risk_score?.toFixed(2) || "0.85"}
                      </span>
                    </div>

                    <p className="text-[11px] text-mirage-muted font-mono truncate">
                      TARGET: {a.target_resource}
                    </p>

                    <div className="flex items-center justify-between text-[10px] text-mirage-muted mt-2 pt-2 border-t border-mirage-border/50">
                      <span className="text-mirage-amber font-semibold">{a.blast_radius}</span>
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
            <div className="bg-mirage-surface/95 rounded border border-mirage-border p-5 shadow-hud-panel space-y-4">
              <div className="flex items-start justify-between pb-3 border-b border-mirage-border">
                <div>
                  <div className="text-[10px] font-mono text-mirage-muted">
                    TICKET_ID: <span className="text-mirage-cyan">{activeApproval.id}</span>
                  </div>
                  <h3 className="text-base font-bold text-mirage-text mt-0.5 font-display">
                    {activeApproval.tool_name}
                  </h3>
                  <div className="text-[10px] font-mono text-mirage-muted mt-0.5">
                    TX_IDENTIFIER: {activeApproval.transaction_id}
                  </div>
                </div>

                <div className="text-right">
                  <div className="text-xs font-bold text-mirage-crimson">
                    RISK SCORE: {activeApproval.risk_score?.toFixed(2) || "0.85"}
                  </div>
                  <div className="text-[10px] text-mirage-amber mt-0.5 font-bold uppercase">
                    BLAST RADIUS: {activeApproval.blast_radius}
                  </div>
                </div>
              </div>

              {/* Reason for Escalation */}
              <div className="p-3 rounded bg-mirage-amber/10 border border-mirage-amber/30 text-xs text-mirage-amber space-y-1">
                <div className="font-bold flex items-center space-x-1.5 uppercase tracking-wider text-[11px]">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  <span>ESCALATION POLICY TRIGGERED</span>
                </div>
                <p className="text-mirage-text leading-relaxed font-sans text-xs">
                  {activeApproval.reason_for_escalation}
                </p>
              </div>

              {/* Parameters JSON Inspector */}
              <div>
                <label className="block text-[11px] font-bold text-mirage-subtext uppercase tracking-wider mb-1">
                  PROPOSED TARGET MUTATION PAYLOAD
                </label>
                <pre className="p-3 rounded bg-mirage-chassis border border-mirage-border text-xs font-mono text-mirage-cyan overflow-x-auto leading-relaxed max-h-56">
                  {JSON.stringify(activeApproval.parameters, null, 2)}
                </pre>
              </div>

              {/* Decision Input & Action Buttons */}
              <div className="pt-3 border-t border-mirage-border space-y-3">
                <label className="block text-[11px] font-bold text-mirage-subtext uppercase tracking-wider">
                  OPERATOR JUSTIFICATION (ANCHORED IN MERKLE LEDGER)
                </label>
                <input
                  type="text"
                  value={decisionReason}
                  onChange={(e) => setDecisionReason(e.target.value)}
                  placeholder="e.g. Verified authorized invoice #INV-2026-99 against vendor ledger"
                  className="w-full text-xs p-2.5 rounded bg-mirage-chassis border border-mirage-border focus:outline-none focus:border-mirage-cyan font-mono text-mirage-text"
                />

                <div className="grid grid-cols-2 gap-3 pt-2">
                  <button
                    type="button"
                    disabled={isSubmitting}
                    onClick={handleDeny}
                    className="flex items-center justify-center space-x-2 py-2.5 rounded border border-mirage-crimson/40 bg-mirage-crimson/15 text-mirage-crimson text-xs font-bold uppercase tracking-wider hover:bg-mirage-crimson hover:text-white transition disabled:opacity-50"
                  >
                    <XCircle className="w-4 h-4" />
                    <span>DENY & TERMINATE</span>
                  </button>

                  <button
                    type="button"
                    disabled={isSubmitting}
                    onClick={handleGrant}
                    className="flex items-center justify-center space-x-2 py-2.5 rounded bg-mirage-cyan text-mirage-void text-xs font-bold uppercase tracking-wider hover:bg-white shadow-hud-glow transition disabled:opacity-50"
                  >
                    <CheckCircle className="w-4 h-4" />
                    <span>GRANT LEASE & DISPATCH</span>
                  </button>
                </div>
              </div>
            </div>
          ) : (
            <div className="h-full min-h-[320px] flex flex-col items-center justify-center rounded border border-dashed border-mirage-border p-8 text-center text-mirage-muted text-xs space-y-2 bg-mirage-surface/50">
              <Shield className="w-8 h-8 text-mirage-muted mx-auto opacity-50" />
              <div className="font-bold text-mirage-text uppercase tracking-wider">NO TICKET SELECTED</div>
              <p className="max-w-xs text-mirage-muted font-sans text-xs">
                Select an escalation ticket from the queue to inspect proposed parameters, target state machines, and authorize execution.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
