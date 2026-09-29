import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import {
  AuthProvider,
  useAuth,
  ROLES,
  PERMISSIONS,
  ROLE_PERMISSIONS,
  parseJwtPayload,
  isTokenExpired,
} from "../AuthContext";
import { getApiToken, onUnauthorized } from "../../api/client";

/**
 * Test helper creating a mock JWT without sensitive secrets or network calls.
 */
function createMockJwt(payload) {
  const header = { alg: "HS256", typ: "JWT" };
  const toBase64Url = (obj) =>
    btoa(unescape(encodeURIComponent(JSON.stringify(obj))))
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");
  return `${toBase64Url(header)}.${toBase64Url(payload)}.mock_test_signature`;
}

// Consumer component to inspect and trigger AuthContext values in tests
function TestConsumer() {
  const {
    isAuthenticated,
    user,
    role,
    tenantId,
    token,
    authError,
    login,
    logout,
    hasPermission,
    hasRole,
  } = useAuth();

  return (
    <div>
      <div data-testid="auth-status">{isAuthenticated ? "authenticated" : "unauthenticated"}</div>
      <div data-testid="user-id">{user?.id || "none"}</div>
      <div data-testid="tenant-id">{tenantId || "none"}</div>
      <div data-testid="user-role">{role || "none"}</div>
      <div data-testid="token-value">{token || "none"}</div>
      <div data-testid="auth-error">{authError || "none"}</div>
      <div data-testid="perm-verify-write">{hasPermission(PERMISSIONS.VERIFY_WRITE) ? "yes" : "no"}</div>
      <div data-testid="perm-dashboard-read">{hasPermission(PERMISSIONS.DASHBOARD_READ) ? "yes" : "no"}</div>
      <div data-testid="perm-alerts-ack">{hasPermission(PERMISSIONS.ALERTS_ACKNOWLEDGE) ? "yes" : "no"}</div>
      <div data-testid="role-operator">{hasRole(ROLES.OPERATOR) ? "yes" : "no"}</div>
      <div data-testid="role-viewer">{hasRole(ROLES.VIEWER) ? "yes" : "no"}</div>
      <div data-testid="role-admin">{hasRole(ROLES.SUPER_ADMIN, ROLES.TENANT_ADMIN) ? "yes" : "no"}</div>

      <button
        data-testid="login-valid"
        onClick={() => {
          const futureExp = Math.floor(Date.now() / 1000) + 3600;
          login(
            createMockJwt({
              sub: "usr_operator_1",
              tenant_id: "tenant_alpha",
              role: "operator",
              exp: futureExp,
            })
          );
        }}
      >
        Login Valid
      </button>

      <button
        data-testid="login-expired"
        onClick={() => {
          const pastExp = Math.floor(Date.now() / 1000) - 3600;
          try {
            login(
              createMockJwt({
                sub: "usr_expired_1",
                tenant_id: "tenant_alpha",
                role: "viewer",
                exp: pastExp,
              })
            );
          } catch {
            // expected rejection
          }
        }}
      >
        Login Expired
      </button>

      <button
        data-testid="login-malformed"
        onClick={() => {
          try {
            login("not-a-valid-jwt");
          } catch {
            // expected rejection
          }
        }}
      >
        Login Malformed
      </button>

      <button data-testid="logout-btn" onClick={() => logout()}>
        Logout
      </button>
    </div>
  );
}

