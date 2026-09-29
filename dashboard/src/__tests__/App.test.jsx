import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { App, DashboardShell } from "../App";
import { AuthProvider } from "../context/AuthContext";
import * as api from "../api";

vi.mock("../api", () => ({
  getDashboardStats: vi.fn(),
  getHealth: vi.fn(),
  getDriftReport: vi.fn(),
  getDashboardSessions: vi.fn(),
  getSessionById: vi.fn(),
  getAlerts: vi.fn(),
  acknowledgeAlert: vi.fn(),
  setApiToken: vi.fn(),
  getApiToken: vi.fn(),
  onUnauthorized: vi.fn(),
}));

/**
 * Helper generating a mock JWT token.
 */
function createMockJwt(payload) {
  const header = { alg: "HS256", typ: "JWT" };
  const toBase64Url = (obj) =>
    btoa(unescape(encodeURIComponent(JSON.stringify(obj))))
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");
  return `${toBase64Url(header)}.${toBase64Url(payload)}.mock_sig`;
}

describe("Dashboard Shell & Application Integration (App.test.jsx)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getHealth.mockResolvedValue({ circuits: {} });
    api.getDashboardStats.mockResolvedValue({
      total_requests: 500,
      average_hrs: 0.08,
      correction_rate: 0.02,
      tier_counts: { LOW: 450, MEDIUM: 40, HIGH: 8, CRITICAL: 2 },
    });
    api.getDriftReport.mockResolvedValue({
      tenant_id: "default",
      days: 30,
      drift_report: {
        psi: 0.024,
        ks_statistic: 0.12,
        ks_pvalue: 0.5,
        status: "stable",
        alert_triggered: false,
        alert_reason: null,
        baseline_sample_count: 500,
        current_sample_count: 500,
        baseline_mean_hrs: 0.08,
        current_mean_hrs: 0.08,
        rolling_7d_delta: 0.0,
        bin_proportions_baseline: [],
        bin_proportions_current: [],
      },
      time_series: [],
    });
    api.getDashboardSessions.mockResolvedValue({
      total: 1,
      page: 1,
      page_size: 10,
      items: [
        {
          session_id: "sess_mock_01",
          tenant_id: "default",
          model_id: "gpt-4o",
          hrs_score: 0.05,
          risk_tier: "LOW",
          claims_count: 2,
          correction_applied: false,
          created_at: "2026-09-28T12:00:00Z",
        },
      ],
    });
    api.getSessionById.mockResolvedValue({
      session_id: "sess_mock_01",
      tenant_id: "default",
      model_id: "gpt-4o",
      hrs_score: 0.05,
      risk_tier: "LOW",
      claims: [],
      signal_attribution: { rav: 0.02, scs: 0.01, nli: 0.02, ics: 0.0 },
    });
    api.getAlerts.mockResolvedValue({
      tenant_id: "default",
      total_alerts: 0,
      active_alerts: 0,
      alerts: [],
    });
  });

  it("renders the navigation shell with header, navigation bar, and footer", async () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "MIRAGE" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Dashboard Sections" })).toBeInTheDocument();
    expect(screen.getByText(/IIIT Bangalore CTRI-DG Research Project/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(api.getDashboardStats).toHaveBeenCalled();
    });
  });

  it("switches views when navigation tabs are clicked", async () => {
    render(<App />);

    // Default tab is Overview
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "System Overview & Telemetry" })).toBeInTheDocument();
    });

    // Switch to Drift tab -> Renders DriftView
    fireEvent.click(screen.getByRole("tab", { name: /drift/i }));
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Longitudinal Drift & Stability Analysis" })).toBeInTheDocument();
    });

    // Switch to Sessions tab -> Renders SessionsView
    fireEvent.click(screen.getByRole("tab", { name: /sessions/i }));
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Sessions Inspector & TreeSHAP Attribution" })).toBeInTheDocument();
    });

    // Switch to Alerts tab -> Renders AlertsView
    fireEvent.click(screen.getByRole("tab", { name: /alerts/i }));
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Operator Alerts & Operational Events" })).toBeInTheDocument();
    });
  });

  describe("Canonical RBAC UX Gating Across All 5 Canonical Roles", () => {
    it("SUPER_ADMIN: all 5 tabs enabled based on full permissions", async () => {
      const token = createMockJwt({
        sub: "usr_super_admin",
        tenant_id: "tenant_admin_corp",
        role: "super_admin",
        exp: Math.floor(Date.now() / 1000) + 3600,
      });

      render(
        <AuthProvider initialToken={token}>
          <DashboardShell />
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByRole("heading", { name: "System Overview & Telemetry" })).toBeInTheDocument();
      });

      // Role SUPER_ADMIN possesses DASHBOARD_READ, VERIFY_READ, AUDIT_READ, VERIFY_WRITE
      expect(screen.getByRole("tab", { name: /overview/i })).not.toBeDisabled();
      expect(screen.getByRole("tab", { name: /drift/i })).not.toBeDisabled();
      expect(screen.getByRole("tab", { name: /sessions/i })).not.toBeDisabled();
      expect(screen.getByRole("tab", { name: /live stream/i })).not.toBeDisabled();
      expect(screen.getByRole("tab", { name: /alerts/i })).not.toBeDisabled();
    });

    it("TENANT_ADMIN: all 5 tabs enabled based on tenant admin permissions", async () => {
      const token = createMockJwt({
        sub: "usr_tenant_admin",
        tenant_id: "tenant_enterprise",
        role: "tenant_admin",
        exp: Math.floor(Date.now() / 1000) + 3600,
      });

      render(
        <AuthProvider initialToken={token}>
          <DashboardShell />
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByRole("heading", { name: "System Overview & Telemetry" })).toBeInTheDocument();
      });

      // Role TENANT_ADMIN possesses DASHBOARD_READ, VERIFY_READ, AUDIT_READ, VERIFY_WRITE
      expect(screen.getByRole("tab", { name: /overview/i })).not.toBeDisabled();
      expect(screen.getByRole("tab", { name: /drift/i })).not.toBeDisabled();
      expect(screen.getByRole("tab", { name: /sessions/i })).not.toBeDisabled();
      expect(screen.getByRole("tab", { name: /live stream/i })).not.toBeDisabled();
      expect(screen.getByRole("tab", { name: /alerts/i })).not.toBeDisabled();
    });

    it("OPERATOR: overview, drift, sessions, alerts enabled; stream disabled (lacks VERIFY_WRITE)", async () => {
      const token = createMockJwt({
        sub: "usr_operator",
        tenant_id: "tenant_ops",
        role: "operator",
        exp: Math.floor(Date.now() / 1000) + 3600,
      });

      render(
        <AuthProvider initialToken={token}>
          <DashboardShell />
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByRole("heading", { name: "System Overview & Telemetry" })).toBeInTheDocument();
      });

      // OPERATOR possesses DASHBOARD_READ (overview, drift, alerts) and AUDIT_READ (sessions)
      expect(screen.getByRole("tab", { name: /overview/i })).not.toBeDisabled();
      expect(screen.getByRole("tab", { name: /drift/i })).not.toBeDisabled();
      expect(screen.getByRole("tab", { name: /sessions/i })).not.toBeDisabled();
      expect(screen.getByRole("tab", { name: /alerts/i })).not.toBeDisabled();

      // OPERATOR lacks VERIFY_WRITE -> stream tab disabled
      expect(screen.getByRole("tab", { name: /live stream/i })).toBeDisabled();
    });

    it("VIEWER: overview, drift, alerts enabled; stream and sessions disabled", async () => {
      const token = createMockJwt({
        sub: "usr_viewer_9",
        tenant_id: "tenant_corp",
        role: "viewer",
        exp: Math.floor(Date.now() / 1000) + 3600,
      });

      render(
        <AuthProvider initialToken={token}>
          <DashboardShell />
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByRole("heading", { name: "System Overview & Telemetry" })).toBeInTheDocument();
      });

      // VIEWER possesses DASHBOARD_READ (overview, drift, alerts)
      expect(screen.getByRole("tab", { name: /overview/i })).not.toBeDisabled();
      expect(screen.getByRole("tab", { name: /drift/i })).not.toBeDisabled();
      expect(screen.getByRole("tab", { name: /alerts/i })).not.toBeDisabled();

      // VIEWER lacks VERIFY_WRITE -> stream disabled
      expect(screen.getByRole("tab", { name: /live stream/i })).toBeDisabled();

      // VIEWER lacks both VERIFY_READ and AUDIT_READ -> sessions disabled
      expect(screen.getByRole("tab", { name: /sessions/i })).toBeDisabled();
    });

    it("API_CLIENT: stream and sessions enabled (possesses VERIFY_WRITE & VERIFY_READ); overview, drift, alerts disabled (lacks DASHBOARD_READ)", async () => {
      const token = createMockJwt({
        sub: "key_client_1",
        tenant_id: "tenant_corp",
        role: "api_client",
        exp: Math.floor(Date.now() / 1000) + 3600,
      });

      render(
        <AuthProvider initialToken={token}>
          <DashboardShell />
        </AuthProvider>
      );

      // API_CLIENT lacks DASHBOARD_READ -> overview tab is disabled
      expect(screen.getByRole("tab", { name: /overview/i })).toBeDisabled();
      expect(screen.getByRole("tab", { name: /drift/i })).toBeDisabled();
      expect(screen.getByRole("tab", { name: /alerts/i })).toBeDisabled();

      // API_CLIENT possesses VERIFY_WRITE -> live stream tab is ENABLED
      const streamTab = screen.getByRole("tab", { name: /live stream/i });
      expect(streamTab).not.toBeDisabled();

      // API_CLIENT possesses VERIFY_READ -> sessions tab is ENABLED
      const sessionsTab = screen.getByRole("tab", { name: /sessions/i });
      expect(sessionsTab).not.toBeDisabled();

      // Active tab default is overview -> renders AccessDenied because role lacks DASHBOARD_READ
      expect(screen.getByRole("alert")).toBeInTheDocument();
      expect(screen.getByText("Overview Access Restricted")).toBeInTheDocument();
      expect(screen.getByText(/dashboard:read/i)).toBeInTheDocument();

      // Clicking an authorized tab (Live Stream) displays the view without AccessDenied
      fireEvent.click(streamTab);
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(screen.getByText("Live WebSocket Verification Stream")).toBeInTheDocument();
    });
  });

  describe("Security Boundaries", () => {
    it("does not render any client-controlled tenant switching dropdowns or inputs", async () => {
      render(<App />);

      await waitFor(() => {
        expect(screen.getByRole("heading", { name: "System Overview & Telemetry" })).toBeInTheDocument();
      });

      // Verify no input or select element exists for changing/switching tenant
      expect(screen.queryByLabelText(/select tenant/i)).not.toBeInTheDocument();
      expect(screen.queryByRole("combobox", { name: /tenant/i })).not.toBeInTheDocument();
      expect(screen.queryByPlaceholderText(/switch tenant/i)).not.toBeInTheDocument();
    });
  });

  describe("Authentication Dialog Flow", () => {
    it("opens authentication dialog, authenticates valid token, and updates session header", async () => {
      render(<App />);

      await waitFor(() => {
        expect(screen.getByRole("heading", { name: "System Overview & Telemetry" })).toBeInTheDocument();
      });

      // Click "Sign In" button in header
      const signInBtn = screen.getByRole("button", { name: /authenticate with access token/i });
      fireEvent.click(signInBtn);

      // Verify dialog opened
      expect(screen.getByRole("dialog", { name: /authenticate session/i })).toBeInTheDocument();

      const futureExp = Math.floor(Date.now() / 1000) + 3600;
      const validToken = createMockJwt({
        sub: "op_vedant",
        tenant_id: "tenant_lab",
        role: "operator",
        exp: futureExp,
      });

      // Enter token and submit
      const input = screen.getByLabelText(/jwt access token/i);
      fireEvent.change(input, { target: { value: validToken } });

      const authBtn = screen.getByRole("button", { name: /^authenticate$/i });
      fireEvent.click(authBtn);

      // Verify session updated in header
      expect(screen.getByText("op_vedant")).toBeInTheDocument();
      expect(screen.getByText("tenant_lab")).toBeInTheDocument();
      expect(screen.getByText("operator", { exact: true })).toBeInTheDocument();

      // Verify logout button is visible
      const logoutBtn = screen.getByRole("button", { name: /log out session/i });
      expect(logoutBtn).toBeInTheDocument();

      // Click logout
      fireEvent.click(logoutBtn);
      expect(screen.getByRole("button", { name: /authenticate with access token/i })).toBeInTheDocument();
    });
  });
});
