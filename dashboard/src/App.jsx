import React, { useState, useEffect, Suspense, lazy } from "react";
import { Header } from "./components/Header";
import { Navigation } from "./components/Navigation";
import AuthModal from "./components/AuthModal";
import { ShieldCheck } from "lucide-react";

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

/**
 * Apple-Styled Loading Fallback for Suspense Code Splitting
 */
function ViewSkeleton() {
  return (
    <div className="py-20 flex flex-col items-center justify-center space-y-4 animate-pulse">
      <div className="w-10 h-10 rounded-full border-2 border-apple-blue/20 border-t-apple-blue animate-spin" />
      <span className="text-xs text-apple-subtext font-medium">Assembling Assurance View...</span>
    </div>
  );
}

export default function App() {
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
    <div className="min-h-screen bg-apple-bg text-apple-text flex flex-col font-sans">
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

      {/* Segmented Pill Navigation (Visible only within the Operator Dashboard) */}
      {currentView === "app" && (
        <Navigation activeTab={activeTab} onTabChange={setActiveTab} />
      )}

      {/* Main View Surface wrapped in Suspense (Requirement 13) */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 pt-6">
        <Suspense fallback={<ViewSkeleton />}>
          {currentView === "landing" && (
            <LandingView
              onLaunchApp={() => handleViewChange("app")}
              onOpenAuth={() => setIsAuthOpen(true)}
              onNavigateContact={() => handleViewChange("contact")}
              onNavigateTerms={() => handleViewChange("terms")}
              onNavigatePrivacy={() => handleViewChange("privacy")}
            />
          )}

          {currentView === "contact" && (
            <ContactView
              onNavigateHome={() => handleViewChange("landing")}
              onNavigateApp={() => handleViewChange("app")}
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
              onNavigateApp={() => handleViewChange("app")}
            />
          )}

          {currentView === "app" && (
            <div className="space-y-6">
              {activeTab === "overview" && <OverviewView onTabChange={setActiveTab} />}
              {activeTab === "playground" && <PlaygroundView />}
              {activeTab === "approvals" && <ApprovalsView />}
              {activeTab === "knowledge" && <KnowledgeBaseView />}
              {activeTab === "developer" && <DeveloperConsoleView />}
              {activeTab === "billing" && <SubscriptionBillingView />}
              {activeTab === "audit" && <AuditLedgerView />}
            </div>
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
