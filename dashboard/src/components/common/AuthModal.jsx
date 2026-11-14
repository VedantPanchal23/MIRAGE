import React, { useState } from 'react';
import { X, Shield, Lock, ArrowRight, UserCheck, Key, Loader2 } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { api } from '../../api/client';

export function AuthModal({ isOpen, onClose, initialMode = 'login', onSuccess }) {
  const { login, loginAsDemo } = useAuth();
  const [mode, setMode] = useState(initialMode); // 'login' | 'register'
  const [tenantName, setTenantName] = useState('');
  const [email, setEmail] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  if (!isOpen) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    if (!email.trim()) {
      setError('Email address is required');
      return;
    }

    if (mode === 'register') {
      try {
        setIsLoading(true);
        const res = await api.registerTenant({
          name: tenantName.trim() || 'Apex Industrial Corp',
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
        if (onSuccess) onSuccess();
        onClose();
      } catch (err) {
        setError(err.message || 'Tenant self-registration failed');
      } finally {
        setIsLoading(false);
      }
    } else {
      login({
        identity_id: `usr_${Date.now()}`,
        name: email.split('@')[0],
        email: email.trim(),
        role: 'OPERATOR',
        tenant_id: tenantName.trim() ? `tenant_${tenantName.toLowerCase().replace(/\s+/g, '_')}` : 'tenant_apex_assurance_corp',
        tenant_name: tenantName.trim() || 'Apex Assurance Corp',
        apiKey: apiKey.trim() || undefined,
      });
      if (onSuccess) onSuccess();
      onClose();
    }
  };

  const handleDemoSelect = (role) => {
    loginAsDemo(role);
    if (onSuccess) onSuccess();
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm animate-fade-in">
      <div className="relative w-full max-w-md bg-white rounded-2xl border border-slate-200 shadow-2xl p-6 overflow-hidden">
        {/* Close Button */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-slate-400 hover:text-slate-600 transition"
        >
          <X className="w-5 h-5" />
        </button>

        {/* Modal Header */}
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 rounded-xl bg-slate-900 flex items-center justify-center text-white">
            <Shield className="w-5 h-5 text-emerald-400" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-slate-900 font-display">
              {mode === 'login' ? 'Sign In to Operator Console' : 'Provision Enterprise Tenant'}
            </h3>
            <p className="text-xs text-slate-500">
              {mode === 'login' ? 'Access your governed AI execution environment' : 'Self-service registration with instant API key issuance'}
            </p>
          </div>
        </div>

        {/* Instant 1-Click Interactive Showcase Pill */}
        <div className="mb-6 p-4 rounded-xl bg-slate-50 border border-slate-200">
          <div className="text-[11px] font-bold text-slate-900 uppercase tracking-wider mb-2 flex items-center gap-1.5">
            <UserCheck className="w-3.5 h-3.5 text-emerald-600" />
            1-Click Interactive Showcase Mode
          </div>
          <p className="text-xs text-slate-500 mb-3">
            Explore the live console immediately without configuring credentials:
          </p>
          <div className="grid grid-cols-3 gap-2">
            <button
              type="button"
              onClick={() => handleDemoSelect('OPERATOR')}
              className="py-1.5 px-2 rounded-lg bg-white border border-slate-200 hover:border-slate-300 text-xs font-semibold text-slate-700 shadow-subtle hover:bg-slate-50 transition text-center"
            >
              Operator
            </button>
            <button
              type="button"
              onClick={() => handleDemoSelect('SUPER_ADMIN')}
              className="py-1.5 px-2 rounded-lg bg-white border border-slate-200 hover:border-slate-300 text-xs font-semibold text-slate-700 shadow-subtle hover:bg-slate-50 transition text-center"
            >
              Super Admin
            </button>
            <button
              type="button"
              onClick={() => handleDemoSelect('AUDITOR')}
              className="py-1.5 px-2 rounded-lg bg-white border border-slate-200 hover:border-slate-300 text-xs font-semibold text-slate-700 shadow-subtle hover:bg-slate-50 transition text-center"
            >
              Auditor
            </button>
          </div>
        </div>

        <div className="relative my-4">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-slate-200"></div>
          </div>
          <div className="relative flex justify-center text-xs uppercase font-mono">
            <span className="bg-white px-2 text-slate-400">or sign in with credentials</span>
          </div>
        </div>

        {/* Standard Form */}
        <form onSubmit={handleSubmit} className="space-y-4 text-xs">
          {error && (
            <div className="p-2.5 rounded-lg bg-rose-50 border border-rose-200 text-rose-700">
              {error}
            </div>
          )}

          {mode === 'register' && (
            <div>
              <label className="block font-semibold text-slate-700 mb-1">Company / Tenant Name</label>
              <input
                type="text"
                placeholder="e.g. Apex Assurance Corp"
                value={tenantName}
                onChange={(e) => setTenantName(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-slate-900 text-slate-900"
              />
            </div>
          )}

          <div>
            <label className="block font-semibold text-slate-700 mb-1">Work Email</label>
            <input
              type="email"
              placeholder="s.chen@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="w-full px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-slate-900 text-slate-900"
            />
          </div>

          <div>
            <label className="block font-semibold text-slate-700 mb-1">
              {mode === 'login' ? 'API Key / Secret' : 'Initial Admin API Key (Optional)'}
            </label>
            <input
              type="password"
              placeholder="mirage_live_key_..."
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-slate-900 text-slate-900 font-mono"
            />
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="w-full py-2.5 rounded-lg bg-slate-900 text-white font-semibold hover:bg-slate-800 transition flex items-center justify-center gap-2 mt-2 disabled:opacity-50"
          >
            {isLoading ? (
              <span className="flex items-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin text-emerald-400" />
                <span>Provisioning Tenant...</span>
              </span>
            ) : (
              <>
                <span>{mode === 'login' ? 'Access Console' : 'Provision Tenant'}</span>
                <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        </form>

        <div className="mt-4 pt-4 border-t border-slate-100 text-center text-xs text-slate-500">
          {mode === 'login' ? (
            <span>
              Need a new enterprise tenant?{' '}
              <button
                onClick={() => setMode('register')}
                className="font-semibold text-slate-900 hover:underline"
              >
                Register here
              </button>
            </span>
          ) : (
            <span>
              Already have credentials?{' '}
              <button
                onClick={() => setMode('login')}
                className="font-semibold text-slate-900 hover:underline"
              >
                Sign in
              </button>
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
