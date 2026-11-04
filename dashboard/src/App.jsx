import React, { useState, useEffect, Suspense, lazy } from "react";
import { Header } from "./components/Header";
import { Navigation } from "./components/Navigation";
import AuthModal from "./components/AuthModal";
import { ShieldCheck, Lock } from "lucide-react";
import { useAuth } from "./context/AuthContext";

// Lazy-loaded Views for Code Splitting & Performance (Requirement 13)
const LandingView = lazy(() => import("./views/LandingView"));
const ContactView = lazy(() => import("./views/ContactView"));
const TermsView = lazy(() => import("./views/TermsView"));
const PrivacyView = lazy(() => import("./views/PrivacyView"));
const NotFoundView = lazy(() => import("./views/NotFoundView"));

const OverviewView = lazy(() => import("./views/OverviewView").then(m => ({ default: m.OverviewView })));
const PlaygroundView = lazy(() => import("./views/PlaygroundView").then(m => ({ default: m.PlaygroundView })));
const ApprovalsView = lazy(() => import("./views/ApprovalsView").then(m => ({ default: m.ApprovalsView })));
const KnowledgeBaseView = lazy(() => import("./views/KnowledgeBaseView").then(m => ({ default: m.KnowledgeBaseView })));
const DeveloperConsoleView = lazy(() => import("./views/DeveloperConsoleView").then(m => ({ default: m.DeveloperConsoleView })));
const SubscriptionBillingView = lazy(() => import("./views/SubscriptionBillingView").then(m => ({ default: m.SubscriptionBillingView })));
const AuditLedgerView = lazy(() => import("./views/AuditLedgerView").then(m => ({ default: m.AuditLedgerView })));
const SettingsView = lazy(() => import("./views/SettingsView").then(m => ({ default: m.SettingsView })));

/**
 * Industrial Tactical Loading Fallback for Suspense Code Splitting
 */
function ViewSkeleton() {
  return (
    <div className="py-24 flex flex-col items-center justify-center space-y-4 font-mono select-none">
      <div className="relative w-12 h-12 flex items-center justify-center">
        <div className="absolute inset-0 rounded-full border-2 border-mirage-cyan/20 border-t-mirage-cyan animate-spin" />
        <div className="w-2 h-2 rounded-full bg-mirage-cyan animate-ping" />
      </div>
      <div className="flex items-center space-x-2 text-xs text-mirage-cyan tracking-wider">
        <span className="w-1.5 h-1.5 rounded-full bg-mirage-cyan animate-pulse" />
        <span>INITIALIZING_ASSURANCE_GATE_VIEW...</span>
      </div>
      <span className="text-[10px] text-mirage-muted">VERIFYING POSTGRESQL RLS & MERKLE ANCHOR</span>
    </div>
  );
}

