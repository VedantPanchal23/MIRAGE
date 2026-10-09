import React, { useState, useEffect, useCallback, useContext } from "react";
import {
  ShieldAlert,
  ShieldCheck,
  Wrench,
  Activity,
  Plus,
  RefreshCw,
  AlertTriangle,
  Lock,
  ExternalLink,
  CheckCircle,
  XCircle,
  Clock,
  DollarSign,
  Fingerprint,
  Send,
  Play,
  Layers,
} from "lucide-react";
import {
  getTools,
  registerTool,
  proposeAction,
  executeAction,
  getPendingApprovals,
  grantApproval,
  denyApproval,
} from "../api";
import { AuthContext, ROLES } from "../context/AuthContext";

/**
 * Gate 3 Action Assurance & Governed Tool Registry View.
 *
 * Implements MIRAGE 3.0 Gate 3 Action Assurance:
 * - Authoritative Tool Registry with strict Egress categorization (INTERNAL_ISOLATED vs EGRESS_EXTERNAL).
 * - Action Contract proposal and SHA-256 parameter hash locking.
 * - Dynamic Information Flow Control (DIFC) Dangerous Triad Interlock enforcement.
 * - Salami-slicing blast radius tracking (1-hour rolling window cost and risk points).
 * - Time-bounded L4 Human-in-the-Loop approvals workflow (agent self-grants prohibited).
 * - Tool Proxy dispatch with precondition verification and postcondition assertions.
 */
