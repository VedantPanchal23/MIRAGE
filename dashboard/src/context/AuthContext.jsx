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
    return localStorage.getItem("mirage_auth_token") || localStorage.getItem("mirage_token") || "";
  });
  const [apiKey, setApiKey] = useState(() => {
    return localStorage.getItem("mirage_api_key") || "";
  });
  const [userEmail, setUserEmail] = useState(() => {
    return localStorage.getItem("mirage_user_email") || "";
  });
  const [isAuthenticated, setIsAuthenticated] = useState(() => {
    const storedToken = localStorage.getItem("mirage_auth_token") || localStorage.getItem("mirage_token");
    const storedKey = localStorage.getItem("mirage_api_key");
    const storedTenant = localStorage.getItem("mirage_tenant_id");
    return Boolean(storedToken || storedKey || (storedTenant && storedTenant !== "tenant_default"));
  });

  useEffect(() => {
    if (tenantId) {
      localStorage.setItem("mirage_tenant_id", tenantId);
    } else {
      localStorage.removeItem("mirage_tenant_id");
    }

    if (userId) {
      localStorage.setItem("mirage_user_id", userId);
    } else {
      localStorage.removeItem("mirage_user_id");
    }

    if (role) {
      localStorage.setItem("mirage_role", role);
    } else {
      localStorage.removeItem("mirage_role");
    }

    if (token) {
      localStorage.setItem("mirage_auth_token", token);
      localStorage.setItem("mirage_token", token);
    } else {
      localStorage.removeItem("mirage_auth_token");
      localStorage.removeItem("mirage_token");
    }

    if (apiKey) {
      localStorage.setItem("mirage_api_key", apiKey);
    } else {
      localStorage.removeItem("mirage_api_key");
    }

    if (userEmail) {
      localStorage.setItem("mirage_user_email", userEmail);
    } else {
      localStorage.removeItem("mirage_user_email");
    }

    setIsAuthenticated(Boolean(token || apiKey || (tenantId && tenantId !== "tenant_default")));
  }, [tenantId, userId, role, token, apiKey, userEmail]);

  const login = (newTenantId, newRole = "admin", newToken = "", newApiKey = "") => {
    setTenantId(newTenantId || "tenant_default");
    setRole(newRole);
    if (newToken) setToken(newToken);
    if (newApiKey) setApiKey(newApiKey);
    setIsAuthenticated(true);
  };

  const logout = () => {
    setToken("");
    setApiKey("");
    setTenantId("tenant_default");
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
        setTenantId,
        userId,
        setUserId,
        role,
        setRole,
        token,
        setToken,
        apiKey,
        setApiKey,
        userEmail,
        setUserEmail,
        isAuthenticated,
        setIsAuthenticated,
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
