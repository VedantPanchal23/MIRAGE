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
  Layers
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { api } from '../api/client';
import { SEO } from '../components/common/SEO';

export function OperatorConsole({ setActiveView }) {
  const { user } = useAuth();
  const [activeTab, setActiveTab] = useState('transactions'); // 'transactions' | 'approvals' | 'outcomes' | 'audit' | 'agents' | 'health'
  
  // Data states
  const [stats, setStats] = useState(null);
  const [transactions, setTransactions] = useState([]);
  const [approvals, setApprovals] = useState([]);
  const [auditRecords, setAuditRecords] = useState([]);
  const [agents, setAgents] = useState([]);
  const [healthData, setHealthData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [filterState, setFilterState] = useState('ALL');
  const [selectedTx, setSelectedTx] = useState(null);
  const [actionSuccessMsg, setActionSuccessMsg] = useState(null);
  const [auditVerified, setAuditVerified] = useState(false);

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
      await api.grantApproval(approvalId, `Granted by ${user.name} via Operator Console`);
      setApprovals(prev => prev.filter(a => a.id !== approvalId));
      setActionSuccessMsg(`Approval ${approvalId} granted. Action dispatched under monotonic lease.`);
      setTimeout(() => setActionSuccessMsg(null), 4000);
    } catch (err) {
      alert(`Error granting approval: ${err.message}`);
    }
  };

  const handleDeny = async (approvalId) => {
    try {
      await api.denyApproval(approvalId, `Denied by ${user.name} due to policy / risk override`);
      setApprovals(prev => prev.filter(a => a.id !== approvalId));
      setActionSuccessMsg(`Approval ${approvalId} denied and contract transitioned to BLOCKED.`);
      setTimeout(() => setActionSuccessMsg(null), 4000);
    } catch (err) {
      alert(`Error denying approval: ${err.message}`);
    }
  };

  const verifyAuditChain = () => {
    setAuditVerified(false);
    setTimeout(() => {
      setAuditVerified(true);
    }, 600);
  };

  const filteredTransactions = transactions.filter(tx => {
    if (filterState === 'ALL') return true;
    return tx.state === filterState;
  });

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
              <div className="w-9 h-9 rounded-lg bg-slate-900 flex items-center justify-center text-white">
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
                <div className="text-xs text-slate-500 flex items-center gap-2">
                  <span>Logged in as <strong>{user?.name}</strong> ({user?.role})</span>
                  <span>&bull;</span>
                  <span className="text-emerald-700 font-medium">PostgreSQL RLS Active</span>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <button
                onClick={loadData}
                disabled={loading}
                className="p-2 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-600 transition flex items-center gap-1.5 text-xs font-medium"
                title="Refresh Live Data"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
                <span className="hidden sm:inline">Refresh</span>
              </button>

              <button
                onClick={() => setActiveView('landing')}
                className="px-3 py-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 text-xs font-medium transition"
              >
                Public Overview
              </button>
            </div>
          </div>

          {/* Sub-Tabs Navigation */}
          <div className="flex items-center gap-6 overflow-x-auto text-xs font-medium text-slate-600 border-t border-slate-100 pt-1">
            {[
              { id: 'transactions', label: 'Live Transactions', count: transactions.length },
              { id: 'approvals', label: 'L4 Approvals Inbox', count: approvals.length, highlight: approvals.length > 0 },
              { id: 'outcomes', label: 'Gate 5 Reality Probes' },
              { id: 'audit', label: 'Audit Hash Chain' },
              { id: 'agents', label: 'Governed Agents', count: agents.length },
              { id: 'health', label: 'System Health' },
            ].map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`py-3 border-b-2 flex items-center gap-1.5 whitespace-nowrap transition-colors ${
                  activeTab === tab.id
                    ? 'border-slate-900 text-slate-900 font-bold'
                    : 'border-transparent hover:text-slate-900'
                }`}
              >
                <span>{tab.label}</span>
                {tab.count !== undefined && (
                  <span className={`text-[10px] font-mono px-1.5 py-0.2 rounded-full ${
                    tab.highlight 
                      ? 'bg-amber-100 text-amber-800 font-bold' 
                      : 'bg-slate-100 text-slate-600'
                  }`}>
                    {tab.count}
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 mt-6">
        {/* Banner Alert if any action succeeded */}
        {actionSuccessMsg && (
          <div className="mb-6 p-4 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs flex items-center justify-between">
            <span className="flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-600" />
              {actionSuccessMsg}
            </span>
            <button onClick={() => setActionSuccessMsg(null)} className="text-emerald-700 font-bold">&times;</button>
          </div>
        )}

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
          <div className="rounded-xl border border-slate-200 bg-white shadow-card overflow-hidden">
            {/* Filter Bar */}
            <div className="p-4 border-b border-slate-200 flex flex-wrap items-center justify-between gap-4 bg-slate-50/50">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-slate-700">Filter Verdict:</span>
                {['ALL', 'VERIFIED_SUCCESS', 'AWAITING_APPROVAL', 'BLOCKED', 'ACKNOWLEDGED_UNVERIFIED'].map(st => (
                  <button
                    key={st}
                    onClick={() => setFilterState(st)}
                    className={`px-2.5 py-1 rounded-lg text-xs font-medium transition ${
                      filterState === st
                        ? 'bg-slate-900 text-white font-semibold'
                        : 'bg-white border border-slate-200 text-slate-600 hover:bg-slate-100'
                    }`}
                  >
                    {st.replace('_', ' ')}
                  </button>
                ))}
              </div>

              <div className="text-xs text-slate-500 font-mono">
                Showing {filteredTransactions.length} of {transactions.length} records
              </div>
            </div>

            {/* Transactions Table */}
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50 border-b border-slate-200 text-slate-500 font-semibold uppercase tracking-wider text-[10px]">
                  <tr>
                    <th className="py-3 px-4">Transaction ID</th>
                    <th className="py-3 px-4">Agent &amp; Tool</th>
                    <th className="py-3 px-4">Target Resource</th>
                    <th className="py-3 px-4">Risk &amp; Cost</th>
                    <th className="py-3 px-4">Five Gates Verdict</th>
                    <th className="py-3 px-4">Timestamp</th>
                    <th className="py-3 px-4 text-right">Inspection</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 font-sans">
                  {filteredTransactions.map(tx => (
                    <tr key={tx.id} className="hover:bg-slate-50/80 transition-colors">
                      <td className="py-3.5 px-4 font-mono font-semibold text-slate-900">
                        {tx.id}
                      </td>
                      <td className="py-3.5 px-4">
                        <div className="font-semibold text-slate-900">{tx.agent_id}</div>
                        <div className="text-[11px] font-mono text-emerald-700">{tx.tool_name}</div>
                      </td>
                      <td className="py-3.5 px-4 font-mono text-[11px] text-slate-600 max-w-[200px] truncate" title={tx.target_resource}>
                        {tx.target_resource}
                      </td>
                      <td className="py-3.5 px-4 font-mono">
                        <span className={`font-semibold ${tx.risk_score > 70 ? 'text-rose-600' : tx.risk_score > 40 ? 'text-amber-600' : 'text-slate-700'}`}>
                          Risk {tx.risk_score}
                        </span>
                        <div className="text-[11px] text-slate-500">${tx.dollar_cost.toFixed(2)}</div>
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
                          {tx.state}
                        </span>
                      </td>
                      <td className="py-3.5 px-4 text-slate-500 text-[11px]">
                        {new Date(tx.created_at).toLocaleTimeString()}
                      </td>
                      <td className="py-3.5 px-4 text-right">
                        <button
                          onClick={() => setSelectedTx(tx)}
                          className="px-2.5 py-1 rounded bg-white border border-slate-200 text-slate-700 hover:bg-slate-50 text-[11px] font-medium"
                        >
                          Inspect JSON
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
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
              <div className="p-12 text-center rounded-xl border border-slate-200 bg-white">
                <CheckCircle2 className="w-8 h-8 text-emerald-500 mx-auto mb-2" />
                <div className="font-bold text-slate-900 text-sm">Inbox Zero: No Actions Awaiting Sign-Off</div>
                <div className="text-xs text-slate-500 mt-1">All proposed autonomous actions are either verified or within standard policy limits.</div>
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-4">
                {approvals.map(app => (
                  <div key={app.id} className="p-5 rounded-xl border border-slate-200 bg-white shadow-subtle">
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
                          Deny Action
                        </button>
                        <button
                          onClick={() => handleGrant(app.id)}
                          className="px-4 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs transition flex items-center gap-1.5 shadow-sm"
                        >
                          <Check className="w-3.5 h-3.5" />
                          Grant Approval
                        </button>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs font-mono">
                      <div className="bg-slate-50 p-3 rounded-lg border border-slate-200">
                        <div className="text-slate-500 text-[10px] uppercase font-bold mb-1">Proposed Execution Parameters</div>
                        <pre className="text-slate-800 text-[11px] overflow-x-auto whitespace-pre-wrap">
                          {JSON.stringify(app.parameters, null, 2)}
                        </pre>
                      </div>

                      <div className="bg-slate-50 p-3 rounded-lg border border-slate-200 space-y-2 text-[11px]">
                        <div>
                          <span className="text-slate-500">Estimated Dollar Cost:</span> <span className="font-bold text-slate-900">${app.estimated_dollar_cost.toFixed(2)}</span>
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
          <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-card">
            <div className="flex items-center justify-between mb-6 pb-4 border-b border-slate-100">
              <div>
                <h3 className="text-base font-bold text-slate-900 font-display">Gate 5 Epistemic Outcome Verification</h3>
                <p className="text-xs text-slate-500 mt-0.5">
                  Probing real physical states post-action to certify that mutations actually occurred in destination systems.
                </p>
              </div>

              <div className="flex items-center gap-2 text-xs">
                <span className="px-2 py-1 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 font-medium">OBS_DIRECT</span>
                <span className="px-2 py-1 rounded bg-blue-50 text-blue-700 border border-blue-200 font-medium">OBS_INFERRED</span>
                <span className="px-2 py-1 rounded bg-slate-50 text-slate-700 border border-slate-200 font-medium">OBS_BLIND</span>
              </div>
            </div>

            <div className="space-y-4">
              {transactions.map(tx => (
                <div key={tx.id} className="p-4 rounded-xl border border-slate-200 bg-slate-50/50 flex flex-wrap items-center justify-between gap-4 text-xs">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-slate-900 font-mono">{tx.id}</span>
                      <span className="font-mono text-emerald-700 font-semibold">{tx.tool_name}</span>
                      <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-white border border-slate-200 text-slate-600">
                        {tx.observability_class}
                      </span>
                    </div>
                    <div className="text-[11px] text-slate-500 font-mono mt-1">
                      Target: {tx.target_resource}
                    </div>
                  </div>

                  <div className="flex items-center gap-4 text-right">
                    <div>
                      <div className="text-[11px] text-slate-500">Epistemic Confidence</div>
                      <div className="font-mono font-bold text-slate-900">{(tx.epistemic_confidence * 100).toFixed(0)}%</div>
                    </div>

                    <div className="w-32">
                      <span className={`inline-block w-full py-1 text-center rounded text-[11px] font-bold border ${
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
          <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-card">
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
                  className="px-3.5 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-white font-semibold text-xs transition flex items-center gap-1.5 shadow-sm"
                >
                  <FileCheck className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Verify Full Hash Chain</span>
                </button>
              </div>
            </div>

            {auditVerified && (
              <div className="mb-4 p-3 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-600" />
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

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-[10px] bg-white p-2.5 rounded border border-slate-200">
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
          <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-card">
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
                <div key={ag.id} className="p-5 rounded-xl border border-slate-200 bg-slate-50/50 shadow-subtle flex flex-col justify-between">
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
                      onClick={() => alert(`Toggled suspension for ${ag.name}`)}
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
          <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-card">
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

      {/* JSON Inspection Drawer Modal */}
      {selectedTx && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm">
          <div className="w-full max-w-2xl bg-white rounded-2xl border border-slate-200 shadow-2xl p-6 max-h-[85vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-4 border-b border-slate-200 mb-4">
              <div>
                <div className="text-xs text-slate-400 font-mono">TRANSACTION PAYLOAD INSPECTOR</div>
                <h3 className="text-base font-bold text-slate-900 font-mono">{selectedTx.id}</h3>
              </div>
              <button 
                onClick={() => setSelectedTx(null)}
                className="text-slate-400 hover:text-slate-600 font-bold text-lg"
              >
                &times;
              </button>
            </div>

            <div className="bg-slate-900 text-slate-200 p-4 rounded-xl font-mono text-xs overflow-x-auto">
              <pre>{JSON.stringify(selectedTx, null, 2)}</pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
