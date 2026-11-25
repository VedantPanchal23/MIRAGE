import React, { useState, useEffect, useRef } from 'react';
import {
  Lock,
  ArrowRight,
  UserCheck,
  Key,
  CheckCircle2,
  AlertTriangle,
  Building,
  Mail,
  Loader2,
  X,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { api } from '../../api/client';
import { MirageLogo } from '../common/MirageLogo';

export function AuthModal({ isOpen, onClose, initialMode = 'login', onSuccessfulLogin }) {
  const { login, loginAsDemo } = useAuth();
  const [mode, setMode] = useState(initialMode);
  const [tenantName, setTenantName] = useState('');
  const [email, setEmail] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const closeBtnRef = useRef(null);

  useEffect(() => {
    setMode(initialMode);
    setError(null);
  }, [initialMode, isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    closeBtnRef.current?.focus();
    const handleKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleSignIn = async (e) => {
    e.preventDefault();
    setError(null);
    if (!apiKey.trim()) {
      setError('Enter a valid tenant API key or Bearer JWT to authenticate against /v1/auth/me.');
      return;
    }

    const raw = apiKey.trim();
    const isJwt = raw.split('.').length === 3 && !raw.startsWith('mirage_');
    const tenantSlug = tenantName.trim() ? tenantName.trim() : '';

    try {
      setIsLoading(true);
      const verified = await api.validateCredentials({
        apiKey: isJwt ? '' : raw,
        token: isJwt ? raw : '',
        tenantId: tenantSlug,
      });

      login({
        identity_id: verified.identity_id || verified.user_id || 'usr_verified',
        name: email.trim() ? email.trim().split('@')[0] : verified.user_id || 'Operator',
        email: email.trim() || `${verified.user_id || 'operator'}@${verified.tenant_id || 'tenant'}.mirage.ai`,
        role: String(verified.role || 'OPERATOR').toUpperCase(),
        tenant_id: verified.tenant_id,
        tenant_name: tenantSlug || verified.tenant_id,
        apiKey: isJwt ? undefined : raw,
        token: isJwt ? raw : undefined,
        isDemo: false,
      });
      if (onSuccessfulLogin) onSuccessfulLogin();
      onClose();
    } catch (err) {
      setError(
        `Credential verification failed (${err.message}). Confirm the gateway is running and your key is active, or use Demo Sandbox access below.`
      );
    } finally {
      setIsLoading(false);
    }
  };

  const handleRegister = async (e) => {
    e.preventDefault();
    setError(null);
    if (!tenantName.trim()) {
      setError('Company / Organization name is required.');
      return;
    }
    if (!email.trim()) {
      setError('Administrator email is required.');
      return;
    }

    try {
      setIsLoading(true);
      const res = await api.registerTenant({
        name: tenantName.trim(),
        email: email.trim(),
        tier: 'business',
      });
      login({
        identity_id: res.admin_identity_id,
        name: res.name || email.split('@')[0],
        email: email.trim(),
        role: 'TENANT_ADMIN',
        tenant_id: res.tenant_id,
        tenant_name: res.name,
        apiKey: res.api_key,
        token: res.access_token,
        access_token: res.access_token,
        isDemo: false,
      });
      if (onSuccessfulLogin) onSuccessfulLogin();
      onClose();
    } catch (err) {
      setError(err.message || 'Tenant self-registration failed.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleDemoSelect = (role) => {
    loginAsDemo(role);
    if (onSuccessfulLogin) onSuccessfulLogin();
    onClose();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="auth-modal-title"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-lg bg-white rounded-2xl border border-slate-200 shadow-2xl overflow-hidden p-6 sm:p-8 max-h-[90vh] overflow-y-auto overscroll-contain"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          ref={closeBtnRef}
          type="button"
          onClick={onClose}
          aria-label="Close authentication modal"
          className="absolute top-5 right-5 p-2 rounded-lg text-slate-500 hover:text-slate-900 hover:bg-slate-100 transition-colors"
        >
          <X className="w-5 h-5" />
        </button>

        <div className="flex items-center gap-3 mb-5">
          <MirageLogo size="md" showText={true} />
          <span
            id="auth-modal-title"
            className="text-[11px] font-semibold px-2.5 py-0.5 rounded bg-emerald-50 text-emerald-800 border border-emerald-200 ml-auto mr-8"
          >
            Enterprise Console
          </span>
        </div>

        <div className="grid grid-cols-2 gap-1 p-1 bg-slate-100 rounded-xl mb-5 text-xs font-semibold">
          <button
            type="button"
            onClick={() => {
              setMode('login');
              setError(null);
            }}
            className={`py-2 px-3 rounded-lg transition-colors ${
              mode === 'login' ? 'bg-white text-slate-900 shadow-xs' : 'text-slate-600 hover:text-slate-900'
            }`}
          >
            Sign In (Live Key / JWT)
          </button>
          <button
            type="button"
            onClick={() => {
              setMode('register');
              setError(null);
            }}
            className={`py-2 px-3 rounded-lg transition-colors ${
              mode === 'register' ? 'bg-white text-slate-900 shadow-xs' : 'text-slate-600 hover:text-slate-900'
            }`}
          >
            Provision Enterprise Tenant
          </button>
        </div>

        <div className="mb-5 p-3.5 rounded-xl bg-slate-50 border border-slate-200">
          <div className="text-[11px] font-bold text-slate-600 uppercase tracking-wider mb-2.5 flex items-center justify-between">
            <span className="flex items-center gap-1.5">
              <UserCheck className="w-3.5 h-3.5 text-emerald-700" />
              Interactive Sandbox Mode (Simulated Telemetry)
            </span>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <button
              type="button"
              onClick={() => handleDemoSelect('OPERATOR')}
              className="p-2.5 rounded-lg border border-slate-200 bg-white hover:border-slate-400 transition-colors text-left"
            >
              <div className="font-bold text-slate-900 text-xs">Vedant (Operator)</div>
              <div className="text-[11px] text-slate-600">Level 3 Autonomy</div>
            </button>
            <button
              type="button"
              onClick={() => handleDemoSelect('SUPER_ADMIN')}
              className="p-2.5 rounded-lg border border-slate-200 bg-white hover:border-slate-400 transition-colors text-left"
            >
              <div className="font-bold text-slate-900 text-xs">Admin</div>
              <div className="text-[11px] text-slate-600">Full L4 Sign-Off</div>
            </button>
            <button
              type="button"
              onClick={() => handleDemoSelect('AUDITOR')}
              className="p-2.5 rounded-lg border border-slate-200 bg-white hover:border-slate-400 transition-colors text-left"
            >
              <div className="font-bold text-slate-900 text-xs">Dax (Auditor)</div>
              <div className="text-[11px] text-slate-600">Audit Read-Only</div>
            </button>
          </div>
        </div>

        {error && (
          <div
            role="alert"
            className="mb-4 p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-800 text-xs flex items-start gap-2"
          >
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5 text-rose-700" />
            <span>{error}</span>
          </div>
        )}

        {mode === 'login' ? (
          <form onSubmit={handleSignIn} className="space-y-4">
            <div>
              <label htmlFor="auth-login-email" className="block text-xs font-semibold text-slate-700 mb-1">
                Work Email (Optional Display Label)
              </label>
              <div className="relative">
                <Mail className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  id="auth-login-email"
                  name="email"
                  type="email"
                  autoComplete="email"
                  placeholder="operator@company.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full pl-9 pr-3 py-2.5 rounded-lg border border-slate-300 text-sm text-slate-900"
                />
              </div>
            </div>

            <div>
              <label htmlFor="auth-login-key" className="block text-xs font-semibold text-slate-700 mb-1">
                MIRAGE API Key or Bearer JWT
              </label>
              <div className="relative">
                <Key className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  id="auth-login-key"
                  name="apiKey"
                  type="password"
                  placeholder="mirage_live_key_..."
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  className="w-full pl-9 pr-3 py-2.5 rounded-lg border border-slate-300 text-sm font-mono text-slate-900"
                />
              </div>
            </div>

            <div>
              <label htmlFor="auth-login-tenant" className="block text-xs font-semibold text-slate-700 mb-1">
                Tenant ID (Optional)
              </label>
              <div className="relative">
                <Building className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  id="auth-login-tenant"
                  name="tenantId"
                  type="text"
                  placeholder="tenant_..."
                  value={tenantName}
                  onChange={(e) => setTenantName(e.target.value)}
                  className="w-full pl-9 pr-3 py-2.5 rounded-lg border border-slate-300 text-sm font-mono text-slate-900"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="w-full py-2.5 px-4 rounded-xl bg-slate-900 hover:bg-slate-800 text-white font-semibold text-sm transition-colors flex items-center justify-center gap-2"
            >
              {isLoading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Verifying against Gateway...</span>
                </>
              ) : (
                <>
                  <span>Verify &amp; Access Console</span>
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </form>
        ) : (
          <form onSubmit={handleRegister} className="space-y-4">
            <div>
              <label htmlFor="auth-reg-org" className="block text-xs font-semibold text-slate-700 mb-1">
                Organization Name
              </label>
              <div className="relative">
                <Building className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  id="auth-reg-org"
                  name="organization"
                  type="text"
                  placeholder="Apex Autonomous Systems"
                  value={tenantName}
                  onChange={(e) => setTenantName(e.target.value)}
                  className="w-full pl-9 pr-3 py-2.5 rounded-lg border border-slate-300 text-sm text-slate-900"
                />
              </div>
            </div>

            <div>
              <label htmlFor="auth-reg-email" className="block text-xs font-semibold text-slate-700 mb-1">
                Administrator Email
              </label>
              <div className="relative">
                <Mail className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  id="auth-reg-email"
                  name="email"
                  type="email"
                  autoComplete="email"
                  placeholder="admin@apexsystems.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full pl-9 pr-3 py-2.5 rounded-lg border border-slate-300 text-sm text-slate-900"
                />
              </div>
            </div>

            <div className="p-3 rounded-lg bg-emerald-50 border border-emerald-200 text-xs text-emerald-900 flex items-start gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-700 shrink-0 mt-0.5" />
              <span>
                Automatically provisions isolated PostgreSQL RLS row context, cryptographic audit ledger root, and a primary API key.
              </span>
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="w-full py-2.5 px-4 rounded-xl bg-slate-900 hover:bg-slate-800 text-white font-semibold text-sm transition-colors flex items-center justify-center gap-2"
            >
              {isLoading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Provisioning Tenant...</span>
                </>
              ) : (
                <>
                  <Lock className="w-4 h-4" />
                  <span>Provision Tenant &amp; Generate Key</span>
                </>
              )}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
