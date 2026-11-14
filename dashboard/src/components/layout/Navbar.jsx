import React, { useState, useRef, useEffect } from 'react';
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
  ExternalLink,
  Activity,
  SlidersHorizontal,
  Key
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';

export function Navbar({ activeView = 'landing', setActiveView = () => {}, onOpenAuth = () => {} }) {
  const { user, isAuthenticated, logout, switchRole, loginAsDemo } = useAuth();
  const [showUserMenu, setShowUserMenu] = useState(false);
  const menuRef = useRef(null);

  // Close menu when clicking outside
  useEffect(() => {
    function handleClickOutside(event) {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        setShowUserMenu(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

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

  const getInitials = (name) => {
    if (!name) return 'OP';
    const parts = name.split(' ');
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return name.slice(0, 2).toUpperCase();
  };

  return (
    <header className="sticky top-0 z-50 bg-white/90 backdrop-blur-md border-b border-slate-200/80">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-14 flex items-center justify-between">
        
        {/* Left: Brand Identity & Subsystem Context */}
        <div className="flex items-center gap-4">
          <div 
            onClick={() => setActiveView('landing')} 
            className="flex items-center gap-2.5 cursor-pointer group select-none"
            title="MIRAGE 3.0 Platform Overview"
          >
            {/* Minimalist Engineered Logo Mark */}
            <div className="w-7 h-7 rounded-lg bg-slate-900 flex items-center justify-center text-white shadow-xs group-hover:bg-slate-800 transition-colors">
              <Shield className="w-4 h-4 text-emerald-400" />
            </div>
            
            <div className="flex items-center gap-2">
              <span className="font-extrabold text-[15px] tracking-tight text-slate-900 font-display">
                MIRAGE
              </span>
              <span className="text-[10px] font-mono font-semibold px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-200/80">
                v3.0
              </span>
            </div>
          </div>

          {/* Discreet Telemetry Indicator next to brand */}
          <div className="hidden sm:flex items-center gap-1.5 pl-3 border-l border-slate-200 text-[11px] font-mono text-slate-500">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
            </span>
            <span>Gateway 99.98%</span>
          </div>
        </div>

        {/* Center: Editorial Navigation Links (Typographically Uniform, No Gimmick Icons) */}
        {activeView === 'landing' && (
          <nav className="hidden md:flex items-center gap-1 text-[13px] font-medium text-slate-600">
            <button 
              onClick={() => handleNavClick('hero')}
              className="px-3 py-1.5 rounded-md hover:text-slate-900 hover:bg-slate-100/70 transition-colors whitespace-nowrap"
            >
              Overview
            </button>
            <button 
              onClick={() => handleNavClick('five-gates')}
              className="px-3 py-1.5 rounded-md hover:text-slate-900 hover:bg-slate-100/70 transition-colors whitespace-nowrap"
            >
              The Five Gates
            </button>
            <button 
              onClick={() => handleNavClick('simulator')}
              className="px-3 py-1.5 rounded-md hover:text-slate-900 hover:bg-slate-100/70 transition-colors whitespace-nowrap"
            >
              Live Simulator
            </button>
            <button 
              onClick={() => handleNavClick('architecture')}
              className="px-3 py-1.5 rounded-md hover:text-slate-900 hover:bg-slate-100/70 transition-colors whitespace-nowrap"
            >
              Architecture
            </button>
            <button 
              onClick={() => handleNavClick('sdk-docs')}
              className="px-3 py-1.5 rounded-md hover:text-slate-900 hover:bg-slate-100/70 transition-colors whitespace-nowrap"
            >
              SDK &amp; API
            </button>
          </nav>
        )}

        {/* Right: Unified Action & Profile Cluster */}
        <div className="flex items-center gap-3">
          {isAuthenticated ? (
            <div className="flex items-center gap-2.5">
              {/* Primary View Toggle */}
              {activeView !== 'console' ? (
                <button
                  onClick={() => setActiveView('console')}
                  className="h-8 px-3 rounded-lg bg-slate-900 text-white text-xs font-medium hover:bg-slate-800 transition flex items-center gap-1.5 shadow-xs"
                >
                  <Terminal className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Operator Console</span>
                </button>
              ) : (
                <button
                  onClick={() => setActiveView('landing')}
                  className="h-8 px-3 rounded-lg border border-slate-200 text-slate-600 hover:text-slate-900 hover:bg-slate-50 text-xs font-medium transition"
                >
                  Public Overview
                </button>
              )}

              {/* Single Unified Workspace & Account Menu (Replaces clunky separate pills) */}
              <div className="relative" ref={menuRef}>
                <button
                  onClick={() => setShowUserMenu(!showUserMenu)}
                  className="h-8 pl-2 pr-2.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-xs font-medium text-slate-700 flex items-center gap-2 transition shadow-2xs"
                  title="Workspace & Account Menu"
                >
                  {/* Avatar Chip */}
                  <div className="w-5 h-5 rounded-full bg-slate-900 text-white text-[10px] font-bold flex items-center justify-center">
                    {getInitials(user?.name)}
                  </div>
                  <span className="font-semibold text-slate-800 max-w-[100px] truncate hidden sm:inline">
                    {user?.name || 'Sarah Chen'}
                  </span>
                  <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-slate-100 text-slate-600 border border-slate-200 font-medium">
                    {user?.role || 'OPERATOR'}
                  </span>
                  <ChevronDown className="w-3 h-3 text-slate-400 ml-0.5" />
                </button>

                {/* Polished Enterprise Dropdown */}
                {showUserMenu && (
                  <div className="absolute right-0 mt-2 w-64 bg-white border border-slate-200 rounded-xl shadow-xl py-1.5 z-50 text-xs animate-in fade-in duration-150">
                    {/* User Identity Header */}
                    <div className="px-3.5 py-2.5 border-b border-slate-100 bg-slate-50/50">
                      <div className="font-semibold text-slate-900 text-xs truncate">
                        {user?.name || 'Sarah Chen'}
                      </div>
                      <div className="text-[11px] text-slate-500 font-mono truncate">
                        {user?.email || 'sarah@apexassurance.com'}
                      </div>
                      <div className="mt-1.5 flex items-center gap-1.5 text-[10px] text-emerald-700 font-medium">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
                        <span className="truncate">{user?.tenant_name || 'Apex Assurance Corp'}</span>
                      </div>
                    </div>

                    {/* Persona Switcher Section */}
                    <div className="px-3.5 py-2 border-b border-slate-100">
                      <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">
                        Simulate Role Persona
                      </div>
                      <div className="space-y-0.5">
                        {[
                          { role: 'OPERATOR', label: 'Operator', sub: 'Level 3 Autonomy' },
                          { role: 'SUPER_ADMIN', label: 'Super Admin', sub: 'Control Plane' },
                          { role: 'AUDITOR', label: 'Auditor', sub: 'Hash Chain & Ledger' }
                        ].map((p) => (
                          <button
                            key={p.role}
                            onClick={() => {
                              switchRole(p.role);
                              setShowUserMenu(false);
                            }}
                            className={`w-full text-left px-2 py-1.5 rounded-lg flex items-center justify-between transition-colors ${
                              user?.role === p.role 
                                ? 'bg-slate-100 text-slate-900 font-bold' 
                                : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
                            }`}
                          >
                            <div>
                              <div className="text-xs">{p.label}</div>
                              <div className="text-[10px] text-slate-400 font-normal">{p.sub}</div>
                            </div>
                            {user?.role === p.role && (
                              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 shrink-0" />
                            )}
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* Sign Out Action */}
                    <div className="p-1">
                      <button
                        onClick={() => {
                          logout();
                          setActiveView('landing');
                          setShowUserMenu(false);
                        }}
                        className="w-full text-left px-2.5 py-1.5 rounded-lg text-rose-600 hover:bg-rose-50 flex items-center gap-2 text-xs font-medium transition"
                      >
                        <LogOut className="w-3.5 h-3.5" />
                        <span>Sign Out of Console</span>
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <button
                onClick={() => onOpenAuth('login')}
                className="px-3 py-1.5 text-xs font-semibold text-slate-600 hover:text-slate-900 transition"
              >
                Sign In
              </button>
              <button
                onClick={() => {
                  loginAsDemo('OPERATOR');
                  setActiveView('console');
                }}
                className="h-8 px-3 rounded-lg bg-slate-900 text-white text-xs font-medium hover:bg-slate-800 transition shadow-xs flex items-center gap-1"
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
