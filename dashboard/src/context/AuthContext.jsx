import React, { createContext, useContext, useState, useEffect } from "react";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [tenantId, setTenantId] = useState(() => {
    return localStorage.getItem("mirage_tenant_id") || "tenant_default";
  });
  const [userId, setUserId] = useState(() => {
    return localStorage.getItem("mirage_user_id") || "user_admin";
  });
  const [role, setRole] = useState(() => {
    return localStorage.getItem("mirage_role") || "admin";
  });
  const [token, setToken] = useState(() => {
    return localStorage.getItem("mirage_auth_token") || "dev_sandbox_bearer_token";
  });
  const [isAuthenticated, setIsAuthenticated] = useState(true);

  useEffect(() => {
    localStorage.setItem("mirage_tenant_id", tenantId);
    localStorage.setItem("mirage_user_id", userId);
    localStorage.setItem("mirage_role", role);
    if (token) {
      localStorage.setItem("mirage_auth_token", token);
    } else {
      localStorage.removeItem("mirage_auth_token");
    }
  }, [tenantId, userId, role, token]);

  const login = (newTenantId, newRole = "admin", newToken = "dev_sandbox_bearer_token") => {
    setTenantId(newTenantId || "tenant_default");
    setRole(newRole);
    setToken(newToken);
    setIsAuthenticated(true);
  };

  const logout = () => {
    setToken("");
    setIsAuthenticated(false);
  };

  const switchTenant = (newTenantId) => {
    if (newTenantId && newTenantId.trim()) {
      setTenantId(newTenantId.trim());
    }
  };

  return (
    <AuthContext.Provider
      value={{
        tenantId,
        userId,
        role,
        token,
        isAuthenticated,
        login,
        logout,
        switchTenant,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
