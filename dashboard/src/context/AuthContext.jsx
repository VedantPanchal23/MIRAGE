import React, { createContext, useContext, useState, useEffect } from 'react';

const AuthContext = createContext(null);

const DEFAULT_DEMO_USER = {
  identity_id: 'usr_vedant',
  name: 'Vedant',
  email: 'vedant@mirage.ai',
  role: 'OPERATOR', // SUPER_ADMIN | OPERATOR | AUDITOR | TENANT_ADMIN
  tenant_id: 'tenant_apex_assurance_corp',
  tenant_name: 'Apex Assurance Corp',
  apiKeyId: 'key_4fe10029c549',
};

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try {
      const saved = localStorage.getItem('mirage_auth_user');
      if (saved) {
        const parsed = JSON.parse(saved);
        if (parsed?.name && (parsed.name.toLowerCase().includes('sarah') || parsed.name.toLowerCase().includes('chen'))) {
          parsed.name = 'Vedant';
          parsed.email = 'vedant@mirage.ai';
          localStorage.setItem('mirage_auth_user', JSON.stringify(parsed));
        }
        return parsed;
      }
      return null;
    } catch {
      return null;
    }
  });

  const [demoMode, setDemoMode] = useState(true);

  useEffect(() => {
    if (user) {
      localStorage.setItem('mirage_auth_user', JSON.stringify(user));
    } else {
      localStorage.removeItem('mirage_auth_user');
    }
  }, [user]);

  const login = (userData) => {
    const active = userData || DEFAULT_DEMO_USER;
    setUser(active);
    return active;
  };

  const loginAsDemo = (role = 'OPERATOR') => {
    const demo = {
      ...DEFAULT_DEMO_USER,
      role,
      name: role === 'SUPER_ADMIN' 
        ? 'Vedant' 
        : role === 'AUDITOR' 
        ? 'Dax' 
        : 'Vedant',
      email: role === 'AUDITOR' ? 'dax@mirage.ai' : 'vedant@mirage.ai',
    };
    setUser(demo);
    setDemoMode(true);
    return demo;
  };

  const logout = () => {
    setUser(null);
  };

  const switchRole = (newRole) => {
    if (!user) return;
    setUser((prev) => ({
      ...prev,
      role: newRole,
      name: newRole === 'AUDITOR' ? 'Dax' : 'Vedant',
      email: newRole === 'AUDITOR' ? 'dax@mirage.ai' : 'vedant@mirage.ai',
    }));
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
