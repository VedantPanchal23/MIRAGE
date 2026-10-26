import React, { useState, useCallback } from "react";
import { ShieldCheck } from "lucide-react";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { Header } from "./components/Header";
import {
  Navigation,
  NAV_ITEMS,
  SECTION_PERMISSIONS,
  isSectionPermitted,
} from "./components/Navigation";
import { AccessDenied } from "./components/AccessDenied";
import { LoginModal } from "./components/LoginModal";
import { OverviewView } from "./views/OverviewView";
import { DriftView } from "./views/DriftView";
import { SessionsView } from "./views/SessionsView";
import { AlertsView } from "./views/AlertsView";
import { LiveStreamView } from "./views/LiveStreamView";
import { ContextAssuranceView } from "./views/ContextAssuranceView";
import { ActionAssuranceView } from "./views/ActionAssuranceView";
import { OutputAssuranceView } from "./views/OutputAssuranceView";
import { OutcomeAssuranceView } from "./views/OutcomeAssuranceView";
import { MultiAgentGovernanceView } from "./views/MultiAgentGovernanceView";
import { TenantsView } from "./views/TenantsView";
import { MCPServersView } from "./views/MCPServersView";
import { AuditIntegrityView } from "./views/AuditIntegrityView";
import { SubscriptionView } from "./views/SubscriptionView";

/**
 * Dashboard application shell managing navigation state, header actions, and view routing.
 *
 * Implements RBAC UX gating derived strictly from authoritative backend route permissions.
 */
