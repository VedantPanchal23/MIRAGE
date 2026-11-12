import React, { useState, useEffect } from 'react';
import Lenis from 'lenis';
import { AuthProvider, useAuth } from './context/AuthContext';
import { Navbar } from './components/layout/Navbar';
import { Footer } from './components/layout/Footer';
import { LandingPage } from './views/LandingPage';
import { OperatorConsole } from './views/OperatorConsole';
import { AuthModal } from './components/common/AuthModal';

function AppContent() {
  const [activeView, setActiveView] = useState('landing'); // 'landing' | 'console'
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [authMode, setAuthMode] = useState('login');

  // Initialize Lenis smooth scroll for landing page
  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    try {
      const lenis = new Lenis({
        duration: 1.2,
        easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
        orientation: 'vertical',
        smoothWheel: true,
      });

      function raf(time) {
        lenis.raf(time);
        requestAnimationFrame(raf);
      }

      const animId = requestAnimationFrame(raf);

      return () => {
        cancelAnimationFrame(animId);
        lenis.destroy();
      };
    } catch (_) {
      // Graceful fallback for non-browser/test environments
    }
  }, []);

  const handleOpenAuth = (mode = 'login') => {
    setAuthMode(mode);
    setAuthModalOpen(true);
  };

  return (
    <div className="min-h-screen flex flex-col bg-white text-slate-900">
      <Navbar 
        activeView={activeView} 
        setActiveView={setActiveView} 
        onOpenAuth={handleOpenAuth} 
      />

      <main className="flex-1">
        {activeView === 'landing' ? (
          <LandingPage 
            setActiveView={setActiveView} 
            onOpenAuth={handleOpenAuth} 
          />
        ) : (
          <OperatorConsole 
            setActiveView={setActiveView} 
          />
        )}
      </main>

      {activeView === 'landing' && (
        <Footer setActiveView={setActiveView} />
      )}

      <AuthModal
        isOpen={authModalOpen}
        onClose={() => setAuthModalOpen(false)}
        initialMode={authMode}
        onSuccess={() => setActiveView('console')}
      />
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
