import React, { useState } from 'react';
import { Shield, ChevronRight, Activity, Terminal, Lock, LogOut, CheckCircle2, UserCheck } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';

export function Navbar({ activeView, setActiveView, onOpenAuth }) {
  const { user, isAuthenticated, logout, switchRole, loginAsDemo } = useAuth();
  const [showRoleMenu, setShowRoleMenu] = useState(false);

  return (
    <header className="sticky top-0 z-50 bg-white/90 backdrop-blur-md border-b border-slate-200/80">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        {/* Brand Logo */}
        <div 
          onClick={() => setActiveView('landing')} 
          className="flex items-center gap-3 cursor-pointer group"
        >
          <div className="w-9 h-9 rounded-lg bg-slate-900 flex items-center justify-center text-white shadow-sm group-hover:scale-105 transition-transform duration-200">
            <Shield className="w-5 h-5 text-emerald-400" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="font-extrabold text-xl tracking-tight text-slate-900 font-display">
              MIRAGE
            </span>
            <span className="text-xs font-semibold px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200/60">
              3.0
            </span>
          </div>
        </div>

        {/* Public Navigation */}
        <nav className="hidden md:flex items-center gap-7 text-sm font-medium text-slate-600">
          <button 
            onClick={() => setActiveView('landing')}
            className={`transition-colors hover:text-slate-900 ${activeView === 'landing' ? 'text-slate-900 font-semibold' : ''}`}
          >
            Overview
          </button>
          <a 
            href="#five-gates" 
            onClick={() => { if (activeView !== 'landing') setActiveView('landing'); }}
            className="transition-colors hover:text-slate-900"
          >
            The Five Gates
          </a>
          <a 
            href="#simulator" 
            onClick={() => { if (activeView !== 'landing') setActiveView('landing'); }}
            className="transition-colors hover:text-slate-900"
          >
            Live Simulator
          </a>
          <a 
            href="#audit-ledger" 
            onClick={() => { if (activeView !== 'landing') setActiveView('landing'); }}
            className="transition-colors hover:text-slate-900"
          >
            Audit Ledger
          </a>
          <a 
            href="#sdk-docs" 
            onClick={() => { if (activeView !== 'landing') setActiveView('landing'); }}
            className="transition-colors hover:text-slate-900"
          >
            SDK & API
          </a>
          <a 
            href="#architecture" 
            onClick={() => { if (activeView !== 'landing') setActiveView('landing'); }}
            className="transition-colors hover:text-slate-900"
          >
            Architecture
          </a>
        </nav>

        {/* Right Action Cluster */}
        <div className="flex items-center gap-3">
          {/* Live System Status Pill */}
          <div className="hidden lg:flex items-center gap-2 px-2.5 py-1 rounded-full bg-slate-50 border border-slate-200 text-xs font-medium text-slate-600">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
            </span>
            <span>Gateway 99.98%</span>
          </div>

          {isAuthenticated ? (
            <div className="flex items-center gap-2">
              {/* Active Console Toggle */}
              {activeView !== 'console' ? (
                <button
                  onClick={() => setActiveView('console')}
                  className="px-3.5 py-1.5 rounded-lg bg-slate-900 text-white text-xs font-semibold hover:bg-slate-800 transition shadow-sm flex items-center gap-1.5"
                >
                  <Terminal className="w-3.5 h-3.5 text-emerald-400" />
                  Operator Console
                </button>
              ) : (
                <button
                  onClick={() => setActiveView('landing')}
                  className="px-3 py-1.5 rounded-lg border border-slate-200 text-slate-700 text-xs font-medium hover:bg-slate-50 transition"
                >
                  Public Overview
                </button>
              )}

              {/* Role Indicator / Switcher */}
              <div className="relative">
                <button
                  onClick={() => setShowRoleMenu(!showRoleMenu)}
                  className="px-2.5 py-1 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-xs font-medium text-slate-700 flex items-center gap-1.5"
                  title="Switch Role Preview"
                >
                  <UserCheck className="w-3.5 h-3.5 text-slate-500" />
                  <span>{user.role}</span>
                </button>

                {showRoleMenu && (
                  <div className="absolute right-0 mt-2 w-48 bg-white border border-slate-200 rounded-lg shadow-lg py-1 z-50 text-xs">
                    <div className="px-3 py-1.5 font-semibold text-slate-400 uppercase tracking-wider text-[10px]">
                      Simulate Persona
                    </div>
                    {['OPERATOR', 'SUPER_ADMIN', 'AUDITOR'].map((role) => (
                      <button
                        key={role}
                        onClick={() => {
                          switchRole(role);
                          setShowRoleMenu(false);
                        }}
                        className={`w-full text-left px-3 py-1.5 hover:bg-slate-50 flex items-center justify-between ${
                          user.role === role ? 'font-semibold text-slate-900 bg-slate-50' : 'text-slate-600'
                        }`}
                      >
                        {role}
                        {user.role === role && <CheckCircle2 className="w-3 h-3 text-emerald-600" />}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Sign Out */}
              <button
                onClick={logout}
                className="p-1.5 text-slate-400 hover:text-slate-700 rounded-lg hover:bg-slate-100 transition"
                title="Sign out"
              >
                <LogOut className="w-4 h-4" />
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <button
                onClick={() => onOpenAuth('login')}
                className="px-3 py-1.5 text-xs font-medium text-slate-700 hover:text-slate-900 transition"
              >
                Sign In
              </button>
              <button
                onClick={() => {
                  loginAsDemo('OPERATOR');
                  setActiveView('console');
                }}
                className="px-3.5 py-1.5 rounded-lg bg-slate-900 text-white text-xs font-semibold hover:bg-slate-800 transition shadow-sm flex items-center gap-1.5"
              >
                <span>Launch Console</span>
                <ChevronRight className="w-3.5 h-3.5 text-slate-400" />
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
