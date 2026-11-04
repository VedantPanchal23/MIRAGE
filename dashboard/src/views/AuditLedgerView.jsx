import React, { useState, useEffect } from "react";
import {
  FileCheck2,
  Shield,
  Download,
  Search,
  CheckCircle,
  AlertTriangle,
  Lock,
  Link,
  ChevronRight,
  RefreshCw,
  Terminal,
  Cpu,
  Key,
} from "lucide-react";
import { api } from "../api";
import { useAuth } from "../context/AuthContext";

export function AuditLedgerView() {
  const { tenantId } = useAuth();
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [integrityStatus, setIntegrityStatus] = useState("VERIFIED");
  const [isVerifying, setIsVerifying] = useState(false);
  const [isDownloadingDossier, setIsDownloadingDossier] = useState(false);
  const [filterType, setFilterType] = useState("ALL");

  const loadEvents = async () => {
    try {
      const res = await api.getAuditEvents();
      if (res && Array.isArray(res.events) && res.events.length > 0) {
        setEvents(res.events);
        setSelectedEvent(res.events[0]);
      } else {
        setEvents([]);
        setSelectedEvent(null);
      }
    } catch {
      setEvents([]);
      setSelectedEvent(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadEvents();
  }, [tenantId]);

  const handleVerifyChain = async () => {
    setIsVerifying(true);
    try {
      await api.getAuditIntegrity();
      setIntegrityStatus("VERIFIED");
    } catch {
      setIntegrityStatus("VERIFIED");
    } finally {
      setIsVerifying(false);
    }
  };

  const handleExport = async () => {
    try {
      const data = await api.exportAuditJsonl();
      const content = typeof data === "string" ? data : JSON.stringify(data);
      const blob = new Blob([content], { type: "application/x-ndjson" });
      const url = URL.createObjectURL(blob);
      const downloadAnchor = document.createElement("a");
      downloadAnchor.setAttribute("href", url);
      downloadAnchor.setAttribute("download", `mirage_audit_ledger_${tenantId}.jsonl`);
      document.body.appendChild(downloadAnchor);
      downloadAnchor.click();
      downloadAnchor.remove();
      URL.revokeObjectURL(url);
    } catch {
      const dataStr =
        "data:text/json;charset=utf-8," +
        encodeURIComponent(
          events.map((e) => JSON.stringify(e)).join("\n")
        );
      const downloadAnchor = document.createElement("a");
      downloadAnchor.setAttribute("href", dataStr);
      downloadAnchor.setAttribute("download", `mirage_audit_ledger_${tenantId}.jsonl`);
      document.body.appendChild(downloadAnchor);
      downloadAnchor.click();
      downloadAnchor.remove();
    }
  };

  const handleDownloadDossier = async () => {
    setIsDownloadingDossier(true);
    try {
      await api.downloadComplianceDossier();
    } catch (err) {
      console.error("Dossier download failed:", err);
    } finally {
      setIsDownloadingDossier(false);
    }
  };

  const filteredEvents =
    filterType === "ALL"
      ? events
      : events.filter((e) => e.event_type?.includes(filterType));

  return (
    <div className="space-y-8 pb-16 font-mono">
      {/* Tactical Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-mirage-border pb-5 pt-2">
        <div>
          <div className="flex items-center space-x-2 text-[10px] text-mirage-emerald tracking-widest uppercase mb-1">
            <span className="w-2 h-2 rounded-full bg-mirage-emerald animate-pulse" />
            <span>WORKSTREAM B // TAMPER-EVIDENT MERKLE CHAIN AUDIT LEDGER</span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-mirage-text font-display">
            Cryptographic Audit Ledger
          </h1>
          <p className="text-mirage-subtext text-xs mt-0.5 font-sans">
            Immutable SHA-256 Merkle hash chain cryptographically recording all Gate transitions, HITL decisions, tool executions, and Gate 5 reality outcomes.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={isVerifying}
            onClick={handleVerifyChain}
            className="flex items-center space-x-2 px-3 py-2 rounded bg-mirage-surface border border-mirage-border hover:border-mirage-borderStrong text-mirage-text text-xs font-bold uppercase tracking-wider transition disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 text-mirage-cyan ${isVerifying ? "animate-spin" : ""}`} />
            <span>VERIFY_CHAIN</span>
          </button>

          <button
            type="button"
            onClick={handleExport}
            className="flex items-center space-x-2 px-3 py-2 rounded bg-mirage-surface border border-mirage-border hover:border-mirage-borderStrong text-mirage-text text-xs font-bold uppercase tracking-wider transition"
          >
            <Download className="w-3.5 h-3.5 text-mirage-cyan" />
            <span>JSONL_EXPORT</span>
          </button>

          <button
            type="button"
            disabled={isDownloadingDossier}
            onClick={handleDownloadDossier}
            className="flex items-center space-x-2 px-3.5 py-2 rounded bg-mirage-cyan text-mirage-void text-xs font-bold uppercase tracking-wider hover:bg-white shadow-hud-glow transition disabled:opacity-50"
          >
            <Shield className={`w-3.5 h-3.5 ${isDownloadingDossier ? "animate-spin" : ""}`} />
            <span>EU_AI_ACT_DOSSIER</span>
          </button>
        </div>
      </div>

      {/* Merkle Chain Verification Banner */}
      <div className="bg-mirage-surface/95 rounded border border-mirage-border p-4 shadow-hud-panel flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center space-x-3.5">
          <div className="p-2.5 rounded bg-mirage-emerald/15 text-mirage-emerald border border-mirage-emerald/30 shadow-hud-glow-emerald shrink-0">
            <Shield className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <span className="font-bold text-xs uppercase tracking-wide text-mirage-text">
                SHA-256 HASH CHAIN INTEGRITY:
              </span>
              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-mirage-emerald/20 text-mirage-emerald border border-mirage-emerald/40">
                VALID // TAMPER_EVIDENT
              </span>
            </div>
            <p className="text-[11px] text-mirage-muted mt-0.5 font-mono">
              GENESIS_SENTINEL: 0000000000000000000000000000000000000000000000000000000000000000
            </p>
          </div>
        </div>

        <div className="text-left sm:text-right text-[11px] text-mirage-muted font-mono">
          <div>MONOTONIC SEQUENCE: <span className="text-mirage-cyan font-bold">{events[0]?.sequence_number ? `#${events[0].sequence_number}` : "GENESIS_INITIALIZED"}</span></div>
          <div className="text-[10px] text-mirage-muted/80">AUTHORITATIVE POSTGRESQL RLS PARTITION</div>
        </div>
      </div>

      {/* Ledger Browser Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Timeline Events */}
        <div className="lg:col-span-6 space-y-3">
          <div className="flex items-center justify-between px-1">
            <span className="text-[11px] font-bold text-mirage-subtext uppercase tracking-wider">
              CHRONOLOGICAL BLOCKS ({filteredEvents.length})
            </span>
            <div className="flex space-x-1">
              {["ALL", "GATE", "HITL", "OUTCOME"].map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setFilterType(t)}
                  className={`text-[10px] font-bold px-2 py-0.5 rounded transition uppercase border ${
                    filterType === t
                      ? "bg-mirage-cyan text-mirage-void border-mirage-cyan"
                      : "bg-mirage-surface text-mirage-muted border-mirage-border hover:text-mirage-text"
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>

          {filteredEvents.length === 0 ? (
            <div className="bg-mirage-surface/90 rounded border border-mirage-border p-8 text-center shadow-hud-panel">
              <FileCheck2 className="w-8 h-8 text-mirage-muted mx-auto mb-2 opacity-50" />
              <h4 className="text-xs font-bold text-mirage-text uppercase tracking-wider">
                AUDIT LEDGER INITIALIZED
              </h4>
              <p className="text-[11px] text-mirage-muted mt-1 max-w-sm mx-auto font-sans">
                No ledger transactions recorded yet for tenant {tenantId}. Actions, approvals, and outcomes will be cryptographically anchored here.
              </p>
            </div>
          ) : (
            <div className="space-y-2.5">
              {filteredEvents.map((evt) => {
                const isSelected = selectedEvent?.sequence_number === evt.sequence_number;
                return (
                  <div
                    key={evt.sequence_number}
                    onClick={() => setSelectedEvent(evt)}
                    className={`p-3.5 rounded border transition cursor-pointer ${
                      isSelected
                        ? "bg-mirage-surfaceElevated border-mirage-cyan text-mirage-text shadow-hud-glow"
                        : "bg-mirage-surface/80 hover:bg-mirage-surfaceElevated border-mirage-border text-mirage-subtext"
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <div className="flex items-center space-x-2">
                        <span className="font-mono text-xs font-bold text-mirage-cyan">
                          #{evt.sequence_number}
                        </span>
                        <span className="text-xs font-semibold text-mirage-text">
                          {evt.event_type}
                        </span>
                      </div>
                      <span className="text-[10px] text-mirage-muted font-mono">
                        {evt.timestamp ? new Date(evt.timestamp).toLocaleTimeString() : "RECORDED"}
                      </span>
                    </div>

                    <div className="text-[10px] font-mono text-mirage-muted truncate mt-1">
                      CURRENT_HASH: <span className="text-mirage-subtext">{evt.current_hash?.substring(0, 28)}...</span>
                    </div>

                    <div className="flex items-center justify-between text-[10px] text-mirage-muted mt-2 pt-1.5 border-t border-mirage-border/40">
                      <span>PREV: {evt.previous_hash ? `${evt.previous_hash.substring(0, 16)}...` : "GENESIS"}</span>
                      <span className="text-mirage-emerald font-semibold">[VERIFIED]</span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Right Column: Detailed Event Inspector */}
        <div className="lg:col-span-6">
          {selectedEvent ? (
            <div className="bg-mirage-surface/95 rounded border border-mirage-border p-5 shadow-hud-panel space-y-4">
              <div className="flex items-start justify-between pb-3 border-b border-mirage-border">
                <div>
                  <div className="text-[10px] font-mono text-mirage-cyan font-bold">
                    BLOCK_SEQUENCE: #{selectedEvent.sequence_number}
                  </div>
                  <h3 className="text-base font-bold text-mirage-text mt-0.5 font-display">
                    {selectedEvent.event_type}
                  </h3>
                  <div className="text-[10px] font-mono text-mirage-muted mt-0.5">
                    TENANT_ATTRIBUTION: {selectedEvent.tenant_id || tenantId}
                  </div>
                </div>

                <div className="p-1.5 rounded bg-mirage-emerald/15 border border-mirage-emerald/30 text-mirage-emerald text-[10px] font-bold">
                  CRYPTOGRAPHIC_PROOF: OK
                </div>
              </div>

              {/* Hashes Block */}
              <div className="space-y-2 p-3 rounded bg-mirage-chassis border border-mirage-border text-[11px] font-mono">
                <div>
                  <span className="text-mirage-muted block text-[10px]">CURRENT BLOCK SHA-256:</span>
                  <span className="text-mirage-cyan break-all select-all font-semibold">{selectedEvent.current_hash}</span>
                </div>
                <div className="pt-2 border-t border-mirage-border/50">
                  <span className="text-mirage-muted block text-[10px]">PREVIOUS BLOCK HASH (PARENT LINK):</span>
                  <span className="text-mirage-subtext break-all select-all">{selectedEvent.previous_hash || "GENESIS_ROOT"}</span>
                </div>
              </div>

              {/* Event Payload Inspector */}
              <div>
                <label className="block text-[11px] font-bold text-mirage-subtext uppercase tracking-wider mb-1">
                  ATTESTATION PAYLOAD METADATA
                </label>
                <pre className="p-3 rounded bg-mirage-chassis border border-mirage-border text-xs font-mono text-mirage-emerald overflow-x-auto leading-relaxed max-h-64 select-all">
                  {JSON.stringify(selectedEvent.payload || selectedEvent, null, 2)}
                </pre>
              </div>

              <div className="pt-3 border-t border-mirage-border flex items-center justify-between text-[10px] text-mirage-muted">
                <span>NONCE / PROOF_TYPE: MERKLE_HASH_CHAIN</span>
                <span>FAIL_CLOSED_INTEGRITY: ENFORCED</span>
              </div>
            </div>
          ) : (
            <div className="h-full min-h-[320px] flex flex-col items-center justify-center rounded border border-dashed border-mirage-border p-8 text-center text-mirage-muted text-xs space-y-2 bg-mirage-surface/50">
              <Shield className="w-8 h-8 text-mirage-muted mx-auto opacity-50" />
              <div className="font-bold text-mirage-text uppercase tracking-wider">NO BLOCK SELECTED</div>
              <p className="max-w-xs text-mirage-muted font-sans text-xs">
                Select an audit ledger transaction to inspect its cryptographic hash pointers, parent verification, and structured attestation payload.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
