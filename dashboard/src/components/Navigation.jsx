import React from "react";
import {
  LayoutDashboard,
  PlayCircle,
  CheckSquare,
  BookOpen,
  Code2,
  CreditCard,
  FileCheck2,
} from "lucide-react";

export const NAV_ITEMS = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "playground", label: "Playground", icon: PlayCircle },
  { id: "approvals", label: "Approvals", icon: CheckSquare },
  { id: "knowledge", label: "Knowledge Base", icon: BookOpen },
  { id: "developer", label: "Developer", icon: Code2 },
  { id: "billing", label: "Plans & Billing", icon: CreditCard },
  { id: "audit", label: "Audit Ledger", icon: FileCheck2 },
];

export function Navigation({ activeTab, onTabChange }) {
  return (
    <nav className="border-b border-apple-border bg-apple-bg/70 backdrop-blur-md sticky top-16 z-30">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center space-x-1 py-2 overflow-x-auto no-scrollbar">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => onTabChange(item.id)}
                className={`flex items-center space-x-2 px-3.5 py-1.5 rounded-full text-xs sm:text-sm font-medium transition-all whitespace-nowrap ${
                  isActive
                    ? "bg-apple-surface text-apple-text shadow-apple-sm border border-apple-border"
                    : "text-apple-secondary hover:text-apple-text hover:bg-apple-subtle/80"
                }`}
              >
                <Icon
                  className={`w-4 h-4 transition-colors ${
                    isActive ? "text-apple-blue" : "text-apple-muted"
                  }`}
                />
                <span>{item.label}</span>
              </button>
            );
          })}
        </div>
      </div>
    </nav>
  );
}
