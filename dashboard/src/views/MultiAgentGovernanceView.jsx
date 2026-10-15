import React, { useState, useEffect, useCallback, useContext } from "react";
import {
  Users,
  Network,
  GitBranch,
  Key,
  ShieldAlert,
  ShieldCheck,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Clock,
  RefreshCw,
  Plus,
  Play,
  X,
  ExternalLink,
  ChevronRight,
  ChevronDown,
  Layers,
  ArrowRight,
  Database,
  Lock,
  Unlock,
  AlertCircle,
  Copy,
  Check,
  Search,
  Filter,
} from "lucide-react";
import {
  listAgents,
  registerAgent,
  activateAgent,
  suspendAgent,
  revokeAgent,
  listDelegations,
  createDelegation,
  activateDelegation,
  revokeDelegation,
  listHandoffs,
  createHandoff,
  acceptHandoff,
  cancelHandoff,
  completeHandoff,
  listLeases,
  acquireLease,
  releaseLease,
  renewLease,
  getTransactionHierarchy,
} from "../api/multiagent";
import { AuthContext, ROLES } from "../context/AuthContext";

/**
 * Phase 8 Governed Multi-Agent Governance & Assurance View.
 *
 * Implements:
 * 1. Agent Governance: lifecycle tracking (registered, active, suspended, revoked), registration, and transitions.
 * 2. Delegation Grants: authority attenuation, parent/child scope constraints, activation, and explicit revocation.
 * 3. Governed Handoffs: parent/child context propagation, accept, complete, and cancel lifecycle.
 * 4. Resource Concurrency: distributed leases with monotonic fencing tokens and target-write safety notice.
 * 5. Hierarchical Outcome Assurance: parent/child lineage aggregation, epistemic confidence, Reality Verifier truth, and discrepancy alerts.
 */
