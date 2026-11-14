import React, { useState } from 'react';
import { 
  Shield, 
  Lock, 
  ArrowRight, 
  UserCheck, 
  Key, 
  CheckCircle2, 
  AlertTriangle, 
  Building, 
  Mail, 
  Loader2,
  X
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { api } from '../../api/client';

export function AuthModal({ isOpen, onClose, initialMode = 'login', onSuccessfulLogin }) {
  const { login, loginAsDemo } = useAuth();
  const [mode, setMode] = useState(initialMode); // 'login' | 'register'
  const [tenantName, setTenantName] = useState('');
  const [email, setEmail] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  if (!isOpen) return null;

  const handleSignIn = (e) => {
    e.preventDefault();
    setError(null);
    if (!email.trim() && !apiKey.trim()) {
      setError('Please provide your work email or an authorized API key');
      return;
    }

    login({
      identity_id: `usr_${Date.now()}`,
      name: email ? email.split('@')[0] : 'Enterprise Operator',
      email: email.trim() || 'operator@enterprise.com',
      role: 'OPERATOR',
      tenant_id: tenantName.trim() ? `tenant_${tenantName.toLowerCase().replace(/\s+/g, '_')}` : 'tenant_apex_assurance_corp',
      tenant_name: tenantName.trim() || 'Apex Assurance Corp',
      apiKey: apiKey.trim() || undefined,
    });
    if (onSuccessfulLogin) onSuccessfulLogin();
    onClose();
  };

  const handleRegister = async (e) => {
    e.preventDefault();
    setError(null);
    if (!tenantName.trim()) {
      setError('Company / Organization name is required');
      return;
    }
    if (!email.trim()) {
      setError('Administrator email is required');
      return;
    }

    try {
      setIsLoading(true);
      const res = await api.registerTenant({
        name: tenantName.trim(),
        email: email.trim(),
        tier: 'enterprise',
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
      });
      if (onSuccessfulLogin) onSuccessfulLogin();
      onClose();
    } catch (err) {
      setError(err.message || 'Tenant self-registration failed');
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
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-200">
      <div 
        className="relative w-full max-w-lg bg-white rounded-2xl border border-slate-200 shadow-2xl overflow-hidden p-6 sm:p-8"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Close Button */}
        <button
          onClick={onClose}
          className="absolute top-5 right-5 p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition"
          title="Close dialog"
        >
          <X className="w-5 h-5" />
        </button>

        {/* Modal Header */}
        <div className="flex items-center gap-3 mb-5">
          <div className="w-10 h-10 rounded-xl bg-slate-900 flex items-center justify-center text-white shadow-sm">
            <Shield className="w-5 h-5 text-emerald-400" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-extrabold text-lg text-slate-900 font-display">
                MIRAGE 3.0
              </span>
              <span className="text-[10px] font-semibold px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200/60">
                Enterprise Access
              </span>
            </div>
            <p className="text-xs text-slate-500">
              Epistemic Execution Assurance &amp; Reality Verification
            </p>
          </div>
        </div>

        {/* Mode Switcher Tabs */}
        <div className="grid grid-cols-2 gap-1 p-1 bg-slate-100 rounded-xl mb-5 text-xs font-semibold">
          <button
            type="button"
            onClick={() => { setMode('login'); setError(null); }}
            className={`py-2 rounded-lg transition-all ${
              mode === 'login'
                ? 'bg-white text-slate-900 shadow-sm'
                : 'text-slate-600 hover:text-slate-900'
            }`}
          >
            Sign In to Console
          </button>
          <button
            type="button"
            onClick={() => { setMode('register'); setError(null); }}
            className={`py-2 rounded-lg transition-all ${
              mode === 'register'
                ? 'bg-white text-slate-900 shadow-sm'
                : 'text-slate-600 hover:text-slate-900'
            }`}
          >
            Provision Enterprise Tenant
          </button>
        </div>

        {/* 1-Click Interactive Showcase Pill */}
        <div className="mb-5 p-3.5 rounded-xl bg-slate-50 border border-slate-200">
          <div className="flex items-center justify-between mb-2">
            <div className="text-[11px] font-bold text-slate-900 uppercase tracking-wider flex items-center gap-1.5">
              <UserCheck className="w-3.5 h-3.5 text-emerald-600" />
              Instant Demonstration Access
            </div>
            <span className="text-[10px] text-slate-400 font-mono">1-Click Entry</span>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <button
              type="button"
              onClick={() => handleDemoSelect('OPERATOR')}
              className="py-2 px-2 rounded-lg bg-white border border-slate-200 hover:border-slate-300 text-xs font-semibold text-slate-700 shadow-subtle hover:bg-slate-50 transition text-center"
            >
              <div className="text-slate-900 font-bold">Operator</div>
              <div className="text-[10px] text-slate-400 font-normal">Level 3 Autonomy</div>
            </button>
            <button
              type="button"
              onClick={() => handleDemoSelect('SUPER_ADMIN')}
              className="py-2 px-2 rounded-lg bg-white border border-slate-200 hover:border-slate-300 text-xs font-semibold text-slate-700 shadow-subtle hover:bg-slate-50 transition text-center"
            >
              <div className="text-slate-900 font-bold">Super Admin</div>
              <div className="text-[10px] text-slate-400 font-normal">Control Plane</div>
            </button>
            <button
              type="button"
              onClick={() => handleDemoSelect('AUDITOR')}
              className="py-2 px-2 rounded-lg bg-white border border-slate-200 hover:border-slate-300 text-xs font-semibold text-slate-700 shadow-subtle hover:bg-slate-50 transition text-center"
            >
              <div className="text-slate-900 font-bold">Auditor</div>
              <div className="text-[10px] text-slate-400 font-normal">Hash Chain</div>
            </button>
          </div>
        </div>

        <div className="relative my-4">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-slate-200"></div>
          </div>
          <div className="relative flex justify-center text-[10px] uppercase font-mono">
            <span className="bg-white px-3 text-slate-400">or enter credentials</span>
          </div>
        </div>

        {/* Error Banner */}
        {error && (
          <div className="mb-4 p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0 text-rose-500" />
            <span>{error}</span>
          </div>
        )}

        {/* Form Mode: Sign In */}
        {mode === 'login' && (
          <form onSubmit={handleSignIn} className="space-y-3.5 text-xs">
            <div>
              <label className="block font-semibold text-slate-700 mb-1 flex items-center gap-1.5">
                <Mail className="w-3.5 h-3.5 text-slate-400" />
                Work Email
              </label>
              <input
                type="email"
                placeholder="operator@enterprise.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-slate-900 text-slate-900"
              />
            </div>

            <div>
              <label className="block font-semibold text-slate-700 mb-1 flex items-center gap-1.5">
                <Key className="w-3.5 h-3.5 text-slate-400" />
                Production API Key (Optional)
              </label>
              <input
                type="password"
                placeholder="mirage_live_key_..."
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-slate-900 text-slate-900 font-mono"
              />
            </div>

            <button
              type="submit"
              className="w-full py-2.5 rounded-xl bg-slate-900 text-white font-semibold hover:bg-slate-800 transition flex items-center justify-center gap-2 shadow-sm mt-2"
            >
              <span>Launch Mission Control</span>
              <ArrowRight className="w-4 h-4" />
            </button>
          </form>
        )}

        {/* Form Mode: Register Tenant */}
        {mode === 'register' && (
          <form onSubmit={handleRegister} className="space-y-3.5 text-xs">
            <div>
              <label className="block font-semibold text-slate-700 mb-1 flex items-center gap-1.5">
                <Building className="w-3.5 h-3.5 text-slate-400" />
                Company / Organization Name
              </label>
              <input
                type="text"
                placeholder="Apex Autonomous Systems"
                value={tenantName}
                onChange={(e) => setTenantName(e.target.value)}
                required
                className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-slate-900 text-slate-900"
              />
            </div>

            <div>
              <label className="block font-semibold text-slate-700 mb-1 flex items-center gap-1.5">
                <Mail className="w-3.5 h-3.5 text-slate-400" />
                Administrator Email
              </label>
              <input
                type="email"
                placeholder="admin@apexsystems.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-slate-900 text-slate-900"
              />
            </div>

            <div className="p-3 rounded-xl bg-slate-50 border border-slate-200">
              <div className="text-[11px] font-bold text-slate-700 mb-1">Provisioned Invariants:</div>
              <ul className="space-y-1 text-[11px] text-slate-500">
                <li className="flex items-center gap-1.5">
                  <CheckCircle2 className="w-3 h-3 text-emerald-600 shrink-0" />
                  PostgreSQL Row-Level Security tenant namespace
                </li>
                <li className="flex items-center gap-1.5">
                  <CheckCircle2 className="w-3 h-3 text-emerald-600 shrink-0" />
                  SHA-256 API Key with monotonic concurrency lease
                </li>
              </ul>
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="w-full py-2.5 rounded-xl bg-slate-900 text-white font-semibold hover:bg-slate-800 transition flex items-center justify-center gap-2 shadow-sm disabled:opacity-50 mt-2"
            >
              {isLoading ? (
                <span className="flex items-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin text-emerald-400" />
                  <span>Provisioning PostgreSQL Namespace...</span>
                </span>
              ) : (
                <>
                  <span>Provision Tenant &amp; Enter Console</span>
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