describe("AuthContext & Canonical RBAC", () => {
  beforeEach(() => {
    onUnauthorized(null);
  });

  describe("Canonical Constants & Matrix", () => {
    it("defines exact canonical MIRAGE authorization roles", () => {
      expect(ROLES.SUPER_ADMIN).toBe("super_admin");
      expect(ROLES.TENANT_ADMIN).toBe("tenant_admin");
      expect(ROLES.OPERATOR).toBe("operator");
      expect(ROLES.VIEWER).toBe("viewer");
      expect(ROLES.API_CLIENT).toBe("api_client");
      expect(Object.keys(ROLES).length).toBe(5);
    });

    it("maps canonical permissions according to Security & Access §13.2", () => {
      // Super admin has all permissions
      expect(ROLE_PERMISSIONS[ROLES.SUPER_ADMIN].has(PERMISSIONS.VERIFY_WRITE)).toBe(true);
      expect(ROLE_PERMISSIONS[ROLES.SUPER_ADMIN].has(PERMISSIONS.CONFIG_WRITE)).toBe(true);
      expect(ROLE_PERMISSIONS[ROLES.SUPER_ADMIN].has(PERMISSIONS.CIRCUITS_MANAGE)).toBe(true);

      // Operator can read dashboard, audit, acknowledge alerts, and manage circuits, but NOT write verification or configs
      expect(ROLE_PERMISSIONS[ROLES.OPERATOR].has(PERMISSIONS.DASHBOARD_READ)).toBe(true);
      expect(ROLE_PERMISSIONS[ROLES.OPERATOR].has(PERMISSIONS.ALERTS_ACKNOWLEDGE)).toBe(true);
      expect(ROLE_PERMISSIONS[ROLES.OPERATOR].has(PERMISSIONS.CIRCUITS_MANAGE)).toBe(true);
      expect(ROLE_PERMISSIONS[ROLES.OPERATOR].has(PERMISSIONS.VERIFY_WRITE)).toBe(false);
      expect(ROLE_PERMISSIONS[ROLES.OPERATOR].has(PERMISSIONS.CONFIG_WRITE)).toBe(false);

      // Viewer only has DASHBOARD_READ
      expect(ROLE_PERMISSIONS[ROLES.VIEWER].has(PERMISSIONS.DASHBOARD_READ)).toBe(true);
      expect(ROLE_PERMISSIONS[ROLES.VIEWER].has(PERMISSIONS.ALERTS_ACKNOWLEDGE)).toBe(false);
      expect(ROLE_PERMISSIONS[ROLES.VIEWER].has(PERMISSIONS.VERIFY_WRITE)).toBe(false);

      // API Client has VERIFY_WRITE and VERIFY_READ only
      expect(ROLE_PERMISSIONS[ROLES.API_CLIENT].has(PERMISSIONS.VERIFY_WRITE)).toBe(true);
      expect(ROLE_PERMISSIONS[ROLES.API_CLIENT].has(PERMISSIONS.VERIFY_READ)).toBe(true);
      expect(ROLE_PERMISSIONS[ROLES.API_CLIENT].has(PERMISSIONS.DASHBOARD_READ)).toBe(false);
    });
  });

  describe("JWT Parsing Helpers", () => {
    it("parses valid JWT claims payload correctly", () => {
      const payload = {
        sub: "usr_alice",
        tenant_id: "tenant_wonderland",
        role: "tenant_admin",
        exp: 1800000000,
      };
      const token = createMockJwt(payload);
      const parsed = parseJwtPayload(token);

      expect(parsed.sub).toBe("usr_alice");
      expect(parsed.tenant_id).toBe("tenant_wonderland");
      expect(parsed.role).toBe("tenant_admin");
      expect(parsed.exp).toBe(1800000000);
    });

    it("returns null for malformed tokens", () => {
      expect(parseJwtPayload(null)).toBeNull();
      expect(parseJwtPayload("")).toBeNull();
      expect(parseJwtPayload("invalid")).toBeNull();
      expect(parseJwtPayload("a.b")).toBeNull();
    });

    it("detects expired timestamps accurately", () => {
      const nowSec = Math.floor(Date.now() / 1000);
      expect(isTokenExpired(nowSec - 100)).toBe(true);
      expect(isTokenExpired(nowSec + 100)).toBe(false);
      expect(isTokenExpired(null)).toBe(false);
    });
  });

  describe("AuthProvider Component Lifecycle", () => {
    it("initializes with unauthenticated state when no token is provided", () => {
      render(
        <AuthProvider>
          <TestConsumer />
        </AuthProvider>
      );

      expect(screen.getByTestId("auth-status")).toHaveTextContent("unauthenticated");
      expect(screen.getByTestId("user-id")).toHaveTextContent("none");
      expect(screen.getByTestId("tenant-id")).toHaveTextContent("none");
      expect(screen.getByTestId("user-role")).toHaveTextContent("none");
      expect(screen.getByTestId("token-value")).toHaveTextContent("none");
      expect(getApiToken()).toBeNull();
    });

    it("initializes as authenticated when a valid initialToken is provided", () => {
      const futureExp = Math.floor(Date.now() / 1000) + 3600;
      const initialToken = createMockJwt({
        sub: "user_init",
        tenant_id: "tenant_init",
        role: "viewer",
        exp: futureExp,
      });

      render(
        <AuthProvider initialToken={initialToken}>
          <TestConsumer />
        </AuthProvider>
      );

      expect(screen.getByTestId("auth-status")).toHaveTextContent("authenticated");
      expect(screen.getByTestId("user-id")).toHaveTextContent("user_init");
      expect(screen.getByTestId("tenant-id")).toHaveTextContent("tenant_init");
      expect(screen.getByTestId("user-role")).toHaveTextContent("viewer");
      expect(getApiToken()).toBe(initialToken);
      expect(screen.getByTestId("perm-dashboard-read")).toHaveTextContent("yes");
      expect(screen.getByTestId("perm-verify-write")).toHaveTextContent("no");
    });

    it("handles login with valid token and synchronizes with API client", () => {
      render(
        <AuthProvider>
          <TestConsumer />
        </AuthProvider>
      );

      expect(screen.getByTestId("auth-status")).toHaveTextContent("unauthenticated");

      act(() => {
        screen.getByTestId("login-valid").click();
      });

      expect(screen.getByTestId("auth-status")).toHaveTextContent("authenticated");
      expect(screen.getByTestId("user-id")).toHaveTextContent("usr_operator_1");
      expect(screen.getByTestId("tenant-id")).toHaveTextContent("tenant_alpha");
      expect(screen.getByTestId("user-role")).toHaveTextContent("operator");

      // Verify synchronization with centralized API client
      expect(getApiToken()).not.toBeNull();

      // UX gating checks for operator
      expect(screen.getByTestId("perm-dashboard-read")).toHaveTextContent("yes");
      expect(screen.getByTestId("perm-alerts-ack")).toHaveTextContent("yes");
      expect(screen.getByTestId("perm-verify-write")).toHaveTextContent("no");
      expect(screen.getByTestId("role-operator")).toHaveTextContent("yes");
      expect(screen.getByTestId("role-viewer")).toHaveTextContent("no");
    });

    it("rejects login with expired token", () => {
      render(
        <AuthProvider>
          <TestConsumer />
        </AuthProvider>
      );

      act(() => {
        screen.getByTestId("login-expired").click();
      });

      expect(screen.getByTestId("auth-status")).toHaveTextContent("unauthenticated");
      expect(screen.getByTestId("user-id")).toHaveTextContent("none");
      expect(getApiToken()).toBeNull();
    });

    it("rejects login with malformed token", () => {
      render(
        <AuthProvider>
          <TestConsumer />
        </AuthProvider>
      );

      act(() => {
        screen.getByTestId("login-malformed").click();
      });

      expect(screen.getByTestId("auth-status")).toHaveTextContent("unauthenticated");
      expect(getApiToken()).toBeNull();
    });

    it("clears authentication and API token upon logout", () => {
      render(
        <AuthProvider>
          <TestConsumer />
        </AuthProvider>
      );

      act(() => {
        screen.getByTestId("login-valid").click();
      });
      expect(screen.getByTestId("auth-status")).toHaveTextContent("authenticated");
      expect(getApiToken()).not.toBeNull();

      act(() => {
        screen.getByTestId("logout-btn").click();
      });
      expect(screen.getByTestId("auth-status")).toHaveTextContent("unauthenticated");
      expect(screen.getByTestId("user-id")).toHaveTextContent("none");
      expect(screen.getByTestId("tenant-id")).toHaveTextContent("none");
      expect(getApiToken()).toBeNull();
    });

    it("throws error when useAuth is called outside AuthProvider", () => {
      const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
      expect(() => render(<TestConsumer />)).toThrow("useAuth must be used within an AuthProvider");
      consoleError.mockRestore();
    });
  });
});