export function MultiAgentGovernanceView({ isRefreshing, onDataLoaded }) {
  const { role, tenantId, hasRole } = useContext(AuthContext);

  // Sub-tabs: "agents" | "delegations" | "handoffs" | "concurrency" | "hierarchy"
  const [activeSubTab, setActiveSubTab] = useState("agents");

  // Global loading and error state
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState(null);
  const [feedback, setFeedback] = useState(null);

  // Data collections
  const [agents, setAgents] = useState([]);
  const [delegations, setDelegations] = useState([]);
  const [handoffs, setHandoffs] = useState([]);
  const [leases, setLeases] = useState([]);

  // Search & Filter
  const [agentStatusFilter, setAgentStatusFilter] = useState("ALL");
  const [delegationStatusFilter, setDelegationStatusFilter] = useState("ALL");
  const [handoffStatusFilter, setHandoffStatusFilter] = useState("ALL");
  const [leaseStatusFilter, setLeaseStatusFilter] = useState("ALL");
  const [searchQuery, setSearchQuery] = useState("");

  // Hierarchy Inspection State
  const [hierarchyTxnId, setHierarchyTxnId] = useState("");
  const [hierarchyData, setHierarchyData] = useState(null);
  const [hierarchyLoading, setHierarchyLoading] = useState(false);
  const [hierarchyError, setHierarchyError] = useState(null);
  const [copiedHash, setCopiedHash] = useState(false);

  // Modals state
  const [modalType, setModalType] = useState(null); // 'REGISTER_AGENT' | 'CONFIRM_AGENT_TRANSITION' | 'CREATE_DELEGATION' | 'ACTIVATE_DELEGATION' | 'REVOKE_DELEGATION' | 'CREATE_HANDOFF' | 'ACCEPT_HANDOFF' | 'CANCEL_HANDOFF' | 'ACQUIRE_LEASE' | 'RELEASE_LEASE' | 'RENEW_LEASE'
  const [targetItem, setTargetItem] = useState(null);
  const [modalReason, setModalReason] = useState("");
  const [modalInput, setModalInput] = useState({});

  // -------------------------------------------------------------
  // Data Fetching
  // -------------------------------------------------------------
  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [agentsRes, delRes, hndRes, lseRes] = await Promise.allSettled([
        listAgents({ limit: 100 }),
        listDelegations({ limit: 100 }),
        listHandoffs({ limit: 100 }),
        listLeases({ limit: 100 }),
      ]);

      if (agentsRes.status === "fulfilled") {
        setAgents(agentsRes.value?.agents || []);
      }
      if (delRes.status === "fulfilled") {
        setDelegations(Array.isArray(delRes.value) ? delRes.value : []);
      }
      if (hndRes.status === "fulfilled") {
        setHandoffs(Array.isArray(hndRes.value) ? hndRes.value : []);
      }
      if (lseRes.status === "fulfilled") {
        setLeases(Array.isArray(lseRes.value) ? lseRes.value : []);
      }

      if (onDataLoaded) {
        onDataLoaded(new Date().toLocaleTimeString());
      }
    } catch (err) {
      setError(err?.message || "Failed to load multi-agent governance data");
    } finally {
      setLoading(false);
    }
  }, [onDataLoaded]);

  useEffect(() => {
    fetchData();
  }, [fetchData, isRefreshing]);

  // Load Hierarchy on demand or when a transaction is selected
  const loadHierarchy = async (txnId) => {
    if (!txnId) return;
    setHierarchyLoading(true);
    setHierarchyError(null);
    try {
      const data = await getTransactionHierarchy(txnId.trim());
      setHierarchyData(data);
    } catch (err) {
      setHierarchyError(err?.message || "Failed to retrieve transaction hierarchy");
      setHierarchyData(null);
    } finally {
      setHierarchyLoading(false);
    }
  };

  const closeModal = () => {
    setModalType(null);
    setTargetItem(null);
    setModalReason("");
    setModalInput({});
  };

  const copyToClipboard = (text) => {
    if (!text) return;
    navigator.clipboard?.writeText(text);
    setCopiedHash(true);
    setTimeout(() => setCopiedHash(false), 2000);
  };

  // -------------------------------------------------------------
  // Action Handlers
  // -------------------------------------------------------------

  // Agent Actions
  const handleRegisterAgentSubmit = async (e) => {
    e.preventDefault();
    setActionLoading(true);
    setError(null);
    try {
      const payload = {
        name: modalInput.name,
        max_autonomy_level: parseInt(modalInput.max_autonomy_level || 0, 10),
        initial_status: modalInput.initial_status || "registered",
        metadata: modalInput.metadata ? JSON.parse(modalInput.metadata) : {},
      };
      await registerAgent(payload);
      setFeedback(`Agent "${payload.name}" registered successfully.`);
      closeModal();
      await fetchData();
    } catch (err) {
      setError(err?.message || "Agent registration failed");
    } finally {
      setActionLoading(false);
    }
  };

  const handleAgentTransitionSubmit = async (e) => {
    e.preventDefault();
    if (!targetItem) return;
    setActionLoading(true);
    setError(null);
    try {
      const { action, agent } = targetItem;
      if (action === "activate") {
        await activateAgent(agent.id, modalReason || "Operator manual activation");
        setFeedback(`Agent "${agent.name}" activated.`);
      } else if (action === "suspend") {
        if (!modalReason.trim()) throw new Error("Suspension reason is required.");
        await suspendAgent(agent.id, modalReason.trim());
        setFeedback(`Agent "${agent.name}" suspended.`);
      } else if (action === "revoke") {
        if (!modalReason.trim()) throw new Error("Revocation reason is required.");
        await revokeAgent(agent.id, modalReason.trim());
        setFeedback(`Agent "${agent.name}" permanently revoked.`);
      }
      closeModal();
      await fetchData();
    } catch (err) {
      setError(err?.message || "Agent state transition failed");
    } finally {
      setActionLoading(false);
    }
  };

  // Delegation Actions
  const handleCreateDelegationSubmit = async (e) => {
    e.preventDefault();
    setActionLoading(true);
    setError(null);
    try {
      const caps = [
        {
          capability_type: modalInput.capability_type || "tools:execution",
          resource_scope: modalInput.resource_scope ? JSON.parse(modalInput.resource_scope) : {},
          constraints: modalInput.constraints ? JSON.parse(modalInput.constraints) : {},
          max_autonomy_level: parseInt(modalInput.max_autonomy_level || 1, 10),
        },
      ];
      const payload = {
        parent_transaction_id: modalInput.parent_transaction_id,
        delegatee_agent_id: modalInput.delegatee_agent_id,
        delegated_capabilities: caps,
        max_turns: parseInt(modalInput.max_turns || 4, 10),
        duration_seconds: parseInt(modalInput.duration_seconds || 300, 10),
        idempotency_key: `del_${Date.now()}_${Math.random().toString(36).substring(2, 8)}`,
        purpose: modalInput.purpose,
      };
      await createDelegation(payload);
      setFeedback("Delegation grant issued successfully.");
      closeModal();
      await fetchData();
    } catch (err) {
      setError(err?.message || "Failed to create delegation grant");
    } finally {
      setActionLoading(false);
    }
  };

  const handleActivateDelegationSubmit = async (e) => {
    e.preventDefault();
    if (!targetItem) return;
    setActionLoading(true);
    setError(null);
    try {
      if (!modalInput.child_transaction_id?.trim()) {
        throw new Error("Child transaction ID is required to bind grant.");
      }
      await activateDelegation(targetItem.id, modalInput.child_transaction_id.trim());
      setFeedback(`Delegation grant ${targetItem.id} activated.`);
      closeModal();
      await fetchData();
    } catch (err) {
      setError(err?.message || "Failed to activate delegation grant");
    } finally {
      setActionLoading(false);
    }
  };

  const handleRevokeDelegationSubmit = async (e) => {
    e.preventDefault();
    if (!targetItem) return;
    setActionLoading(true);
    setError(null);
    try {
      if (!modalReason.trim()) throw new Error("Revocation reason is required.");
      await revokeDelegation(targetItem.id, modalReason.trim());
      setFeedback(`Delegation grant ${targetItem.id} revoked.`);
      closeModal();
      await fetchData();
    } catch (err) {
      setError(err?.message || "Failed to revoke delegation grant");
    } finally {
      setActionLoading(false);
    }
  };

  // Handoff Actions
  const handleCreateHandoffSubmit = async (e) => {
    e.preventDefault();
    setActionLoading(true);
    setError(null);
    try {
      const payload = {
        parent_transaction_id: modalInput.parent_transaction_id,
        child_agent_id: modalInput.child_agent_id,
        delegation_id: modalInput.delegation_id,
        purpose: modalInput.purpose,
        duration_seconds: parseInt(modalInput.duration_seconds || 300, 10),
        idempotency_key: `hnd_${Date.now()}_${Math.random().toString(36).substring(2, 8)}`,
      };
      await createHandoff(payload);
      setFeedback("Governed handoff offered successfully.");
      closeModal();
      await fetchData();
    } catch (err) {
      setError(err?.message || "Failed to create handoff");
    } finally {
      setActionLoading(false);
    }
  };

  const handleAcceptHandoffSubmit = async (e) => {
    e.preventDefault();
    if (!targetItem) return;
    setActionLoading(true);
    setError(null);
    try {
      const payload = {
        input_context: modalInput.input_context ? JSON.parse(modalInput.input_context) : {},
      };
      const res = await acceptHandoff(targetItem.id, payload);
      setFeedback(`Handoff accepted. Child transaction ${res.child_transaction_id} spawned.`);
      closeModal();
      await fetchData();
    } catch (err) {
      setError(err?.message || "Failed to accept handoff");
    } finally {
      setActionLoading(false);
    }
  };

  const handleCancelHandoffSubmit = async (e) => {
    e.preventDefault();
    if (!targetItem) return;
    setActionLoading(true);
    setError(null);
    try {
      if (!modalReason.trim()) throw new Error("Cancellation reason is required.");
      await cancelHandoff(targetItem.id, modalReason.trim());
      setFeedback(`Handoff ${targetItem.id} cancelled.`);
      closeModal();
      await fetchData();
    } catch (err) {
      setError(err?.message || "Failed to cancel handoff");
    } finally {
      setActionLoading(false);
    }
  };

  const handleCompleteHandoffDirect = async (handoff) => {
    setActionLoading(true);
    setError(null);
    try {
      await completeHandoff(handoff.id);
      setFeedback(`Handoff ${handoff.id} marked as completed.`);
      await fetchData();
    } catch (err) {
      setError(err?.message || "Failed to complete handoff");
    } finally {
      setActionLoading(false);
    }
  };

  // Concurrency Lease Actions
  const handleAcquireLeaseSubmit = async (e) => {
    e.preventDefault();
    setActionLoading(true);
    setError(null);
    try {
      const payload = {
        resource_uri: modalInput.resource_uri,
        transaction_id: modalInput.transaction_id,
        agent_id: modalInput.agent_id,
        handoff_id: modalInput.handoff_id || null,
        concurrency_mode: modalInput.concurrency_mode || "EXCLUSIVE",
        duration_seconds: parseInt(modalInput.duration_seconds || 60, 10),
      };
      const res = await acquireLease(payload);
      setFeedback(`Lease acquired on ${res.resource_uri} with Fencing Token #${res.fencing_token}`);
      closeModal();
      await fetchData();
    } catch (err) {
      setError(err?.message || "Failed to acquire lease");
    } finally {
      setActionLoading(false);
    }
  };

  const handleReleaseLeaseSubmit = async (e) => {
    e.preventDefault();
    if (!targetItem) return;
    setActionLoading(true);
    setError(null);
    try {
      const payload = {
        transaction_id: targetItem.holder_transaction_id,
        agent_id: targetItem.holder_agent_id,
        fencing_token: targetItem.fencing_token,
      };
      await releaseLease(targetItem.id, payload);
      setFeedback(`Lease ${targetItem.id} released.`);
      closeModal();
      await fetchData();
    } catch (err) {
      setError(err?.message || "Failed to release lease");
    } finally {
      setActionLoading(false);
    }
  };

  const handleRenewLeaseSubmit = async (e) => {
    e.preventDefault();
    if (!targetItem) return;
    setActionLoading(true);
    setError(null);
    try {
      const payload = {
        transaction_id: targetItem.holder_transaction_id,
        agent_id: targetItem.holder_agent_id,
        fencing_token: targetItem.fencing_token,
        duration_seconds: parseInt(modalInput.duration_seconds || 60, 10),
      };
      await renewLease(targetItem.id, payload);
      setFeedback(`Lease ${targetItem.id} renewed.`);
      closeModal();
      await fetchData();
    } catch (err) {
      setError(err?.message || "Failed to renew lease");
    } finally {
      setActionLoading(false);
    }
  };

  // -------------------------------------------------------------
  // Filtered Lists
  // -------------------------------------------------------------
  const filteredAgents = agents.filter((a) => {
    if (agentStatusFilter !== "ALL" && a.status?.toLowerCase() !== agentStatusFilter.toLowerCase()) {
      return false;
    }
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      return a.name.toLowerCase().includes(q) || a.id.toLowerCase().includes(q);
    }
    return true;
  });

  const filteredDelegations = delegations.filter((d) => {
    if (delegationStatusFilter !== "ALL" && d.status !== delegationStatusFilter) {
      return false;
    }
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      return (
        d.id.toLowerCase().includes(q) ||
        d.parent_transaction_id?.toLowerCase().includes(q) ||
        d.child_agent_id?.toLowerCase().includes(q)
      );
    }
    return true;
  });

  const filteredHandoffs = handoffs.filter((h) => {
    if (handoffStatusFilter !== "ALL" && h.status !== handoffStatusFilter) {
      return false;
    }
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      return (
        h.id.toLowerCase().includes(q) ||
        h.parent_transaction_id?.toLowerCase().includes(q) ||
        h.child_agent_id?.toLowerCase().includes(q)
      );
    }
    return true;
  });

  const filteredLeases = leases.filter((l) => {
    if (leaseStatusFilter !== "ALL" && l.status !== leaseStatusFilter) {
      return false;
    }
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      return (
        l.resource_uri.toLowerCase().includes(q) ||
        l.holder_transaction_id?.toLowerCase().includes(q) ||
        l.id.toLowerCase().includes(q)
      );
    }
    return true;
  });

  // Calculate high-level metrics
  const activeAgentsCount = agents.filter((a) => a.status === "active").length;
  const activeDelegationsCount = delegations.filter((d) => d.status === "ACTIVE").length;
  const pendingHandoffsCount = handoffs.filter((h) => h.status === "PENDING").length;
  const activeLeasesCount = leases.filter((l) => l.status === "ACQUIRED").length;

  return (
    <div className="space-y-6">
      {/* View Header with High-Level Metrics */}
      <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-5 shadow-sm">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800/80 pb-4">
          <div>
            <div className="flex items-center space-x-2">
              <Network className="w-5 h-5 text-indigo-400" />
              <h1 className="text-lg font-semibold text-white tracking-tight">
                Governed Multi-Agent Coordination & Assurance
              </h1>
              <span className="text-xs px-2 py-0.5 rounded font-mono bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                Phase 8
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1">
              Authoritative agent lifecycle governance, attenuated delegation grants, governed handoffs, distributed resource leases, and Gate 5 hierarchical outcome assurance.
            </p>
          </div>

          <div className="flex items-center space-x-3">
            <button
              onClick={fetchData}
              disabled={loading}
              className="px-3 py-1.5 text-xs font-medium text-slate-300 hover:text-white bg-slate-800/80 hover:bg-slate-800 border border-slate-700/60 rounded-lg flex items-center space-x-1.5 transition"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin text-sky-400" : ""}`} />
              <span>Refresh State</span>
            </button>
          </div>
        </div>

        {/* Global Stats Cards */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-4">
          <div className="bg-slate-950/60 border border-slate-800/60 rounded-lg p-3">
            <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider block">
              Active Governed Agents
            </span>
            <div className="flex items-baseline space-x-2 mt-1">
              <span className="text-xl font-bold text-emerald-400 font-mono">{activeAgentsCount}</span>
              <span className="text-xs text-slate-500">/ {agents.length} registered</span>
            </div>
          </div>

          <div className="bg-slate-950/60 border border-slate-800/60 rounded-lg p-3">
            <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider block">
              Active Delegations
            </span>
            <div className="flex items-baseline space-x-2 mt-1">
              <span className="text-xl font-bold text-sky-400 font-mono">{activeDelegationsCount}</span>
              <span className="text-xs text-slate-500">/ {delegations.length} total</span>
            </div>
          </div>

          <div className="bg-slate-950/60 border border-slate-800/60 rounded-lg p-3">
            <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider block">
              Pending Handoffs
            </span>
            <div className="flex items-baseline space-x-2 mt-1">
              <span className="text-xl font-bold text-amber-400 font-mono">{pendingHandoffsCount}</span>
              <span className="text-xs text-slate-500">awaiting acceptance</span>
            </div>
          </div>

          <div className="bg-slate-950/60 border border-slate-800/60 rounded-lg p-3">
            <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider block">
              Active Concurrency Leases
            </span>
            <div className="flex items-baseline space-x-2 mt-1">
              <span className="text-xl font-bold text-purple-400 font-mono">{activeLeasesCount}</span>
              <span className="text-xs text-slate-500">fencing tokens active</span>
            </div>
          </div>
        </div>
      </div>

      {/* Global Alerts / Feedback */}
      {error && (
        <div
          role="alert"
          className="bg-rose-950/70 border border-rose-800 text-rose-200 text-xs px-4 py-3 rounded-lg flex items-center justify-between shadow-sm"
        >
          <div className="flex items-center space-x-2">
            <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
            <span>{error}</span>
          </div>
          <button
            onClick={() => setError(null)}
            className="text-rose-400 hover:text-white"
            aria-label="Dismiss error"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {feedback && (
        <div
          role="status"
          className="bg-emerald-950/70 border border-emerald-800 text-emerald-200 text-xs px-4 py-3 rounded-lg flex items-center justify-between shadow-sm"
        >
          <div className="flex items-center space-x-2">
            <CheckCircle className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>{feedback}</span>
          </div>
          <button
            onClick={() => setFeedback(null)}
            className="text-emerald-400 hover:text-white"
            aria-label="Dismiss message"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Primary Sub-Navigation Bar */}
      <div className="flex items-center space-x-1 border-b border-slate-800 pb-2 overflow-x-auto scrollbar-none">
        {[
          { id: "agents", label: "Agents & Lifecycle", icon: Users, count: agents.length },
          { id: "delegations", label: "Delegation Grants", icon: Key, count: delegations.length },
          { id: "handoffs", label: "Governed Handoffs", icon: GitBranch, count: handoffs.length },
          { id: "concurrency", label: "Resource Leases", icon: Lock, count: leases.length },
          { id: "hierarchy", label: "Hierarchical Assurance", icon: Layers, count: null },
        ].map((tab) => {
          const Icon = tab.icon;
          const isActive = activeSubTab === tab.id;
          return (
            <button
              key={tab.id}
              role="tab"
              aria-selected={isActive}
              onClick={() => {
                setActiveSubTab(tab.id);
                setSearchQuery("");
              }}
              className={`flex items-center space-x-2 px-3.5 py-2 rounded-lg text-xs font-medium transition focus:outline-none focus:ring-1 focus:ring-indigo-500 whitespace-nowrap ${
                isActive
                  ? "bg-indigo-600/15 text-indigo-300 border border-indigo-500/30"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-900/60 border border-transparent"
              }`}
            >
              <Icon className="w-4 h-4" />
              <span>{tab.label}</span>
              {tab.count !== null && (
                <span
                  className={`text-[10px] px-1.5 py-0.2 rounded-full font-mono ${
                    isActive ? "bg-indigo-500/20 text-indigo-200" : "bg-slate-800 text-slate-400"
                  }`}
                >
                  {tab.count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* ========================================================= */}
      {/* 1. AGENTS & LIFECYCLE TAB */}
      {/* ========================================================= */}
      {activeSubTab === "agents" && (
        <div className="space-y-4">
          {/* Controls Bar */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-slate-900/40 p-3 rounded-lg border border-slate-800">
            <div className="flex items-center space-x-2 flex-1 max-w-md">
              <Search className="w-4 h-4 text-slate-500" />
              <input
                type="text"
                placeholder="Filter agents by name or ID..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="bg-slate-950 border border-slate-800 text-slate-200 text-xs rounded-md px-2.5 py-1.5 w-full focus:outline-none focus:border-indigo-500"
              />
            </div>

            <div className="flex items-center space-x-2">
              <select
                value={agentStatusFilter}
                onChange={(e) => setAgentStatusFilter(e.target.value)}
                className="bg-slate-950 border border-slate-800 text-slate-300 text-xs rounded-md px-2.5 py-1.5 focus:outline-none focus:border-indigo-500"
                aria-label="Filter agents by status"
              >
                <option value="ALL">All Statuses</option>
                <option value="active">Active</option>
                <option value="registered">Registered</option>
                <option value="suspended">Suspended</option>
                <option value="revoked">Revoked</option>
              </select>

              <button
                onClick={() => {
                  setModalType("REGISTER_AGENT");
                  setModalInput({ name: "", max_autonomy_level: 1, initial_status: "registered" });
                }}
                className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-md text-xs font-medium flex items-center space-x-1.5 transition"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>Register Agent</span>
              </button>
            </div>
          </div>

          {/* Agents Table */}
          <div className="border border-slate-800 rounded-xl overflow-hidden bg-slate-900/40">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="bg-slate-950/80 border-b border-slate-800 text-slate-400 font-semibold uppercase text-[11px] tracking-wider">
                  <th className="py-3 px-4">Agent Name / ID</th>
                  <th className="py-3 px-4">Lifecycle Status</th>
                  <th className="py-3 px-4">Autonomy Ceiling</th>
                  <th className="py-3 px-4">Registered Date</th>
                  <th className="py-3 px-4 text-right">Governed Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {filteredAgents.length === 0 ? (
                  <tr>
                    <td colSpan="5" className="py-8 text-center text-slate-500">
                      {loading ? "Loading registered agents..." : "No matching agents found in tenant registry."}
                    </td>
                  </tr>
                ) : (
                  filteredAgents.map((agent) => {
                    const isRevoked = agent.status === "revoked";
                    const isSuspended = agent.status === "suspended";
                    const isActive = agent.status === "active";
                    const isRegistered = agent.status === "registered";

                    return (
                      <tr key={agent.id} className="hover:bg-slate-800/30 transition">
                        <td className="py-3 px-4">
                          <div className="font-semibold text-slate-200">{agent.name}</div>
                          <div className="font-mono text-[11px] text-slate-500 flex items-center space-x-1">
                            <span>{agent.id}</span>
                            <button
                              onClick={() => copyToClipboard(agent.id)}
                              className="text-slate-600 hover:text-slate-400 p-0.5"
                              title="Copy ID"
                            >
                              <Copy className="w-2.5 h-2.5" />
                            </button>
                          </div>
                        </td>
                        <td className="py-3 px-4">
                          {isActive && (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-emerald-950/80 text-emerald-400 border border-emerald-800/80">
                              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 mr-1.5 animate-pulse" />
                              Active
                            </span>
                          )}
                          {isRegistered && (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-sky-950/80 text-sky-400 border border-sky-800/80">
                              Registered
                            </span>
                          )}
                          {isSuspended && (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-amber-950/80 text-amber-400 border border-amber-800/80">
                              Suspended
                            </span>
                          )}
                          {isRevoked && (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-rose-950/80 text-rose-400 border border-rose-800/80">
                              Revoked (Terminal)
                            </span>
                          )}
                          {agent.suspension_reason && (
                            <div className="text-[10px] text-amber-500/80 mt-0.5 truncate max-w-xs" title={agent.suspension_reason}>
                              Reason: {agent.suspension_reason}
                            </div>
                          )}
                          {agent.revocation_reason && (
                            <div className="text-[10px] text-rose-500/80 mt-0.5 truncate max-w-xs" title={agent.revocation_reason}>
                              Reason: {agent.revocation_reason}
                            </div>
                          )}
                        </td>
                        <td className="py-3 px-4">
                          <span className="font-mono bg-slate-800 text-slate-300 px-2 py-0.5 rounded text-xs">
                            L{agent.max_autonomy_level}
                          </span>
                        </td>
                        <td className="py-3 px-4 text-slate-400 text-xs">
                          {agent.created_at ? new Date(agent.created_at).toLocaleString() : "—"}
                        </td>
                        <td className="py-3 px-4 text-right space-x-1.5">
                          {isRevoked ? (
                            <span className="text-slate-600 text-xs italic">Terminal state</span>
                          ) : (
                            <>
                              {(isRegistered || isSuspended) && (
                                <button
                                  onClick={() => {
                                    setTargetItem({ action: "activate", agent });
                                    setModalType("CONFIRM_AGENT_TRANSITION");
                                    setModalReason("Operator verified readiness");
                                  }}
                                  className="px-2.5 py-1 text-[11px] font-medium bg-emerald-900/40 hover:bg-emerald-900/60 text-emerald-300 border border-emerald-700/60 rounded transition"
                                >
                                  Activate
                                </button>
                              )}
                              {isActive && (
                                <button
                                  onClick={() => {
                                    setTargetItem({ action: "suspend", agent });
                                    setModalType("CONFIRM_AGENT_TRANSITION");
                                    setModalReason("");
                                  }}
                                  className="px-2.5 py-1 text-[11px] font-medium bg-amber-900/40 hover:bg-amber-900/60 text-amber-300 border border-amber-700/60 rounded transition"
                                >
                                  Suspend
                                </button>
                              )}
                              <button
                                onClick={() => {
                                  setTargetItem({ action: "revoke", agent });
                                  setModalType("CONFIRM_AGENT_TRANSITION");
                                  setModalReason("");
                                }}
                                className="px-2.5 py-1 text-[11px] font-medium bg-rose-950/50 hover:bg-rose-900/70 text-rose-300 border border-rose-800/70 rounded transition"
                              >
                                Revoke
                              </button>
                            </>
                          )}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* 2. DELEGATION GRANTS TAB */}
      {/* ========================================================= */}
      {activeSubTab === "delegations" && (
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-slate-900/40 p-3 rounded-lg border border-slate-800">
            <div className="flex items-center space-x-2 flex-1 max-w-md">
              <Search className="w-4 h-4 text-slate-500" />
              <input
                type="text"
                placeholder="Search delegations by ID, parent txn, child agent..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="bg-slate-950 border border-slate-800 text-slate-200 text-xs rounded-md px-2.5 py-1.5 w-full focus:outline-none focus:border-indigo-500"
              />
            </div>

            <div className="flex items-center space-x-2">
              <select
                value={delegationStatusFilter}
                onChange={(e) => setDelegationStatusFilter(e.target.value)}
                className="bg-slate-950 border border-slate-800 text-slate-300 text-xs rounded-md px-2.5 py-1.5 focus:outline-none focus:border-indigo-500"
                aria-label="Filter delegations by status"
              >
                <option value="ALL">All Statuses</option>
                <option value="ACTIVE">ACTIVE</option>
                <option value="PENDING">PENDING</option>
                <option value="REVOKED">REVOKED</option>
                <option value="EXPIRED">EXPIRED</option>
                <option value="CONSUMED">CONSUMED</option>
              </select>

              <button
                onClick={() => {
                  setModalType("CREATE_DELEGATION");
                  setModalInput({
                    parent_transaction_id: "",
                    delegatee_agent_id: "",
                    capability_type: "tools:file_read",
                    max_autonomy_level: 1,
                    max_turns: 4,
                    duration_seconds: 300,
                    purpose: "",
                  });
                }}
                className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-md text-xs font-medium flex items-center space-x-1.5 transition"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>Issue Delegation</span>
              </button>
            </div>
          </div>

          <div className="border border-slate-800 rounded-xl overflow-hidden bg-slate-900/40">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="bg-slate-950/80 border-b border-slate-800 text-slate-400 font-semibold uppercase text-[11px] tracking-wider">
                  <th className="py-3 px-4">Grant ID & Lineage</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4">Attenuated Capabilities</th>
                  <th className="py-3 px-4">Ceiling & Turns</th>
                  <th className="py-3 px-4">Expiry (UTC)</th>
                  <th className="py-3 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {filteredDelegations.length === 0 ? (
                  <tr>
                    <td colSpan="6" className="py-8 text-center text-slate-500">
                      {loading ? "Loading delegation grants..." : "No delegation grants found."}
                    </td>
                  </tr>
                ) : (
                  filteredDelegations.map((grant) => {
                    const isPending = grant.status === "PENDING";
                    const isActive = grant.status === "ACTIVE";
                    const isRevoked = grant.status === "REVOKED";

                    return (
                      <tr key={grant.id} className="hover:bg-slate-800/30 transition">
                        <td className="py-3 px-4">
                          <div className="font-mono font-semibold text-slate-200">{grant.id}</div>
                          <div className="text-[11px] text-slate-400 mt-0.5">
                            <span className="text-slate-500">Parent:</span> {grant.parent_transaction_id}
                          </div>
                          <div className="text-[11px] text-indigo-400">
                            <span className="text-slate-500">Target Agent:</span> {grant.child_agent_id}
                          </div>
                          {grant.child_transaction_id && (
                            <div className="text-[10px] text-emerald-400 font-mono mt-0.5">
                              Bound Child Txn: {grant.child_transaction_id}
                            </div>
                          )}
                        </td>
                        <td className="py-3 px-4">
                          <span
                            className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium ${
                              isActive
                                ? "bg-emerald-950/80 text-emerald-400 border border-emerald-800/80"
                                : isPending
                                ? "bg-sky-950/80 text-sky-400 border border-sky-800/80"
                                : isRevoked
                                ? "bg-rose-950/80 text-rose-400 border border-rose-800/80"
                                : "bg-slate-800 text-slate-400"
                            }`}
                          >
                            {grant.status}
                          </span>
                        </td>
                        <td className="py-3 px-4">
                          <div className="space-y-1">
                            {grant.delegated_capabilities?.map((c, idx) => (
                              <span
                                key={idx}
                                className="inline-block bg-slate-950 border border-slate-800 text-slate-300 font-mono text-[10px] px-1.5 py-0.5 rounded mr-1"
                              >
                                {c.capability_type} (L{c.max_autonomy_level})
                              </span>
                            ))}
                          </div>
                          <div className="text-[11px] text-slate-400 italic mt-1 truncate max-w-xs">
                            "{grant.purpose}"
                          </div>
                        </td>
                        <td className="py-3 px-4">
                          <div className="font-mono text-slate-300">Ceiling: L{grant.max_autonomy_level}</div>
                          <div className="text-slate-500 text-[11px]">Budget: {grant.max_turns} turns</div>
                        </td>
                        <td className="py-3 px-4 text-slate-400 font-mono text-xs">
                          {grant.expires_at ? new Date(grant.expires_at).toLocaleTimeString() : "—"}
                        </td>
                        <td className="py-3 px-4 text-right space-x-1.5">
                          {isPending && (
                            <button
                              onClick={() => {
                                setTargetItem(grant);
                                setModalType("ACTIVATE_DELEGATION");
                                setModalInput({ child_transaction_id: "" });
                              }}
                              className="px-2 py-1 text-[11px] font-medium bg-sky-900/40 hover:bg-sky-900/60 text-sky-300 border border-sky-700/60 rounded transition"
                            >
                              Activate
                            </button>
                          )}
                          {(isPending || isActive) && (
                            <button
                              onClick={() => {
                                setTargetItem(grant);
                                setModalType("REVOKE_DELEGATION");
                                setModalReason("");
                              }}
                              className="px-2 py-1 text-[11px] font-medium bg-rose-950/50 hover:bg-rose-900/70 text-rose-300 border border-rose-800/70 rounded transition"
                            >
                              Revoke
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* 3. GOVERNED HANDOFFS TAB */}
      {/* ========================================================= */}
      {activeSubTab === "handoffs" && (
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-slate-900/40 p-3 rounded-lg border border-slate-800">
            <div className="flex items-center space-x-2 flex-1 max-w-md">
              <Search className="w-4 h-4 text-slate-500" />
              <input
                type="text"
                placeholder="Search handoffs by ID, parent txn, child agent..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="bg-slate-950 border border-slate-800 text-slate-200 text-xs rounded-md px-2.5 py-1.5 w-full focus:outline-none focus:border-indigo-500"
              />
            </div>

            <div className="flex items-center space-x-2">
              <select
                value={handoffStatusFilter}
                onChange={(e) => setHandoffStatusFilter(e.target.value)}
                className="bg-slate-950 border border-slate-800 text-slate-300 text-xs rounded-md px-2.5 py-1.5 focus:outline-none focus:border-indigo-500"
                aria-label="Filter handoffs by status"
              >
                <option value="ALL">All Statuses</option>
                <option value="PENDING">PENDING</option>
                <option value="ACCEPTED">ACCEPTED</option>
                <option value="COMPLETED">COMPLETED</option>
                <option value="CANCELLED">CANCELLED</option>
                <option value="REJECTED">REJECTED</option>
              </select>

              <button
                onClick={() => {
                  setModalType("CREATE_HANDOFF");
                  setModalInput({
                    parent_transaction_id: "",
                    child_agent_id: "",
                    delegation_id: "",
                    purpose: "",
                    duration_seconds: 300,
                  });
                }}
                className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-md text-xs font-medium flex items-center space-x-1.5 transition"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>Initiate Handoff</span>
              </button>
            </div>
          </div>

          <div className="border border-slate-800 rounded-xl overflow-hidden bg-slate-900/40">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="bg-slate-950/80 border-b border-slate-800 text-slate-400 font-semibold uppercase text-[11px] tracking-wider">
                  <th className="py-3 px-4">Handoff ID & Lineage</th>
                  <th className="py-3 px-4">Bound Delegation</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4">Inherited Taints</th>
                  <th className="py-3 px-4">Expires</th>
                  <th className="py-3 px-4 text-right">Lifecycle Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {filteredHandoffs.length === 0 ? (
                  <tr>
                    <td colSpan="6" className="py-8 text-center text-slate-500">
                      {loading ? "Loading agent handoffs..." : "No agent handoffs found."}
                    </td>
                  </tr>
                ) : (
                  filteredHandoffs.map((handoff) => {
                    const isPending = handoff.status === "PENDING";
                    const isAccepted = handoff.status === "ACCEPTED";
                    const isCompleted = handoff.status === "COMPLETED";

                    return (
                      <tr key={handoff.id} className="hover:bg-slate-800/30 transition">
                        <td className="py-3 px-4">
                          <div className="font-mono font-semibold text-slate-200">{handoff.id}</div>
                          <div className="flex items-center space-x-1.5 text-[11px] text-slate-400 mt-1">
                            <span>Txn: {handoff.parent_transaction_id}</span>
                            <ArrowRight className="w-3 h-3 text-slate-500" />
                            <span className="text-indigo-400 font-semibold">{handoff.child_agent_id}</span>
                          </div>
                          {handoff.child_transaction_id && (
                            <div className="text-[10px] text-emerald-400 font-mono mt-0.5">
                              Spawned Txn: {handoff.child_transaction_id}
                            </div>
                          )}
                          <div className="text-[11px] text-slate-400 italic mt-0.5">"{handoff.purpose}"</div>
                        </td>
                        <td className="py-3 px-4 font-mono text-slate-400 text-xs">
                          {handoff.delegation_id}
                        </td>
                        <td className="py-3 px-4">
                          <span
                            className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium ${
                              isCompleted
                                ? "bg-emerald-950/80 text-emerald-400 border border-emerald-800/80"
                                : isAccepted
                                ? "bg-indigo-950/80 text-indigo-400 border border-indigo-800/80"
                                : isPending
                                ? "bg-amber-950/80 text-amber-400 border border-amber-800/80 animate-pulse"
                                : "bg-rose-950/80 text-rose-400 border border-rose-800/80"
                            }`}
                          >
                            {handoff.status}
                          </span>
                        </td>
                        <td className="py-3 px-4">
                          {handoff.inherited_taint_flags?.length > 0 ? (
                            <div className="flex flex-wrap gap-1">
                              {handoff.inherited_taint_flags.map((t, idx) => (
                                <span
                                  key={idx}
                                  className="text-[10px] font-mono bg-amber-950/40 text-amber-300 border border-amber-800/50 px-1.5 py-0.2 rounded"
                                >
                                  {t}
                                </span>
                              ))}
                            </div>
                          ) : (
                            <span className="text-slate-600 text-xs">None</span>
                          )}
                        </td>
                        <td className="py-3 px-4 text-slate-400 font-mono text-xs">
                          {handoff.expires_at ? new Date(handoff.expires_at).toLocaleTimeString() : "—"}
                        </td>
                        <td className="py-3 px-4 text-right space-x-1.5">
                          {isPending && (
                            <>
                              <button
                                onClick={() => {
                                  setTargetItem(handoff);
                                  setModalType("ACCEPT_HANDOFF");
                                  setModalInput({ input_context: "{}" });
                                }}
                                className="px-2 py-1 text-[11px] font-medium bg-emerald-900/40 hover:bg-emerald-900/60 text-emerald-300 border border-emerald-700/60 rounded transition"
                              >
                                Accept
                              </button>
                              <button
                                onClick={() => {
                                  setTargetItem(handoff);
                                  setModalType("CANCEL_HANDOFF");
                                  setModalReason("");
                                }}
                                className="px-2 py-1 text-[11px] font-medium bg-rose-950/50 hover:bg-rose-900/70 text-rose-300 border border-rose-800/70 rounded transition"
                              >
                                Cancel
                              </button>
                            </>
                          )}
                          {isAccepted && (
                            <>
                              <button
                                onClick={() => handleCompleteHandoffDirect(handoff)}
                                className="px-2 py-1 text-[11px] font-medium bg-indigo-900/40 hover:bg-indigo-900/60 text-indigo-300 border border-indigo-700/60 rounded transition"
                              >
                                Complete
                              </button>
                              <button
                                onClick={() => {
                                  setTargetItem(handoff);
                                  setModalType("CANCEL_HANDOFF");
                                  setModalReason("");
                                }}
                                className="px-2 py-1 text-[11px] font-medium bg-rose-950/50 hover:bg-rose-900/70 text-rose-300 border border-rose-800/70 rounded transition"
                              >
                                Abort
                              </button>
                            </>
                          )}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* 4. RESOURCE CONCURRENCY & LEASES TAB */}
      {/* ========================================================= */}
      {activeSubTab === "concurrency" && (
        <div className="space-y-4">
          {/* Safety Disclaimer Banner */}
          <div className="bg-purple-950/40 border border-purple-800/60 rounded-xl p-4 text-xs text-purple-200 flex items-start space-x-3">
            <Lock className="w-4 h-4 text-purple-400 mt-0.5 shrink-0" />
            <div>
              <div className="font-semibold text-purple-300">
                Distributed Resource Concurrency & Fencing Coordination Notice
              </div>
              <p className="text-purple-300/80 mt-0.5">
                Resource leases and monotonically increasing fencing tokens provide authoritative coordination metadata across concurrent agents.
                They coordinate access within MIRAGE; physical write safety requires the underlying storage target to enforce conditional monotonic token checks.
              </p>
            </div>
          </div>

          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-slate-900/40 p-3 rounded-lg border border-slate-800">
            <div className="flex items-center space-x-2 flex-1 max-w-md">
              <Search className="w-4 h-4 text-slate-500" />
              <input
                type="text"
                placeholder="Filter leases by Resource URI, holder txn..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="bg-slate-950 border border-slate-800 text-slate-200 text-xs rounded-md px-2.5 py-1.5 w-full focus:outline-none focus:border-indigo-500"
              />
            </div>

            <div className="flex items-center space-x-2">
              <select
                value={leaseStatusFilter}
                onChange={(e) => setLeaseStatusFilter(e.target.value)}
                className="bg-slate-950 border border-slate-800 text-slate-300 text-xs rounded-md px-2.5 py-1.5 focus:outline-none focus:border-indigo-500"
                aria-label="Filter leases by status"
              >
                <option value="ALL">All Statuses</option>
                <option value="ACQUIRED">ACQUIRED</option>
                <option value="RELEASED">RELEASED</option>
                <option value="EXPIRED">EXPIRED</option>
                <option value="REVOKED">REVOKED</option>
              </select>

              <button
                onClick={() => {
                  setModalType("ACQUIRE_LEASE");
                  setModalInput({
                    resource_uri: "",
                    transaction_id: "",
                    agent_id: "",
                    concurrency_mode: "EXCLUSIVE",
                    duration_seconds: 60,
                  });
                }}
                className="px-3 py-1.5 bg-purple-600 hover:bg-purple-500 text-white rounded-md text-xs font-medium flex items-center space-x-1.5 transition"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>Acquire Lease</span>
              </button>
            </div>
          </div>

          <div className="border border-slate-800 rounded-xl overflow-hidden bg-slate-900/40">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="bg-slate-950/80 border-b border-slate-800 text-slate-400 font-semibold uppercase text-[11px] tracking-wider">
                  <th className="py-3 px-4">Resource URI & Lease ID</th>
                  <th className="py-3 px-4">Mode</th>
                  <th className="py-3 px-4">Fencing Token</th>
                  <th className="py-3 px-4">Holder Identification</th>
                  <th className="py-3 px-4">Status & Expiry</th>
                  <th className="py-3 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {filteredLeases.length === 0 ? (
                  <tr>
                    <td colSpan="6" className="py-8 text-center text-slate-500">
                      {loading ? "Loading concurrency leases..." : "No active or historical leases found."}
                    </td>
                  </tr>
                ) : (
                  filteredLeases.map((lease) => {
                    const isAcquired = lease.status === "ACQUIRED";

                    return (
                      <tr key={lease.id} className="hover:bg-slate-800/30 transition">
                        <td className="py-3 px-4">
                          <div className="font-semibold text-slate-200">{lease.resource_uri}</div>
                          <div className="font-mono text-[11px] text-slate-500">{lease.id}</div>
                        </td>
                        <td className="py-3 px-4">
                          <span
                            className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-mono font-medium ${
                              lease.concurrency_mode === "EXCLUSIVE"
                                ? "bg-amber-950/80 text-amber-400 border border-amber-800/80"
                                : "bg-sky-950/80 text-sky-400 border border-sky-800/80"
                            }`}
                          >
                            {lease.concurrency_mode}
                          </span>
                        </td>
                        <td className="py-3 px-4">
                          <span className="font-mono text-purple-300 font-bold bg-purple-950/80 border border-purple-800 px-2 py-0.5 rounded text-xs">
                            Token #{lease.fencing_token}
                          </span>
                        </td>
                        <td className="py-3 px-4 font-mono text-[11px]">
                          <div className="text-slate-300">Txn: {lease.holder_transaction_id}</div>
                          <div className="text-slate-500">Agent: {lease.holder_agent_id}</div>
                        </td>
                        <td className="py-3 px-4">
                          <div
                            className={`text-[11px] font-medium ${
                              isAcquired ? "text-emerald-400" : "text-slate-500"
                            }`}
                          >
                            {lease.status}
                          </div>
                          <div className="font-mono text-[10px] text-slate-400">
                            {lease.expires_at ? new Date(lease.expires_at).toLocaleTimeString() : "—"}
                          </div>
                        </td>
                        <td className="py-3 px-4 text-right space-x-1.5">
                          {isAcquired && (
                            <>
                              <button
                                onClick={() => {
                                  setTargetItem(lease);
                                  setModalType("RENEW_LEASE");
                                  setModalInput({ duration_seconds: 60 });
                                }}
                                className="px-2 py-1 text-[11px] font-medium bg-purple-900/40 hover:bg-purple-900/60 text-purple-300 border border-purple-700/60 rounded transition"
                              >
                                Renew
                              </button>
                              <button
                                onClick={() => {
                                  setTargetItem(lease);
                                  setModalType("RELEASE_LEASE");
                                }}
                                className="px-2 py-1 text-[11px] font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-600 rounded transition"
                              >
                                Release
                              </button>
                            </>
                          )}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* 5. HIERARCHICAL OUTCOME ASSURANCE TAB */}
      {/* ========================================================= */}
      {activeSubTab === "hierarchy" && (
        <div className="space-y-6">
          {/* Inspection Input */}
          <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 flex flex-col sm:flex-row items-center gap-3">
            <div className="flex-1 w-full">
              <label htmlFor="hierarchy-txn-input" className="block text-[11px] font-medium text-slate-400 mb-1">
                Enter Root or Parent Transaction ID:
              </label>
              <div className="flex items-center space-x-2">
                <input
                  id="hierarchy-txn-input"
                  type="text"
                  placeholder="e.g. txn_..."
                  value={hierarchyTxnId}
                  onChange={(e) => setHierarchyTxnId(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && loadHierarchy(hierarchyTxnId)}
                  className="bg-slate-950 border border-slate-800 text-slate-200 font-mono text-xs rounded-lg px-3 py-2 w-full focus:outline-none focus:border-indigo-500"
                />
                <button
                  onClick={() => loadHierarchy(hierarchyTxnId)}
                  disabled={hierarchyLoading || !hierarchyTxnId.trim()}
                  className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-medium transition disabled:opacity-50 shrink-0"
                >
                  {hierarchyLoading ? "Auditing..." : "Audit Lineage"}
                </button>
              </div>
            </div>

            {/* Quick Pick from known handoffs */}
            {handoffs.length > 0 && (
              <div className="w-full sm:w-auto shrink-0">
                <label className="block text-[11px] font-medium text-slate-400 mb-1">
                  Or select recent parent transaction:
                </label>
                <select
                  onChange={(e) => {
                    setHierarchyTxnId(e.target.value);
                    loadHierarchy(e.target.value);
                  }}
                  className="bg-slate-950 border border-slate-800 text-slate-300 text-xs rounded-lg px-3 py-2 w-full focus:outline-none focus:border-indigo-500"
                >
                  <option value="">Select a transaction...</option>
                  {Array.from(new Set(handoffs.map((h) => h.parent_transaction_id))).map((tId) => (
                    <option key={tId} value={tId}>
                      {tId}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          {hierarchyError && (
            <div className="bg-rose-950/70 border border-rose-800 text-rose-200 text-xs p-4 rounded-xl flex items-center space-x-2">
              <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
              <span>{hierarchyError}</span>
            </div>
          )}

          {hierarchyData && (
            <div className="space-y-6">
              {/* Parent Aggregation Hero Card */}
              <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-5 space-y-4">
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 border-b border-slate-800 pb-4">
                  <div>
                    <span className="text-xs text-slate-400 font-mono">Transaction ID:</span>
                    <h2 className="text-base font-bold text-white font-mono">{hierarchyData.parent_transaction_id}</h2>
                    <div className="flex items-center space-x-3 text-xs text-slate-400 mt-1">
                      <span>
                        State: <strong className="text-slate-200">{hierarchyData.parent_transaction_state}</strong>
                      </span>
                      <span>•</span>
                      <span>
                        Disposition:{" "}
                        <strong className="text-slate-200">{hierarchyData.parent_final_disposition || "IN_PROGRESS"}</strong>
                      </span>
                    </div>
                  </div>

                  {/* Hierarchical Outcome Status Badge */}
                  <div className="flex flex-col sm:items-end">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                      Aggregated Gate 5 Status
                    </span>
                    <div className="mt-1">
                      {hierarchyData.hierarchical_status === "VERIFIED_SUCCESS" && (
                        <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-emerald-950 text-emerald-400 border border-emerald-800">
                          <CheckCircle className="w-3.5 h-3.5 mr-1.5 text-emerald-400" />
                          VERIFIED SUCCESS (Reality Confirmed)
                        </span>
                      )}
                      {hierarchyData.hierarchical_status === "AWAITING_OUTCOME_VERIFICATION" && (
                        <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-amber-950 text-amber-400 border border-amber-800 animate-pulse">
                          <Clock className="w-3.5 h-3.5 mr-1.5 text-amber-400" />
                          AWAITING OUTCOME VERIFICATION (Executed != Verified)
                        </span>
                      )}
                      {hierarchyData.hierarchical_status === "PENDING_CHILD_WORK" && (
                        <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-sky-950 text-sky-400 border border-sky-800">
                          <Clock className="w-3.5 h-3.5 mr-1.5 text-sky-400" />
                          PENDING CHILD EXECUTION / HANDOFF
                        </span>
                      )}
                      {hierarchyData.hierarchical_status === "HIERARCHICAL_FAILURE" && (
                        <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-rose-950 text-rose-400 border border-rose-800">
                          <XCircle className="w-3.5 h-3.5 mr-1.5 text-rose-400" />
                          HIERARCHICAL FAILURE
                        </span>
                      )}
                      {hierarchyData.hierarchical_status === "PARTIAL_ACHIEVEMENT" && (
                        <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-amber-950 text-amber-300 border border-amber-700">
                          <AlertTriangle className="w-3.5 h-3.5 mr-1.5 text-amber-300" />
                          PARTIAL ACHIEVEMENT (Sub-goals Failed)
                        </span>
                      )}
                      {hierarchyData.hierarchical_status === "UNVERIFIABLE" && (
                        <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-slate-800 text-slate-300 border border-slate-700">
                          UNVERIFIABLE (Blind Sink Target)
                        </span>
                      )}
                      {hierarchyData.hierarchical_status === "CANCELLED" && (
                        <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-rose-950/70 text-rose-400 border border-rose-800">
                          CANCELLED
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                {/* Epistemic Confidence and Hash Details */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="bg-slate-950/60 border border-slate-800/80 rounded-lg p-3">
                    <div className="flex justify-between items-center text-xs mb-1">
                      <span className="text-slate-400 font-medium">Weakest-Link Epistemic Confidence:</span>
                      <span className="font-mono font-bold text-white">
                        {(hierarchyData.epistemic_confidence * 100).toFixed(1)}%
                      </span>
                    </div>
                    <div className="w-full bg-slate-800 rounded-full h-2 overflow-hidden">
                      <div
                        className={`h-full transition-all duration-500 ${
                          hierarchyData.epistemic_confidence >= 0.9
                            ? "bg-emerald-500"
                            : hierarchyData.epistemic_confidence >= 0.5
                            ? "bg-amber-500"
                            : "bg-rose-500"
                        }`}
                        style={{ width: `${hierarchyData.epistemic_confidence * 100}%` }}
                      />
                    </div>
                    <span className="text-[10px] text-slate-500 mt-1 block">
                      Guaranteed lower bound across all verified consequential action postconditions.
                    </span>
                  </div>

                  <div className="bg-slate-950/60 border border-slate-800/80 rounded-lg p-3">
                    <span className="text-slate-400 text-xs font-medium block">Cryptographic Evaluation Hash:</span>
                    <div className="flex items-center space-x-2 mt-1">
                      <span className="font-mono text-[11px] text-indigo-300 truncate select-all">
                        {hierarchyData.evaluation_hash}
                      </span>
                      <button
                        onClick={() => copyToClipboard(hierarchyData.evaluation_hash)}
                        className="text-slate-400 hover:text-white p-1"
                        title="Copy SHA-256 hash"
                      >
                        {copiedHash ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                      </button>
                    </div>
                    <span className="text-[10px] text-slate-500 mt-1 block">
                      Tamper-evident canonical evaluation digest for tenant audit chain.
                    </span>
                  </div>
                </div>

                {/* Discrepancies and Reconciliation Alerts */}
                {hierarchyData.discrepancies?.length > 0 && (
                  <div className="bg-rose-950/40 border border-rose-800/60 rounded-lg p-3">
                    <span className="text-xs font-bold text-rose-300 flex items-center space-x-1.5">
                      <AlertTriangle className="w-3.5 h-3.5 text-rose-400" />
                      <span>Lineage Discrepancies Detected:</span>
                    </span>
                    <ul className="list-disc list-inside text-xs text-rose-200 mt-1 space-y-0.5">
                      {hierarchyData.discrepancies.map((d, i) => (
                        <li key={i}>{d}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {hierarchyData.reconciliation_notes?.length > 0 && (
                  <div className="bg-slate-950/80 border border-slate-800 rounded-lg p-3">
                    <span className="text-xs font-semibold text-slate-300">Reconciliation Analysis:</span>
                    <ul className="list-disc list-inside text-xs text-slate-400 mt-1 space-y-0.5">
                      {hierarchyData.reconciliation_notes.map((n, i) => (
                        <li key={i}>{n}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>

              {/* Lineage Tree Breakdown */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Parent Actions */}
                <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-4 space-y-3">
                  <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300">
                      Parent Consequential Actions ({hierarchyData.parent_actions?.length || 0})
                    </h3>
                  </div>
                  {hierarchyData.parent_actions?.length === 0 ? (
                    <div className="text-slate-500 text-xs py-4 text-center">No direct parent actions executed.</div>
                  ) : (
                    <div className="space-y-2">
                      {hierarchyData.parent_actions.map((act) => (
                        <div key={act.action_id} className="bg-slate-950 border border-slate-800/80 rounded-lg p-3 text-xs">
                          <div className="flex justify-between items-start">
                            <div>
                              <span className="font-mono text-indigo-300 font-semibold">{act.action_id}</span>
                              <div className="text-slate-400 text-[11px] mt-0.5">
                                Target: {act.target_resource || "None"}
                              </div>
                            </div>
                            <div className="text-right">
                              <span className="font-mono text-[10px] bg-slate-800 px-1.5 py-0.5 rounded text-slate-300">
                                {act.action_state}
                              </span>
                            </div>
                          </div>
                          <div className="mt-2 pt-2 border-t border-slate-800/60 flex justify-between items-center">
                            <span className="text-[11px] text-slate-400">Reality Verifier Status:</span>
                            <span
                              className={`text-[11px] font-semibold ${
                                act.outcome_status === "VERIFIED_SUCCESS" || act.outcome_status === "SUCCESS_CONFIRMED"
                                  ? "text-emerald-400"
                                  : act.outcome_status === "PENDING_VERIFICATION"
                                  ? "text-amber-400"
                                  : "text-slate-400"
                              }`}
                            >
                              {act.outcome_status || "Awaiting Verification"}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Child Transactions Lineage */}
                <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-4 space-y-3">
                  <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300">
                      Child Transaction Lineage ({hierarchyData.child_executions?.length || 0})
                    </h3>
                  </div>
                  {hierarchyData.child_executions?.length === 0 ? (
                    <div className="text-slate-500 text-xs py-4 text-center">No delegated child transactions spawned.</div>
                  ) : (
                    <div className="space-y-3">
                      {hierarchyData.child_executions.map((child) => (
                        <div key={child.transaction_id} className="bg-slate-950 border border-slate-800/80 rounded-lg p-3 text-xs space-y-2">
                          <div className="flex justify-between items-start">
                            <div>
                              <span className="font-mono text-emerald-400 font-semibold">{child.transaction_id}</span>
                              <div className="text-slate-400 text-[11px]">
                                Delegatee: <strong className="text-slate-200">{child.agent_id || "Unknown"}</strong>
                              </div>
                            </div>
                            <span
                              className={`text-[10px] font-mono px-2 py-0.5 rounded ${
                                child.execution_completed ? "bg-emerald-950 text-emerald-300" : "bg-sky-950 text-sky-300 animate-pulse"
                              }`}
                            >
                              {child.state} ({child.execution_completed ? "Completed" : "Executing"})
                            </span>
                          </div>

                          {/* Child actions within this transaction */}
                          {child.action_summaries?.length > 0 && (
                            <div className="bg-slate-900/60 rounded p-2 text-[11px] space-y-1">
                              <span className="text-slate-400 font-semibold block text-[10px] uppercase">
                                Verified Child Actions:
                              </span>
                              {child.action_summaries.map((ca) => (
                                <div key={ca.action_id} className="flex justify-between items-center text-[10px] font-mono">
                                  <span className="text-slate-300">{ca.action_id}</span>
                                  <span
                                    className={
                                      ca.outcome_status === "VERIFIED_SUCCESS"
                                        ? "text-emerald-400 font-semibold"
                                        : "text-amber-400"
                                    }
                                  >
                                    {ca.outcome_status || "Awaiting Verification"}
                                  </span>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ========================================================= */}
      {/* MODALS */}
      {/* ========================================================= */}

      {/* 1. Register Agent Modal */}
      {modalType === "REGISTER_AGENT" && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-5 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-sm font-semibold text-white">Register New Governed Agent</h3>
              <button onClick={closeModal} className="text-slate-400 hover:text-white">
                <X className="w-4 h-4" />
              </button>
            </div>
            <form onSubmit={handleRegisterAgentSubmit} className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-300 mb-1 font-medium">Agent Unique Name *</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. data_analyst_agent"
                  value={modalInput.name || ""}
                  onChange={(e) => setModalInput({ ...modalInput, name: e.target.value })}
                  className="w-full bg-slate-950 border border-slate-800 text-slate-200 px-3 py-2 rounded focus:outline-none focus:border-indigo-500 font-mono"
                />
              </div>

              <div>
                <label className="block text-slate-300 mb-1 font-medium">Max Autonomy Ceiling (0 to 5) *</label>
                <select
                  value={modalInput.max_autonomy_level || 0}
                  onChange={(e) => setModalInput({ ...modalInput, max_autonomy_level: e.target.value })}
                  className="w-full bg-slate-950 border border-slate-800 text-slate-200 px-3 py-2 rounded focus:outline-none focus:border-indigo-500"
                >
                  <option value={0}>L0 — Advisory Only (No autonomous mutations)</option>
                  <option value={1}>L1 — Simple Reads & Deterministic Verification</option>
                  <option value={2}>L2 — Scoped Autonomous Actions with Pre-approvals</option>
                  <option value={3}>L3 — Multi-step Execution with Salami-Slicing Guards</option>
                  <option value={4}>L4 — High-Impact Actions with Dual Operator Approvals</option>
                </select>
              </div>

              <div>
                <label className="block text-slate-300 mb-1 font-medium">Initial Lifecycle Status</label>
                <select
                  value={modalInput.initial_status || "registered"}
                  onChange={(e) => setModalInput({ ...modalInput, initial_status: e.target.value })}
                  className="w-full bg-slate-950 border border-slate-800 text-slate-200 px-3 py-2 rounded focus:outline-none focus:border-indigo-500"
                >
                  <option value="registered">Registered (Requires explicit activation)</option>
                  <option value="active">Active (Immediate execution authorization)</option>
                </select>
              </div>

              <div className="flex justify-end space-x-2 pt-2 border-t border-slate-800">
                <button
                  type="button"
                  onClick={closeModal}
                  className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={actionLoading}
                  className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white font-medium rounded transition disabled:opacity-50"
                >
                  {actionLoading ? "Registering..." : "Submit Registration"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 2. Confirm Agent Transition Modal */}
      {modalType === "CONFIRM_AGENT_TRANSITION" && targetItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-5 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-sm font-semibold text-white capitalize">
                {targetItem.action} Agent: {targetItem.agent.name}
              </h3>
              <button onClick={closeModal} className="text-slate-400 hover:text-white">
                <X className="w-4 h-4" />
              </button>
            </div>
            <form onSubmit={handleAgentTransitionSubmit} className="space-y-3 text-xs">
              {targetItem.action === "revoke" && (
                <div className="bg-rose-950/50 border border-rose-800 text-rose-300 p-3 rounded-lg">
                  <strong>Warning:</strong> Revocation is permanent and terminal. Once revoked, an agent cannot be reactivated or receive delegated handoffs.
                </div>
              )}

              <div>
                <label className="block text-slate-300 mb-1 font-medium">Audit Justification / Reason *</label>
                <textarea
                  required
                  rows={3}
                  placeholder={`Reason for ${targetItem.action}ing this agent...`}
                  value={modalReason}
                  onChange={(e) => setModalReason(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 text-slate-200 px-3 py-2 rounded focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div className="flex justify-end space-x-2 pt-2 border-t border-slate-800">
                <button
                  type="button"
                  onClick={closeModal}
                  className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={actionLoading || !modalReason.trim()}
                  className={`px-3 py-1.5 font-medium rounded transition disabled:opacity-50 ${
                    targetItem.action === "revoke"
                      ? "bg-rose-600 hover:bg-rose-500 text-white"
                      : "bg-indigo-600 hover:bg-indigo-500 text-white"
                  }`}
                >
                  {actionLoading ? "Processing..." : `Confirm ${targetItem.action}`}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 3. Create Delegation Grant Modal */}
      {modalType === "CREATE_DELEGATION" && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-5 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-sm font-semibold text-white">Create Attenuated Delegation Grant</h3>
              <button onClick={closeModal} className="text-slate-400 hover:text-white">
                <X className="w-4 h-4" />
              </button>
            </div>
            <form onSubmit={handleCreateDelegationSubmit} className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-300 mb-1 font-medium">Parent Transaction ID *</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. txn_parent_01"
                  value={modalInput.parent_transaction_id || ""}
                  onChange={(e) => setModalInput({ ...modalInput, parent_transaction_id: e.target.value })}
                  className="w-full bg-slate-950 border border-slate-800 text-slate-200 px-3 py-2 rounded focus:outline-none focus:border-indigo-500 font-mono"
                />
              </div>

              <div>
                <label className="block text-slate-300 mb-1 font-medium">Delegatee Agent ID *</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. agt_delegatee_01"
                  value={modalInput.delegatee_agent_id || ""}
                  onChange={(e) => setModalInput({ ...modalInput, delegatee_agent_id: e.target.value })}
                  className="w-full bg-slate-950 border border-slate-800 text-slate-200 px-3 py-2 rounded focus:outline-none focus:border-indigo-500 font-mono"
                />
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-slate-300 mb-1 font-medium">Capability Type *</label>
                  <input
                    type="text"
                    required
                    placeholder="tools:file_read"
                    value={modalInput.capability_type || ""}
                    onChange={(e) => setModalInput({ ...modalInput, capability_type: e.target.value })}
                    className="w-full bg-slate-950 border border-slate-800 text-slate-200 px-3 py-2 rounded focus:outline-none focus:border-indigo-500 font-mono"
                  />
                </div>
                <div>
                  <label className="block text-slate-300 mb-1 font-medium">Max Autonomy (L0-L4)</label>
                  <select
                    value={modalInput.max_autonomy_level || 1}
                    onChange={(e) => setModalInput({ ...modalInput, max_autonomy_level: e.target.value })}
                    className="w-full bg-slate-950 border border-slate-800 text-slate-200 px-3 py-2 rounded focus:outline-none focus:border-indigo-500"
                  >
                    <option value={0}>L0</option>
                    <option value={1}>L1</option>
                    <option value={2}>L2</option>
                    <option value={3}>L3</option>
                    <option value={4}>L4</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-slate-300 mb-1 font-medium">Max Turns (1-32)</label>
                  <input
                    type="number"
                    min="1"
                    max="32"
                    value={modalInput.max_turns || 4}
                    onChange={(e) => setModalInput({ ...modalInput, max_turns: e.target.value })}
                    className="w-full bg-slate-950 border border-slate-800 text-slate-200 px-3 py-2 rounded focus:outline-none focus:border-indigo-500 font-mono"
                  />
                </div>
                <div>
                  <label className="block text-slate-300 mb-1 font-medium">Lifespan (seconds)</label>
                  <input
                    type="number"
                    min="10"
                    max="86400"
                    value={modalInput.duration_seconds || 300}
                    onChange={(e) => setModalInput({ ...modalInput, duration_seconds: e.target.value })}
                    className="w-full bg-slate-950 border border-slate-800 text-slate-200 px-3 py-2 rounded focus:outline-none focus:border-indigo-500 font-mono"
                  />
                </div>
              </div>

              <div>
                <label className="block text-slate-300 mb-1 font-medium">Operational Purpose *</label>
                <textarea
                  required
                  rows={2}
                  placeholder="Business justification for delegation..."
                  value={modalInput.purpose || ""}
                  onChange={(e) => setModalInput({ ...modalInput, purpose: e.target.value })}
                  className="w-full bg-slate-950 border border-slate-800 text-slate-200 px-3 py-2 rounded focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div className="flex justify-end space-x-2 pt-2 border-t border-slate-800">
                <button
                  type="button"
                  onClick={closeModal}
                  className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={actionLoading}
                  className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white font-medium rounded transition disabled:opacity-50"
                >
                  {actionLoading ? "Issuing..." : "Create Grant"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 4. Activate Delegation Modal */}
      {modalType === "ACTIVATE_DELEGATION" && targetItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-5 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-sm font-semibold text-white">Activate Delegation: {targetItem.id}</h3>
              <button onClick={closeModal} className="text-slate-400 hover:text-white">
                <X className="w-4 h-4" />
              </button>
            </div>
            <form onSubmit={handleActivateDelegationSubmit} className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-300 mb-1 font-medium">Spawned Child Transaction ID *</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. txn_child_01"
                  value={modalInput.child_transaction_id || ""}
                  onChange={(e) => setModalInput({ ...modalInput, child_transaction_id: e.target.value })}
                  className="w-full bg-slate-950 border border-slate-800 text-slate-200 px-3 py-2 rounded focus:outline-none focus:border-indigo-500 font-mono"
                />
                <span className="text-[10px] text-slate-500 mt-1 block">
                  Binds this grant atomically to the child execution context.
                </span>
              </div>

              <div className="flex justify-end space-x-2 pt-2 border-t border-slate-800">
                <button
                  type="button"
                  onClick={closeModal}
                  className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={actionLoading || !modalInput.child_transaction_id?.trim()}
                  className="px-3 py-1.5 bg-sky-600 hover:bg-sky-500 text-white font-medium rounded transition disabled:opacity-50"
                >
                  {actionLoading ? "Activating..." : "Bind & Activate"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 5. Revoke Delegation Modal */}
      {modalType === "REVOKE_DELEGATION" && targetItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-5 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-sm font-semibold text-white">Revoke Delegation Grant: {targetItem.id}</h3>
              <button onClick={closeModal} className="text-slate-400 hover:text-white">
                <X className="w-4 h-4" />
              </button>
            </div>
            <form onSubmit={handleRevokeDelegationSubmit} className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-300 mb-1 font-medium">Revocation Reason *</label>
                <textarea
                  required
                  rows={3}
                  placeholder="Explicit security or operational reason..."
                  value={modalReason}
                  onChange={(e) => setModalReason(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 text-slate-200 px-3 py-2 rounded focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div className="flex justify-end space-x-2 pt-2 border-t border-slate-800">
                <button
                  type="button"
                  onClick={closeModal}
                  className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={actionLoading || !modalReason.trim()}
                  className="px-3 py-1.5 bg-rose-600 hover:bg-rose-500 text-white font-medium rounded transition disabled:opacity-50"
                >
                  {actionLoading ? "Revoking..." : "Revoke Grant"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 6. Initiate Handoff Modal */}
      {modalType === "CREATE_HANDOFF" && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-5 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-sm font-semibold text-white">Initiate Governed Agent Handoff</h3>
              <button onClick={closeModal} className="text-slate-400 hover:text-white">
                <X className="w-4 h-4" />
              </button>
            </div>
            <form onSubmit={handleCreateHandoffSubmit} className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-300 mb-1 font-medium">Originating Parent Transaction ID *</label>
                <input
                  type="text"
                  required
                  placeholder="txn_parent_01"
                  value={modalInput.parent_transaction_id || ""}
                  onChange={(e) => setModalInput({ ...modalInput, parent_transaction_id: e.target.value })}
                  className="w-full bg-slate-950 border border-slate-800 text-slate-200 px-3 py-2 rounded focus:outline-none focus:border-indigo-500 font-mono"
                />
              </div>

              <div>
                <label className="block text-slate-300 mb-1 font-medium">Target Delegatee Agent ID *</label>
                <input
                  type="text"
                  required
                  placeholder="agt_child_01"
                  value={modalInput.child_agent_id || ""}
                  onChange={(e) => setModalInput({ ...modalInput, child_agent_id: e.target.value })}
                  className="w-full bg-slate-950 border border-slate-800 text-slate-200 px-3 py-2 rounded focus:outline-none focus:border-indigo-500 font-mono"
                />
              </div>

              <div>
                <label className="block text-slate-300 mb-1 font-medium">Bound Delegation Grant ID *</label>
                <input
                  type="text"
                  required
                  placeholder="del_grant_01"
                  value={modalInput.delegation_id || ""}
                  onChange={(e) => setModalInput({ ...modalInput, delegation_id: e.target.value })}
                  className="w-full bg-slate-950 border border-slate-800 text-slate-200 px-3 py-2 rounded focus:outline-none focus:border-indigo-500 font-mono"
                />
              </div>

              <div>
                <label className="block text-slate-300 mb-1 font-medium">Operational Purpose *</label>
                <textarea
                  required
                  rows={2}
                  placeholder="Handoff objective..."
                  value={modalInput.purpose || ""}
                  onChange={(e) => setModalInput({ ...modalInput, purpose: e.target.value })}
                  className="w-full bg-slate-950 border border-slate-800 text-slate-200 px-3 py-2 rounded focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div className="flex justify-end space-x-2 pt-2 border-t border-slate-800">
                <button
                  type="button"
                  onClick={closeModal}
                  className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={actionLoading}
                  className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white font-medium rounded transition disabled:opacity-50"
                >
                  {actionLoading ? "Submitting..." : "Initiate Handoff"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 7. Accept Handoff Modal */}
      {modalType === "ACCEPT_HANDOFF" && targetItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-5 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-sm font-semibold text-white">Accept Handoff: {targetItem.id}</h3>
              <button onClick={closeModal} className="text-slate-400 hover:text-white">
                <X className="w-4 h-4" />
              </button>
            </div>
            <form onSubmit={handleAcceptHandoffSubmit} className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-300 mb-1 font-medium">Input Context (JSON)</label>
                <textarea
                  rows={3}
                  placeholder="{}"
                  value={modalInput.input_context || "{}"}
                  onChange={(e) => setModalInput({ ...modalInput, input_context: e.target.value })}
                  className="w-full bg-slate-950 border border-slate-800 text-slate-200 px-3 py-2 rounded focus:outline-none focus:border-indigo-500 font-mono"
                />
                <span className="text-[10px] text-slate-500 mt-1 block">
                  Acceptance spawns a new child transaction and inherits parent taints.
                </span>
              </div>

              <div className="flex justify-end space-x-2 pt-2 border-t border-slate-800">
                <button
                  type="button"
                  onClick={closeModal}
                  className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={actionLoading}
                  className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white font-medium rounded transition disabled:opacity-50"
                >
                  {actionLoading ? "Accepting..." : "Accept Handoff"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 8. Cancel Handoff Modal */}
      {modalType === "CANCEL_HANDOFF" && targetItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-5 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-sm font-semibold text-white">Cancel Handoff: {targetItem.id}</h3>
              <button onClick={closeModal} className="text-slate-400 hover:text-white">
                <X className="w-4 h-4" />
              </button>
            </div>
            <form onSubmit={handleCancelHandoffSubmit} className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-300 mb-1 font-medium">Cancellation Reason *</label>
                <textarea
                  required
                  rows={3}
                  placeholder="Reason for cancelling handoff..."
                  value={modalReason}
                  onChange={(e) => setModalReason(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 text-slate-200 px-3 py-2 rounded focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div className="flex justify-end space-x-2 pt-2 border-t border-slate-800">
                <button
                  type="button"
                  onClick={closeModal}
                  className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={actionLoading || !modalReason.trim()}
                  className="px-3 py-1.5 bg-rose-600 hover:bg-rose-500 text-white font-medium rounded transition disabled:opacity-50"
                >
                  {actionLoading ? "Processing..." : "Confirm Cancellation"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 9. Acquire Concurrency Lease Modal */}
      {modalType === "ACQUIRE_LEASE" && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-5 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-sm font-semibold text-white">Acquire Resource Concurrency Lease</h3>
              <button onClick={closeModal} className="text-slate-400 hover:text-white">
                <X className="w-4 h-4" />
              </button>
            </div>
            <form onSubmit={handleAcquireLeaseSubmit} className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-300 mb-1 font-medium">Resource URI *</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. db://records/user_42"
                  value={modalInput.resource_uri || ""}
                  onChange={(e) => setModalInput({ ...modalInput, resource_uri: e.target.value })}
                  className="w-full bg-slate-950 border border-slate-800 text-slate-200 px-3 py-2 rounded focus:outline-none focus:border-indigo-500 font-mono"
                />
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-slate-300 mb-1 font-medium">Transaction ID *</label>
                  <input
                    type="text"
                    required
                    placeholder="txn_holder_01"
                    value={modalInput.transaction_id || ""}
                    onChange={(e) => setModalInput({ ...modalInput, transaction_id: e.target.value })}
                    className="w-full bg-slate-950 border border-slate-800 text-slate-200 px-3 py-2 rounded focus:outline-none focus:border-indigo-500 font-mono"
                  />
                </div>
                <div>
                  <label className="block text-slate-300 mb-1 font-medium">Agent ID *</label>
                  <input
                    type="text"
                    required
                    placeholder="agt_holder_01"
                    value={modalInput.agent_id || ""}
                    onChange={(e) => setModalInput({ ...modalInput, agent_id: e.target.value })}
                    className="w-full bg-slate-950 border border-slate-800 text-slate-200 px-3 py-2 rounded focus:outline-none focus:border-indigo-500 font-mono"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-slate-300 mb-1 font-medium">Mode</label>
                  <select
                    value={modalInput.concurrency_mode || "EXCLUSIVE"}
                    onChange={(e) => setModalInput({ ...modalInput, concurrency_mode: e.target.value })}
                    className="w-full bg-slate-950 border border-slate-800 text-slate-200 px-3 py-2 rounded focus:outline-none focus:border-indigo-500 font-mono"
                  >
                    <option value="EXCLUSIVE">EXCLUSIVE (Writes)</option>
                    <option value="SHARED">SHARED (Reads)</option>
                  </select>
                </div>
                <div>
                  <label className="block text-slate-300 mb-1 font-medium">Duration (5-300s)</label>
                  <input
                    type="number"
                    min="5"
                    max="300"
                    value={modalInput.duration_seconds || 60}
                    onChange={(e) => setModalInput({ ...modalInput, duration_seconds: e.target.value })}
                    className="w-full bg-slate-950 border border-slate-800 text-slate-200 px-3 py-2 rounded focus:outline-none focus:border-indigo-500 font-mono"
                  />
                </div>
              </div>

              <div className="flex justify-end space-x-2 pt-2 border-t border-slate-800">
                <button
                  type="button"
                  onClick={closeModal}
                  className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={actionLoading}
                  className="px-3 py-1.5 bg-purple-600 hover:bg-purple-500 text-white font-medium rounded transition disabled:opacity-50"
                >
                  {actionLoading ? "Acquiring..." : "Acquire Lease"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 10. Release Lease Confirmation Modal */}
      {modalType === "RELEASE_LEASE" && targetItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-5 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-sm font-semibold text-white">Release Concurrency Lease</h3>
              <button onClick={closeModal} className="text-slate-400 hover:text-white">
                <X className="w-4 h-4" />
              </button>
            </div>
            <form onSubmit={handleReleaseLeaseSubmit} className="space-y-3 text-xs">
              <p className="text-slate-300">
                Are you sure you want to release the lease on{" "}
                <strong className="text-white font-mono">{targetItem.resource_uri}</strong>?
              </p>
              <div className="bg-slate-950 p-3 rounded border border-slate-800 space-y-1 font-mono text-[11px]">
                <div>Lease ID: {targetItem.id}</div>
                <div>Fencing Token: #{targetItem.fencing_token}</div>
                <div>Holding Txn: {targetItem.holder_transaction_id}</div>
              </div>

              <div className="flex justify-end space-x-2 pt-2 border-t border-slate-800">
                <button
                  type="button"
                  onClick={closeModal}
                  className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={actionLoading}
                  className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-white font-medium rounded transition disabled:opacity-50"
                >
                  {actionLoading ? "Releasing..." : "Confirm Release"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 11. Renew Lease Modal */}
      {modalType === "RENEW_LEASE" && targetItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-5 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-sm font-semibold text-white">Renew Lease: {targetItem.resource_uri}</h3>
              <button onClick={closeModal} className="text-slate-400 hover:text-white">
                <X className="w-4 h-4" />
              </button>
            </div>
            <form onSubmit={handleRenewLeaseSubmit} className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-300 mb-1 font-medium">Extend Duration (5-300s)</label>
                <input
                  type="number"
                  min="5"
                  max="300"
                  value={modalInput.duration_seconds || 60}
                  onChange={(e) => setModalInput({ ...modalInput, duration_seconds: e.target.value })}
                  className="w-full bg-slate-950 border border-slate-800 text-slate-200 px-3 py-2 rounded focus:outline-none focus:border-indigo-500 font-mono"
                />
              </div>

              <div className="flex justify-end space-x-2 pt-2 border-t border-slate-800">
                <button
                  type="button"
                  onClick={closeModal}
                  className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={actionLoading}
                  className="px-3 py-1.5 bg-purple-600 hover:bg-purple-500 text-white font-medium rounded transition disabled:opacity-50"
                >
                  {actionLoading ? "Renewing..." : "Extend Lease"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

export default MultiAgentGovernanceView;
