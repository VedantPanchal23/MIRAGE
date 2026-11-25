import React, { useState } from 'react';
import { CheckCircle2, Copy, Key, Terminal, ShieldCheck, X } from 'lucide-react';

export function OnboardingChecklist({ user, apiKeysCount = 0, onOpenTab = () => {} }) {
  const [dismissed, setDismissed] = useState(false);
  const [copiedSdk, setCopiedSdk] = useState(false);

  if (dismissed) return null;

  const sampleSnippet = `from mirage_sdk import MirageClient, govern_action

client = MirageClient(api_key="${user?.apiKey || 'mirage_live_...'}")

@govern_action(capability="payments:transfer", client=client)
def transfer(account_id: str, amount: float):
    return {"status": "submitted", "account_id": account_id}`;

  const handleCopySnippet = () => {
    navigator.clipboard?.writeText(sampleSnippet);
    setCopiedSdk(true);
    setTimeout(() => setCopiedSdk(false), 2000);
  };

  return (
    <section
      aria-label="Quickstart Onboarding Checklist"
      className="mb-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-xs"
    >
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h2 className="text-sm font-bold text-slate-900">Production Quickstart Checklist</h2>
          <p className="text-xs text-slate-600 mt-0.5">
            Wire your first agent or MCP server through the Five Assurance Gates in under five minutes.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setDismissed(true)}
          aria-label="Dismiss quickstart checklist"
          className="p-1.5 rounded-lg text-slate-500 hover:text-slate-900 hover:bg-slate-100 transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-3 text-xs">
        <button
          type="button"
          onClick={() => onOpenTab('access')}
          className="text-left p-3.5 rounded-xl border border-slate-200 hover:border-slate-400 bg-slate-50/60 transition-colors"
        >
          <div className="flex items-center gap-2 font-semibold text-slate-900 mb-1">
            <Key className="w-4 h-4 text-emerald-700" />
            <span>1. Issue Scoped Key</span>
          </div>
          <p className="text-[11px] text-slate-600">
            {apiKeysCount > 0 ? `${apiKeysCount} active key(s) detected.` : 'Create least-privilege API credentials.'}
          </p>
        </button>

        <button
          type="button"
          onClick={handleCopySnippet}
          className="text-left p-3.5 rounded-xl border border-slate-200 hover:border-slate-400 bg-slate-50/60 transition-colors"
        >
          <div className="flex items-center justify-between gap-2 font-semibold text-slate-900 mb-1">
            <span className="flex items-center gap-2">
              <Terminal className="w-4 h-4 text-slate-700" />
              <span>2. Wrap with @govern_action</span>
            </span>
            <Copy className="w-3.5 h-3.5 text-slate-500" />
          </div>
          <p className="text-[11px] text-slate-600">
            {copiedSdk ? 'Python snippet copied to clipboard.' : 'Click to copy Python SDK starter snippet.'}
          </p>
        </button>

        <button
          type="button"
          onClick={() => onOpenTab('mcp')}
          className="text-left p-3.5 rounded-xl border border-slate-200 hover:border-slate-400 bg-slate-50/60 transition-colors"
        >
          <div className="flex items-center gap-2 font-semibold text-slate-900 mb-1">
            <ShieldCheck className="w-4 h-4 text-slate-700" />
            <span>3. Register MCP / Tools</span>
          </div>
          <p className="text-[11px] text-slate-600">
            Bind egress limits, trust tier, and blast-radius policies.
          </p>
        </button>

        <button
          type="button"
          onClick={() => onOpenTab('audit')}
          className="text-left p-3.5 rounded-xl border border-slate-200 hover:border-slate-400 bg-slate-50/60 transition-colors"
        >
          <div className="flex items-center gap-2 font-semibold text-slate-900 mb-1">
            <CheckCircle2 className="w-4 h-4 text-emerald-700" />
            <span>4. Verify Audit Chain</span>
          </div>
          <p className="text-[11px] text-slate-600">
            Confirm SHA-256 chain integrity back to genesis block.
          </p>
        </button>
      </div>
    </section>
  );
}
