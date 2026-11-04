import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { api } from '../api';
import { Shield, Key, Copy, Check, Terminal, Lock, Sparkles, ArrowRight } from 'lucide-react';

/**
 * AuthModal: Enterprise tenant onboarding and authentication terminal.
 * Directly communicates with POST /v1/auth/register-tenant with resilient sandbox fallback.
 */
export default function AuthModal({ isOpen, onClose, onAuthSuccess }) {
  const { setTenantId, setApiKey, setUserEmail } = useAuth();
  const [mode, setMode] = useState('register'); // 'register' | 'existing' | 'demo'
  const [orgName, setOrgName] = useState('');
  const [email, setEmail] = useState('');
  const [tier, setTier] = useState('developer');
  const [manualKey, setManualKey] = useState('');
  const [manualTenant, setManualTenant] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [registeredKey, setRegisteredKey] = useState(null);
  const [copied, setCopied] = useState(false);

  if (!isOpen) return null;

  const handleRegister = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const targetTier = tier === 'team' ? 'business' : tier;
      const res = await api.registerTenant({
        name: orgName.trim(),
        admin_email: email.trim(),
        tier: targetTier,
      });

      if (res && res.tenant_id && res.api_key) {
        setRegisteredKey(res);
        setTenantId(res.tenant_id);
        setApiKey(res.api_key);
        if (email.trim() && setUserEmail) {
          setUserEmail(email.trim());
        }
        localStorage.setItem('mirage_tenant_id', res.tenant_id);
        localStorage.setItem('mirage_api_key', res.api_key);
        localStorage.setItem('mirage_user_email', email.trim());
        if (res.access_token) {
          localStorage.setItem('mirage_auth_token', res.access_token);
          localStorage.setItem('mirage_token', res.access_token);
        }
      } else {
        throw new Error('Registration completed but API credentials were not returned.');
      }
    } catch (err) {
      setError(err?.message || 'Failed to connect to MIRAGE Gateway. Please ensure the backend is running on port 8000.');
    } finally {
      setLoading(false);
    }
  };

  const handleManualLogin = (e) => {
    e.preventDefault();
    if (!manualTenant.trim() || !manualKey.trim()) {
      setError('Please provide both Tenant ID and API Key.');
      return;
    }
    setTenantId(manualTenant.trim());
    setApiKey(manualKey.trim());
    localStorage.setItem('mirage_tenant_id', manualTenant.trim());
    localStorage.setItem('mirage_api_key', manualKey.trim());
    onClose();
    if (onAuthSuccess) onAuthSuccess();
  };

  const handleCopyKey = () => {
    if (registeredKey?.api_key) {
      navigator.clipboard.writeText(registeredKey.api_key);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-mirage-void/85 backdrop-blur-md animate-fade-in font-mono"
      role="dialog"
      aria-modal="true"
      aria-labelledby="auth-modal-title"
    >
      <div className="bg-mirage-surfaceElevated border border-mirage-borderStrong rounded shadow-hud-panel max-w-md w-full p-6 relative overflow-hidden transition-all text-mirage-text">
        {/* Tactical Corner Crosshairs */}
        <div className="absolute top-0 left-0 w-3 h-3 border-t-2 border-l-2 border-mirage-cyan pointer-events-none" />
        <div className="absolute bottom-0 right-0 w-3 h-3 border-b-2 border-r-2 border-mirage-cyan pointer-events-none" />

        {/* Close Button */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-mirage-muted hover:text-mirage-cyan p-1.5 rounded hover:bg-mirage-surface transition-colors"
          aria-label="Close dialog"
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>

        {registeredKey ? (
          /* Success Screen displaying newly generated live API Key */
          <div className="text-center py-2 space-y-4">
            <div className="w-12 h-12 bg-mirage-emerald/15 text-mirage-emerald border border-mirage-emerald/40 rounded flex items-center justify-center mx-auto shadow-hud-glow-emerald">
              <Check className="w-6 h-6" />
            </div>
            <div>
              <h3 id="auth-modal-title" className="text-lg font-bold text-mirage-text tracking-wide uppercase font-display">
                TENANT PROVISIONED // RLS ISOLATED
              </h3>
              <p className="text-xs text-mirage-muted mt-1">
                TENANT_ID: <span className="text-mirage-cyan font-bold">{registeredKey.tenant_id}</span>
              </p>
            </div>

            <div className="bg-mirage-chassis border border-mirage-border rounded p-3 text-left">
              <div className="flex items-center justify-between mb-1 text-[11px]">
                <span className="text-mirage-muted font-bold">// PRODUCTION_API_KEY</span>
                <button
                  type="button"
                  onClick={handleCopyKey}
                  className="text-mirage-cyan hover:underline font-bold flex items-center space-x-1"
                >
                  {copied ? (
                    <>
                      <Check className="w-3 h-3" />
                      <span>COPIED</span>
                    </>
                  ) : (
                    <>
                      <Copy className="w-3 h-3" />
                      <span>COPY_KEY</span>
                    </>
                  )}
                </button>
              </div>
              <div className="font-mono text-xs break-all text-mirage-cyan select-all bg-mirage-surface p-2 rounded border border-mirage-border/80">
                {registeredKey.api_key}
              </div>
              <p className="text-[10px] text-mirage-muted mt-1.5">
                Cryptographically bound to PostgreSQL Row-Level Security. Carries <span className="text-mirage-amber font-semibold">Role.TENANT_ADMIN</span>.
              </p>
            </div>

            <button
              onClick={() => {
                onClose();
                if (onAuthSuccess) onAuthSuccess();
              }}
              className="w-full py-2.5 px-4 bg-mirage-cyan text-mirage-void rounded font-bold text-xs uppercase tracking-wider hover:bg-white shadow-hud-glow transition-all active:scale-[0.98]"
            >
              INITIALIZE MISSION CONTROL &rarr;
            </button>
          </div>
        ) : (
          /* Registration / Sign-in Tabs */
          <div>
            <div className="flex border-b border-mirage-border mb-4">
              <button
                type="button"
                onClick={() => { setMode('register'); setError(''); }}
                className={`flex-1 pb-2.5 text-xs font-bold tracking-wider uppercase transition-colors ${
                  mode === 'register'
                    ? 'border-b-2 border-mirage-cyan text-mirage-cyan'
                    : 'text-mirage-muted hover:text-mirage-text'
                }`}
              >
                PROVISION TENANT
              </button>
              <button
                type="button"
                onClick={() => { setMode('existing'); setError(''); }}
                className={`flex-1 pb-2.5 text-xs font-bold tracking-wider uppercase transition-colors ${
                  mode === 'existing'
                    ? 'border-b-2 border-mirage-cyan text-mirage-cyan'
                    : 'text-mirage-muted hover:text-mirage-text'
                }`}
              >
                ATTACH API KEY
              </button>
            </div>

            <h3 id="auth-modal-title" className="text-sm font-bold text-mirage-text mb-1 uppercase font-display tracking-wide">
              {mode === 'register' ? 'Deploy Governed Namespace' : 'Authorize Session'}
            </h3>
            <p className="text-xs text-mirage-muted mb-4 font-sans">
              {mode === 'register'
                ? 'Provision dedicated cryptographic tenant schema and acquire root governance credentials.'
                : 'Enter your credentials to bind PostgreSQL RLS context to the execution plane.'}
            </p>

            {error && (
              <div className="mb-4 p-2.5 bg-mirage-crimson/15 border border-mirage-crimson/40 text-mirage-crimson text-xs rounded flex items-start space-x-2">
                <span className="font-bold">!</span>
                <span>{error}</span>
              </div>
            )}

            {mode === 'register' ? (
              <form onSubmit={handleRegister} className="space-y-3">
                <div>
                  <label className="block text-[10px] font-bold text-mirage-subtext uppercase tracking-wider mb-1">
                    ORGANIZATION / TENANT IDENTIFIER
                  </label>
                  <input
                    type="text"
                    required
                    value={orgName}
                    onChange={(e) => setOrgName(e.target.value)}
                    placeholder="e.g. Acme Financial Technologies"
                    className="w-full px-3 py-2 text-xs border border-mirage-border rounded bg-mirage-surface text-mirage-text focus:outline-none focus:border-mirage-cyan transition-all font-mono"
                  />
                </div>

                <div>
                  <label className="block text-[10px] font-bold text-mirage-subtext uppercase tracking-wider mb-1">
                    ADMIN CONTACT EMAIL
                  </label>
                  <input
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="alex@acmefinance.com"
                    className="w-full px-3 py-2 text-xs border border-mirage-border rounded bg-mirage-surface text-mirage-text focus:outline-none focus:border-mirage-cyan transition-all font-mono"
                  />
                </div>

                <div>
                  <label className="block text-[10px] font-bold text-mirage-subtext uppercase tracking-wider mb-1">
                    EXECUTION ASSURANCE TIER
                  </label>
                  <select
                    value={tier}
                    onChange={(e) => setTier(e.target.value)}
                    className="w-full px-3 py-2 text-xs border border-mirage-border rounded bg-mirage-surface text-mirage-text focus:outline-none focus:border-mirage-cyan transition-all font-mono"
                  >
                    <option value="developer">Developer (Free / $0 — 10k req/mo)</option>
                    <option value="team">Pro / Starter ($29 / ₹1,999 — 75k req/mo)</option>
                    <option value="enterprise">Enterprise ($299 / ₹24,999 — 2M req/mo)</option>
                  </select>
                </div>

                <div className="pt-2">
                  <button
                    type="submit"
                    disabled={loading}
                    className="w-full py-2.5 px-4 bg-mirage-cyan text-mirage-void rounded font-bold text-xs uppercase tracking-wider hover:bg-white shadow-hud-glow transition-all active:scale-[0.98] disabled:opacity-50 flex items-center justify-center space-x-2"
                  >
                    {loading ? (
                      <span>PROVISIONING RLS SCHEMA & KEYS...</span>
                    ) : (
                      <span>INITIALIZE GOVERNED EXECUTION &rarr;</span>
                    )}
                  </button>
                </div>
              </form>
            ) : (
              <form onSubmit={handleManualLogin} className="space-y-3">
                <div>
                  <label className="block text-[10px] font-bold text-mirage-subtext uppercase tracking-wider mb-1">
                    TARGET TENANT ID
                  </label>
                  <input
                    type="text"
                    required
                    value={manualTenant}
                    onChange={(e) => setManualTenant(e.target.value)}
                    placeholder="e.g. tenant_acme_corp"
                    className="w-full px-3 py-2 text-xs border border-mirage-border rounded bg-mirage-surface text-mirage-text focus:outline-none focus:border-mirage-cyan transition-all font-mono"
                  />
                </div>

                <div>
                  <label className="block text-[10px] font-bold text-mirage-subtext uppercase tracking-wider mb-1">
                    PRODUCTION API KEY
                  </label>
                  <input
                    type="password"
                    required
                    value={manualKey}
                    onChange={(e) => setManualKey(e.target.value)}
                    placeholder="mirage_live_..."
                    className="w-full px-3 py-2 text-xs border border-mirage-border rounded bg-mirage-surface text-mirage-text focus:outline-none focus:border-mirage-cyan transition-all font-mono"
                  />
                </div>

                <div className="pt-2">
                  <button
                    type="submit"
                    className="w-full py-2.5 px-4 bg-mirage-cyan text-mirage-void rounded font-bold text-xs uppercase tracking-wider hover:bg-white shadow-hud-glow transition-all active:scale-[0.98]"
                  >
                    AUTHENTICATE SESSION &rarr;
                  </button>
                </div>
              </form>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
