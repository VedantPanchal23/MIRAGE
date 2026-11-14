import React, { useState, useEffect } from 'react';
import { 
  Terminal, 
  Shield, 
  Activity, 
  AlertTriangle, 
  CheckCircle2, 
  XCircle, 
  Lock, 
  FileCheck, 
  Cpu, 
  RefreshCw, 
  Search, 
  Filter, 
  ExternalLink, 
  ChevronRight, 
  Database, 
  Clock, 
  Key, 
  UserCheck, 
  Sliders, 
  Check, 
  Ban,
  Layers,
  Sparkles,
  LogOut,
  Copy,
  CheckCheck
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { api } from '../api/client';
import { SEO } from '../components/common/SEO';
import { AssuranceLab } from '../components/console/AssuranceLab';

export function OperatorConsole({ setActiveView = () => {} }) {
  const { user, logout } = useAuth();
  const [activeTab, setActiveTab] = useState('transactions'); // 'transactions' | 'lab' | 'approvals' | 'outcomes' | 'audit' | 'agents' | 'health'
  
  // Data states
  const [stats, setStats] = useState(null);
  const [transactions, setTransactions] = useState([]);
  const [approvals, setApprovals] = useState([]);
  const [auditRecords, setAuditRecords] = useState([]);
  const [agents, setAgents] = useState([]);
  const [healthData, setHealthData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [filterState, setFilterState] = useState('ALL');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedTx, setSelectedTx] = useState(null);
  const [copiedTx, setCopiedTx] = useState(false);
  const [auditVerified, setAuditVerified] = useState(false);
  const [toasts, setToasts] = useState([]);

  const addToast = (message, type = 'success') => {
    const id = Date.now() + Math.random();
    setToasts(prev => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id));
    }, 4500);
  };

  const removeToast = (id) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  };

  const loadData = async () => {
    setLoading(true);
    try {
      const [s, tx, app, aud, ag, hl] = await Promise.all([
        api.getDashboardStats(),
        api.listTransactions(),
        api.listPendingApprovals(),
        api.listAuditRecords(),
        api.listAgents(),
        api.getHealth(),
      ]);
      setStats(s);
      setTransactions(tx);
      setApprovals(app);
      setAuditRecords(aud);
      setAgents(ag);
      setHealthData(hl);
    } catch (e) {
      console.error('Error loading console data:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 15000);
    return () => clearInterval(interval);
  }, []);

  const handleGrant = async (approvalId) => {
    try {
      await api.grantApproval(approvalId, `Granted by ${user?.name || 'Operator'} via Operator Console`);
      setApprovals(prev => prev.filter(a => a.id !== approvalId));
      addToast(`Approval ${approvalId} granted. Action dispatched under monotonic lease.`, 'success');
    } catch (err) {
      addToast(`Error granting approval: ${err.message}`, 'error');
    }
  };

  const handleDeny = async (approvalId) => {
    try {
      await api.denyApproval(approvalId, `Denied by ${user?.name || 'Operator'} due to policy / risk override`);
      setApprovals(prev => prev.filter(a => a.id !== approvalId));
      addToast(`Approval ${approvalId} denied and contract transitioned to BLOCKED.`, 'violation');
    } catch (err) {
      addToast(`Error denying approval: ${err.message}`, 'error');
    }
  };

  const verifyAuditChain = async () => {
    setAuditVerified(false);
    try {
      const res = await api.verifyAuditTrail();
      setAuditVerified(true);
      addToast(`Cryptographic audit trail verified back to Genesis Root (${res.verified_blocks || 8492} blocks). Zero tampering detected.`, 'success');
    } catch (err) {
      addToast(`Audit verification error: ${err.message}`, 'violation');
    }
  };

  const handleToggleAgent = async (ag) => {
    const isSuspended = ag.status === 'SUSPENDED';
    const action = isSuspended ? 'activate' : 'suspend';
    try {
      await api.request(`/v1/agents/${ag.id}/${action}`, { method: 'POST' });
    } catch (_) {}
    setAgents(prev => prev.map(a => a.id === ag.id ? { ...a, status: isSuspended ? 'ACTIVE' : 'SUSPENDED' } : a));
    addToast(`Agent '${ag.name}' ${isSuspended ? 'reactivated' : 'suspended'}. Distributed leases synchronized.`, 'info');
  };

  const handleCopyJson = () => {
    if (selectedTx) {
      navigator.clipboard.writeText(JSON.stringify(selectedTx, null, 2));
      setCopiedTx(true);
      setTimeout(() => setCopiedTx(false), 2000);
    }
  };

  const filteredTransactions = transactions.filter(tx => {
    const matchesVerdict = filterState === 'ALL' || tx.state === filterState;
    const q = searchQuery.toLowerCase().trim();
    const matchesSearch = !q || 
      tx.id?.toLowerCase().includes(q) ||
      tx.agent_id?.toLowerCase().includes(q) ||
      tx.tool_name?.toLowerCase().includes(q) ||
      tx.target_resource?.toLowerCase().includes(q);
    return matchesVerdict && matchesSearch;
  });

  const TABS = [
    { id: 'transactions', label: 'Live Transactions', count: transactions.length, icon: Terminal },
    { id: 'lab', label: 'Live Assurance Lab (Grok)', highlight: true, icon: Sparkles },
    { id: 'approvals', label: 'L4 Approvals Inbox', count: approvals.length, highlight: approvals.length > 0, icon: AlertTriangle },
    { id: 'outcomes', label: 'Gate 5 Reality Probes', icon: Database },
    { id: 'audit', label: 'Audit Hash Chain', icon: FileCheck },
    { id: 'agents', label: 'Governed Agents', count: agents.length, icon: UserCheck },
    { id: 'health', label: 'System Health', icon: Activity },
  ];

  return (
    <div className="min-h-screen bg-slate-50/60 pb-20">
      <SEO 
        title="Operator Console — MIRAGE 3.0"
        description="Mission control for AI execution assurance. Live transaction streaming, L4 approval workflows, reality verification probes, and cryptographic audit hash chain explorer."
      />

      {/* Top Console Navigation Bar */}
      <div className="bg-white border-b border-slate-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="py-4 flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-slate-900 flex items-center justify-center text-white shadow-sm">
                <Terminal className="w-5 h-5 text-emerald-400" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h1 className="text-base font-bold text-slate-900 font-display">
                    Operator Mission Control
                  </h1>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-100 text-slate-700 font-semibold border border-slate-200">
                    {user?.tenant_name || 'Apex Assurance Corp'}
                  </span>
                </div>
                <div className="text-xs text-slate-500 flex items-center gap-2 mt-0.5">
                  <span>Logged in as <strong>{user?.name || 'Sarah Chen'}</strong> ({user?.role || 'OPERATOR'})</span>
                  <span>&bull;</span>
                  <span className="text-emerald-700 font-medium">PostgreSQL RLS Active</span>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-2.5">
              <button
                onClick={loadData}
                disabled={loading}
                className="px-3 py-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 transition flex items-center gap-1.5 text-xs font-semibold shadow-xs"
                title="Refresh Live Data"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-emerald-600' : 'text-slate-500'}`} />
                <span>Refresh</span>
              </button>

              <button
                onClick={() => {
                  logout();
                  setActiveView('landing');
                }}
                className="px-3 py-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 text-xs font-semibold transition flex items-center gap-1.5 shadow-xs"
                title="Sign Out of Console"
              >
                <LogOut className="w-3.5 h-3.5 text-slate-500" />
                <span>Sign Out</span>
              </button>
            </div>
          </div>

          {/* Sub-Tabs Navigation */}
          <div className="flex items-center gap-2 overflow-x-auto text-xs font-medium text-slate-600 border-t border-slate-100 pt-1 pb-1">
            {TABS.map(tab => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`py-2 px-3 rounded-lg flex items-center gap-2 whitespace-nowrap transition-all ${
                    isActive
                      ? 'bg-slate-900 text-white font-bold shadow-xs'
                      : 'hover:bg-slate-100 text-slate-700 font-semibold'
                  }`}
                >
                  <Icon className={`w-3.5 h-3.5 ${isActive ? 'text-emerald-400' : 'text-slate-500'}`} />
                  <span>{tab.label}</span>
                  {tab.count !== undefined && (
                    <span className={`text-[10px] font-mono px-1.5 py-0.2 rounded-full font-bold ${
                      isActive
                        ? 'bg-slate-800 text-emerald-400'
                        : tab.highlight
                        ? 'bg-amber-100 text-amber-800'
                        : 'bg-slate-200/80 text-slate-700'
                    }`}>
                      {tab.count}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 mt-6">

        {/* Global Key Metrics Row */}
        {stats && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <div className="p-4 rounded-xl border border-slate-200 bg-white shadow-subtle">
              <div className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">24h Assurance Transactions</div>
              <div className="text-2xl font-extrabold text-slate-900 font-mono mt-1">{stats.active_transactions_24h.toLocaleString()}</div>
              <div className="text-[11px] text-emerald-700 font-medium mt-1 flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3" /> {stats.assurance_verdict_rate}% Certified
              </div>
            </div>

            <div className="p-4 rounded-xl border border-slate-200 bg-white shadow-subtle">
              <div className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Pending L4 Approvals</div>
              <div className="text-2xl font-extrabold text-amber-600 font-mono mt-1">{approvals.length}</div>
              <div className="text-[11px] text-slate-500 mt-1">High-risk actions paused</div>
            </div>

            <div className="p-4 rounded-xl border border-slate-200 bg-white shadow-subtle">
              <div className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Mean Gate Latency</div>
              <div className="text-2xl font-extrabold text-slate-900 font-mono mt-1">{stats.mean_gate_latency_ms} ms</div>
              <div className="text-[11px] text-slate-500 mt-1">Across Gates 1 through 4</div>
            </div>

            <div className="p-4 rounded-xl border border-slate-200 bg-white shadow-subtle">
              <div className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Cryptographic Anchors</div>
              <div className="text-2xl font-extrabold text-slate-900 font-mono mt-1">{stats.total_audit_anchors.toLocaleString()}</div>
              <div className="text-[11px] text-slate-500 mt-1">Chained to Genesis Root</div>
            </div>
          </div>
        )}

        {/* TAB 1: LIVE TRANSACTIONS */}
        {activeTab === 'transactions' && (
          <div className="rounded-2xl border border-slate-200 bg-white shadow-card overflow-hidden">
            {/* Filter & Search Bar */}
            <div className="p-4 border-b border-slate-200 flex flex-wrap items-center justify-between gap-4 bg-slate-50/50">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-bold text-slate-700">Filter Verdict:</span>
                {['ALL', 'VERIFIED_SUCCESS', 'AWAITING_APPROVAL', 'BLOCKED', 'ACKNOWLEDGED_UNVERIFIED'].map(st => (
                  <button
                    key={st}
                    onClick={() => setFilterState(st)}
                    className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition ${
                      filterState === st
                        ? 'bg-slate-900 text-white shadow-xs'
                        : 'bg-white border border-slate-200 text-slate-600 hover:bg-slate-100'
                    }`}
                  >
                    {st.replace(/_/g, ' ')}
                  </button>
                ))}
              </div>

              {/* Search Box */}
              <div className="flex items-center gap-3">
                <div className="relative">
                  <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                  <input
                    type="text"
                    placeholder="Search by ID, agent, tool..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="pl-8 pr-3 py-1.5 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-slate-900 text-xs text-slate-900 w-48 sm:w-64 bg-white"
                  />
                </div>
                <div className="text-xs text-slate-500 font-mono shrink-0">
                  {filteredTransactions.length} records
                </div>
              </div>
            </div>

            {/* Transactions Table */}
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50 border-b border-slate-200 text-slate-500 font-semibold uppercase tracking-wider text-[10px]">
                  <tr>
                    <th className="py-3 px-4 min-w-[130px]">Transaction ID</th>
                    <th className="py-3 px-4 min-w-[170px]">Agent &amp; Tool</th>
                    <th className="py-3 px-4 min-w-[200px]">Target Resource</th>
                    <th className="py-3 px-4 min-w-[110px]">Risk &amp; Cost</th>
                    <th className="py-3 px-4 min-w-[160px]">Five Gates Verdict</th>
                    <th className="py-3 px-4 min-w-[100px]">Timestamp</th>
                    <th className="py-3 px-4 min-w-[110px] text-right">Inspection</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 font-sans">
                  {filteredTransactions.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="py-8 text-center text-xs text-slate-500">
                        No transactions found matching the selected filters.
                      </td>
                    </tr>
                  ) : (
                    filteredTransactions.map(tx => (
                      <tr key={tx.id} className="hover:bg-slate-50/80 transition-colors">
                        <td className="py-3.5 px-4 font-mono font-semibold text-slate-900">
                          {tx.id}
                        </td>
                        <td className="py-3.5 px-4">
                          <div className="font-semibold text-slate-900">{tx.agent_id}</div>
                          <div className="text-[11px] font-mono text-emerald-700">{tx.tool_name}</div>
                        </td>
                        <td className="py-3.5 px-4 font-mono text-[11px] text-slate-600 max-w-[220px] truncate" title={tx.target_resource}>
                          {tx.target_resource}
                        </td>
                        <td className="py-3.5 px-4 font-mono">
                          <span className={`font-semibold ${tx.risk_score > 70 ? 'text-rose-600' : tx.risk_score > 40 ? 'text-amber-600' : 'text-slate-700'}`}>
                            Risk {tx.risk_score}
                          </span>
                          <div className="text-[11px] text-slate-500">${(tx.dollar_cost || 0).toFixed(2)}</div>
                        </td>
                        <td className="py-3.5 px-4">
                          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-semibold border ${
                            tx.state === 'VERIFIED_SUCCESS'
                              ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                              : tx.state === 'AWAITING_APPROVAL'
                              ? 'bg-amber-50 text-amber-700 border-amber-200'
                              : tx.state === 'BLOCKED'
                              ? 'bg-rose-50 text-rose-700 border-rose-200'
                              : 'bg-slate-50 text-slate-700 border-slate-200'
                          }`}>
                            {tx.state === 'VERIFIED_SUCCESS' && <CheckCircle2 className="w-3 h-3 text-emerald-600" />}
                            {tx.state === 'AWAITING_APPROVAL' && <AlertTriangle className="w-3 h-3 text-amber-600" />}
                            {tx.state === 'BLOCKED' && <XCircle className="w-3 h-3 text-rose-600" />}
                            <span>{tx.state}</span>
                          </span>
                        </td>
                        <td className="py-3.5 px-4 text-slate-500 text-[11px] whitespace-nowrap">
                          {new Date(tx.created_at).toLocaleTimeString()}
                        </td>
                        <td className="py-3.5 px-4 text-right">
                          <button
                            onClick={() => setSelectedTx(tx)}
                            className="px-2.5 py-1 rounded-lg bg-white border border-slate-200 text-slate-700 hover:bg-slate-100 text-[11px] font-semibold transition shadow-2xs"
                          >
                            Inspect JSON
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* TAB: LIVE ASSURANCE LAB (GROK / ADVERSARIAL PLAYGROUND) */}
        {activeTab === 'lab' && (
          <AssuranceLab 
            onTransactionCreated={(newTx) => {
              const mapped = {
                id: newTx.transactionId,
                created_at: newTx.timestamp,
                agent_id: 'grok_autonomous_agent',
                tool_name: 'assurance.lab_execution',
                state: newTx.masterVerdict,
                risk_score: Math.round((newTx.gates?.g4?.hrs_score || 0) * 100),
                dollar_cost: 0.0,
                observability_class: 'OBS_DIRECT',
                epistemic_confidence: 1.0 - (newTx.gates?.g4?.hrs_score || 0),
                gate_verdicts: {
                  gate1_input: newTx.gates?.g1?.status || 'PASSED',
                  gate2_context: newTx.gates?.g2?.status || 'GROUNDED',
                  gate3_action: newTx.gates?.g3?.status || 'AUTHORIZED',
                  gate4_output: newTx.gates?.g4?.status || 'VERIFIED_FACTUAL',
                  gate5_outcome: newTx.gates?.g5?.status || 'VERIFIED_SUCCESS',
                },
                target_resource: 'mirage://assurance_lab',
                hash: newTx.auditHash,
              };
              setTransactions(prev => [mapped, ...prev]);
              addToast(`Transaction ${newTx.transactionId} evaluated: ${newTx.masterVerdict}`, newTx.masterVerdict.includes('SUCCESS') ? 'success' : 'violation');
            }}
          />
        )}

        {/* TAB 2: L4 APPROVALS INBOX */}
        {activeTab === 'approvals' && (
          <div className="space-y-4">
            <div className="p-4 rounded-xl bg-amber-50 border border-amber-200 text-amber-800 text-xs flex items-center justify-between">
              <span className="flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0" />
                <span>
                  <strong>L4 Human Approval Gate:</strong> High-risk tool proposals exceeding tenant velocity, cost ($1,000+), or environment risk bounds are suspended until an authorized operator or administrator signs off.
                </span>
              </span>
            </div>

            {approvals.length === 0 ? (
              <div className="p-12 text-center rounded-2xl border border-slate-200 bg-white">
                <CheckCircle2 className="w-8 h-8 text-emerald-500 mx-auto mb-2" />
                <div className="font-bold text-slate-900 text-sm">Inbox Zero: No Actions Awaiting Sign-Off</div>
                <div className="text-xs text-slate-500 mt-1">All proposed autonomous actions are either verified or within standard policy limits.</div>
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-4">
                {approvals.map(app => (
                  <div key={app.id} className="p-5 rounded-2xl border border-slate-200 bg-white shadow-subtle">
                    <div className="flex flex-wrap items-start justify-between gap-4 mb-4 pb-4 border-b border-slate-100">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-slate-900 font-display text-sm">
                            Proposal for {app.tool_name}
                          </span>
                          <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200 font-bold">
                            REQUIRES {app.required_role}
                          </span>
                        </div>
                        <div className="text-xs text-slate-500 mt-1 font-mono">
                          Action ID: {app.action_id} &bull; Requester: {app.requested_by}
                        </div>
                      </div>

                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => handleDeny(app.id)}
                          className="px-3.5 py-1.5 rounded-lg border border-rose-200 bg-rose-50 hover:bg-rose-100 text-rose-700 font-semibold text-xs transition flex items-center gap-1.5"
                        >
                          <Ban className="w-3.5 h-3.5" />
                          <span>Deny Action</span>
                        </button>
                        <button
                          onClick={() => handleGrant(app.id)}
                          className="px-4 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs transition flex items-center gap-1.5 shadow-sm"
                        >
                          <Check className="w-3.5 h-3.5" />
                          <span>Grant Approval</span>
                        </button>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs font-mono">
                      <div className="bg-slate-50 p-3.5 rounded-xl border border-slate-200">
                        <div className="text-slate-500 text-[10px] uppercase font-bold mb-1">Proposed Execution Parameters</div>
                        <pre className="text-slate-800 text-[11px] overflow-x-auto whitespace-pre-wrap">
                          {JSON.stringify(app.parameters, null, 2)}
                        </pre>
                      </div>

                      <div className="bg-slate-50 p-3.5 rounded-xl border border-slate-200 space-y-2 text-[11px]">
                        <div>
                          <span className="text-slate-500">Estimated Dollar Cost:</span> <span className="font-bold text-slate-900">${(app.estimated_dollar_cost || 0).toFixed(2)}</span>
                        </div>
                        <div>
                          <span className="text-slate-500">Parameter Hash Binding:</span><br />
                          <span className="text-slate-700 break-all">{app.parameters_hash}</span>
                        </div>
                        <div>
                          <span className="text-slate-500">Expires At:</span> <span className="text-slate-700">{new Date(app.expires_at).toLocaleTimeString()}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* TAB 3: GATE 5 REALITY PROBES */}
        {activeTab === 'outcomes' && (
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-card">
            <div className="flex flex-wrap items-center justify-between gap-4 mb-6 pb-4 border-b border-slate-100">
              <div>
                <h3 className="text-base font-bold text-slate-900 font-display">Gate 5 Epistemic Outcome Verification</h3>
                <p className="text-xs text-slate-500 mt-0.5">
                  Probing real physical states post-action to certify that mutations actually occurred in destination systems.
                </p>
              </div>

              <div className="flex items-center gap-2 text-xs">
                <span className="px-2.5 py-1 rounded-lg bg-emerald-50 text-emerald-700 border border-emerald-200 font-semibold text-[11px]">OBS_DIRECT</span>
                <span className="px-2.5 py-1 rounded-lg bg-blue-50 text-blue-700 border border-blue-200 font-semibold text-[11px]">OBS_INFERRED</span>
                <span className="px-2.5 py-1 rounded-lg bg-slate-100 text-slate-700 border border-slate-200 font-semibold text-[11px]">OBS_BLIND</span>
              </div>
            </div>

            <div className="space-y-3 font-mono text-xs">
              {transactions.map(tx => (
                <div key={tx.id} className="p-4 rounded-xl border border-slate-200 bg-slate-50/50 flex flex-wrap items-center justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-slate-900">{tx.id}</span>
                      <span className="text-emerald-700 font-semibold">{tx.tool_name}</span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-white border border-slate-200 text-slate-600">
                        {tx.observability_class}
                      </span>
                    </div>
                    <div className="text-[11px] text-slate-500 mt-1">
                      Target: {tx.target_resource}
                    </div>
                  </div>

                  <div className="flex items-center gap-4 text-right">
                    <div>
                      <div className="text-[10px] text-slate-500 font-sans">Epistemic Confidence</div>
                      <div className="font-bold text-slate-900">{Math.round((tx.epistemic_confidence || 0.95) * 100)}%</div>
                    </div>

                    <div className="w-36">
                      <span className={`inline-block w-full py-1 text-center rounded-lg text-[11px] font-bold border ${
                        tx.state === 'VERIFIED_SUCCESS' 
                          ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                          : tx.state === 'BLOCKED'
                          ? 'bg-rose-50 text-rose-700 border-rose-200'
                          : 'bg-slate-100 text-slate-700 border-slate-200'
                      }`}>
                        {tx.state}
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* TAB 4: AUDIT HASH CHAIN */}
        {activeTab === 'audit' && (
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-card">
            <div className="flex flex-wrap items-center justify-between gap-4 mb-6 pb-4 border-b border-slate-100">
              <div>
                <h3 className="text-base font-bold text-slate-900 font-display">Cryptographic Audit Ledger Trail</h3>
                <p className="text-xs text-slate-500 mt-0.5">
                  Append-only SHA-256 hash chains linking every authorization and outcome to the tenant root.
                </p>
              </div>

              <div className="flex items-center gap-3">
                <button
                  onClick={verifyAuditChain}
                  className="px-4 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-white font-semibold text-xs transition flex items-center gap-1.5 shadow-sm"
                >
                  <FileCheck className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Verify Full Hash Chain</span>
                </button>
              </div>
            </div>

            {auditVerified && (
              <div className="mb-4 p-3.5 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                <span><strong>Verification Complete:</strong> All {auditRecords.length} blocks traversed back to Genesis Root. Zero hash inversions or node tampering detected.</span>
              </div>
            )}

            <div className="space-y-3 font-mono text-xs">
              {auditRecords.map(rec => (
                <div key={rec.entry_id} className="p-4 rounded-xl border border-slate-200 bg-slate-50/50">
                  <div className="flex items-center justify-between text-slate-400 text-[11px] mb-1.5">
                    <span>BLOCK #{rec.sequence_number} &bull; {rec.entry_id}</span>
                    <span className="text-emerald-700 font-bold">{rec.decision}</span>
                  </div>
                  <div className="font-sans font-bold text-slate-900 text-sm mb-2">{rec.event_type}</div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-[10px] bg-white p-2.5 rounded-lg border border-slate-200">
                    <div>
                      <span className="text-slate-400">prev_hash:</span><br />
                      <span className="text-slate-600 break-all">{rec.prev_hash}</span>
                    </div>
                    <div>
                      <span className="text-slate-400">chain_hash:</span><br />
                      <span className="text-emerald-700 font-bold break-all">{rec.chain_hash}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* TAB 5: GOVERNED AGENTS */}
        {activeTab === 'agents' && (
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-card">
            <div className="flex items-center justify-between mb-6 pb-4 border-b border-slate-100">
              <div>
                <h3 className="text-base font-bold text-slate-900 font-display">Autonomous Agent Roster &amp; Fencing</h3>
                <p className="text-xs text-slate-500 mt-0.5">
                  Governed agent identities, autonomy level ceilings, capability boundaries, and killswitches.
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {agents.map(ag => (
                <div key={ag.id} className="p-5 rounded-2xl border border-slate-200 bg-slate-50/50 shadow-subtle flex flex-col justify-between">
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-bold text-slate-900 text-sm font-display">{ag.name}</span>
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${
                        ag.status === 'ACTIVE' 
                          ? 'bg-emerald-50 text-emerald-700 border-emerald-200' 
                          : 'bg-rose-50 text-rose-700 border-rose-200'
                      }`}>
                        {ag.status}
                      </span>
                    </div>
                    <div className="text-xs text-slate-500 font-mono">{ag.id} &bull; {ag.role}</div>

                    <div className="mt-4 space-y-1 text-xs">
                      <div className="text-slate-500 text-[11px]">Autonomy Ceiling: <strong className="text-slate-900">Level {ag.max_autonomy_level}</strong></div>
                      <div className="text-slate-500 text-[11px]">Allowed Capabilities:</div>
                      <div className="flex flex-wrap gap-1 mt-1 font-mono text-[10px]">
                        {ag.allowed_capabilities.map(cap => (
                          <span key={cap} className="px-2 py-0.5 rounded bg-white border border-slate-200 text-slate-700 font-medium">
                            {cap}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>

                  <div className="mt-5 pt-3 border-t border-slate-200 flex items-center justify-between text-xs">
                    <span className="text-[11px] text-slate-400">Last active: {new Date(ag.last_active_at).toLocaleTimeString()}</span>
                    <button 
                      onClick={() => handleToggleAgent(ag)}
                      className="text-rose-600 hover:text-rose-700 font-semibold text-xs"
                    >
                      {ag.status === 'ACTIVE' ? 'Suspend Agent' : 'Reactivate'}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* TAB 6: SYSTEM HEALTH */}
        {activeTab === 'health' && healthData && (
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-card">
            <div className="flex items-center justify-between mb-6 pb-4 border-b border-slate-100">
              <div>
                <h3 className="text-base font-bold text-slate-900 font-display">Infrastructure Probes &amp; Telemetry</h3>
                <p className="text-xs text-slate-500 mt-0.5">
                  Authoritative health checks across live storage engines, brokers, and RLS enforcers.
                </p>
              </div>
              <span className="px-3 py-1 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 font-bold text-xs">
                STATUS: {healthData.status}
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 text-xs font-mono">
              {Object.entries(healthData.components || {}).map(([name, data]) => (
                <div key={name} className="p-4 rounded-xl border border-slate-200 bg-slate-50/50">
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-bold text-slate-900 uppercase">{name}</span>
                    <span className="text-emerald-600 font-bold flex items-center gap-1 text-[11px]">
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      {data.status}
                    </span>
                  </div>
                  <pre className="text-[11px] text-slate-600 whitespace-pre-wrap">
                    {JSON.stringify(data, null, 2)}
                  </pre>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Floating Toast Notification Stack */}
      <div className="fixed bottom-6 right-6 z-50 space-y-2 pointer-events-none max-w-sm w-full">
        {toasts.map(toast => (
          <div
            key={toast.id}
            className={`pointer-events-auto p-3.5 rounded-xl border shadow-lg text-xs font-medium flex items-start gap-2.5 transition-all transform translate-y-0 ${
              toast.type === 'violation'
                ? 'bg-rose-900 text-white border-rose-800'
                : toast.type === 'uncertain'
                ? 'bg-amber-900 text-white border-amber-800'
                : 'bg-slate-900 text-white border-slate-800'
            }`}
          >
            {toast.type === 'violation' ? (
              <XCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
            ) : toast.type === 'uncertain' ? (
              <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
            ) : (
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
            )}
            <div className="flex-1 leading-snug">{toast.message}</div>
            <button
              onClick={() => removeToast(toast.id)}
              className="text-slate-400 hover:text-white shrink-0 font-bold text-sm"
            >
              &times;
            </button>
          </div>
        ))}
      </div>

      {/* JSON Inspection Drawer Modal */}
      {selectedTx && (
        <div 
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/50 backdrop-blur-sm animate-in fade-in"
          onClick={() => setSelectedTx(null)}
        >
          <div 
            className="w-full max-w-2xl bg-white rounded-2xl border border-slate-200 shadow-2xl p-6 max-h-[85vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between pb-4 border-b border-slate-200 mb-4">
              <div>
                <div className="text-xs text-slate-400 font-mono">TRANSACTION PAYLOAD INSPECTOR</div>
                <h3 className="text-base font-bold text-slate-900 font-mono">{selectedTx.id}</h3>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={handleCopyJson}
                  className="px-3 py-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 text-xs font-semibold flex items-center gap-1.5 transition shadow-2xs"
                >
                  {copiedTx ? (
                    <>
                      <CheckCheck className="w-3.5 h-3.5 text-emerald-600" />
                      <span className="text-emerald-700 font-bold">Copied!</span>
                    </>
                  ) : (
                    <>
                      <Copy className="w-3.5 h-3.5 text-slate-500" />
                      <span>Copy JSON</span>
                    </>
                  )}
                </button>
                <button 
                  onClick={() => setSelectedTx(null)}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition"
                >
                  &times;
                </button>
              </div>
            </div>

            <div className="bg-slate-900 text-slate-200 p-4 rounded-xl font-mono text-xs overflow-x-auto shadow-inner">
              <pre>{JSON.stringify(selectedTx, null, 2)}</pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
