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
    <header className="sticky top-0 z-50 bg-[#ffffff]/90 backdrop-blur-md border-b border-[#ededed] transition-all">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        
        {/* Left: Microdose-Style Editorial Logo */}
        <div 
          onClick={() => setActiveView('landing')} 
          className="cursor-pointer group flex items-center select-none"
          title="MIRAGE — Execution Assurance Platform"
        >
          <MirageLogo size="md" showText={true} />
        </div>

        {/* Center: Microdose-Style Floating Nav Pill with Numeric Identifiers */}
        {activeView === 'landing' && (
          <nav className="hidden lg:flex items-center gap-1 bg-[#ffffff] border border-[#ededed] shadow-[0px_2px_8px_rgba(14,15,43,0.04)] rounded-full px-2 py-1.5 text-xs text-[#0c152a]">
            <button 
              onClick={() => handleNavClick('hero')}
              className="px-3.5 py-1.5 rounded-full hover:bg-[#ededed] transition-colors flex items-center gap-1.5 font-normal whitespace-nowrap"
            >
              <span>Overview</span>
              <span className="text-[10px] text-[#6b6c71] font-mono">01</span>
            </button>
            <button 
              onClick={() => handleNavClick('five-gates')}
              className="px-3.5 py-1.5 rounded-full hover:bg-[#ededed] transition-colors flex items-center gap-1.5 font-normal whitespace-nowrap"
            >
              <span>The Five Gates</span>
              <span className="text-[10px] text-[#6b6c71] font-mono">02</span>
            </button>
            <button 
              onClick={() => handleNavClick('simulator')}
              className="px-3.5 py-1.5 rounded-full hover:bg-[#ededed] transition-colors flex items-center gap-1.5 font-normal whitespace-nowrap"
            >
              <span>Live Simulator</span>
              <span className="text-[10px] text-[#6b6c71] font-mono">03</span>
            </button>
            <button 
              onClick={() => handleNavClick('architecture')}
              className="px-3.5 py-1.5 rounded-full hover:bg-[#ededed] transition-colors flex items-center gap-1.5 font-normal whitespace-nowrap"
            >
              <span>Architecture</span>
              <span className="text-[10px] text-[#6b6c71] font-mono">04</span>
            </button>
            <button 
              onClick={() => handleNavClick('sdk-docs')}
              className="px-3.5 py-1.5 rounded-full hover:bg-[#ededed] transition-colors flex items-center gap-1.5 font-normal whitespace-nowrap"
            >
              <span>SDK &amp; API</span>
              <span className="text-[10px] text-[#6b6c71] font-mono">05</span>
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
                  className="h-9 px-4 rounded-full bg-[#0c152a] text-white text-xs font-normal hover:bg-[#19171b] transition flex items-center gap-1.5 shadow-2xs"
                >
                  <Terminal className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Operator Console</span>
                </button>
              ) : (
                <button
                  onClick={() => setActiveView('landing')}
                  className="h-9 px-4 rounded-full bg-[#f4f4f6] text-[#0c152a] hover:bg-[#ededed] text-xs font-normal transition border border-[#ededed]"
                >
                  Public Overview
                </button>
              )}

              {/* Single Unified Workspace & Account Menu (Microdose Pill) */}
              <div className="relative" ref={menuRef}>
                <button
                  onClick={() => setShowUserMenu(!showUserMenu)}
                  className="h-9 pl-2 pr-3 rounded-full border border-[#ededed] bg-[#ffffff] hover:bg-[#f4f4f6] text-xs font-normal text-[#0c152a] flex items-center gap-2 transition shadow-2xs"
                  title="Workspace & Account Menu"
                >
                  {/* Avatar Chip */}
                  <div className="w-5 h-5 rounded-full bg-[#0c152a] text-white text-[10px] font-medium flex items-center justify-center">
                    {getInitials(user?.name)}
                  </div>
                  <span className="font-medium text-[#0c152a] hidden sm:inline">
                    {user?.name || 'Vedant'}
                  </span>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-[#f4f4f6] text-[#6b6c71] border border-[#ededed]">
                    {user?.role || 'OPERATOR'}
                  </span>
                  <ChevronDown className="w-3 h-3 text-[#6b6c71]" />
                </button>

                {/* Dropdown Menu in Microdose Clean Style */}
                {showUserMenu && (
                  <div className="absolute right-0 mt-2 w-64 bg-[#ffffff] border border-[#ededed] rounded-[20px] shadow-[0px_10px_30px_rgba(14,15,43,0.08)] py-2 z-50 text-xs animate-in fade-in duration-150">
                    {/* User Identity Header */}
                    <div className="px-4 py-2.5 border-b border-[#ededed] bg-[#f9f9fb]">
                      <div className="font-medium text-[#0c152a] text-xs">
                        {user?.name || 'Vedant'}
                      </div>
                      <div className="text-[11px] text-[#6b6c71] font-mono">
                        {user?.email || 'vedant@mirage.ai'}
                      </div>
                      <div className="mt-1 flex items-center gap-1.5 text-[10px] text-emerald-700 font-normal">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
                        <span>{user?.tenant_name || 'Apex Assurance Corp'}</span>
                      </div>
                    </div>

                    {/* Persona Switcher Section */}
                    <div className="px-3 py-2 border-b border-[#ededed]">
                      <div className="text-[10px] font-mono text-[#6b6c71] uppercase tracking-wider mb-1.5 px-1">
                        Active Profile
                      </div>
                      <div className="space-y-1">
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
                              className={`w-full text-left px-3 py-1.5 rounded-full flex items-center justify-between transition-colors ${
                                isSelected 
                                  ? 'bg-[#ededed] text-[#0c152a] font-medium' 
                                  : 'text-[#6b6c71] hover:bg-[#f4f4f6] hover:text-[#0c152a]'
                              }`}
                            >
                              <div>
                                <div className="text-xs">{p.name} ({p.role})</div>
                                <div className="text-[10px] text-[#6b6c71]">{p.sub}</div>
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
                    <div className="p-1.5">
                      <button
                        onClick={() => {
                          logout();
                          setActiveView('landing');
                          setShowUserMenu(false);
                        }}
                        className="w-full text-left px-3 py-1.5 rounded-full text-rose-600 hover:bg-rose-50 flex items-center gap-2 text-xs font-normal transition"
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
                className="px-4 py-2 text-xs font-normal text-[#6b6c71] hover:text-[#0c152a] transition"
              >
                Sign In
              </button>
              <button
                onClick={() => {
                  loginAsDemo('OPERATOR');
                  setActiveView('console');
                }}
                className="h-9 px-4 rounded-full bg-[#0c152a] text-white text-xs font-normal hover:bg-[#19171b] transition shadow-2xs flex items-center gap-1.5"
              >
                <span>Launch Console</span>
                <ChevronRight className="w-3.5 h-3.5 text-emerald-400" />
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
