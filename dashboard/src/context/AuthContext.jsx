/**
 * Authentication & Authorization Context for MIRAGE Dashboard.
 *
 * Implements Security & Access §3.2, §13, and PRD FR-DFT-01:
 * - In-memory access token management (Security & Access §3.2: never in localStorage).
 * - React 18 Context providing authentication state and UX identity attributes.
 * - Integration with centralized API client (syncing active Bearer token and 401 handler).
 * - Canonical MIRAGE roles: SUPER_ADMIN, TENANT_ADMIN, OPERATOR, VIEWER, API_CLIENT.
 * - Granular permissions matching `shared.schemas.auth.Permission`.
 * - UX gating helpers: `hasPermission(permission)` and `hasRole(...roles)`.
 *
 * SECURITY BOUNDARIES:
 * The frontend is NOT the security authority.
 * 1. Token decoding on the client is strictly for UX presentation (displaying username,
 *    role badge, tenant label) and client-side proactive expiration detection.
 * 2. Client-supplied tenant identifiers are NEVER authoritative; the backend enforces
 *    authoritative tenant isolation strictly from the cryptographically verified JWT.
 * 3. Client-side role and permission checks are strictly for UX gating (e.g., hiding or
 *    disabling action buttons). Backend authorization checks remain authoritative on every call.
 * 4. Secrets are never hard-coded or logged.
 */

import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useMemo,
} from "react";
import { setApiToken, onUnauthorized } from "../api/client";

/**
 * Canonical enterprise authorization roles (Security & Access §13.1, shared.schemas.auth.Role).
 */
export const ROLES = Object.freeze({
  SUPER_ADMIN: "super_admin",
  TENANT_ADMIN: "tenant_admin",
  OPERATOR: "operator",
  VIEWER: "viewer",
  API_CLIENT: "api_client",
});

/**
 * Granular resource action permissions (Security & Access §13.2, shared.schemas.auth.Permission).
 */
export const PERMISSIONS = Object.freeze({
  VERIFY_WRITE: "verify:write",
  VERIFY_READ: "verify:read",
  DASHBOARD_READ: "dashboard:read",
  CONFIG_WRITE: "config:write",
  AUDIT_READ: "audit:read",
  AUDIT_EXPORT: "audit:export",
  CIRCUITS_MANAGE: "circuits:manage",
  KB_WRITE: "kb:write",
  KB_READ: "kb:read",
  ALERTS_ACKNOWLEDGE: "alerts:acknowledge",
});

/**
 * Role-to-Permissions Access Matrix for UX presentation (Security & Access §13.2).
 */
export const ROLE_PERMISSIONS = Object.freeze({
  [ROLES.SUPER_ADMIN]: new Set(Object.values(PERMISSIONS)),
  [ROLES.TENANT_ADMIN]: new Set([
    PERMISSIONS.VERIFY_WRITE,
    PERMISSIONS.VERIFY_READ,
    PERMISSIONS.DASHBOARD_READ,
    PERMISSIONS.CONFIG_WRITE,
    PERMISSIONS.AUDIT_READ,
    PERMISSIONS.AUDIT_EXPORT,
    PERMISSIONS.KB_WRITE,
    PERMISSIONS.KB_READ,
    PERMISSIONS.ALERTS_ACKNOWLEDGE,
  ]),
  [ROLES.OPERATOR]: new Set([
    PERMISSIONS.DASHBOARD_READ,
    PERMISSIONS.AUDIT_READ,
    PERMISSIONS.CIRCUITS_MANAGE,
    PERMISSIONS.KB_READ,
    PERMISSIONS.ALERTS_ACKNOWLEDGE,
  ]),
  [ROLES.VIEWER]: new Set([
    PERMISSIONS.DASHBOARD_READ,
  ]),
  [ROLES.API_CLIENT]: new Set([
    PERMISSIONS.VERIFY_WRITE,
    PERMISSIONS.VERIFY_READ,
  ]),
});

/**
 * Non-authoritative client-side JWT payload parser.
 *
 * Extracts claims for non-authoritative UX rendering.
 * Does NOT cryptographically verify signatures; cryptographic verification is
 * strictly performed by the backend gateway on every API interaction.
 *
 * @param {string} token - Raw JWT string
 * @returns {object|null} Decoded JSON payload or null if invalid
 */
export function parseJwtPayload(token) {
  if (!token || typeof token !== "string") return null;
  const parts = token.trim().split(".");
  if (parts.length !== 3) return null;

  try {
    const base64Url = parts[1];
    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), "=");
    const jsonPayload = decodeURIComponent(
      atob(padded)
        .split("")
        .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
        .join("")
    );
    return JSON.parse(jsonPayload);
  } catch {
    return null;
  }
}

