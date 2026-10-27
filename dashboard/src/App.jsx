import React, { useState } from "react";
import { Header } from "./components/Header";
import { Navigation } from "./components/Navigation";
import { OverviewView } from "./views/OverviewView";
import { PlaygroundView } from "./views/PlaygroundView";
import { ApprovalsView } from "./views/ApprovalsView";
import { KnowledgeBaseView } from "./views/KnowledgeBaseView";
import { DeveloperConsoleView } from "./views/DeveloperConsoleView";
import { SubscriptionBillingView } from "./views/SubscriptionBillingView";
import { AuditLedgerView } from "./views/AuditLedgerView";
import { ShieldCheck } from "lucide-react";

export default function App() {
  const [activeTab, setActiveTab] = useState("overview");

  return (
    <div className="min-h-screen bg-apple-bg text-apple-text flex flex-col font-sans">
      {/* Apple Frosted Sticky Header */}
      <Header activeTab={activeTab} onTabChange={setActiveTab} />

      {/* Segmented Pill Navigation */}
      <Navigation activeTab={activeTab} onTabChange={setActiveTab} />

      {/* Main Content Surface */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 pt-8">
        {activeTab === "overview" && <OverviewView onTabChange={setActiveTab} />}
        {activeTab === "playground" && <PlaygroundView />}
        {activeTab === "approvals" && <ApprovalsView />}
        {activeTab === "knowledge" && <KnowledgeBaseView />}
        {activeTab === "developer" && <DeveloperConsoleView />}
        {activeTab === "billing" && <SubscriptionBillingView />}
        {activeTab === "audit" && <AuditLedgerView />}
      </main>

      {/* Apple-Clean Footer */}
      <footer className="border-t border-apple-border bg-apple-surface/60 backdrop-blur-sm py-8 mt-auto">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-apple-secondary">
          <div className="flex items-center space-x-2">
            <ShieldCheck className="w-4 h-4 text-apple-blue" />
            <span>
              MIRAGE 3.0 Commercial SaaS • Control AI Before It Acts. Verify AI After It Acts.
            </span>
          </div>

          <div className="flex items-center space-x-6 text-[11px] text-apple-muted font-medium">
            <span>Fail-Closed PostgreSQL RLS</span>
            <span>•</span>
            <span>Cryptographic Fencing</span>
            <span>•</span>
            <span>Razorpay & Stripe Ready</span>
            <span>•</span>
            <span>© 2026 MIRAGE</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
