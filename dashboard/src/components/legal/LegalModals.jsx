import React, { useEffect, useState, useRef } from 'react';
import { X, Shield, Lock, FileText, Activity, CheckCircle2 } from 'lucide-react';
import { api } from '../../api/client';

export function LegalModals({ activeDoc, onClose = () => {} }) {
  const [statusData, setStatusData] = useState(null);
  const [statusError, setStatusError] = useState(null);
  const closeRef = useRef(null);

  useEffect(() => {
    if (!activeDoc) return;
    closeRef.current?.focus();
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    if (activeDoc === 'status') {
      setStatusError(null);
      api
        .getPublicStatus()
        .then(setStatusData)
        .catch((err) => setStatusError(err.message));
    }
    return () => window.removeEventListener('keydown', onKey);
  }, [activeDoc, onClose]);

  if (!activeDoc) return null;

  const titles = {
    privacy: 'Privacy Policy & GDPR Notice',
    terms: 'Terms of Service & Data Processing Addendum',
    trust: 'Security & Compliance Trust Center',
    status: 'MIRAGE Operational System Status',
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="legal-modal-title"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl bg-white rounded-2xl border border-[#ededed] shadow-2xl p-6 sm:p-8 max-h-[85vh] overflow-y-auto overscroll-contain text-sm text-[#19171b]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between pb-4 border-b border-[#ededed] mb-5">
          <div className="flex items-center gap-2.5">
            {activeDoc === 'privacy' && <Lock className="w-5 h-5 text-emerald-700" />}
            {activeDoc === 'terms' && <FileText className="w-5 h-5 text-[#0c152a]" />}
            {activeDoc === 'trust' && <Shield className="w-5 h-5 text-emerald-700" />}
            {activeDoc === 'status' && <Activity className="w-5 h-5 text-emerald-700" />}
            <h2 id="legal-modal-title" className="text-lg font-medium text-[#0c152a]">
              {titles[activeDoc] || 'Governance Notice'}
            </h2>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Close legal and compliance dialog"
            className="p-2 rounded-lg text-slate-500 hover:text-slate-900 hover:bg-slate-100 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {activeDoc === 'privacy' && (
          <div className="space-y-3 text-xs text-[#6b6c71] leading-relaxed">
            <p className="text-[#0c152a] font-medium">
              Effective Notice — MIRAGE Systems Inc. (Template SaaS Privacy Summary)
            </p>
            <p>
              MIRAGE processes prompt metadata, action proposals, and audit ledger hashes strictly within tenant-isolated PostgreSQL Row-Level Security (`NOBYPASSRLS`) boundaries, partitioned MongoDB trace collections, and tenant-scoped Qdrant indices.
            </p>
            <p>
              <strong>Retention &amp; GDPR Rights:</strong> Telemetry traces follow configurable TTL (`MONGO_RETENTION_DAYS`, 90d default), while immutable compliance anchors retain for audit verification. Authorized tenant administrators can export DSAR packages via <code>GET /v1/privacy/export</code> or revoke keys/offboard via <code>/v1/admin/tenants/&#123;id&#125;/offboard</code>.
            </p>
            <p className="p-3 rounded-xl bg-[#f8f8fa] border border-[#ededed]">
              Note: Before commercial production launch, replace entity address, DPO contact, and subprocessor schedules under counsel review.
            </p>
          </div>
        )}

        {activeDoc === 'terms' && (
          <div className="space-y-3 text-xs text-[#6b6c71] leading-relaxed">
            <p className="text-[#0c152a] font-medium">
              Master Subscription Terms &amp; DPA Summary — MIRAGE Systems Inc.
            </p>
            <p>
              Subscriptions govern API throughput quotas, distributed lease concurrency limits, and monthly budget ceilings per tier. MIRAGE enforces fail-closed policy gating at Gate 1–5; customers remain responsible for downstream external target systems where remote conditional mutations are unsupported (documented under <code>RSK-FENCE-01</code>).
            </p>
            <p>
              <strong>Acceptable Use:</strong> Customers may not intentionally bypass capability attenuation, probe internal metadata endpoints, or disable audit chain checks in production clusters.
            </p>
          </div>
        )}

        {activeDoc === 'trust' && (
          <div className="space-y-4 text-xs text-[#6b6c71] leading-relaxed">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {[
                ['PostgreSQL 16 RLS', 'FORCE ROW LEVEL SECURITY under unprivileged mirage_app role.'],
                ['Immutable Audit Chain', '14-field SHA-256 chain + HMAC/S3 Object Lock WORM anchors.'],
                ['EU AI Act Alignment', 'Articles 12, 14 & 50 traceability, L4 HITL, and dossier bundles.'],
                ['SSRF & DIFC Guard', 'Socket IP pinning + Dangerous Triad egress lock.'],
              ].map(([title, desc]) => (
                <div key={title} className="p-3.5 rounded-xl border border-[#ededed] bg-[#f8f8fa]">
                  <div className="font-semibold text-[#0c152a] flex items-center gap-1.5 mb-1">
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-700" />
                    <span>{title}</span>
                  </div>
                  <p>{desc}</p>
                </div>
              ))}
            </div>
            <p>
              Audit artifacts (including ZIP compliance bundles and integrity verification proofs) are downloadable directly from Operator Console under <strong>Governance &amp; Billing</strong> or <code>GET /v1/privacy/export?format=zip</code>.
            </p>
          </div>
        )}

        {activeDoc === 'status' && (
          <div className="space-y-3 text-xs">
            {statusError ? (
              <div role="alert" className="p-4 rounded-xl border border-amber-200 bg-amber-50 text-amber-900">
                Could not reach live gateway <code>/v1/status</code> ({statusError}). Start the MIRAGE gateway stack to inspect live runtime status.
              </div>
            ) : statusData ? (
              <div className="space-y-3">
                <div className="p-3.5 rounded-xl border border-emerald-200 bg-emerald-50 text-emerald-900 flex items-center justify-between">
                  <span className="font-semibold">{statusData.service}</span>
                  <span className="font-mono uppercase font-bold">{statusData.status}</span>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 font-mono text-[11px]">
                  {Object.entries(statusData.gates || {}).map(([gate, st]) => (
                    <div key={gate} className="p-2.5 rounded-lg border border-[#ededed] bg-[#f8f8fa]">
                      <div className="text-[#6b6c71]">{gate}</div>
                      <div className="font-bold text-emerald-700 uppercase mt-0.5">{st}</div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <p className="text-slate-500">Checking runtime status...</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