export function DashboardShell() {
  const {
    isAuthenticated,
    user,
    role,
    tenantId,
    login,
    logout,
    hasPermission,
    authError,
  } = useAuth();

  const [activeTab, setActiveTab] = useState("overview");
  const [isLoginOpen, setIsLoginOpen] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastRefreshed, setLastRefreshed] = useState("");

  const handleRefresh = useCallback(() => {
    setIsRefreshing(true);
    // OverviewView will update lastRefreshed on completion
    setTimeout(() => setIsRefreshing(false), 500);
  }, []);

  const handleDataLoaded = useCallback((timeStr) => {
    setLastRefreshed(timeStr);
    setIsRefreshing(false);
  }, []);

  // Determine view to render based on activeTab and authoritative permission check
  const renderView = () => {
    if (!isAuthenticated) {
      return (
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="bg-white border border-slate-200 rounded-xl p-8 max-w-md w-full shadow-sm text-center">
            <div className="w-12 h-12 rounded-xl bg-sky-50 text-sky-600 flex items-center justify-center mx-auto mb-4 border border-sky-100">
              <ShieldCheck className="w-6 h-6" />
            </div>
            <h2 className="text-lg font-bold text-slate-900 mb-2">Authentication Required</h2>
            <p className="text-xs text-slate-500 mb-6">
              Please authenticate your enterprise operator session to access real-time assurance gates and telemetry.
            </p>
            <button
              onClick={() => setIsLoginOpen(true)}
              className="w-full py-2.5 px-4 bg-sky-600 hover:bg-sky-700 text-white rounded-lg text-xs font-semibold shadow-xs transition"
            >
              ⚡ Authenticate Operator Session
            </button>
          </div>
        </div>
      );
    }

    // Authoritative RBAC UX Gating: Check whether authenticated user possesses required permissions
    if (isAuthenticated && !isSectionPermitted(activeTab, hasPermission)) {
      const required = SECTION_PERMISSIONS[activeTab] || [];
      const sectionItem = NAV_ITEMS.find((item) => item.id === activeTab);
      const sectionName = sectionItem?.label || activeTab;

      return (
        <AccessDenied
          title={`${sectionName} Access Restricted`}
          requiredPermission={required.join(" or ")}
          userRole={role}
        />
      );
    }

    switch (activeTab) {
      case "overview":
        return (
          <OverviewView
            isRefreshing={isRefreshing}
            onDataLoaded={handleDataLoaded}
          />
        );

      case "subscription":
        return (
          <SubscriptionView
            isRefreshing={isRefreshing}
            onDataLoaded={handleDataLoaded}
          />
        );

      case "context":
        return (
          <ContextAssuranceView
            isRefreshing={isRefreshing}
            onDataLoaded={handleDataLoaded}
          />
        );

      case "actions":
        return (
          <ActionAssuranceView
            isRefreshing={isRefreshing}
            onDataLoaded={handleDataLoaded}
          />
        );

      case "output":
        return (
          <OutputAssuranceView
            isRefreshing={isRefreshing}
            onDataLoaded={handleDataLoaded}
          />
        );

      case "outcomes":
        return (
          <OutcomeAssuranceView
            isRefreshing={isRefreshing}
            onDataLoaded={handleDataLoaded}
          />
        );

      case "multiagent":
        return (
          <MultiAgentGovernanceView
            isRefreshing={isRefreshing}
            onDataLoaded={handleDataLoaded}
          />
        );

      case "drift":
        return (
          <DriftView
            isRefreshing={isRefreshing}
            onDataLoaded={handleDataLoaded}
          />
        );

      case "sessions":
        return (
          <SessionsView
            isRefreshing={isRefreshing}
            onDataLoaded={handleDataLoaded}
          />
        );

      case "stream":
        return <LiveStreamView />;

      case "alerts":
        return (
          <AlertsView
            isRefreshing={isRefreshing}
            onDataLoaded={handleDataLoaded}
          />
        );

      case "tenants":
        return (
          <TenantsView
            isRefreshing={isRefreshing}
            onDataLoaded={handleDataLoaded}
          />
        );

      case "mcp":
        return <MCPServersView />;

      case "audit":
        return (
          <AuditIntegrityView
            isRefreshing={isRefreshing}
            onDataLoaded={handleDataLoaded}
          />
        );

      default:
        return null;
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 flex flex-col font-sans selection:bg-sky-500 selection:text-white">
      {/* Top Header */}
      <Header
        isAuthenticated={isAuthenticated}
        user={user}
        tenantId={tenantId}
        role={role}
        onLogout={logout}
        onOpenLogin={() => setIsLoginOpen(true)}
        onRefresh={handleRefresh}
        isRefreshing={isRefreshing}
        lastRefreshed={lastRefreshed}
      />

      {/* Main Navigation Bar */}
      <Navigation
        activeTab={activeTab}
        onSelectTab={setActiveTab}
        hasPermission={hasPermission}
        isAuthenticated={isAuthenticated}
      />

      {/* Auth Notification Banner (e.g. on 401 session expiration) */}
      {authError && (
        <div
          role="alert"
          className="bg-amber-50 border-b border-amber-200 text-amber-900 text-xs px-6 py-2.5 flex items-center justify-between"
        >
          <span>{authError}</span>
          <button
            onClick={() => setIsLoginOpen(true)}
            className="text-xs underline font-semibold text-amber-800 hover:text-amber-950"
          >
            Authenticate
          </button>
        </div>
      )}

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-6">
        {renderView()}
      </main>

      {/* Application Footer */}
      <footer className="border-t border-slate-200 bg-white px-6 py-4 text-xs text-slate-500 flex flex-wrap justify-between items-center gap-2">
        <span>MIRAGE — CSPIT, CHARUSAT Research Project</span>
        <span>React 18 | Vite | Python 3.12 | OpenTelemetry | pybreaker</span>
      </footer>

      {/* Authentication Dialog */}
      <LoginModal
        isOpen={isLoginOpen}
        onClose={() => setIsLoginOpen(false)}
        onLogin={login}
      />
    </div>
  );
}

/**
 * Root Application component providing the global AuthProvider.
 */
export function App() {
  return (
    <AuthProvider>
      <DashboardShell />
    </AuthProvider>
  );
}

export default App;
