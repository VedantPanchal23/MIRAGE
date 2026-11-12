import React, { createContext, useContext, useState, useEffect } from 'react';

const AuthContext = createContext(null);

const DEFAULT_DEMO_USER = {
  identity_id: 'usr_sarah_chen',
  name: 'Sarah Chen',
  email: 's.chen@apex-assurance.io',
  role: 'OPERATOR', // SUPER_ADMIN | OPERATOR | AUDITOR | TENANT_ADMIN
  tenant_id: 'tenant_apex_assurance_corp',
  tenant_name: 'Apex Assurance Corp',
  apiKeyId: 'key_4fe10029c549',
};

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try {
      const saved = localStorage.getItem('mirage_auth_user');
      return saved ? JSON.parse(saved) : null;
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
      name: role === 'SUPER_ADMIN' ? 'Marcus Vance (SecOps)' : role === 'AUDITOR' ? 'Elena Rostova (Compliance)' : 'Sarah Chen (Operator)',
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
