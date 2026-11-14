import React, { useState } from 'react';
import { 
  Shield, 
  ChevronRight, 
  Terminal, 
  LogOut, 
  CheckCircle2, 
  UserCheck,
  ChevronDown,
  Layers,
  Sparkles,
  ExternalLink
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';

export function Navbar({ activeView = 'landing', setActiveView = () => {}, onOpenAuth = () => {} }) {
  const { user, isAuthenticated, logout, switchRole, loginAsDemo } = useAuth();
  const [showRoleMenu, setShowRoleMenu] = useState(false);

  const handleNavClick = (anchorId) => {
    if (activeView !== 'landing') {
      setActiveView('landing');
      setTimeout(() => {
        const el = document.getElementById(anchorId);
        if (el) el.scrollIntoView({ behavior: 'smooth' });
      }, 50);
    } else {
      const el = document.getElementById(anchorId);
      if (el) el.scrollIntoView({ behavior: 'smooth' });
    }
  };

  return (
    <header className="sticky top-0 z-40 bg-white/95 backdrop-blur-md border-b border-slate-200">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        {/* Brand Logo & Context Breadcrumb */}
        <div className="flex items-center gap-3">
          <div 
            onClick={() => setActiveView('landing')} 
            className="flex items-center gap-2.5 cursor-pointer group"
            title="Return to Home / Overview"
          >
            <div className="w-8 h-8 rounded-lg bg-slate-900 flex items-center justify-center text-white shadow-sm group-hover:scale-105 transition-transform duration-200">
              <Shield className="w-4 h-4 text-emerald-400" />
            </div>
            <div className="flex items-baseline gap-1.5">
              <span className="font-extrabold text-lg tracking-tight text-slate-900 font-display">
                MIRAGE
              </span>
              <span className="text-[10px] font-bold px-1.5 py-0.2 rounded bg-slate-100 text-slate-700 border border-slate-200">
                3.0
              </span>
            </div>
          </div>

          {activeView === 'console' && (
            <div className="hidden sm:flex items-center gap-2 pl-3 border-l border-slate-200 text-xs">
              <span className="text-slate-400">/</span>
              <span className="font-semibold text-slate-800">Operator Console</span>
            </div>
          )}
        </div>

        {/* Public Navigation Links (Visible on Landing Page or Desktop) */}
        {activeView === 'landing' && (
          <nav className="hidden md:flex items-center gap-4 lg:gap-6 text-xs font-semibold text-slate-600">
            <button 
              onClick={() => handleNavClick('hero')}
              className="hover:text-slate-900 transition-colors py-1 whitespace-nowrap"
            >
              Overview
            </button>
            <button 
              onClick={() => handleNavClick('five-gates')}
              className="hover:text-slate-900 transition-colors py-1 whitespace-nowrap"
            >
              The Five Gates
            </button>
            <button 
              onClick={() => handleNavClick('simulator')}
              className="hover:text-slate-900 transition-colors py-1 flex items-center gap-1 text-slate-900 whitespace-nowrap"
            >
              <Sparkles className="w-3.5 h-3.5 text-emerald-600" />
              <span>Live Simulator</span>
            </button>
            <button 
              onClick={() => handleNavClick('architecture')}
              className="hover:text-slate-900 transition-colors py-1 whitespace-nowrap"
            >
              Architecture
            </button>
            <button 
              onClick={() => handleNavClick('sdk-docs')}
              className="hover:text-slate-900 transition-colors py-1 whitespace-nowrap"
            >
              SDK &amp; API
            </button>
          </nav>
        )}

        {/* Right Action Cluster */}
        <div className="flex items-center gap-2.5">
          {/* Live System Status Pill */}
          <div className="hidden lg:flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-slate-50 border border-slate-200 text-[11px] font-medium text-slate-600">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
            </span>
            <span>Gateway 99.98%</span>
          </div>

          {isAuthenticated ? (
            <div className="flex items-center gap-2">
              {/* Switch View Toggle */}
              {activeView !== 'console' ? (
                <button
                  onClick={() => setActiveView('console')}
                  className="px-3 py-1.5 rounded-lg bg-slate-900 text-white text-xs font-semibold hover:bg-slate-800 transition shadow-sm flex items-center gap-1.5"
                >
                  <Terminal className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Operator Console</span>
                </button>
              ) : (
                <button
                  onClick={() => setActiveView('landing')}
                  className="px-3 py-1.5 rounded-lg border border-slate-200 text-slate-700 text-xs font-semibold hover:bg-slate-50 transition"
                >
                  Public Overview
                </button>
              )}

              {/* Persona Switcher Dropdown */}
              <div className="relative">
                <button
                  onClick={() => setShowRoleMenu(!showRoleMenu)}
                  className="px-2.5 py-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-xs font-semibold text-slate-700 flex items-center gap-1.5 shadow-xs"
                  title="Switch Active Persona"
                >
                  <UserCheck className="w-3.5 h-3.5 text-slate-500" />
                  <span>{user?.role || 'OPERATOR'}</span>
                  <ChevronDown className="w-3 h-3 text-slate-400" />
                </button>

                {showRoleMenu && (
                  <div className="absolute right-0 mt-2 w-48 bg-white border border-slate-200 rounded-xl shadow-xl py-1 z-50 text-xs animate-in fade-in">
                    <div className="px-3 py-1.5 font-bold text-slate-400 uppercase tracking-wider text-[10px]">
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
                          user?.role === role ? 'font-bold text-slate-900 bg-slate-50' : 'text-slate-600'
                        }`}
                      >
                        <span>{role}</span>
                        {user?.role === role && <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Sign Out Button */}
              <button
                onClick={() => {
                  logout();
                  setActiveView('landing');
                }}
                className="p-1.5 text-slate-400 hover:text-slate-700 rounded-lg hover:bg-slate-100 transition"
                title="Sign out of console"
              >
                <LogOut className="w-4 h-4" />
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <button
                onClick={() => onOpenAuth('login')}
                className="px-3 py-1.5 text-xs font-semibold text-slate-700 hover:text-slate-900 transition"
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
