import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { api } from '../api';

/**
 * AuthModal: Enterprise tenant onboarding and authentication modal.
 * Directly communicates with POST /v1/auth/register-tenant for zero-mock live account generation.
 */
export default function AuthModal({ isOpen, onClose, onAuthSuccess }) {
  const { setTenantId, setApiKey } = useAuth();
  const [mode, setMode] = useState('register'); // 'register' | 'existing'
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
        localStorage.setItem('mirage_tenant_id', res.tenant_id);
        localStorage.setItem('mirage_api_key', res.api_key);
        if (res.access_token) {
          localStorage.setItem('mirage_token', res.access_token);
        }
      } else {
        setError('Registration completed but API credentials were not returned.');
      }
    } catch (err) {
      const msg = typeof err.message === 'string'
        ? err.message
        : (Array.isArray(err.detail) ? err.detail.map(d => d.msg || JSON.stringify(d)).join(', ') : 'Registration failed');
      setError(msg || 'Failed to register enterprise tenant. Please check inputs.');
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
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-apple-text/30 backdrop-blur-sm animate-fade-in"
      role="dialog"
      aria-modal="true"
      aria-labelledby="auth-modal-title"
    >
      <div className="bg-apple-card border border-apple-border/70 rounded-2xl shadow-apple-lg max-w-md w-full p-6 relative overflow-hidden transition-all">
        {/* Close Button */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-apple-gray hover:text-apple-text p-1.5 rounded-full hover:bg-apple-bg transition-colors"
          aria-label="Close dialog"
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>

        {registeredKey ? (
          /* Success Screen displaying newly generated live API Key */
          <div className="text-center py-2 space-y-4">
            <div className="w-12 h-12 bg-apple-green/10 text-apple-green rounded-full flex items-center justify-center mx-auto">
              <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <div>
              <h3 id="auth-modal-title" className="text-xl font-semibold text-apple-text">
                Workspace Provisioned!
              </h3>
              <p className="text-xs text-apple-subtext mt-1">
                Tenant ID: <span className="font-mono text-apple-text font-medium">{registeredKey.tenant_id}</span>
              </p>
            </div>

            <div className="bg-apple-bg border border-apple-border rounded-xl p-3 text-left">
              <div className="flex items-center justify-between mb-1">
                <span className="text-[11px] font-medium text-apple-subtext">Live Production API Key</span>
                <button
                  type="button"
                  onClick={handleCopyKey}
                  className="text-xs text-apple-blue hover:underline font-medium"
                >
                  {copied ? 'Copied!' : 'Copy'}
                </button>
              </div>
              <div className="font-mono text-xs break-all text-apple-text select-all bg-white p-2 rounded border border-apple-border/40">
                {registeredKey.api_key}
              </div>
              <p className="text-[10px] text-apple-gray mt-1.5">
                Save this key securely. It carries <span className="font-medium text-apple-text">Role.TENANT_ADMIN</span> permissions.
              </p>
            </div>

            <button
              onClick={() => {
                onClose();
                if (onAuthSuccess) onAuthSuccess();
              }}
              className="w-full py-2.5 px-4 bg-apple-blue text-white rounded-xl font-medium text-sm hover:bg-apple-blue/90 shadow-sm transition-all"
            >
              Enter Dashboard &rarr;
            </button>
          </div>
        ) : (
          /* Registration / Sign-in Tabs */
          <div>
            <div className="flex border-b border-apple-border mb-5">
              <button
                type="button"
                onClick={() => { setMode('register'); setError(''); }}
                className={`flex-1 pb-2.5 text-xs font-semibold tracking-wide transition-colors ${
                  mode === 'register'
                    ? 'border-b-2 border-apple-blue text-apple-blue'
                    : 'text-apple-subtext hover:text-apple-text'
                }`}
              >
                Create Account
              </button>
              <button
                type="button"
                onClick={() => { setMode('existing'); setError(''); }}
                className={`flex-1 pb-2.5 text-xs font-semibold tracking-wide transition-colors ${
                  mode === 'existing'
                    ? 'border-b-2 border-apple-blue text-apple-blue'
                    : 'text-apple-subtext hover:text-apple-text'
                }`}
              >
                Sign In with Key
              </button>
            </div>

            <h3 id="auth-modal-title" className="text-lg font-semibold text-apple-text mb-1">
              {mode === 'register' ? 'Launch Your Governed Tenant' : 'Authenticate Workspace'}
            </h3>
            <p className="text-xs text-apple-subtext mb-4">
              {mode === 'register'
                ? 'Get instant access to live Five-Gate AI execution assurance.'
                : 'Enter your credentials to manage active leases and policies.'}
            </p>

            {error && (
              <div className="mb-4 p-2.5 bg-red-50 border border-red-200 text-red-700 text-xs rounded-xl flex items-start space-x-2">
                <span className="font-bold">!</span>
                <span>{error}</span>
              </div>
            )}

            {mode === 'register' ? (
              <form onSubmit={handleRegister} className="space-y-3.5">
                <div>
                  <label className="block text-xs font-medium text-apple-text mb-1">
                    Organization / Company Name
                  </label>
                  <input
                    type="text"
                    required
                    value={orgName}
                    onChange={(e) => setOrgName(e.target.value)}
                    placeholder="e.g. Acme Financial Technologies"
                    className="w-full px-3 py-2 text-xs border border-apple-border rounded-xl bg-apple-bg focus:bg-white focus:outline-none focus:ring-2 focus:ring-apple-blue/20 focus:border-apple-blue transition-all"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-apple-text mb-1">
                    Work Email
                  </label>
                  <input
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="alex@acmefinance.com"
                    className="w-full px-3 py-2 text-xs border border-apple-border rounded-xl bg-apple-bg focus:bg-white focus:outline-none focus:ring-2 focus:ring-apple-blue/20 focus:border-apple-blue transition-all"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-apple-text mb-1">
                    Subscription Tier
                  </label>
                  <select
                    value={tier}
                    onChange={(e) => setTier(e.target.value)}
                    className="w-full px-3 py-2 text-xs border border-apple-border rounded-xl bg-apple-bg focus:bg-white focus:outline-none focus:ring-2 focus:ring-apple-blue/20 focus:border-apple-blue transition-all"
                  >
                    <option value="developer">Developer (Free / $0 — 10k req/mo)</option>
                    <option value="team">Team ($149 / ₹12,499 — 250k req/mo)</option>
                    <option value="enterprise">Enterprise ($999 / ₹82,999 — 2M req/mo)</option>
                  </select>
                </div>

                <div className="pt-2">
                  <button
                    type="submit"
                    disabled={loading}
                    className="w-full py-2.5 px-4 bg-apple-blue text-white rounded-xl font-medium text-xs hover:bg-apple-blue/90 shadow-sm transition-all disabled:opacity-50 flex items-center justify-center space-x-2"
                  >
                    {loading ? (
                      <span>Provisioning Postgres RLS & Keys...</span>
                    ) : (
                      <span>Start Governed Execution &rarr;</span>
                    )}
                  </button>
                </div>
              </form>
            ) : (
              <form onSubmit={handleManualLogin} className="space-y-3.5">
                <div>
                  <label className="block text-xs font-medium text-apple-text mb-1">
                    Tenant ID
                  </label>
                  <input
                    type="text"
                    required
                    value={manualTenant}
                    onChange={(e) => setManualTenant(e.target.value)}
                    placeholder="e.g. tenant_acme_corp"
                    className="w-full px-3 py-2 text-xs border border-apple-border rounded-xl bg-apple-bg focus:bg-white focus:outline-none focus:ring-2 focus:ring-apple-blue/20 focus:border-apple-blue transition-all"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-apple-text mb-1">
                    Production API Key
                  </label>
                  <input
                    type="password"
                    required
                    value={manualKey}
                    onChange={(e) => setManualKey(e.target.value)}
                    placeholder="mirage_live_..."
                    className="w-full px-3 py-2 text-xs border border-apple-border rounded-xl bg-apple-bg focus:bg-white focus:outline-none focus:ring-2 focus:ring-apple-blue/20 focus:border-apple-blue transition-all font-mono"
                  />
                </div>

                <div className="pt-2">
                  <button
                    type="submit"
                    className="w-full py-2.5 px-4 bg-apple-blue text-white rounded-xl font-medium text-xs hover:bg-apple-blue/90 shadow-sm transition-all"
                  >
                    Authenticate Workspace &rarr;
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
