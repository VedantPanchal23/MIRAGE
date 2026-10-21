import React, { useState, useEffect, useCallback } from "react";
import {
  ShieldCheck,
  ShieldAlert,
  AlertTriangle,
  RefreshCw,
  Download,
  Anchor,
  Search,
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  Lock,
  FileText,
  Clock,
  X,
} from "lucide-react";
import {
  getAuditEvents,
  getAuditIntegrity,
  exportEvidenceBundle,
  commitAuditAnchor,
} from "../api/audit";

export function AuditIntegrityView({ isRefreshing, onDataLoaded }) {
  // Integrity state
  const [integrity, setIntegrity] = useState(null);
  const [loadingIntegrity, setLoadingIntegrity] = useState(true);
  const [integrityError, setIntegrityError] = useState(null);

  // Events query state
  const [events, setEvents] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loadingEvents, setLoadingEvents] = useState(true);
  const [offset, setOffset] = useState(0);
  const limit = 25;

  // Filters
  const [eventTypeFilter, setEventTypeFilter] = useState("");
  const [transactionFilter, setTransactionFilter] = useState("");

  // Actions state
  const [anchoring, setAnchoring] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [evidenceBundle, setEvidenceBundle] = useState(null);
  const [actionMessage, setActionMessage] = useState(null);
  const [actionError, setActionError] = useState(null);

  const fetchIntegrity = useCallback(async () => {
    setLoadingIntegrity(true);
    setIntegrityError(null);
    try {
      const data = await getAuditIntegrity();
      setIntegrity(data);
    } catch (err) {
      setIntegrityError(err.message || "Failed to verify audit integrity");
    } finally {
      setLoadingIntegrity(false);
    }
  }, []);

  const fetchEvents = useCallback(async () => {
    setLoadingEvents(true);
    try {
      const params = {
        limit,
        offset,
      };
      if (eventTypeFilter.trim()) params.event_type = eventTypeFilter.trim();
      if (transactionFilter.trim()) params.transaction_id = transactionFilter.trim();

      const res = await getAuditEvents(params);
      setEvents(res.events || []);
      setTotalCount(res.total_count || 0);
      if (onDataLoaded) onDataLoaded();
    } catch (err) {
      console.error("Failed to load audit events", err);
    } finally {
      setLoadingEvents(false);
    }
  }, [offset, eventTypeFilter, transactionFilter, onDataLoaded]);

  useEffect(() => {
    fetchIntegrity();
  }, [fetchIntegrity]);

  useEffect(() => {
    fetchEvents();
  }, [fetchEvents]);

  useEffect(() => {
    if (isRefreshing) {
      fetchIntegrity();
      fetchEvents();
    }
  }, [isRefreshing, fetchIntegrity, fetchEvents]);

  const handleCommitAnchor = async () => {
    setAnchoring(true);
    setActionMessage(null);
    setActionError(null);
    try {
      const res = await commitAuditAnchor();
      setActionMessage(
        `Anchor successfully committed! Sequence #${res.checkpoint?.sequence_number || ""}`
      );
      await fetchIntegrity();
    } catch (err) {
      setActionError(err.message || "Failed to commit external audit anchor");
    } finally {
      setAnchoring(false);
    }
  };

  const handleExportBundle = async () => {
    setExporting(true);
    setActionMessage(null);
    setActionError(null);
    try {
      const bundle = await exportEvidenceBundle({
        transaction_id: transactionFilter.trim() || undefined,
        limit: 250,
      });
      setEvidenceBundle(bundle);
      setActionMessage(`Compliance evidence bundle generated (ID: ${bundle.bundle_id})`);
    } catch (err) {
      setActionError(err.message || "Failed to export compliance evidence bundle");
    } finally {
      setExporting(false);
    }
  };

  const downloadBundleJson = () => {
    if (!evidenceBundle) return;
    const blob = new Blob([JSON.stringify(evidenceBundle, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `mirage-compliance-bundle-${evidenceBundle.bundle_id}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const getStatusBadge = (status) => {
    switch (status) {
      case "ANCHORED":
        return {
          bg: "bg-emerald-50 border-emerald-200 text-emerald-800",
          icon: ShieldCheck,
          label: "Anchored (Synchronized with External Notary)",
        };
      case "ANCHOR_STALE":
        return {
          bg: "bg-amber-50 border-amber-200 text-amber-800",
          icon: Clock,
          label: "Anchor Stale (New Events Since Last Anchor)",
        };
      case "CHAIN_VALID":
        return {
          bg: "bg-sky-50 border-sky-200 text-sky-800",
          icon: CheckCircle2,
          label: "Chain Valid (Hash Chain Intact, Unanchored)",
        };
      case "ANCHOR_UNAVAILABLE":
        return {
          bg: "bg-yellow-50 border-yellow-200 text-yellow-800",
          icon: AlertTriangle,
          label: "Anchor Unavailable (External Notary Unreachable)",
        };
      case "INTEGRITY_FAILURE":
      default:
        return {
          bg: "bg-rose-50 border-rose-200 text-rose-800",
          icon: ShieldAlert,
          label: "Integrity Failure (Tampering or Truncation Detected!)",
        };
    }
  };

  const statusConfig = integrity ? getStatusBadge(integrity.status) : null;
  const StatusIcon = statusConfig ? statusConfig.icon : ShieldAlert;

  return (
    <div className="space-y-6">
      {/* View Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-slate-200 pb-5">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900 flex items-center gap-2">
            <Lock className="w-6 h-6 text-sky-600" />
            Audit Ledger & Cryptographic Integrity
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Five-gate immutable ledger verification, deterministic SHA-256 hash chaining, and external notary anchoring.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={fetchIntegrity}
            disabled={loadingIntegrity}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 shadow-xs transition"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loadingIntegrity ? "animate-spin" : ""}`} />
            Verify Now
          </button>
          <button
            type="button"
            onClick={handleCommitAnchor}
            disabled={anchoring}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-sky-600 hover:bg-sky-700 text-white transition shadow-xs"
          >
            <Anchor className={`w-3.5 h-3.5 ${anchoring ? "animate-spin" : ""}`} />
            Commit Anchor
          </button>
          <button
            type="button"
            onClick={handleExportBundle}
            disabled={exporting}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 shadow-xs transition"
          >
            <Download className={`w-3.5 h-3.5 ${exporting ? "animate-spin" : ""}`} />
            Export Bundle
          </button>
        </div>
      </div>

      {/* Notifications */}
      {actionMessage && (
        <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-lg text-emerald-800 text-xs flex items-center justify-between">
          <span>{actionMessage}</span>
          <button type="button" onClick={() => setActionMessage(null)}>
            <X className="w-4 h-4" />
          </button>
        </div>
      )}
      {actionError && (
        <div className="p-3 bg-rose-50 border border-rose-200 rounded-lg text-rose-800 text-xs flex items-center justify-between">
          <span>{actionError}</span>
          <button type="button" onClick={() => setActionError(null)}>
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Integrity Status Card */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="md:col-span-2 bg-white border border-slate-200 rounded-xl p-5 shadow-xs space-y-4">
          <div className="flex items-center justify-between">
            <span className="text-xs uppercase font-semibold tracking-wider text-slate-500">
              Audit Hash Chain Status
            </span>
            {integrity && (
              <span
                className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${statusConfig.bg}`}
              >
                <StatusIcon className="w-3.5 h-3.5" />
                {statusConfig.label}
              </span>
            )}
          </div>

          {loadingIntegrity ? (
            <div className="py-6 flex justify-center text-slate-500 text-xs items-center gap-2">
              <RefreshCw className="w-4 h-4 animate-spin text-sky-600" />
              Verifying cryptographic hash chain across all records...
            </div>
          ) : integrityError ? (
            <div className="p-4 bg-rose-50 border border-rose-200 rounded-lg text-rose-800 text-xs">
              <strong>Verification Error:</strong> {integrityError}
            </div>
          ) : integrity ? (
            <div className="space-y-4">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
                  <div className="text-slate-500">Total Records</div>
                  <div className="text-lg font-bold text-slate-900 mt-1">
                    {integrity.total_records.toLocaleString()}
                  </div>
                </div>
                <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
                  <div className="text-slate-500">Head Sequence</div>
                  <div className="text-lg font-bold text-sky-700 mt-1">
                    #{integrity.head_sequence}
                  </div>
                </div>
                <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
                  <div className="text-slate-500">Tenant Boundary</div>
                  <div className="text-sm font-semibold text-slate-800 mt-1 truncate">
                    {integrity.tenant_id}
                  </div>
                </div>
                <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
                  <div className="text-slate-500">Chain Integrity</div>
                  <div className="text-sm font-semibold mt-1">
                    {integrity.chain_valid ? (
                      <span className="text-emerald-700 flex items-center gap-1 font-bold">
                        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" /> Valid
                      </span>
                    ) : (
                      <span className="text-rose-700 flex items-center gap-1 font-bold">
                        <AlertTriangle className="w-3.5 h-3.5 text-rose-600" /> Tampered
                      </span>
                    )}
                  </div>
                </div>
              </div>

              <div>
                <span className="text-xs text-slate-500 block mb-1">Authoritative Head Hash:</span>
                <code className="text-xs font-mono bg-slate-50 px-2.5 py-1.5 rounded border border-slate-200 text-slate-800 break-all select-all block">
                  {integrity.head_chain_hash}
                </code>
              </div>

              {integrity.defects && integrity.defects.length > 0 && (
                <div className="p-3 bg-rose-50 border border-rose-200 rounded-lg space-y-1">
                  <div className="text-xs font-bold text-rose-800 flex items-center gap-1.5">
                    <AlertTriangle className="w-4 h-4 text-rose-600" />
                    Detected Ledger Defects:
                  </div>
                  <ul className="list-disc list-inside text-xs text-rose-700 space-y-0.5">
                    {integrity.defects.map((d, idx) => (
                      <li key={idx} className="font-mono text-[11px]">
                        {d}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ) : null}
        </div>

        {/* Latest Notary Anchor Card */}
        <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs uppercase font-semibold tracking-wider text-slate-500 flex items-center gap-1.5">
              <Anchor className="w-3.5 h-3.5 text-sky-600" />
              Latest Anchor Proof
            </span>
            <span className="text-[10px] text-slate-600 bg-slate-100 px-2 py-0.5 rounded border border-slate-200">
              External Storage
            </span>
          </div>

          {integrity?.latest_anchor ? (
            <div className="space-y-3 text-xs">
              <div>
                <span className="text-slate-500 block">Anchor ID:</span>
                <span className="text-slate-800 font-mono text-[11px] truncate block">
                  {integrity.latest_anchor.anchor_id || integrity.latest_anchor.checkpoint_id}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <span className="text-slate-500 block">Anchored Seq:</span>
                  <span className="text-sky-700 font-bold">
                    #{integrity.latest_anchor.sequence_number}
                  </span>
                </div>
                <div>
                  <span className="text-slate-500 block">Trust Level:</span>
                  <span className="text-slate-800 font-medium">
                    {integrity.latest_anchor.trust_tier}
                  </span>
                </div>
              </div>
              <div>
                <span className="text-slate-500 block">Notary Signer:</span>
                <span className="text-slate-800 text-[11px] font-mono">
                  {integrity.latest_anchor.signer_identity}
                </span>
              </div>
              <div>
                <span className="text-slate-500 block mb-1">Committed Checkpoint Hash:</span>
                <code className="text-[11px] font-mono bg-slate-50 px-2 py-1 rounded border border-slate-200 text-slate-800 truncate block">
                  {integrity.latest_anchor.checkpoint_hash}
                </code>
              </div>
            </div>
          ) : (
            <div className="py-8 text-center text-xs text-slate-500 space-y-2">
              <p>No external anchor committed for this tenant yet.</p>
              <button
                type="button"
                onClick={handleCommitAnchor}
                disabled={anchoring}
                className="text-xs text-sky-600 hover:text-sky-700 underline font-medium"
              >
                Commit initial checkpoint anchor
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Events Browser Card */}
      <div className="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden">
        {/* Filter Toolbar */}
        <div className="p-4 border-b border-slate-200 bg-slate-50/50 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative">
              <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-slate-400" />
              <input
                type="text"
                placeholder="Filter by Transaction ID..."
                value={transactionFilter}
                onChange={(e) => {
                  setTransactionFilter(e.target.value);
                  setOffset(0);
                }}
                className="pl-8 pr-3 py-1.5 text-xs bg-white border border-slate-300 rounded-md text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-500/20 focus:border-sky-500 w-56"
              />
            </div>
            <select
              value={eventTypeFilter}
              onChange={(e) => {
                setEventTypeFilter(e.target.value);
                setOffset(0);
              }}
              className="py-1.5 px-2.5 text-xs bg-white border border-slate-300 rounded-md text-slate-900 focus:outline-none focus:ring-2 focus:ring-sky-500/20 focus:border-sky-500"
            >
              <option value="">All Event Types</option>
              <option value="VERIFICATION">VERIFICATION</option>
              <option value="GATE_DECISION">GATE_DECISION</option>
              <option value="ACTION_LIFECYCLE">ACTION_LIFECYCLE</option>
              <option value="TOOL_DISPATCH">TOOL_DISPATCH</option>
              <option value="SECURITY_DENIAL">SECURITY_DENIAL</option>
              <option value="OUTCOME_VERIFICATION">OUTCOME_VERIFICATION</option>
            </select>
          </div>

          <div className="text-xs text-slate-500">
            Total Events: <span className="font-semibold text-slate-900">{totalCount.toLocaleString()}</span>
          </div>
        </div>

        {/* Events Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200 text-slate-600 uppercase tracking-wider text-[11px]">
                <th className="py-2.5 px-4 font-semibold">Seq</th>
                <th className="py-2.5 px-4 font-semibold">Event Type</th>
                <th className="py-2.5 px-4 font-semibold">Transaction / Session</th>
                <th className="py-2.5 px-4 font-semibold">Actor</th>
                <th className="py-2.5 px-4 font-semibold">Decision / HRS</th>
                <th className="py-2.5 px-4 font-semibold">Chain Hash</th>
                <th className="py-2.5 px-4 font-semibold">Timestamp</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loadingEvents ? (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-slate-500">
                    <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-sky-600" />
                    Loading audit events...
                  </td>
                </tr>
              ) : events.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-slate-500">
                    No audit records matching query criteria.
                  </td>
                </tr>
              ) : (
                events.map((ev) => (
                  <tr key={ev.entry_id} className="hover:bg-slate-50 transition border-b border-slate-100">
                    <td className="py-2.5 px-4 font-mono font-bold text-sky-700">
                      #{ev.sequence_number}
                    </td>
                    <td className="py-2.5 px-4">
                      <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-slate-100 text-slate-700 border border-slate-200">
                        {ev.event_type}
                      </span>
                    </td>
                    <td className="py-2.5 px-4 font-mono text-[11px] text-slate-800">
                      {ev.transaction_id || ev.session_id || "—"}
                    </td>
                    <td className="py-2.5 px-4 text-slate-600">
                      {ev.actor_identity_id || "system"}
                    </td>
                    <td className="py-2.5 px-4">
                      {ev.decision ? (
                        <span
                          className={`font-semibold ${
                            ev.decision === "ALLOW"
                              ? "text-emerald-700"
                              : ev.decision === "BLOCK" || ev.decision === "DENY"
                              ? "text-rose-700"
                              : "text-amber-800"
                          }`}
                        >
                          {ev.decision}
                        </span>
                      ) : ev.hrs_score > 0 ? (
                        <span className="text-slate-800 font-mono">
                          HRS {Number(ev.hrs_score).toFixed(2)}
                        </span>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                    <td className="py-2.5 px-4 font-mono text-[11px] text-slate-600 truncate max-w-[140px]">
                      {ev.chain_hash}
                    </td>
                    <td className="py-2.5 px-4 text-slate-500 text-[11px] whitespace-nowrap">
                      {ev.created_at ? new Date(ev.created_at).toLocaleString() : "—"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Toolbar */}
        <div className="p-3 border-t border-slate-200 bg-slate-50/50 flex items-center justify-between text-xs text-slate-500">
          <div>
            Showing{" "}
            <span className="text-slate-900 font-medium">
              {totalCount === 0 ? 0 : offset + 1}
            </span>{" "}
            to{" "}
            <span className="text-slate-900 font-medium">
              {Math.min(offset + limit, totalCount)}
            </span>{" "}
            of <span className="text-slate-900 font-medium">{totalCount}</span> records
          </div>
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              disabled={offset === 0 || loadingEvents}
              onClick={() => setOffset(Math.max(0, offset - limit))}
              className="p-1 rounded bg-white hover:bg-slate-50 disabled:opacity-50 text-slate-700 border border-slate-200 shadow-xs transition"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button
              type="button"
              disabled={offset + limit >= totalCount || loadingEvents}
              onClick={() => setOffset(offset + limit)}
              className="p-1 rounded bg-white hover:bg-slate-50 disabled:opacity-50 text-slate-700 border border-slate-200 shadow-xs transition"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Compliance Evidence Bundle Export Modal */}
      {evidenceBundle && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-xs">
          <div className="bg-white border border-slate-200 rounded-xl max-w-2xl w-full p-6 shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-200 pb-3">
              <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
                <FileText className="w-5 h-5 text-sky-600" />
                Sealed Compliance Evidence Bundle
              </h3>
              <button
                type="button"
                onClick={() => setEvidenceBundle(null)}
                className="text-slate-400 hover:text-slate-700"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <span className="text-slate-500 block">Bundle ID:</span>
                  <span className="font-mono text-sky-700 font-semibold">
                    {evidenceBundle.bundle_id}
                  </span>
                </div>
                <div>
                  <span className="text-slate-500 block">Event Count:</span>
                  <span className="text-slate-900 font-bold">
                    {evidenceBundle.event_count}
                  </span>
                </div>
              </div>

              <div>
                <span className="text-slate-500 block mb-1">Bundle SHA-256 Digest:</span>
                <code className="text-xs font-mono bg-slate-50 px-2 py-1.5 rounded border border-slate-200 text-emerald-700 block break-all">
                  {evidenceBundle.bundle_digest}
                </code>
              </div>

              <div>
                <span className="text-slate-500 block mb-1">Chain Verification Status:</span>
                <div className="p-2.5 bg-slate-50 rounded border border-slate-200 text-[11px] text-slate-800 font-mono">
                  {JSON.stringify(evidenceBundle.chain_verification, null, 2)}
                </div>
              </div>
            </div>

            <div className="flex justify-end gap-2 border-t border-slate-200 pt-3">
              <button
                type="button"
                onClick={() => setEvidenceBundle(null)}
                className="px-3 py-1.5 text-xs rounded bg-white text-slate-700 border border-slate-200 hover:bg-slate-50 shadow-xs"
              >
                Close
              </button>
              <button
                type="button"
                onClick={downloadBundleJson}
                className="px-3 py-1.5 text-xs rounded bg-sky-600 text-white font-medium hover:bg-sky-700 shadow-xs flex items-center gap-1.5"
              >
                <Download className="w-3.5 h-3.5" />
                Download JSON Bundle
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
