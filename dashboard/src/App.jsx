import React, { useState, useCallback } from "react";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { Header } from "./components/Header";
import {
  Navigation,
  NAV_ITEMS,
  SECTION_PERMISSIONS,
  isSectionPermitted,
} from "./components/Navigation";
import { AccessDenied } from "./components/AccessDenied";
import { PlaceholderView } from "./components/PlaceholderView";
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

      default:
        return null;
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans selection:bg-sky-500 selection:text-white">
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
          className="bg-amber-950/70 border-b border-amber-800 text-amber-300 text-xs px-6 py-2.5 flex items-center justify-between"
        >
          <span>{authError}</span>
          <button
            onClick={() => setIsLoginOpen(true)}
            className="text-xs underline font-semibold text-white hover:text-amber-200"
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
      <footer className="border-t border-slate-800/80 px-6 py-4 text-xs text-slate-500 flex flex-wrap justify-between items-center gap-2">
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
