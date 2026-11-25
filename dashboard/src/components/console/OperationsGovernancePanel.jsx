import React, { useState, useEffect } from 'react';
import { AlertTriangle, BookOpen, CreditCard, Download, Trash2, Webhook } from 'lucide-react';
import { api } from '../../api/client';

export function OperationsGovernancePanel({ onToast = () => {} }) {
  const [stranded, setStranded] = useState([]);
  const [kbDocs, setKbDocs] = useState([]);
  const [webhooks, setWebhooks] = useState([]);
  const [subscription, setSubscription] = useState(null);
  const [error, setError] = useState(null);

  const [docFilename, setDocFilename] = useState('');
  const [docContent, setDocContent] = useState('');
  const [webhookUrl, setWebhookUrl] = useState('');

  const loadGovernance = async () => {
    setError(null);
    try {
      const [strRes, kbRes, whRes, subRes] = await Promise.all([
        api.listStrandedActions(),
        api.listKbDocuments(),
        api.listWebhooks(),
        api.getSubscription(),
      ]);
      setStranded(Array.isArray(strRes) ? strRes : []);
      setKbDocs(kbRes.documents || (Array.isArray(kbRes) ? kbRes : []));
      setWebhooks(whRes.webhooks || (Array.isArray(whRes) ? whRes : []));
      setSubscription(subRes);
    } catch (err) {
      setError(`Could not load operational governance state: ${err.message}`);
    }
  };

  useEffect(() => {
    loadGovernance();
  }, []);

  const handleReconcile = async (actionId, resolution) => {
    try {
      await api.reconcileAction(actionId, {
        resolution,
        notes: `Operator resolved stranded action as ${resolution} via Console`,
      });
      onToast(`Stranded action ${actionId} reconciled as ${resolution}.`, 'success');
      await loadGovernance();
    } catch (err) {
      onToast(`Reconciliation failed: ${err.message}`, 'violation');
    }
  };

  const handleUploadKb = async (e) => {
    e.preventDefault();
    if (!docFilename.trim() || !docContent.trim()) return;
    try {
      await api.uploadKbDocument({
        filename: docFilename.trim(),
        content: docContent.trim(),
      });
      setDocFilename('');
      setDocContent('');
      onToast('Knowledge Base document enqueued/indexed.', 'success');
      await loadGovernance();
      setTimeout(loadGovernance, 1200);
    } catch (err) {
      onToast(`KB upload failed: ${err.message}`, 'violation');
    }
  };

  const handleAddWebhook = async (e) => {
    e.preventDefault();
    if (!webhookUrl.trim()) return;
    try {
      await api.registerWebhook({
        url: webhookUrl.trim(),
        events: ['ACTION_AWAITING_APPROVAL', 'ACTION_BLOCKED'],
        description: 'Operator Console Webhook',
      });
      setWebhookUrl('');
      onToast('Outbound webhook registered.', 'success');
      await loadGovernance();
    } catch (err) {
      onToast(`Webhook registration failed: ${err.message}`, 'violation');
    }
  };

  const handleDeleteWebhook = async (webhookId) => {
    try {
      await api.deleteWebhook(webhookId);
      onToast('Outbound webhook deleted.', 'info');
      await loadGovernance();
    } catch (err) {
      onToast(`Webhook deletion failed: ${err.message}`, 'violation');
    }
  };

  const handleExportDsar = async () => {
    try {
      const data = await api.exportPrivacyDossier();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `mirage_dsar_summary.json`;
      a.click();
      URL.revokeObjectURL(url);
      onToast('GDPR DSAR summary exported & audited.', 'success');
    } catch (err) {
      onToast(`DSAR export failed: ${err.message}`, 'violation');
    }
  };

  return (
    <div className="space-y-6">
      {error && (
        <div role="alert" className="p-4 rounded-xl bg-rose-50 border border-rose-200 text-rose-800 text-xs flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Stranded EXECUTION_UNCERTAIN Queue */}
      <div className="rounded-2xl border border-slate-200 bg-white p-6">
        <h3 className="text-base font-bold text-slate-900 mb-1">Stranded Execution Reconciliation Queue</h3>
        <p className="text-xs text-slate-600 mb-4">
          Resolve actions stuck in <code>EXECUTING</code> or <code>EXECUTION_UNCERTAIN</code> without blind redispatch.
        </p>
        {stranded.length === 0 ? (
          <p className="text-xs text-slate-500 py-3">No stranded actions require reconciliation.</p>
        ) : (
          <div className="space-y-2.5 text-xs">
            {stranded.map((item) => (
              <div key={item.action_id} className="p-3.5 rounded-xl border border-amber-200 bg-amber-50/60 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="font-mono font-bold text-slate-900">{item.action_id}</div>
                  <div className="text-slate-700">{item.tool_name} &rarr; {item.target_resource}</div>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => handleReconcile(item.action_id, 'MARK_FAILED')}
                    className="px-3 py-1.5 rounded-lg bg-rose-600 text-white text-[11px] font-semibold"
                  >
                    Mark Failed
                  </button>
                  <button
                    type="button"
                    onClick={() => handleReconcile(item.action_id, 'MARK_COMPLETED')}
                    className="px-3 py-1.5 rounded-lg bg-emerald-600 text-white text-[11px] font-semibold"
                  >
                    Confirm Completed
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Budgets, Subscription & DSAR Privacy Export */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="rounded-2xl border border-slate-200 bg-white p-6">
          <h3 className="text-base font-bold text-slate-900 flex items-center gap-2 mb-3">
            <CreditCard className="w-4 h-4 text-slate-700" />
            <span>Subscription &amp; Budget Headroom</span>
          </h3>
          {subscription ? (
            <div className="space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-slate-600">Current Tier</span>
                <span className="font-bold uppercase text-slate-900">{subscription.current_tier}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-600">Monthly Budget</span>
                <span className="font-mono font-bold tabular-nums">${subscription.monthly_budget_usd}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-600">Remaining Headroom</span>
                <span className="font-mono font-bold text-emerald-700 tabular-nums">${subscription.remaining_headroom_usd}</span>
              </div>
            </div>
          ) : (
            <p className="text-xs text-slate-500">Connect to gateway to view billing and budget telemetry.</p>
          )}

          <div className="mt-5 pt-4 border-t border-slate-200 flex items-center justify-between gap-2">
            <span className="text-xs text-slate-600">GDPR Portability &amp; Audit Dossier</span>
            <button
              type="button"
              onClick={handleExportDsar}
              className="px-3 py-1.5 rounded-lg bg-slate-900 text-white text-xs font-semibold hover:bg-slate-800 flex items-center gap-1.5"
            >
              <Download className="w-3.5 h-3.5" />
              <span>Export DSAR Summary</span>
            </button>
          </div>
        </div>

        {/* Outbound Alert Webhooks */}
        <div className="rounded-2xl border border-slate-200 bg-white p-6">
          <h3 className="text-base font-bold text-slate-900 flex items-center gap-2 mb-3">
            <Webhook className="w-4 h-4 text-slate-700" />
            <span>Alert Webhooks ({webhooks.length})</span>
          </h3>
          <form onSubmit={handleAddWebhook} className="flex gap-2 mb-4">
            <label htmlFor="webhook-target-url" className="sr-only">
              Webhook HTTPS URL
            </label>
            <input
              id="webhook-target-url"
              type="url"
              placeholder="https://hooks.slack.com/services/..."
              value={webhookUrl}
              onChange={(e) => setWebhookUrl(e.target.value)}
              className="flex-1 px-3 py-2 rounded-lg border border-slate-300 text-xs font-mono text-slate-900"
            />
            <button
              type="submit"
              className="px-3.5 py-2 rounded-lg bg-slate-900 text-white text-xs font-semibold"
            >
              Add Webhook
            </button>
          </form>
          <div className="space-y-2 text-xs">
            {webhooks.map((w) => (
              <div key={w.id} className="p-2.5 rounded-lg border border-slate-200 bg-slate-50 flex items-center justify-between gap-2">
                <span className="font-mono text-[11px] truncate">{w.url}</span>
                <button
                  type="button"
                  aria-label={`Delete webhook ${w.id}`}
                  onClick={() => handleDeleteWebhook(w.id)}
                  className="text-rose-600 hover:text-rose-800 p-1"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Knowledge Base */}
      <div className="rounded-2xl border border-slate-200 bg-white p-6">
        <h3 className="text-base font-bold text-slate-900 flex items-center gap-2 mb-3">
          <BookOpen className="w-4 h-4 text-slate-700" />
          <span>Gate 2 Authoritative Knowledge Base ({kbDocs.length} docs)</span>
        </h3>
        <form onSubmit={handleUploadKb} className="space-y-2 mb-4">
          <div className="flex gap-2">
            <label htmlFor="kb-doc-filename" className="sr-only">
              Document Filename
            </label>
            <input
              id="kb-doc-filename"
              type="text"
              placeholder="policy_handbook.md"
              value={docFilename}
              onChange={(e) => setDocFilename(e.target.value)}
              className="flex-1 px-3 py-2 rounded-lg border border-slate-300 text-xs font-mono"
            />
            <button type="submit" className="px-4 py-2 rounded-lg bg-slate-900 text-white text-xs font-semibold">
              Ingest Document
            </button>
          </div>
          <label htmlFor="kb-doc-content" className="sr-only">
            Document Content
          </label>
          <textarea
            id="kb-doc-content"
            rows={2}
            placeholder="Paste authoritative ground-truth text for RAV / Gate 2 provenance..."
            value={docContent}
            onChange={(e) => setDocContent(e.target.value)}
            className="w-full px-3 py-2 rounded-lg border border-slate-300 text-xs"
          />
        </form>
        <div className="space-y-2 text-xs">
          {kbDocs.map((d) => (
            <div key={d.document_id || d.id} className="p-2.5 rounded-lg border border-slate-200 flex items-center justify-between">
              <span className="font-mono">{d.filename}</span>
              <span className="text-slate-600">{d.status}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
