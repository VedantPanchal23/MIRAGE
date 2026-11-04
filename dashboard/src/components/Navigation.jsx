import React from "react";
import {
  LayoutDashboard,
  PlayCircle,
  CheckSquare,
  BookOpen,
  Code2,
  CreditCard,
  FileCheck2,
  Settings,
  Shield,
  Activity,
} from "lucide-react";

export const NAV_ITEMS = [
  { id: "overview", label: "Overview", code: "01_SYS", icon: LayoutDashboard },
  { id: "playground", label: "Playground", code: "02_LAB", icon: PlayCircle },
  { id: "approvals", label: "Approvals", code: "03_HITL", icon: CheckSquare },
  { id: "knowledge", label: "Knowledge Base", code: "04_CTX", icon: BookOpen },
  { id: "developer", label: "Developer", code: "05_SDK", icon: Code2 },
  { id: "billing", label: "Plans & Billing", code: "06_SUB", icon: CreditCard },
  { id: "audit", label: "Audit Ledger", code: "07_LED", icon: FileCheck2 },
  { id: "settings", label: "Settings", code: "08_OPS", icon: Settings },
];

export function Navigation({ activeTab, onTabChange }) {
  return (
    <nav className="border-b border-mirage-border bg-mirage-surface/90 backdrop-blur-md sticky top-16 z-30 shadow-md">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center space-x-1.5 py-2.5 overflow-x-auto no-scrollbar">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => onTabChange(item.id)}
                className={`group flex items-center space-x-2 px-3 py-1.5 rounded text-xs font-mono tracking-tight transition-all whitespace-nowrap border ${
                  isActive
                    ? "bg-mirage-border/60 text-mirage-cyan border-mirage-cyan/60 shadow-hud-glow"
                    : "bg-mirage-chassis/60 text-mirage-subtext hover:text-mirage-text hover:bg-mirage-surfaceHover border-mirage-border/50"
                }`}
              >
                <Icon
                  className={`w-3.5 h-3.5 transition-colors ${
                    isActive ? "text-mirage-cyan" : "text-mirage-muted group-hover:text-mirage-subtext"
                  }`}
                />
                <span className="font-medium text-xs font-sans">{item.label}</span>
                <span
                  className={`text-[9px] font-mono px-1 py-0.2 rounded border ${
                    isActive
                      ? "bg-mirage-cyan/10 text-mirage-cyan border-mirage-cyan/30"
                      : "bg-mirage-border/40 text-mirage-muted border-mirage-border/60"
                  }`}
                >
                  {item.code}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </nav>
  );
}
