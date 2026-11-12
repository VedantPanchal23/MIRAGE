import React from 'react';
import { Shield, Lock, FileCheck, Database, Terminal, Cpu, CheckCircle } from 'lucide-react';

export function Footer({ setActiveView }) {
  return (
    <footer className="bg-white border-t border-slate-200 mt-24">
      {/* Trust & Invariant Bar */}
      <div className="border-b border-slate-100 bg-slate-50/50 py-8">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded bg-emerald-50 text-emerald-600 border border-emerald-200/50">
                <Shield className="w-4 h-4" />
              </div>
              <div>
                <div className="text-xs font-semibold text-slate-900">Epistemic Outcome Independence</div>
                <div className="text-[11px] text-slate-500">Gate 5 reality checks verify physical side effects</div>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <div className="p-2 rounded bg-blue-50 text-blue-600 border border-blue-200/50">
                <Lock className="w-4 h-4" />
              </div>
              <div>
                <div className="text-xs font-semibold text-slate-900">Monotonic Lease Fencing</div>
                <div className="text-[11px] text-slate-500">Stale token replay defense across distributed workers</div>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <div className="p-2 rounded bg-purple-50 text-purple-600 border border-purple-200/50">
                <FileCheck className="w-4 h-4" />
              </div>
              <div>
                <div className="text-xs font-semibold text-slate-900">SHA-256 Audit Chaining</div>
                <div className="text-[11px] text-slate-500">Cryptographic hash ledger anchored to Genesis Root</div>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <div className="p-2 rounded bg-amber-50 text-amber-600 border border-amber-200/50">
                <Database className="w-4 h-4" />
              </div>
              <div>
                <div className="text-xs font-semibold text-slate-900">PostgreSQL RLS Fail-Closed</div>
                <div className="text-[11px] text-slate-500">Zero cross-tenant data leakage guaranteed at DB layer</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Main Sitemap & Links */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-14">
        <div className="grid grid-cols-2 md:grid-cols-5 gap-8">
          {/* Brand Info */}
          <div className="col-span-2">
            <div className="flex items-center gap-2.5 mb-4">
              <div className="w-8 h-8 rounded-lg bg-slate-900 flex items-center justify-center text-white">
                <Shield className="w-4 h-4 text-emerald-400" />
              </div>
              <span className="font-extrabold text-lg tracking-tight text-slate-900 font-display">
                MIRAGE 3.0
              </span>
            </div>
            <p className="text-sm text-slate-500 max-w-sm mb-4 leading-relaxed">
              The AI Execution Assurance Platform. Sitting between autonomous models and the real world to govern identity, policy, capabilities, and independent physical reality verification.
            </p>
            <div className="text-xs text-slate-400 font-mono">
              Core Promise: &quot;Control AI before it acts. Verify AI after it acts.&quot;
            </div>
          </div>

          {/* Column 1: The Five Gates */}
          <div>
            <h4 className="text-xs font-bold text-slate-900 uppercase tracking-wider mb-3">
              The Five Gates
            </h4>
            <ul className="space-y-2 text-xs text-slate-600">
              <li><a href="#five-gates" className="hover:text-slate-900 transition">Gate 1: Input Assurance</a></li>
              <li><a href="#five-gates" className="hover:text-slate-900 transition">Gate 2: Context Assurance</a></li>
              <li><a href="#five-gates" className="hover:text-slate-900 transition">Gate 3: Action Assurance</a></li>
              <li><a href="#five-gates" className="hover:text-slate-900 transition">Gate 4: Output Assurance</a></li>
              <li><a href="#five-gates" className="hover:text-slate-900 transition">Gate 5: Outcome Assurance</a></li>
            </ul>
          </div>

          {/* Column 2: Developer & SDK */}
          <div>
            <h4 className="text-xs font-bold text-slate-900 uppercase tracking-wider mb-3">
              Developer SDKs
            </h4>
            <ul className="space-y-2 text-xs text-slate-600">
              <li><a href="#sdk-docs" className="hover:text-slate-900 transition font-mono">pip install mirage-sdk</a></li>
              <li><a href="#sdk-docs" className="hover:text-slate-900 transition">OpenAI Proxy Drop-In</a></li>
              <li><a href="#sdk-docs" className="hover:text-slate-900 transition">LangChain Interceptor</a></li>
              <li><a href="#sdk-docs" className="hover:text-slate-900 transition">OpenAPI 3.1 Contract</a></li>
              <li><a href="#sdk-docs" className="hover:text-slate-900 transition">Model Context Protocol (MCP)</a></li>
            </ul>
          </div>

          {/* Column 3: Enterprise & Compliance */}
          <div>
            <h4 className="text-xs font-bold text-slate-900 uppercase tracking-wider mb-3">
              Enterprise
            </h4>
            <ul className="space-y-2 text-xs text-slate-600">
              <li><span className="text-slate-700 font-medium">SOC2 Type II Aligned</span></li>
              <li><span className="text-slate-700 font-medium">GDPR & HIPAA DLP Redaction</span></li>
              <li><span className="text-slate-700 font-medium">PostgreSQL RLS Tenant Isolation</span></li>
              <li><span className="text-slate-700 font-medium">FIPS 140-3 Hash Chaining</span></li>
              <li><span className="text-slate-700 font-medium">Sovereign Air-Gapped K8s</span></li>
            </ul>
          </div>
        </div>

        {/* Bottom Baseline */}
        <div className="border-t border-slate-100 mt-12 pt-8 flex flex-col sm:flex-row items-center justify-between text-xs text-slate-500 gap-4">
          <div className="flex items-center gap-4">
            <span>&copy; {new Date().getFullYear()} MIRAGE Assurance Platform. All rights reserved.</span>
            <span className="inline-block w-1 h-1 rounded-full bg-slate-300"></span>
            <span>Charter Specification 3.0</span>
          </div>

          <div className="flex items-center gap-6">
            <button 
              onClick={() => setActiveView('console')} 
              className="hover:text-slate-900 font-medium transition"
            >
              Operator Console
            </button>
            <a href="https://github.com/VedantPanchal23/MIRAGE" target="_blank" rel="noreferrer" className="hover:text-slate-900 transition">
              GitHub Repository
            </a>
            <span className="flex items-center gap-1.5 text-emerald-700 font-medium bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200/50">
              <CheckCircle className="w-3 h-3" />
              All Gates Operational
            </span>
          </div>
        </div>
      </div>
    </footer>
  );
}
