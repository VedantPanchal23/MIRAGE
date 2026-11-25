import React, { useState } from 'react';
import { AuthProvider, useAuth } from './context/AuthContext';
import { Navbar } from './components/layout/Navbar';
import { OperatorConsole } from './views/OperatorConsole';
import { LandingPage } from './views/LandingPage';
import { AuthModal } from './components/auth/AuthModal';
import { CookieConsent } from './components/legal/CookieConsent';
import { LegalModals } from './components/legal/LegalModals';

function AppContent() {
  const { isAuthenticated, loginAsDemo } = useAuth();
  const [activeView, setActiveView] = useState(() => {
    return isAuthenticated ? 'console' : 'landing';
  });
  const [isAuthModalOpen, setIsAuthModalOpen] = useState(false);
  const [authModalMode, setAuthModalMode] = useState('login');
  const [legalDoc, setLegalDoc] = useState(null);

  const handleOpenAuth = (mode = 'login') => {
    setAuthModalMode(mode);
    setIsAuthModalOpen(true);
  };

  const handleLaunchDemo = (role = 'OPERATOR') => {
    loginAsDemo(role);
    setActiveView('console');
  };

  const handleNavigateView = (view) => {
    if (view === 'console' && !isAuthenticated) {
      handleLaunchDemo('OPERATOR');
      return;
    }
    setActiveView(view);
  };

  return (
    <div className="min-h-screen flex flex-col bg-white text-slate-900">
      <Navbar
        activeView={activeView}
        setActiveView={handleNavigateView}
        onOpenAuth={handleOpenAuth}
      />

      <main className="flex-1">
        {activeView === 'console' && isAuthenticated ? (
          <OperatorConsole setActiveView={setActiveView} />
        ) : (
          <LandingPage
            onOpenAuth={handleOpenAuth}
            onLaunchDemo={handleLaunchDemo}
            onOpenLegal={(doc) => setLegalDoc(doc)}
          />
        )}
      </main>

      <AuthModal
        isOpen={isAuthModalOpen}
        onClose={() => setIsAuthModalOpen(false)}
        initialMode={authModalMode}
        onSuccessfulLogin={() => setActiveView('console')}
      />

      <LegalModals activeDoc={legalDoc} onClose={() => setLegalDoc(null)} />
      <CookieConsent onOpenPrivacy={() => setLegalDoc('privacy')} />
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  );
}
