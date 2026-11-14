import React, { useState, useRef, useEffect } from 'react';
import { 
  ChevronRight, 
  Terminal, 
  LogOut, 
  CheckCircle2, 
  ChevronDown
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { MirageLogo } from '../common/MirageLogo';

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
    if (!name) return 'V';
    if (name.toLowerCase().includes('dax')) return 'D';
    if (name.toLowerCase().includes('vedant')) return 'V';
    return name.slice(0, 2).toUpperCase();
  };

  return (
    <header className="sticky top-0 z-50 bg-white/90 backdrop-blur-md border-b border-slate-200/80 shadow-[0_1px_3px_rgba(0,0,0,0.02)] transition-all">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        
        {/* Left: Custom High-Craft Logo Lockup */}
        <div 
          onClick={() => setActiveView('landing')} 
          className="cursor-pointer group flex items-center select-none"
          title="MIRAGE — Execution Assurance Platform"
        >
          <MirageLogo size="md" showText={true} />
        </div>

        {/* Center: Clean Editorial Navigation Links */}
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

        {/* Right: Unified Action & User Profile (Vedant / Dax) */}
        <div className="flex items-center gap-3">
          {isAuthenticated ? (
            <div className="flex items-center gap-2.5">
              {/* Primary View Switcher */}
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

              {/* Single Unified Workspace & Account Menu */}
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
                  <span className="font-semibold text-slate-800 hidden sm:inline">
                    {user?.name || 'Vedant'}
                  </span>
                  <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-slate-100 text-slate-600 border border-slate-200 font-medium">
                    {user?.role || 'OPERATOR'}
                  </span>
                  <ChevronDown className="w-3 h-3 text-slate-400" />
                </button>

                {/* Polished Enterprise Dropdown */}
                {showUserMenu && (
                  <div className="absolute right-0 mt-2 w-64 bg-white border border-slate-200 rounded-xl shadow-xl py-1.5 z-50 text-xs animate-in fade-in duration-150">
                    {/* User Identity Header */}
                    <div className="px-3.5 py-2.5 border-b border-slate-100 bg-slate-50/50">
                      <div className="font-semibold text-slate-900 text-xs">
                        {user?.name || 'Vedant'}
                      </div>
                      <div className="text-[11px] text-slate-500 font-mono">
                        {user?.email || 'vedant@mirage.ai'}
                      </div>
                      <div className="mt-1.5 flex items-center gap-1.5 text-[10px] text-emerald-700 font-medium">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
                        <span>{user?.tenant_name || 'Apex Assurance Corp'}</span>
                      </div>
                    </div>

                    {/* Persona Switcher Section */}
                    <div className="px-3.5 py-2 border-b border-slate-100">
                      <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">
                        Switch Active User
                      </div>
                      <div className="space-y-0.5">
                        {[
                          { role: 'OPERATOR', name: 'Vedant', sub: 'Operator · Level 3 Autonomy' },
                          { role: 'SUPER_ADMIN', name: 'Vedant', sub: 'Super Admin · Control Plane' },
                          { role: 'AUDITOR', name: 'Dax', sub: 'Auditor · Hash Chain & Ledger' }
                        ].map((p) => {
                          const isSelected = user?.role === p.role;
                          return (
                            <button
                              key={p.role}
                              onClick={() => {
                                switchRole(p.role);
                                setShowUserMenu(false);
                              }}
                              className={`w-full text-left px-2 py-1.5 rounded-lg flex items-center justify-between transition-colors ${
                                isSelected 
                                  ? 'bg-slate-100 text-slate-900 font-bold' 
                                  : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
                              }`}
                            >
                              <div>
                                <div className="text-xs font-semibold">{p.name} ({p.role})</div>
                                <div className="text-[10px] text-slate-400 font-normal">{p.sub}</div>
                              </div>
                              {isSelected && (
                                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 shrink-0" />
                              )}
                            </button>
                          );
                        })}
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
                        <span>Sign Out</span>
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
