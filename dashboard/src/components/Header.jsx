import React, { useState } from "react";
import { Shield, Activity, Terminal, CreditCard, ChevronDown, Check, UserPlus, Cpu, Zap } from "lucide-react";
import { useAuth } from "../context/AuthContext";

export function Header({ currentView, onViewChange, activeTab, onTabChange, onOpenAuth }) {
  const { tenantId, switchTenant, role, isAuthenticated, logout } = useAuth();
  const [isTenantMenuOpen, setIsTenantMenuOpen] = useState(false);
  const [customTenantInput, setCustomTenantInput] = useState("");

  const [recentTenants, setRecentTenants] = useState(() => {
    try {
      const stored = localStorage.getItem("mirage_recent_tenants");
      return stored ? JSON.parse(stored) : [tenantId];
    } catch {
      return [tenantId];
    }
  });

  const handleSelectTenant = (id) => {
    switchTenant(id);
    setIsTenantMenuOpen(false);
  };

  const handleCustomSubmit = (e) => {
    e.preventDefault();
    if (customTenantInput.trim()) {
      const newId = customTenantInput.trim();
      switchTenant(newId);
      setRecentTenants((prev) => {
        const updated = Array.from(new Set([newId, ...prev])).slice(0, 5);
        try {
          localStorage.setItem("mirage_recent_tenants", JSON.stringify(updated));
        } catch {}
        return updated;
      });
      setCustomTenantInput("");
      setIsTenantMenuOpen(false);
    }
  };

  const isStorefrontView = ["landing", "terms", "privacy", "contact", "404"].includes(currentView);

  return (
    <header className="sticky top-0 z-40 bg-mirage-chassis/95 backdrop-blur-md border-b border-mirage-border text-mirage-text shadow-hud-panel transition-all">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo & Product Brand */}
          <div
            className="flex items-center space-x-3 cursor-pointer group select-none"
            onClick={() => onViewChange("landing")}
            title="MIRAGE Home"
          >
            <div className="relative w-9 h-9 rounded bg-mirage-surface border border-mirage-cyan/40 text-mirage-cyan flex items-center justify-center shadow-hud-glow group-hover:border-mirage-cyan transition-all">
              <Shield className="w-5 h-5 text-mirage-cyan animate-pulse-slow" />
              <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-mirage-cyan animate-ping opacity-75" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <span className="font-display font-bold text-lg tracking-wider text-mirage-text group-hover:text-mirage-cyan transition-colors">
                  MIRAGE
                </span>
                <span className="text-[11px] font-mono text-mirage-cyan/80 font-medium px-1.5 py-0.5 rounded bg-mirage-surface border border-mirage-cyan/20">
                  v3.0
                </span>
              </div>
              <p className="text-[10px] font-mono text-mirage-muted hidden sm:block tracking-wide">
                AI Execution Assurance Platform
              </p>
            </div>
          </div>

          {/* Navigation Links for Storefront */}
          {isStorefrontView ? (
            <nav className="hidden md:flex items-center space-x-7 text-xs font-mono font-medium text-mirage-subtext">
              <button
                type="button"
                onClick={() => {
                  if (currentView !== "landing") {
                    onViewChange("landing");
                    setTimeout(() => window.scrollTo({ top: 0, behavior: "smooth" }), 50);
                  } else {
                    window.scrollTo({ top: 0, behavior: "smooth" });
                  }
                }}
                className={`hover:text-mirage-cyan transition-colors ${currentView === "landing" ? "text-mirage-cyan font-semibold" : ""}`}
              >
                Overview
              </button>
              <button
                type="button"
                onClick={() => {
                  if (currentView !== "landing") {
                    onViewChange("landing");
                    setTimeout(() => {
                      document.getElementById("architecture")?.scrollIntoView({ behavior: "smooth" });
                    }, 100);
                  } else {
                    document.getElementById("architecture")?.scrollIntoView({ behavior: "smooth" });
                  }
                }}
                className="hover:text-mirage-cyan transition-colors"
              >
                Architecture
              </button>
              <button
                type="button"
                onClick={() => {
                  if (currentView !== "landing") {
                    onViewChange("landing");
                    setTimeout(() => {
                      document.getElementById("playground")?.scrollIntoView({ behavior: "smooth" });
                    }, 100);
                  } else {
                    document.getElementById("playground")?.scrollIntoView({ behavior: "smooth" });
                  }
                }}
                className="hover:text-mirage-cyan transition-colors"
              >
                Playground
              </button>
              <button
                type="button"
                onClick={() => {
                  if (currentView !== "landing") {
                    onViewChange("landing");
                    setTimeout(() => {
                      document.getElementById("pricing")?.scrollIntoView({ behavior: "smooth" });
                    }, 100);
                  } else {
                    document.getElementById("pricing")?.scrollIntoView({ behavior: "smooth" });
                  }
                }}
                className="hover:text-mirage-cyan transition-colors"
              >
                Pricing
              </button>
              <button
                type="button"
                onClick={() => onViewChange("contact")}
                className={`hover:text-mirage-cyan transition-colors ${currentView === "contact" ? "text-mirage-cyan font-semibold" : ""}`}
              >
                Contact
              </button>
            </nav>
          ) : (
            <div className="hidden lg:flex items-center space-x-3 text-xs font-mono">
              <div className="flex items-center space-x-2 px-2.5 py-1 rounded bg-mirage-surface border border-mirage-border text-mirage-subtext">
                <span className="w-1.5 h-1.5 rounded-full bg-mirage-emerald animate-pulse" />
                <span className="text-[11px] text-mirage-muted font-mono">EXEC_PLANE:</span>
                <span className="text-mirage-emerald font-semibold text-[11px]">ONLINE [2-PHASE LEASED]</span>
              </div>
              <button
                type="button"
                onClick={() => onViewChange("landing")}
                className="text-xs text-mirage-muted hover:text-mirage-cyan font-mono px-2 py-1 rounded hover:bg-mirage-surface transition-colors"
              >
                &larr; Storefront & Specs
              </button>
            </div>
          )}

          {/* Right Controls */}
          <div className="flex items-center space-x-3">
            {isAuthenticated ? (
              <div className="flex items-center space-x-2">
                <div className="hidden sm:flex items-center space-x-1.5 px-2.5 py-1 text-xs rounded bg-mirage-surface border border-mirage-border text-mirage-subtext">
                  <span className="w-1.5 h-1.5 rounded-full bg-mirage-cyan animate-pulse" />
                  <span className="font-mono text-[11px] font-medium text-mirage-text truncate max-w-[120px]">
                    {tenantId}
                  </span>
                </div>
                {isStorefrontView ? (
                  <button
                    type="button"
                    onClick={() => onViewChange("app")}
                    className="flex items-center space-x-1.5 px-3.5 py-1.5 text-xs font-mono font-bold rounded bg-mirage-cyan text-mirage-void hover:bg-white shadow-hud-glow transition-all"
                  >
                    <span>Operator Console</span>
                    <span>&rarr;</span>
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={logout}
                    className="text-xs font-mono text-mirage-muted hover:text-mirage-crimson px-2 py-1 transition-colors"
                  >
                    Disconnect
                  </button>
                )}
              </div>
            ) : (
              <div className="flex items-center space-x-3 font-mono">
                <button
                  type="button"
                  onClick={onOpenAuth}
                  className="px-3 py-1.5 text-xs font-medium text-mirage-subtext hover:text-mirage-cyan transition-colors"
                >
                  Sign In
                </button>
                <button
                  type="button"
                  onClick={onOpenAuth}
                  className="px-3.5 py-1.5 text-xs font-bold rounded bg-mirage-cyan text-mirage-void hover:bg-white shadow-hud-glow transition-all tracking-tight"
                >
                  Get Started &rarr;
                </button>
              </div>
            )}

            {/* If in app view: Tactical Tenant Switcher Dropdown */}
            {!isStorefrontView && (
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setIsTenantMenuOpen(!isTenantMenuOpen)}
                  className="flex items-center space-x-2 px-2.5 py-1.5 text-xs font-mono rounded bg-mirage-surface hover:bg-mirage-surfaceElevated border border-mirage-border text-mirage-text transition-colors shadow-sm"
                >
                  <span className="text-mirage-muted">TENANT:</span>
                  <span className="text-mirage-cyan font-bold truncate max-w-[100px]">{tenantId}</span>
                  <ChevronDown className="w-3.5 h-3.5 text-mirage-muted" />
                </button>

                {isTenantMenuOpen && (
                  <div className="absolute right-0 mt-2 w-72 bg-mirage-surfaceElevated rounded border border-mirage-borderStrong shadow-hud-panel p-2.5 z-50 font-mono">
                    <div className="text-[10px] font-semibold text-mirage-muted uppercase px-2 py-1 tracking-wider border-b border-mirage-border/60 pb-1 mb-2">
                      ACTIVE TENANT PARTITION (POSTGRESQL RLS)
                    </div>
                    <div className="space-y-1 mb-2">
                      {recentTenants.map((tId) => (
                        <button
                          key={tId}
                          type="button"
                          onClick={() => handleSelectTenant(tId)}
                          className={`w-full flex items-center justify-between px-2.5 py-1.5 text-xs rounded transition text-left border ${
                            tenantId === tId
                              ? "bg-mirage-cyan/10 text-mirage-cyan border-mirage-cyan/30 font-medium"
                              : "hover:bg-mirage-surface text-mirage-subtext border-transparent"
                          }`}
                        >
                          <div>
                            <div className="font-medium">{tId}</div>
                            <div className="text-[10px] text-mirage-muted">
                              {tId === "tenant_default" ? "Standard Cluster Isolation" : "Enterprise Tenant Namespace"}
                            </div>
                          </div>
                          {tenantId === tId && <Check className="w-3.5 h-3.5 text-mirage-cyan" />}
                        </button>
                      ))}
                    </div>

                    <form onSubmit={handleCustomSubmit} className="pt-2 border-t border-mirage-border">
                      <label className="block text-[10px] text-mirage-muted mb-1 px-1">
                        SWITCH TO TENANT ID:
                      </label>
                      <div className="flex space-x-1">
                        <input
                          type="text"
                          value={customTenantInput}
                          onChange={(e) => setCustomTenantInput(e.target.value)}
                          placeholder="tenant_custom"
                          className="w-full text-xs px-2 py-1 bg-mirage-surface rounded border border-mirage-border focus:outline-none focus:border-mirage-cyan font-mono text-mirage-text"
                        />
                        <button
                          type="submit"
                          className="px-2.5 py-1 bg-mirage-cyan text-mirage-void text-xs rounded font-bold hover:bg-white transition"
                        >
                          SET
                        </button>
                      </div>
                    </form>
                  </div>
                )}
              </div>
            )}

            {/* View Action: Upgrade when in app view */}
            {!isStorefrontView && (
              <button
                type="button"
                onClick={() => onTabChange("billing")}
                className="flex items-center space-x-1.5 text-xs font-mono font-medium px-3 py-1.5 rounded bg-mirage-amber/15 text-mirage-amber border border-mirage-amber/30 hover:bg-mirage-amber hover:text-mirage-void shadow-hud-glow-amber transition-all"
              >
                <CreditCard className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">CAPACITY_TIER</span>
              </button>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