/**
 * Check if a Unix expiration timestamp (in seconds) has passed.
 * @param {number|null|undefined} exp - Expiration epoch in seconds
 * @returns {boolean}
 */
export function isTokenExpired(exp) {
  if (!exp || typeof exp !== "number") return false;
  return Date.now() >= exp * 1000;
}

export const AuthContext = createContext(null);

/**
 * AuthProvider component managing authentication state in React memory.
 *
 * @param {object} props
 * @param {React.ReactNode} props.children
 * @param {string|null} [props.initialToken=null] - Optional initial token (e.g. for testing)
 */
export function AuthProvider({ children, initialToken = null }) {
  const [token, setToken] = useState(initialToken ? initialToken.trim().replace(/^Bearer\s+/i, "") : null);
  const [authError, setAuthError] = useState(null);

  // Synchronize active in-memory token with the centralized API client
  useEffect(() => {
    setApiToken(token);
  }, [token]);

  // Register 401 Unauthorized handler to reset invalid/expired sessions
  useEffect(() => {
    const handleUnauthorized = () => {
      setToken(null);
      setApiToken(null);
      setAuthError("Session expired or unauthorized. Please authenticate.");
    };
    onUnauthorized(handleUnauthorized);
    return () => onUnauthorized(null);
  }, []);

  // Parse claims for UX presentation
  const parsed = useMemo(() => {
    if (!token) return null;
    const payload = parseJwtPayload(token);
    if (!payload) return null;

    const expired = isTokenExpired(payload.exp);
    return {
      payload,
      expired,
      userId: String(payload.sub || "unknown"),
      tenantId: payload.tenant_id ? String(payload.tenant_id) : null,
      role: (payload.role || "").toLowerCase(),
      exp: payload.exp,
    };
  }, [token]);

  const isAuthenticated = Boolean(token && parsed && !parsed.expired);

  /**
   * Log in with a Bearer JWT access token.
   * Parses the token payload, validates format, checks expiration, and updates state.
   *
   * @param {string} rawToken
   * @returns {object} Parsed UX identity attributes
   */
  const login = useCallback((rawToken) => {
    if (!rawToken || typeof rawToken !== "string") {
      throw new Error("Invalid token: token must be a non-empty string");
    }
    const cleanToken = rawToken.trim().replace(/^Bearer\s+/i, "");
    const payload = parseJwtPayload(cleanToken);

    if (!payload) {
      throw new Error("Invalid token format: could not parse JWT payload");
    }
    if (isTokenExpired(payload.exp)) {
      throw new Error("Token has expired");
    }

    setAuthError(null);
    setToken(cleanToken);
    setApiToken(cleanToken);

    return {
      userId: String(payload.sub || "unknown"),
      tenantId: payload.tenant_id ? String(payload.tenant_id) : null,
      role: (payload.role || "").toLowerCase(),
    };
  }, []);

  /**
   * Clear in-memory token and reset authentication state.
   */
  const logout = useCallback(() => {
    setToken(null);
    setApiToken(null);
    setAuthError(null);
  }, []);

  /**
   * UX permission gating check.
   *
   * @param {string} permission - One of PERMISSIONS
   * @returns {boolean} Whether the current role is configured with this permission
   */
  const hasPermission = useCallback(
    (permission) => {
      if (!isAuthenticated || !parsed?.role) return false;
      const rolePerms = ROLE_PERMISSIONS[parsed.role];
      return rolePerms ? rolePerms.has(permission) : false;
    },
    [isAuthenticated, parsed]
  );

  /**
   * UX role gating check.
   *
   * @param {...string} allowedRoles - One or more roles from ROLES
   * @returns {boolean} Whether the current role matches any of the allowed roles
   */
  const hasRole = useCallback(
    (...allowedRoles) => {
      if (!isAuthenticated || !parsed?.role) return false;
      const normalized = allowedRoles.map((r) => String(r).toLowerCase());
      return normalized.includes(parsed.role);
    },
    [isAuthenticated, parsed]
  );

  const contextValue = useMemo(
    () => ({
      isAuthenticated,
      token,
      user: isAuthenticated
        ? {
            id: parsed.userId,
            tenantId: parsed.tenantId,
            role: parsed.role,
            exp: parsed.exp,
          }
        : null,
      role: isAuthenticated ? parsed.role : null,
      tenantId: isAuthenticated ? parsed.tenantId : null,
      authError,
      login,
      logout,
      hasPermission,
      hasRole,
    }),
    [isAuthenticated, token, parsed, authError, login, logout, hasPermission, hasRole]
  );

  return <AuthContext.Provider value={contextValue}>{children}</AuthContext.Provider>;
}

/**
 * Hook to consume authentication context in dashboard components.
 * @returns {object} AuthContext value
 */
export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
