import React, { createContext, useContext, useState, useEffect } from 'react';

const AuthContext = createContext(null);

const DEFAULT_DEMO_USER = {
  identity_id: 'usr_vedant',
  name: 'Vedant',
  email: 'vedant@mirage.ai',
  role: 'OPERATOR',
  tenant_id: 'tenant_apex_assurance_corp',
  tenant_name: 'Apex Assurance Corp',
  apiKeyId: 'key_4fe10029c549',
  isDemo: true,
};

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try {
      const saved = localStorage.getItem('mirage_auth_user');
      if (saved) {
        const parsed = JSON.parse(saved);
        if (parsed && !parsed.isDemo && !parsed.token && !parsed.access_token && !parsed.apiKey && !parsed.api_key) {
          localStorage.removeItem('mirage_auth_user');
          localStorage.removeItem('mirage_demo_mode');
          return null;
        }
        return parsed;
      }
      return null;
    } catch {
      return null;
    }
  });

  const [demoMode, setDemoMode] = useState(() => {
    try {
      const saved = localStorage.getItem('mirage_auth_user');
      if (saved) {
        const parsed = JSON.parse(saved);
        return Boolean(parsed?.isDemo);
      }
      return localStorage.getItem('mirage_demo_mode') === 'true';
    } catch {
      return false;
    }
  });

  const _persistSession = (nextUser) => {
    try {
      if (nextUser) {
        localStorage.setItem('mirage_auth_user', JSON.stringify(nextUser));
        localStorage.setItem('mirage_demo_mode', nextUser.isDemo ? 'true' : 'false');
      } else {
        localStorage.removeItem('mirage_auth_user');
        localStorage.removeItem('mirage_demo_mode');
      }
    } catch {
      // ignore storage quota errors
    }
  };

  useEffect(() => {
    _persistSession(user);
  }, [user]);

  const login = (userData) => {
    const active = { ...(userData || DEFAULT_DEMO_USER), isDemo: Boolean(userData?.isDemo) };
    _persistSession(active);
    setUser(active);
    setDemoMode(Boolean(active.isDemo));
    return active;
  };

  const loginAsDemo = (role = 'OPERATOR') => {
    const demo = {
      ...DEFAULT_DEMO_USER,
      role,
      name: role === 'AUDITOR' ? 'Dax' : 'Vedant',
      email: role === 'AUDITOR' ? 'dax@mirage.ai' : 'vedant@mirage.ai',
      isDemo: true,
    };
    _persistSession(demo);
    setUser(demo);
    setDemoMode(true);
    return demo;
  };

  const logout = () => {
    _persistSession(null);
    setUser(null);
    setDemoMode(false);
  };

  const switchRole = (newRole) => {
    if (!user || !user.isDemo) return;
    setUser((prev) => {
      const next = {
        ...prev,
        role: newRole,
        name: newRole === 'AUDITOR' ? 'Dax' : 'Vedant',
        email: newRole === 'AUDITOR' ? 'dax@mirage.ai' : 'vedant@mirage.ai',
      };
      _persistSession(next);
      return next;
    });
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        demoMode,
        login,
        loginAsDemo,
        logout,
        switchRole,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return ctx;
}