export default function App() {
  const { isAuthenticated } = useAuth();

  // Routing View: 'landing' | 'app' | 'contact' | 'terms' | 'privacy' | '404'
  const [currentView, setCurrentView] = useState(() => {
    const path = window.location.pathname.toLowerCase();
    if (path === "/contact") return "contact";
    if (path === "/terms") return "terms";
    if (path === "/privacy") return "privacy";
    if (path === "/app") return "app";
    if (path === "/" || path === "") return "landing";
    return "404";
  });

  // App Dashboard Tab: 'overview' | 'playground' | 'approvals' | 'knowledge' | 'developer' | 'billing' | 'audit'
  const [activeTab, setActiveTab] = useState("overview");

  // Auth Modal State
  const [isAuthOpen, setIsAuthOpen] = useState(false);

  // Sync route state with browser history (Requirement 10: Clean URLs & Router redirects)
  const handleViewChange = (newView) => {
    setCurrentView(newView);
    const targetPath = newView === "landing" ? "/" : `/${newView}`;
    if (window.location.pathname !== targetPath) {
      window.history.pushState({ view: newView }, "", targetPath);
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  useEffect(() => {
    if (currentView === "app" && !isAuthenticated) {
      setIsAuthOpen(true);
    }
  }, [currentView, isAuthenticated]);

  useEffect(() => {
    const onPopState = (e) => {
      const path = window.location.pathname.toLowerCase();
      if (path === "/contact") setCurrentView("contact");
      else if (path === "/terms") setCurrentView("terms");
      else if (path === "/privacy") setCurrentView("privacy");
      else if (path === "/app") setCurrentView("app");
      else if (path === "/" || path === "") setCurrentView("landing");
      else setCurrentView("404");
    };

    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  return (
    <div className="min-h-screen bg-mirage-chassis text-mirage-text flex flex-col font-sans bg-grid-pattern selection:bg-mirage-cyan/20 selection:text-mirage-cyan">
      {/* Sticky Header with Dynamic Storefront & App States */}
      <Header
        currentView={currentView}
        onViewChange={handleViewChange}
        activeTab={activeTab}
        onTabChange={(tab) => {
          setActiveTab(tab);
          if (currentView !== "app") handleViewChange("app");
        }}
        onOpenAuth={() => setIsAuthOpen(true)}
      />

      {/* Segmented Pill Navigation (Visible only within the Operator Dashboard when authenticated) */}
      {currentView === "app" && isAuthenticated && (
        <Navigation activeTab={activeTab} onTabChange={setActiveTab} />
      )}

      {/* Main View Surface wrapped in Suspense (Requirement 13) */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 pt-6">
        <Suspense fallback={<ViewSkeleton />}>
          {currentView === "landing" && (
            <LandingView
              onLaunchApp={() => {
                if (isAuthenticated) {
                  handleViewChange("app");
                } else {
                  setIsAuthOpen(true);
                }
              }}
              onOpenAuth={() => setIsAuthOpen(true)}
              onNavigateContact={() => handleViewChange("contact")}
              onNavigateTerms={() => handleViewChange("terms")}
              onNavigatePrivacy={() => handleViewChange("privacy")}
            />
          )}

          {currentView === "contact" && (
            <ContactView
              onNavigateHome={() => handleViewChange("landing")}
              onNavigateApp={() => {
                if (isAuthenticated) {
                  handleViewChange("app");
                } else {
                  setIsAuthOpen(true);
                }
              }}
            />
          )}

          {currentView === "terms" && (
            <TermsView
              onNavigateHome={() => handleViewChange("landing")}
              onNavigateContact={() => handleViewChange("contact")}
            />
          )}

          {currentView === "privacy" && (
            <PrivacyView
              onNavigateHome={() => handleViewChange("landing")}
              onNavigateContact={() => handleViewChange("contact")}
            />
          )}

          {currentView === "404" && (
            <NotFoundView
              onNavigateHome={() => handleViewChange("landing")}
              onNavigateApp={() => {
                if (isAuthenticated) {
                  handleViewChange("app");
                } else {
                  setIsAuthOpen(true);
                }
              }}
            />
          )}

          {currentView === "app" && (
            !isAuthenticated ? (
              <div className="max-w-md mx-auto my-16 p-8 bg-mirage-surface border border-mirage-borderStrong rounded shadow-hud-panel text-center space-y-5 animate-fade-in font-mono relative">
                <div className="absolute top-0 left-0 w-3 h-3 border-t-2 border-l-2 border-mirage-cyan pointer-events-none" />
                <div className="absolute bottom-0 right-0 w-3 h-3 border-b-2 border-r-2 border-mirage-cyan pointer-events-none" />
                <div className="w-12 h-12 rounded bg-mirage-cyan/15 text-mirage-cyan border border-mirage-cyan/40 flex items-center justify-center mx-auto shadow-hud-glow">
                  <Lock className="w-6 h-6" />
                </div>
                <div>
                  <h2 className="text-xl font-bold text-mirage-text uppercase tracking-wide font-display">
                    WORKSPACE AUTHENTICATION REQUIRED
                  </h2>
                  <p className="text-xs text-mirage-muted mt-1.5 leading-relaxed font-sans">
                    The Operator Console enforces strict PostgreSQL Row-Level Security. Authenticate or provision a sandbox workspace to inspect live telemetry.
                  </p>
                </div>
                <div className="pt-2 flex flex-col gap-2.5">
                  <button
                    type="button"
                    onClick={() => setIsAuthOpen(true)}
                    className="w-full py-2.5 bg-mirage-cyan text-mirage-void rounded text-xs font-bold uppercase tracking-wider hover:bg-white shadow-hud-glow transition"
                  >
                    AUTHENTICATE WORKSPACE &rarr;
                  </button>
                  <button
                    type="button"
                    onClick={() => handleViewChange("landing")}
                    className="text-xs text-mirage-muted hover:text-mirage-cyan py-1 transition-colors uppercase font-mono"
                  >
                    &larr; RETURN TO PUBLIC OVERVIEW
                  </button>
                </div>
              </div>
            ) : (
              <div className="space-y-6">
                {activeTab === "overview" && <OverviewView onTabChange={setActiveTab} />}
                {activeTab === "playground" && <PlaygroundView />}
                {activeTab === "approvals" && <ApprovalsView />}
                {activeTab === "knowledge" && <KnowledgeBaseView />}
                {activeTab === "developer" && <DeveloperConsoleView />}
                {activeTab === "billing" && <SubscriptionBillingView />}
                {activeTab === "audit" && <AuditLedgerView />}
                {activeTab === "settings" && <SettingsView />}
              </div>
            )
          )}
        </Suspense>
      </main>

      {/* Auth & Tenant Registration Modal */}
      <AuthModal
        isOpen={isAuthOpen}
        onClose={() => setIsAuthOpen(false)}
        onAuthSuccess={() => {
          handleViewChange("app");
          setActiveTab("overview");
        }}
      />
    </div>
  );
}
