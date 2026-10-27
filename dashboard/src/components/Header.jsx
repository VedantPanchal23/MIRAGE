import React, { useState } from "react";
import { ShieldCheck, Activity, Terminal, CreditCard, ChevronDown, Check } from "lucide-react";
import { useAuth } from "../context/AuthContext";

export function Header({ activeTab, onTabChange }) {
  const { tenantId, switchTenant, role } = useAuth();
  const [isTenantMenuOpen, setIsTenantMenuOpen] = useState(false);
  const [customTenantInput, setCustomTenantInput] = useState("");

  const sampleTenants = [
    { id: "tenant_default", name: "Default Sandbox" },
    { id: "tenant_demo", name: "Acme FinTech Corp" },
    { id: "tenant_enterprise", name: "Apex Global Health" },
  ];

  const handleSelectTenant = (id) => {
    switchTenant(id);
    setIsTenantMenuOpen(false);
  };

  const handleCustomSubmit = (e) => {
    e.preventDefault();
    if (customTenantInput.trim()) {
      switchTenant(customTenantInput.trim());
      setCustomTenantInput("");
      setIsTenantMenuOpen(false);
    }
  };

  return (
    <header className="apple-glass sticky top-0 z-40 border-b border-apple-border transition-all">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo & Product Brand */}
          <div className="flex items-center space-x-3 cursor-pointer" onClick={() => onTabChange("overview")}>
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

          {/* Right Controls: Tenant Switcher, System Health, Operator Badge */}
          <div className="flex items-center space-x-3">
            {/* Live Gateway Indicator */}
            <div className="hidden md:flex items-center space-x-1.5 px-2.5 py-1 rounded-full bg-apple-green/10 border border-apple-green/20 text-xs text-apple-text font-medium">
              <span className="w-2 h-2 rounded-full bg-apple-green animate-pulse" />
              <span>5 Gates Active</span>
            </div>

            {/* Tenant Selector Dropdown */}
            <div className="relative">
              <button
                type="button"
                onClick={() => setIsTenantMenuOpen(!isTenantMenuOpen)}
                className="flex items-center space-x-2 px-3 py-1.5 text-xs font-medium rounded-lg bg-apple-subtle hover:bg-apple-border/50 border border-apple-border transition-colors text-apple-text"
              >
                <span className="text-apple-secondary">Tenant:</span>
                <span className="font-mono font-semibold truncate max-w-[120px]">{tenantId}</span>
                <ChevronDown className="w-3.5 h-3.5 text-apple-secondary" />
              </button>

              {isTenantMenuOpen && (
                <div className="absolute right-0 mt-2 w-64 bg-apple-surface rounded-xl shadow-apple-float border border-apple-border p-2 z-50">
                  <div className="text-[11px] font-semibold text-apple-secondary uppercase px-2 py-1">
                    Select Tenant Workspace
                  </div>
                  <div className="space-y-1 mb-2">
                    {sampleTenants.map((t) => (
                      <button
                        key={t.id}
                        type="button"
                        onClick={() => handleSelectTenant(t.id)}
                        className={`w-full flex items-center justify-between px-2.5 py-1.5 text-xs rounded-lg transition text-left ${
                          tenantId === t.id
                            ? "bg-apple-blue/10 text-apple-blue font-medium"
                            : "hover:bg-apple-subtle text-apple-text"
                        }`}
                      >
                        <div>
                          <div className="font-medium">{t.name}</div>
                          <div className="text-[10px] text-apple-secondary font-mono">{t.id}</div>
                        </div>
                        {tenantId === t.id && <Check className="w-3.5 h-3.5 text-apple-blue" />}
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

            {/* Role Badge */}
            <div className="hidden sm:flex items-center space-x-1 text-xs text-apple-secondary font-medium px-2 py-1 rounded bg-apple-subtle border border-apple-border">
              <span>Role:</span>
              <span className="font-semibold text-apple-text uppercase text-[11px]">{role}</span>
            </div>

            {/* Quick Pricing Upgrade Button */}
            <button
              type="button"
              onClick={() => onTabChange("billing")}
              className="flex items-center space-x-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-apple-blue text-white hover:bg-apple-blueHover shadow-apple-sm transition"
            >
              <CreditCard className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Upgrade</span>
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}
