import React, { useState } from 'react';
import { 
  Shield, 
  Lock, 
  ArrowRight, 
  UserCheck, 
  Key, 
  CheckCircle2, 
  AlertTriangle, 
  Server, 
  Database, 
  Cpu, 
  FileCheck,
  Building,
  Mail,
  Loader2
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { api } from '../api/client';
import { SEO } from '../components/common/SEO';

export function AuthPortal() {
  const { login, loginAsDemo } = useAuth();
  const [mode, setMode] = useState('login'); // 'login' | 'register'
  const [tenantName, setTenantName] = useState('');
  const [email, setEmail] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [registeredCreds, setRegisteredCreds] = useState(null);

  const handleSignIn = (e) => {
    e.preventDefault();
    setError(null);
    if (!email.trim() && !apiKey.trim()) {
      setError('Enter your work email or an authorized API key');
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
      setRegisteredCreds(res);
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
    } catch (err) {
      setError(err.message || 'Tenant self-registration failed');
    } finally {
      setIsLoading(false);
    }
  };

  const handleDemoSelect = (role) => {
    loginAsDemo(role);
  };

  return (
    <div className="min-h-screen bg-slate-50/60 flex flex-col justify-between text-slate-900 selection:bg-slate-900 selection:text-white">
      <SEO 
        title="Enterprise Access Portal | MIRAGE 3.0"
        description="Authenticate into the MIRAGE 3.0 Execution Assurance Platform. Governed AI execution, capability access control, and Gate 5 reality verification."
      />

      {/* Top Security Banner */}
      <header className="border-b border-slate-200/80 bg-white/90 backdrop-blur-md py-4 px-4 sm:px-8">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-slate-900 flex items-center justify-center text-white shadow-sm">
              <Shield className="w-5 h-5 text-emerald-400" />
            </div>
            <div className="flex items-baseline gap-2">
              <span className="font-extrabold text-xl tracking-tight text-slate-900 font-display">
                MIRAGE
              </span>
              <span className="text-xs font-semibold px-2 py-0.5 rounded bg-slate-100 text-slate-700 border border-slate-200">
                3.0
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-slate-100 border border-slate-200 text-xs font-medium text-slate-700">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
            <span>Fail-Closed Security Active</span>
          </div>
        </div>
      </header>

      {/* Main Authentication & Provisioning Container */}
      <main className="flex-1 flex items-center justify-center p-4 sm:p-6 lg:p-8">
        <div className="w-full max-w-xl">
          {/* Header Typography */}
          <div className="text-center mb-8">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-slate-100 text-slate-700 border border-slate-200 text-xs font-semibold uppercase tracking-wider mb-3">
              <Lock className="w-3.5 h-3.5 text-slate-600" />
              Charter Specification 3.0
            </div>
            <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 font-display tracking-tight">
              Control AI before it acts. Verify AI after it acts.
            </h1>
            <p className="text-sm text-slate-500 mt-2 max-w-md mx-auto">
              Autonomous execution assurance, capability-based access control, and Gate 5 reality verification for enterprise systems.
            </p>
          </div>

          {/* Central Portal Card */}
          <div className="bg-white rounded-2xl border border-slate-200 shadow-xl overflow-hidden p-6 sm:p-8">
            {/* Mode Switcher Tabs */}
            <div className="grid grid-cols-2 gap-1 p-1 bg-slate-100 rounded-xl mb-6 text-xs font-semibold">
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
            <div className="mb-6 p-4 rounded-xl bg-slate-50 border border-slate-200">
              <div className="flex items-center justify-between mb-2">
                <div className="text-[11px] font-bold text-slate-900 uppercase tracking-wider flex items-center gap-1.5">
                  <UserCheck className="w-3.5 h-3.5 text-emerald-600" />
                  Instant Demonstration Access
                </div>
                <span className="text-[10px] text-slate-400 font-mono">1-Click Entry</span>
              </div>
              <p className="text-xs text-slate-500 mb-3">
                Select an operational role to inspect the live assurance console immediately:
              </p>
              <div className="grid grid-cols-3 gap-2">
                <button
                  type="button"
                  onClick={() => handleDemoSelect('OPERATOR')}
                  className="py-2 px-2.5 rounded-lg bg-white border border-slate-200 hover:border-slate-300 text-xs font-semibold text-slate-700 shadow-subtle hover:bg-slate-50 transition text-center"
                >
                  <div className="text-slate-900 font-bold">Operator</div>
                  <div className="text-[10px] text-slate-400 font-normal">Level 3 Autonomy</div>
                </button>
                <button
                  type="button"
                  onClick={() => handleDemoSelect('SUPER_ADMIN')}
                  className="py-2 px-2.5 rounded-lg bg-white border border-slate-200 hover:border-slate-300 text-xs font-semibold text-slate-700 shadow-subtle hover:bg-slate-50 transition text-center"
                >
                  <div className="text-slate-900 font-bold">Super Admin</div>
                  <div className="text-[10px] text-slate-400 font-normal">Control Plane</div>
                </button>
                <button
                  type="button"
                  onClick={() => handleDemoSelect('AUDITOR')}
                  className="py-2 px-2.5 rounded-lg bg-white border border-slate-200 hover:border-slate-300 text-xs font-semibold text-slate-700 shadow-subtle hover:bg-slate-50 transition text-center"
                >
                  <div className="text-slate-900 font-bold">Auditor</div>
                  <div className="text-[10px] text-slate-400 font-normal">Ledger & Hash Chain</div>
                </button>
              </div>
            </div>

            <div className="relative my-6">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-slate-200"></div>
              </div>
              <div className="relative flex justify-center text-xs uppercase font-mono">
                <span className="bg-white px-3 text-slate-400">or authenticate credentials</span>
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
              <form onSubmit={handleSignIn} className="space-y-4 text-xs">
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
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-slate-900 text-slate-900 font-sans"
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
                  className="w-full py-3 rounded-xl bg-slate-900 text-white font-semibold hover:bg-slate-800 transition flex items-center justify-center gap-2 shadow-sm"
                >
                  <span>Launch Console</span>
                  <ArrowRight className="w-4 h-4" />
                </button>
              </form>
            )}

            {/* Form Mode: Register Tenant */}
            {mode === 'register' && (
              <form onSubmit={handleRegister} className="space-y-4 text-xs">
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
                      <CheckCircle2 className="w-3 h-3 text-emerald-600" />
                      Isolated PostgreSQL tenant namespace with Row-Level Security
                    </li>
                    <li className="flex items-center gap-1.5">
                      <CheckCircle2 className="w-3 h-3 text-emerald-600" />
                      High-entropy SHA-256 API key issued atomically
                    </li>
                    <li className="flex items-center gap-1.5">
                      <CheckCircle2 className="w-3 h-3 text-emerald-600" />
                      $5,000.00 / month sliding-window risk & spend budget
                    </li>
                  </ul>
                </div>

                <button
                  type="submit"
                  disabled={isLoading}
                  className="w-full py-3 rounded-xl bg-slate-900 text-white font-semibold hover:bg-slate-800 transition flex items-center justify-center gap-2 shadow-sm disabled:opacity-50"
                >
                  {isLoading ? (
                    <span className="flex items-center gap-2">
                      <Loader2 className="w-4 h-4 animate-spin text-emerald-400" />
                      <span>Provisioning PostgreSQL Tenant...</span>
                    </span>
                  ) : (
                    <>
                      <span>Provision Tenant & Enter Console</span>
                      <ArrowRight className="w-4 h-4" />
                    </>
                  )}
                </button>
              </form>
            )}
          </div>

          {/* Architectural Invariants Bar */}
          <div className="mt-8 grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
            <div className="p-2.5 rounded-xl border border-slate-200 bg-white shadow-subtle">
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Gate 1 & 2</div>
              <div className="text-xs font-bold text-slate-900 mt-0.5">Input & Context</div>
            </div>
            <div className="p-2.5 rounded-xl border border-slate-200 bg-white shadow-subtle">
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Gate 3</div>
              <div className="text-xs font-bold text-slate-900 mt-0.5">Action & Leases</div>
            </div>
            <div className="p-2.5 rounded-xl border border-slate-200 bg-white shadow-subtle">
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Gate 4</div>
              <div className="text-xs font-bold text-slate-900 mt-0.5">Output & HRS</div>
            </div>
            <div className="p-2.5 rounded-xl border border-slate-200 bg-white shadow-subtle">
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Gate 5</div>
              <div className="text-xs font-bold text-slate-900 mt-0.5">Reality Probes</div>
            </div>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-200/80 bg-white py-4 px-4 text-center text-xs text-slate-400">
        <p>MIRAGE 3.0 Execution Assurance Platform &bull; Epistemic Reality Verification &bull; PostgreSQL RLS Isolated</p>
      </footer>
    </div>
  );
}
