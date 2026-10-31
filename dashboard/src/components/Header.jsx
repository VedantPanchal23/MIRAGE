import React, { useState } from "react";
import { ShieldCheck, Activity, Terminal, CreditCard, ChevronDown, Check, UserPlus } from "lucide-react";
import { useAuth } from "../context/AuthContext";

export function Header({ currentView, onViewChange, activeTab, onTabChange, onOpenAuth }) {
  const { tenantId, switchTenant, role } = useAuth();
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
    <header className="apple-glass sticky top-0 z-40 border-b border-apple-border transition-all">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo & Product Brand */}
          <div
            className="flex items-center space-x-3 cursor-pointer"
            onClick={() => onViewChange("landing")}
            title="MIRAGE Home"
          >
            <div className="w-9 h-9 rounded-xl bg-apple-text text-white flex items-center justify-center shadow-apple-sm">
              <ShieldCheck className="w-5 h-5 text-white" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <span className="font-semibold text-lg tracking-tight text-apple-text">MIRAGE</span>
                <span className="text-[10px] uppercase font-bold tracking-wider px-1.5 py-0.5 rounded-full bg-apple-blue/10 text-apple-blue border border-apple-blue/20">
                  3.0 SaaS
                </span>
              </div>
              <p className="text-[11px] text-apple-secondary hidden sm:block font-normal -mt-0.5">
                AI Execution Assurance Platform
              </p>
            </div>
          </div>

          {/* Navigation Links for Storefront */}
          {isStorefrontView ? (
            <nav className="hidden md:flex items-center space-x-6 text-xs font-medium text-apple-secondary">
              <button
                type="button"
                onClick={() => onViewChange("landing")}
                className={`hover:text-apple-text transition-colors ${currentView === "landing" ? "text-apple-blue font-semibold" : ""}`}
              >
                Overview
              </button>
              <button
                type="button"
                onClick={() => onViewChange("contact")}
                className={`hover:text-apple-text transition-colors ${currentView === "contact" ? "text-apple-blue font-semibold" : ""}`}
              >
                Enterprise Inquiries
              </button>
              <button
                type="button"
                onClick={() => onViewChange("terms")}
                className={`hover:text-apple-text transition-colors ${currentView === "terms" ? "text-apple-blue font-semibold" : ""}`}
              >
                Terms
              </button>
              <button
                type="button"
                onClick={() => onViewChange("privacy")}
                className={`hover:text-apple-text transition-colors ${currentView === "privacy" ? "text-apple-blue font-semibold" : ""}`}
              >
                Privacy
              </button>
            </nav>
          ) : (
            <div className="hidden lg:flex items-center space-x-2">
              <button
                type="button"
                onClick={() => onViewChange("landing")}
                className="text-xs text-apple-secondary hover:text-apple-blue font-medium px-2 py-1 rounded hover:bg-apple-subtle transition-colors"
              >
                &larr; Storefront & Pricing
              </button>
            </div>
          )}

          {/* Right Controls */}
          <div className="flex items-center space-x-3">
            {/* Live Gateway Indicator */}
            <div className="hidden sm:flex items-center space-x-1.5 px-2.5 py-1 rounded-full bg-apple-green/10 border border-apple-green/20 text-xs text-apple-text font-medium">
              <span className="w-2 h-2 rounded-full bg-apple-green animate-pulse" />
              <span>5 Gates Active</span>
            </div>

            {/* Auth / Account Registration Button */}
            <button
              type="button"
              onClick={onOpenAuth}
              className="flex items-center space-x-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-apple-subtle hover:bg-apple-border/50 border border-apple-border transition-colors text-apple-text"
            >
              <UserPlus className="w-3.5 h-3.5 text-apple-secondary" />
              <span className="hidden sm:inline">Workspace Sign In</span>
            </button>

            {/* If in app view: Tenant Switcher Dropdown */}
            {!isStorefrontView && (
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setIsTenantMenuOpen(!isTenantMenuOpen)}
                  className="flex items-center space-x-2 px-3 py-1.5 text-xs font-medium rounded-lg bg-apple-subtle hover:bg-apple-border/50 border border-apple-border transition-colors text-apple-text"
                >
                  <span className="text-apple-secondary">Tenant:</span>
                  <span className="font-mono font-semibold truncate max-w-[100px]">{tenantId}</span>
                  <ChevronDown className="w-3.5 h-3.5 text-apple-secondary" />
                </button>

                {isTenantMenuOpen && (
                  <div className="absolute right-0 mt-2 w-64 bg-apple-surface rounded-xl shadow-apple-float border border-apple-border p-2 z-50">
                    <div className="text-[11px] font-semibold text-apple-secondary uppercase px-2 py-1">
                      Active Workspace
                    </div>
                    <div className="space-y-1 mb-2">
                      {recentTenants.map((tId) => (
                        <button
                          key={tId}
                          type="button"
                          onClick={() => handleSelectTenant(tId)}
                          className={`w-full flex items-center justify-between px-2.5 py-1.5 text-xs rounded-lg transition text-left ${
                            tenantId === tId
                              ? "bg-apple-blue/10 text-apple-blue font-medium"
                              : "hover:bg-apple-subtle text-apple-text"
                          }`}
                        >
                          <div>
                            <div className="font-medium font-mono">{tId}</div>
                            <div className="text-[10px] text-apple-secondary">
                              {tId === "tenant_default" ? "Default Sandbox" : "Registered Tenant"}
                            </div>
                          </div>
                          {tenantId === tId && <Check className="w-3.5 h-3.5 text-apple-blue" />}
                        </button>
                      ))}
                    </div>

                    <form onSubmit={handleCustomSubmit} className="pt-2 border-t border-apple-border">
                      <label className="block text-[10px] text-apple-secondary mb-1 px-1">
                        Or custom Tenant ID:
                      </label>
                      <div className="flex space-x-1">
                        <input
                          type="text"
                          value={customTenantInput}
                          onChange={(e) => setCustomTenantInput(e.target.value)}
                          placeholder="tenant_custom"
                          className="w-full text-xs px-2 py-1 bg-apple-subtle rounded border border-apple-border focus:outline-none focus:border-apple-blue font-mono"
                        />
                        <button
                          type="submit"
                          className="px-2.5 py-1 bg-apple-text text-white text-xs rounded font-medium hover:bg-black transition"
                        >
                          Set
                        </button>
                      </div>
                    </form>
                  </div>
                )}
              </div>
            )}

            {/* View Switching CTA: Launch App vs View Storefront */}
            {isStorefrontView ? (
              <button
                type="button"
                onClick={() => onViewChange("app")}
                className="flex items-center space-x-1.5 text-xs font-medium px-3.5 py-1.5 rounded-lg bg-apple-blue text-white hover:bg-apple-blueHover shadow-apple-sm transition"
              >
                <span>Operator Dashboard</span>
                <span>&rarr;</span>
              </button>
            ) : (
              <button
                type="button"
                onClick={() => onTabChange("billing")}
                className="flex items-center space-x-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-apple-blue text-white hover:bg-apple-blueHover shadow-apple-sm transition"
              >
                <CreditCard className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">Upgrade</span>
              </button>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