export function ActionAssuranceView({ isRefreshing, onDataLoaded }) {
  const { role, tenantId, hasRole } = useContext(AuthContext);

  const [tools, setTools] = useState([]);
  const [approvals, setApprovals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Register Tool Modal State
  const [showToolModal, setShowToolModal] = useState(false);
  const [toolName, setToolName] = useState("");
  const [toolDesc, setToolDesc] = useState("");
  const [toolType, setToolType] = useState("DETERMINISTIC_FUNCTION");
  const [egressType, setEgressType] = useState("INTERNAL_ISOLATED");
  const [trustLevel, setTrustLevel] = useState("SANDBOXED");
  const [reqCapability, setReqCapability] = useState("tools:read");
  const [registering, setRegistering] = useState(false);

  // Approval Modal State
  const [activeApproval, setActiveApproval] = useState(null);
  const [approvalDecision, setApprovalDecision] = useState("GRANT");
  const [approvalReason, setApprovalReason] = useState("");
  const [processingApproval, setProcessingApproval] = useState(false);

  // Action Sandbox Proposal State
  const [sandboxTxnId, setSandboxTxnId] = useState("txn_action_gate3_demo");
  const [sandboxTool, setSandboxTool] = useState("");
  const [sandboxResource, setSandboxResource] = useState("db://records/financial_report");
  const [sandboxCost, setSandboxCost] = useState("25.00");
  const [sandboxParams, setSandboxParams] = useState(
    JSON.stringify({ query: "SELECT * FROM financial_records", limit: 10 }, null, 2)
  );
  const [evaluating, setEvaluating] = useState(false);
  const [proposalDecision, setProposalDecision] = useState(null);
  const [executing, setExecuting] = useState(false);
  const [executionResult, setExecutionResult] = useState(null);

  const canApprove = hasRole(ROLES.SUPER_ADMIN, ROLES.TENANT_ADMIN, ROLES.OPERATOR);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [toolsData, approvalsData] = await Promise.all([
        getTools().catch(() => []),
        getPendingApprovals().catch(() => []),
      ]);
      setTools(toolsData || []);
      setApprovals(approvalsData || []);
      if (toolsData && toolsData.length > 0 && !sandboxTool) {
        setSandboxTool(toolsData[0].name);
      }
      if (onDataLoaded) onDataLoaded(new Date().toLocaleTimeString());
    } catch (err) {
      setError(err.message || "Failed to load action assurance data");
    } finally {
      setLoading(false);
    }
  }, [onDataLoaded, sandboxTool]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  useEffect(() => {
    if (isRefreshing) {
      loadData();
    }
  }, [isRefreshing, loadData]);

  const handleRegisterTool = async (e) => {
    e.preventDefault();
    if (!toolName.trim()) return;
    setRegistering(true);
    setError(null);
    try {
      await registerTool({
        name: toolName.trim(),
        description: toolDesc.trim() || undefined,
        tool_type: toolType,
        egress_type: egressType,
        trust_level: trustLevel,
        required_capability: reqCapability.trim() || undefined,
        parameters_schema: { type: "object", additionalProperties: true },
        config: {},
        active: true,
      });
      setShowToolModal(false);
      setToolName("");
      setToolDesc("");
      await loadData();
    } catch (err) {
      setError(err.message || "Failed to register tool");
    } finally {
      setRegistering(false);
    }
  };

  const handleOpenApprovalModal = (approval, decision) => {
    setActiveApproval(approval);
    setApprovalDecision(decision);
    setApprovalReason(
      decision === "GRANT"
        ? "Authorized by operator after reviewing parameters hash and risk profile."
        : "Denied due to risk profile exceeding threshold or untrusted context."
    );
  };

  const handleSubmitApproval = async (e) => {
    e.preventDefault();
    if (!activeApproval) return;
    setProcessingApproval(true);
    setError(null);
    try {
      if (approvalDecision === "GRANT") {
        await grantApproval(activeApproval.id, approvalReason);
      } else {
        await denyApproval(activeApproval.id, approvalReason);
      }
      setActiveApproval(null);
      await loadData();
    } catch (err) {
      setError(err.message || `Failed to ${approvalDecision.toLowerCase()} approval`);
    } finally {
      setProcessingApproval(false);
    }
  };

  const handleEvaluateProposal = async () => {
    if (!sandboxTool) {
      setError("Please select a registered tool for evaluation.");
      return;
    }
    setEvaluating(true);
    setError(null);
    setProposalDecision(null);
    setExecutionResult(null);

    try {
      let parsedParams = {};
      try {
        parsedParams = JSON.parse(sandboxParams);
      } catch (e) {
        throw new Error("Invalid JSON formatted in action parameters");
      }

      const res = await proposeAction({
        transaction_id: sandboxTxnId,
        tool_name: sandboxTool,
        action_type: "EXECUTE",
        target_resource: sandboxResource,
        parameters: parsedParams,
        idempotency_key: `key_${Date.now()}`,
        blast_radius: {
          estimated_cost_usd: parseFloat(sandboxCost) || 0.0,
          target_criticality: 0.5,
          data_classification: "CONFIDENTIAL",
        },
        preconditions: [
          {
            field: "target_resource",
            operator: "EQUALS",
            expected_value: sandboxResource,
          },
        ],
        postconditions: [
          {
            field: "status",
            operator: "EQUALS",
            expected_value: "SUCCESS",
          },
        ],
      });
      setProposalDecision(res);
      await loadData();
    } catch (err) {
      setError(err.message || "Failed to evaluate action proposal");
    } finally {
      setEvaluating(false);
    }
  };

  const handleExecuteAction = async () => {
    if (!proposalDecision || !proposalDecision.action_id) return;
    setExecuting(true);
    setError(null);
    try {
      const res = await executeAction({ action_id: proposalDecision.action_id });
      setExecutionResult(res);
      await loadData();
    } catch (err) {
      setError(err.message || "Failed to execute action contract");
    } finally {
      setExecuting(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Top Banner & Overview */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-6">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                Gate 3 Action Assurance
              </span>
              <span className="text-xs text-slate-400">
                AI Action Contracts & Tool Proxy Active
              </span>
            </div>
            <h1 className="text-xl font-bold text-white mt-1">
              Action Governance & Blast Radius Control
            </h1>
            <p className="text-sm text-slate-400 mt-0.5">
              Strict tool capability verification, DIFC Dangerous Triad interlock, parameter hash locking, salami-slicing window defense, and L4 approvals.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={loadData}
              disabled={loading}
              className="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium rounded-lg border border-slate-700 flex items-center gap-1.5 transition-colors"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </button>
            <button
              onClick={() => setShowToolModal(true)}
              className="px-3.5 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium rounded-lg shadow-sm flex items-center gap-1.5 transition-colors"
            >
              <Plus className="w-3.5 h-3.5" />
              Register Governed Tool
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 flex items-center gap-3 text-red-400 text-sm">
          <AlertTriangle className="w-5 h-5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Metrics Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4">
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400 font-medium">Governed Tools</span>
            <Wrench className="w-4 h-4 text-indigo-400" />
          </div>
          <div className="text-2xl font-bold text-white mt-2">
            {tools.length}
          </div>
          <p className="text-[11px] text-slate-500 mt-1">
            {tools.filter((t) => t.egress_type === "EGRESS_EXTERNAL").length} external egress,{" "}
            {tools.filter((t) => t.egress_type === "INTERNAL_ISOLATED").length} internal
          </p>
        </div>

        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4">
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400 font-medium">Pending Approvals</span>
            <Clock className={`w-4 h-4 ${approvals.length > 0 ? "text-amber-400" : "text-slate-500"}`} />
          </div>
          <div className={`text-2xl font-bold mt-2 ${approvals.length > 0 ? "text-amber-400" : "text-white"}`}>
            {approvals.length}
          </div>
          <p className="text-[11px] text-slate-500 mt-1">L4 high-risk human approval tickets</p>
        </div>

        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4">
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400 font-medium">Dangerous Triad Interlock</span>
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-2xl font-bold text-emerald-400 mt-2">Enforced</div>
          <p className="text-[11px] text-slate-500 mt-1">Untrusted context blocks external egress</p>
        </div>

        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4">
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400 font-medium">Salami-Slicing Defense</span>
            <Activity className="w-4 h-4 text-cyan-400" />
          </div>
          <div className="text-2xl font-bold text-cyan-400 mt-2">1h Rolling</div>
          <p className="text-[11px] text-slate-500 mt-1">Cumulative spend & risk accumulation tracker</p>
        </div>
      </div>

      {/* Pending Human Approvals Queue (L4 Tickets) */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-amber-400" />
            <h2 className="text-sm font-semibold text-white">Pending L4 Human Approvals Queue</h2>
          </div>
          <span className="text-xs text-slate-400">
            {approvals.length} ticket{approvals.length !== 1 ? "s" : ""} awaiting authorization
          </span>
        </div>

        {approvals.length === 0 ? (
          <div className="p-6 text-center text-slate-500 text-xs">
            No pending human approvals required at this time. High-risk actions (L4/L5) will queue here.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-800/40 text-slate-400 border-b border-slate-800 uppercase text-[10px] tracking-wider">
                <tr>
                  <th className="px-6 py-3">Approval ID</th>
                  <th className="px-6 py-3">Action ID</th>
                  <th className="px-6 py-3">Parameters Hash</th>
                  <th className="px-6 py-3">Expires At</th>
                  <th className="px-6 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 text-slate-300">
                {approvals.map((appr) => (
                  <tr key={appr.id} className="hover:bg-slate-800/20 transition-colors">
                    <td className="px-6 py-3.5 whitespace-nowrap font-mono text-amber-400">
                      {appr.id.slice(0, 14)}...
                    </td>
                    <td className="px-6 py-3.5 whitespace-nowrap font-mono text-slate-300">
                      {appr.action_id.slice(0, 14)}...
                    </td>
                    <td className="px-6 py-3.5 whitespace-nowrap font-mono text-[10px] text-slate-400">
                      {appr.parameters_hash.slice(0, 16)}...
                    </td>
                    <td className="px-6 py-3.5 whitespace-nowrap text-slate-400 text-[11px]">
                      {new Date(appr.expires_at).toLocaleTimeString()}
                    </td>
                    <td className="px-6 py-3.5 whitespace-nowrap text-right space-x-2">
                      <button
                        onClick={() => handleOpenApprovalModal(appr, "GRANT")}
                        disabled={!canApprove}
                        className="px-2.5 py-1 bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-400 border border-emerald-500/30 rounded text-[11px] font-medium transition-colors disabled:opacity-50"
                        title={!canApprove ? "Requires Operator or Admin role" : "Authorize action"}
                      >
                        Grant
                      </button>
                      <button
                        onClick={() => handleOpenApprovalModal(appr, "DENY")}
                        disabled={!canApprove}
                        className="px-2.5 py-1 bg-red-600/20 hover:bg-red-600/30 text-red-400 border border-red-500/30 rounded text-[11px] font-medium transition-colors disabled:opacity-50"
                        title={!canApprove ? "Requires Operator or Admin role" : "Reject action"}
                      >
                        Deny
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Governed Tool Registry Table */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Wrench className="w-4 h-4 text-indigo-400" />
            <h2 className="text-sm font-semibold text-white">Authoritative Tool Registry</h2>
          </div>
          <span className="text-xs text-slate-400">
            {tools.length} registered tool{tools.length !== 1 ? "s" : ""}
          </span>
        </div>

        {loading ? (
          <div className="p-8 text-center text-slate-500 text-xs animate-pulse">
            Loading governed tool definitions...
          </div>
        ) : tools.length === 0 ? (
          <div className="p-8 text-center text-slate-500 text-xs">
            No governed tools registered for this tenant. Click "Register Governed Tool" to register one.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-800/40 text-slate-400 border-b border-slate-800 uppercase text-[10px] tracking-wider">
                <tr>
                  <th className="px-6 py-3">Tool Name / Type</th>
                  <th className="px-6 py-3">Egress Boundary</th>
                  <th className="px-6 py-3">Trust Level</th>
                  <th className="px-6 py-3">Required Capability</th>
                  <th className="px-6 py-3">Description</th>
                  <th className="px-6 py-3 text-right">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 text-slate-300">
                {tools.map((t) => (
                  <tr key={t.id || t.name} className="hover:bg-slate-800/20 transition-colors">
                    <td className="px-6 py-3.5 whitespace-nowrap">
                      <div className="font-semibold text-white font-mono">{t.name}</div>
                      <span className="text-[10px] text-slate-500 font-mono">{t.tool_type}</span>
                    </td>
                    <td className="px-6 py-3.5 whitespace-nowrap">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-semibold border ${
                          t.egress_type === "EGRESS_EXTERNAL"
                            ? "bg-purple-500/10 text-purple-400 border-purple-500/20"
                            : "bg-blue-500/10 text-blue-400 border-blue-500/20"
                        }`}
                      >
                        {t.egress_type}
                      </span>
                    </td>
                    <td className="px-6 py-3.5 whitespace-nowrap">
                      <span className="px-2 py-0.5 rounded text-[10px] bg-slate-800 text-slate-300 border border-slate-700">
                        {t.trust_level}
                      </span>
                    </td>
                    <td className="px-6 py-3.5 whitespace-nowrap font-mono text-[11px] text-cyan-400">
                      {t.required_capability || "None"}
                    </td>
                    <td className="px-6 py-3.5 max-w-xs truncate text-slate-400" title={t.description}>
                      {t.description || "No description provided"}
                    </td>
                    <td className="px-6 py-3.5 whitespace-nowrap text-right">
                      <span
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold ${
                          t.active
                            ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                            : "bg-red-500/10 text-red-400 border border-red-500/20"
                        }`}
                      >
                        {t.active ? "ACTIVE" : "DISABLED"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Action Proposal & Tool Proxy Execution Sandbox */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-6">
        <div className="flex items-center gap-2 mb-2">
          <Fingerprint className="w-4 h-4 text-indigo-400" />
          <h2 className="text-sm font-semibold text-white">Action Contract Proposal & Execution Sandbox</h2>
        </div>
        <p className="text-xs text-slate-400 mb-6">
          Submit an action proposal through Gate 3 to simulate parameter hash locking, risk scoring, DIFC checks, and proxy execution.
        </p>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Proposal Input Form */}
          <div className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">
                Transaction ID
              </label>
              <input
                type="text"
                value={sandboxTxnId}
                onChange={(e) => setSandboxTxnId(e.target.value)}
                className="w-full bg-slate-800/80 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 font-mono focus:outline-none focus:border-indigo-500"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Target Governed Tool
                </label>
                <select
                  value={sandboxTool}
                  onChange={(e) => setSandboxTool(e.target.value)}
                  className="w-full bg-slate-800/80 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
                >
                  {tools.map((t) => (
                    <option key={t.name} value={t.name}>
                      {t.name} ({t.egress_type})
                    </option>
                  ))}
                  {tools.length === 0 && <option value="">No tools registered</option>}
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Estimated Cost (USD)
                </label>
                <input
                  type="number"
                  step="0.01"
                  value={sandboxCost}
                  onChange={(e) => setSandboxCost(e.target.value)}
                  className="w-full bg-slate-800/80 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">
                Target Resource URI
              </label>
              <input
                type="text"
                value={sandboxResource}
                onChange={(e) => setSandboxResource(e.target.value)}
                className="w-full bg-slate-800/80 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 font-mono focus:outline-none focus:border-indigo-500"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">
                Normalized Parameters (JSON)
              </label>
              <textarea
                rows={4}
                value={sandboxParams}
                onChange={(e) => setSandboxParams(e.target.value)}
                className="w-full bg-slate-800/80 border border-slate-700 rounded-lg p-3 text-xs text-slate-200 font-mono focus:outline-none focus:border-indigo-500"
              />
            </div>

            <div className="flex justify-end">
              <button
                onClick={handleEvaluateProposal}
                disabled={evaluating || !sandboxTool}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium rounded-lg flex items-center gap-1.5 transition-colors disabled:opacity-50"
              >
                <Send className="w-3.5 h-3.5" />
                {evaluating ? "Evaluating..." : "Evaluate Proposal (Gate 3)"}
              </button>
            </div>
          </div>

          {/* Decision & Execution Results */}
          <div className="bg-slate-950/60 border border-slate-800 rounded-xl p-4 flex flex-col justify-between">
            <div>
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-3">
                Authorization Decision
              </span>

              {proposalDecision ? (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-slate-400">Decision Status:</span>
                    <span
                      className={`px-2 py-0.5 rounded text-xs font-bold border ${
                        proposalDecision.status === "AUTHORIZED"
                          ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
                          : proposalDecision.status === "AWAITING_APPROVAL"
                          ? "bg-amber-500/10 text-amber-400 border-amber-500/20"
                          : "bg-red-500/10 text-red-400 border-red-500/20"
                      }`}
                    >
                      {proposalDecision.status}
                    </span>
                  </div>

                  <div className="flex items-center justify-between text-xs">
                    <span className="text-slate-400">Risk Level:</span>
                    <span className="font-semibold text-slate-200 font-mono">
                      {proposalDecision.risk_level}
                    </span>
                  </div>

                  <div className="flex items-center justify-between text-xs">
                    <span className="text-slate-400">Parameters Hash:</span>
                    <span className="font-mono text-[10px] text-slate-400 truncate max-w-[200px]" title={proposalDecision.parameters_hash}>
                      {proposalDecision.parameters_hash}
                    </span>
                  </div>

                  <div className="bg-slate-900 border border-slate-800 rounded-lg p-3 text-xs text-slate-300">
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider block font-semibold mb-1">
                      Reasoning
                    </span>
                    {proposalDecision.decision_reason}
                  </div>

                  {proposalDecision.status === "AUTHORIZED" && (
                    <div className="pt-3">
                      <button
                        onClick={handleExecuteAction}
                        disabled={executing}
                        className="w-full py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold rounded-lg flex items-center justify-center gap-1.5 transition-colors"
                      >
                        <Play className="w-3.5 h-3.5" />
                        {executing ? "Dispatching..." : "Execute via Governed Tool Proxy"}
                      </button>
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-xs text-slate-500 py-12 text-center">
                  Submit an action proposal on the left to inspect Gate 3 authorization.
                </div>
              )}
            </div>

            {executionResult && (
              <div className="mt-4 pt-4 border-t border-slate-800">
                <span className="text-xs font-semibold text-emerald-400 block mb-1">
                  Tool Execution Result: {executionResult.status}
                </span>
                <pre className="bg-slate-900 p-3 rounded-lg border border-slate-800 text-[10px] font-mono text-slate-300 overflow-x-auto whitespace-pre-wrap max-h-32">
                  {JSON.stringify(executionResult.result, null, 2)}
                </pre>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Register Governed Tool Modal */}
      {showToolModal && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-6 shadow-2xl">
            <h3 className="text-base font-bold text-white mb-1">Register Governed Tool</h3>
            <p className="text-xs text-slate-400 mb-4">
              Register a tool definition with authoritative egress boundaries and required capabilities.
            </p>

            <form onSubmit={handleRegisterTool} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Tool Name
                </label>
                <input
                  required
                  type="text"
                  value={toolName}
                  onChange={(e) => setToolName(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 font-mono focus:outline-none focus:border-indigo-500"
                  placeholder="e.g., internal_sql_query"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Egress Classification
                </label>
                <select
                  value={egressType}
                  onChange={(e) => setEgressType(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
                >
                  <option value="INTERNAL_ISOLATED">INTERNAL_ISOLATED (Air-gapped / Local DB)</option>
                  <option value="EGRESS_EXTERNAL">EGRESS_EXTERNAL (Outbound Network / API / Webhook)</option>
                </select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Tool Type
                  </label>
                  <select
                    value={toolType}
                    onChange={(e) => setToolType(e.target.value)}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
                  >
                    <option value="DETERMINISTIC_FUNCTION">DETERMINISTIC_FUNCTION</option>
                    <option value="REST_API">REST_API</option>
                    <option value="MCP_BRIDGE">MCP_BRIDGE</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Trust Level
                  </label>
                  <select
                    value={trustLevel}
                    onChange={(e) => setTrustLevel(e.target.value)}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
                  >
                    <option value="SANDBOXED">SANDBOXED</option>
                    <option value="VERIFIED_INTERNAL">VERIFIED_INTERNAL</option>
                    <option value="UNTRUSTED_EXTERNAL">UNTRUSTED_EXTERNAL</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Required Capability
                </label>
                <input
                  type="text"
                  value={reqCapability}
                  onChange={(e) => setReqCapability(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 font-mono focus:outline-none focus:border-indigo-500"
                  placeholder="e.g. tools:read or db:query"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Description
                </label>
                <textarea
                  rows={2}
                  value={toolDesc}
                  onChange={(e) => setToolDesc(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg p-3 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
                  placeholder="Explain what this tool does..."
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowToolModal(false)}
                  className="px-3.5 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={registering}
                  className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium rounded-lg transition-colors"
                >
                  {registering ? "Registering..." : "Register Tool"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Human Approval Decision Modal */}
      {activeApproval && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-6 shadow-2xl">
            <h3 className="text-base font-bold text-white mb-1">
              {approvalDecision === "GRANT" ? "Authorize Action Contract" : "Deny Action Contract"}
            </h3>
            <p className="text-xs text-slate-400 mb-4">
              Action ID: <span className="font-mono text-slate-200">{activeApproval.action_id}</span>
            </p>

            <form onSubmit={handleSubmitApproval} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Decision Rationale / Audit Comment
                </label>
                <textarea
                  required
                  rows={3}
                  value={approvalReason}
                  onChange={(e) => setApprovalReason(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg p-3 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setActiveApproval(null)}
                  className="px-3.5 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={processingApproval}
                  className={`px-4 py-2 text-white text-xs font-medium rounded-lg transition-colors ${
                    approvalDecision === "GRANT"
                      ? "bg-emerald-600 hover:bg-emerald-500"
                      : "bg-red-600 hover:bg-red-500"
                  }`}
                >
                  {processingApproval
                    ? "Submitting..."
                    : `Confirm ${approvalDecision === "GRANT" ? "Authorization" : "Rejection"}`}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

export default ActionAssuranceView;
