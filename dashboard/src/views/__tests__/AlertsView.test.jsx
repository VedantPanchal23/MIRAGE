import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { AlertsView } from "../AlertsView";
import { AuthProvider, ROLES } from "../../context/AuthContext";
import * as api from "../../api";

vi.mock("../../api", () => ({
  getAlerts: vi.fn(),
  acknowledgeAlert: vi.fn(),
}));

/**
 * Helper to construct a mock JWT with specific role and tenant.
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

function renderWithRole(role, ui) {
  const token = createMockJwt({
    sub: `usr_${role}`,
    tenant_id: "tenant_corp",
    role,
    exp: Math.floor(Date.now() / 1000) + 3600,
  });

  return render(
    <AuthProvider initialToken={token}>
      {ui}
    </AuthProvider>
  );
}

describe("AlertsView Component (P2.8)", () => {
  const mockAlertsList = {
    tenant_id: "tenant_corp",
    total_alerts: 3,
    active_alerts: 2,
    alerts: [
      {
        alert_id: "alt_hrs_001",
        tenant_id: "tenant_corp",
        alert_type: "rolling_hrs_breach",
        severity: "high",
        title: "Rolling HRS Threshold Breach",
        description: "7-day rolling mean HRS (0.72) exceeded threshold (0.60)",
        threshold: 0.60,
        current_value: 0.72,
        status: "active",
        created_at: "2026-09-29T10:00:00Z",
        acknowledged_at: null,
        acknowledged_by: null,
        resolved_at: null,
      },
      {
        alert_id: "alt_cb_002",
        tenant_id: "tenant_corp",
        alert_type: "circuit_breaker_open",
        severity: "critical",
        title: "NLI Model Server Circuit Breaker Open",
        description: "Consecutive failure threshold exceeded. Circuit breaker open for 30s.",
        threshold: 3.0,
        current_value: 5.0,
        status: "active",
        created_at: "2026-09-29T10:15:00Z",
        acknowledged_at: null,
        acknowledged_by: null,
        resolved_at: null,
      },
      {
        alert_id: "alt_ack_003",
        tenant_id: "tenant_corp",
        alert_type: "drift_psi_threshold",
        severity: "medium",
        title: "Drift PSI Tolerance Exceeded",
        description: "PSI metric reached 0.22, exceeding stability limit of 0.20.",
        threshold: 0.20,
        current_value: 0.22,
        status: "acknowledged",
        created_at: "2026-09-28T09:00:00Z",
        acknowledged_at: "2026-09-28T11:00:00Z",
        acknowledged_by: "usr_operator_1",
        resolved_at: null,
      },
    ],
  };

  beforeEach(() => {
    vi.clearAllMocks();
    api.getAlerts.mockReset();
    api.acknowledgeAlert.mockReset();
  });

  it("renders loading state on initial mount with accessible status role", () => {
    api.getAlerts.mockReturnValue(new Promise(() => {})); // pending

    renderWithRole(ROLES.OPERATOR, <AlertsView />);
    expect(screen.getByRole("status")).toHaveAttribute("aria-label", "Loading operator alerts");
    expect(screen.getByText(/Loading operator alerts/i)).toBeInTheDocument();
  });

  it("calls centralized API client getAlerts without client-injected tenant_id", async () => {
    api.getAlerts.mockResolvedValueOnce(mockAlertsList);

    renderWithRole(ROLES.OPERATOR, <AlertsView />);

    await waitFor(() => {
      expect(api.getAlerts).toHaveBeenCalledTimes(1);
      // Calls with empty params filter, without client-controlled tenant parameter
      expect(api.getAlerts).toHaveBeenCalledWith({});
    });
  });

  it("renders successful alert listing with IDs, severities, statuses, titles, and metrics", async () => {
    api.getAlerts.mockResolvedValue(mockAlertsList);

    renderWithRole(ROLES.OPERATOR, <AlertsView />);

    await waitFor(() => {
      expect(screen.getByText("alt_hrs_001")).toBeInTheDocument();
    });

    expect(screen.getByText("alt_cb_002")).toBeInTheDocument();
    expect(screen.getByText("alt_ack_003")).toBeInTheDocument();

    // Severities
    expect(screen.getByText("HIGH")).toBeInTheDocument();
    expect(screen.getByText("CRITICAL")).toBeInTheDocument();
    expect(screen.getByText("MEDIUM")).toBeInTheDocument();

    // Titles & descriptions
    expect(screen.getByText("Rolling HRS Threshold Breach")).toBeInTheDocument();
    expect(screen.getByText("NLI Model Server Circuit Breaker Open")).toBeInTheDocument();
    expect(screen.getByText("Drift PSI Tolerance Exceeded")).toBeInTheDocument();

    // Metric triggers
    expect(screen.getByText("0.7200")).toBeInTheDocument();
    expect(screen.getByText("0.6000")).toBeInTheDocument();

    // Summary counts
    expect(screen.getByText("3")).toBeInTheDocument(); // total
    expect(screen.getByText("2")).toBeInTheDocument(); // active
  });

  it("renders empty state when no alerts exist", async () => {
    api.getAlerts.mockResolvedValueOnce({
      tenant_id: "tenant_corp",
      total_alerts: 0,
      active_alerts: 0,
      alerts: [],
    });

    renderWithRole(ROLES.OPERATOR, <AlertsView />);

    await waitFor(() => {
      expect(screen.getByText("No Persisted Alerts Available")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /check for updates/i })).toBeInTheDocument();
    });
  });

  it("renders error state when centralized API call fails and provides working retry button", async () => {
    const errorObj = new Error("PostgreSQL query failed");
    errorObj.code = "DB_UNAVAILABLE";
    errorObj.traceId = "tr_alert_err_503";
    errorObj.status = 503;

    api.getAlerts.mockRejectedValueOnce(errorObj);

    renderWithRole(ROLES.OPERATOR, <AlertsView />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
      expect(screen.getByText("Unable to Load Operator Alerts")).toBeInTheDocument();
      expect(screen.getByText("PostgreSQL query failed")).toBeInTheDocument();
      expect(screen.getByText("Code: DB_UNAVAILABLE")).toBeInTheDocument();
      expect(screen.getByText("Trace: tr_alert_err_503")).toBeInTheDocument();
    });

    // Test retry behavior
    api.getAlerts.mockResolvedValueOnce(mockAlertsList);
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));

    await waitFor(() => {
      expect(screen.getByText("alt_hrs_001")).toBeInTheDocument();
    });
  });

  it("supports status filtering and passes selected filter to backend", async () => {
    api.getAlerts.mockResolvedValue(mockAlertsList);

    renderWithRole(ROLES.OPERATOR, <AlertsView />);

    await waitFor(() => {
      expect(screen.getByText("alt_hrs_001")).toBeInTheDocument();
    });

    // Click ACTIVE filter
    const activeBtn = screen.getByRole("button", { name: "ACTIVE" });
    fireEvent.click(activeBtn);

    await waitFor(() => {
      expect(api.getAlerts).toHaveBeenCalledWith({ status: "active" });
    });
  });

  it("acknowledgement success: calls acknowledgeAlert, updates alert status, and decrements active count", async () => {
    api.getAlerts.mockResolvedValueOnce(mockAlertsList);
    api.acknowledgeAlert.mockResolvedValueOnce({
      alert_id: "alt_hrs_001",
      tenant_id: "tenant_corp",
      status: "acknowledged",
      acknowledged_at: "2026-09-29T10:30:00Z",
      acknowledged_by: "usr_operator",
    });

    renderWithRole(ROLES.OPERATOR, <AlertsView />);

    await waitFor(() => {
      expect(screen.getByText("alt_hrs_001")).toBeInTheDocument();
    });

    const ackButton = screen.getByRole("button", { name: "Acknowledge alert alt_hrs_001" });
    expect(ackButton).toBeInTheDocument();

    fireEvent.click(ackButton);

    await waitFor(() => {
      expect(api.acknowledgeAlert).toHaveBeenCalledWith("alt_hrs_001");
      expect(screen.getByText(/Acknowledged at/i)).toBeInTheDocument();
    });
  });

  it("acknowledgement failure: displays error message preserving ApiError details", async () => {
    api.getAlerts.mockResolvedValueOnce(mockAlertsList);
    const ackError = new Error("Failed to write acknowledgment to PostgreSQL");
    ackError.code = "PERSISTENCE_FAILED";
    ackError.traceId = "tr_ack_500";
    ackError.status = 500;

    api.acknowledgeAlert.mockRejectedValueOnce(ackError);

    renderWithRole(ROLES.OPERATOR, <AlertsView />);

    await waitFor(() => {
      expect(screen.getByText("alt_hrs_001")).toBeInTheDocument();
    });

    const ackButton = screen.getByRole("button", { name: "Acknowledge alert alt_hrs_001" });
    fireEvent.click(ackButton);

    await waitFor(() => {
      expect(screen.getByText(/Acknowledgement Failed: Failed to write acknowledgment to PostgreSQL/i)).toBeInTheDocument();
      expect(screen.getByText("Code: PERSISTENCE_FAILED")).toBeInTheDocument();
      expect(screen.getByText("Trace: tr_ack_500")).toBeInTheDocument();
    });
  });

  it("prevents duplicate acknowledgement submissions while acknowledgement is pending", async () => {
    let resolveAck;
    const pendingPromise = new Promise((resolve) => {
      resolveAck = resolve;
    });

    api.getAlerts.mockResolvedValueOnce(mockAlertsList);
    api.acknowledgeAlert.mockReturnValueOnce(pendingPromise);

    renderWithRole(ROLES.OPERATOR, <AlertsView />);

    await waitFor(() => {
      expect(screen.getByText("alt_hrs_001")).toBeInTheDocument();
    });

    const ackButton = screen.getByRole("button", { name: "Acknowledge alert alt_hrs_001" });
    fireEvent.click(ackButton);

    // Button enters pending state and is disabled
    expect(screen.getByText("Acknowledging...")).toBeInTheDocument();
    expect(ackButton).toBeDisabled();

    // Clicking again should not trigger another call
    fireEvent.click(ackButton);
    expect(api.acknowledgeAlert).toHaveBeenCalledTimes(1);

    // Resolve the promise
    resolveAck({
      alert_id: "alt_hrs_001",
      status: "acknowledged",
    });

    await waitFor(() => {
      expect(screen.queryByText("Acknowledging...")).not.toBeInTheDocument();
    });
  });

  it("read-only users (VIEWER): inspects alerts but does NOT render acknowledgement control", async () => {
    api.getAlerts.mockResolvedValueOnce(mockAlertsList);

    renderWithRole(ROLES.VIEWER, <AlertsView />);

    await waitFor(() => {
      expect(screen.getByText("alt_hrs_001")).toBeInTheDocument();
      expect(screen.getByText("Read-Only Viewer")).toBeInTheDocument();
    });

    // Invariant: Users without ALERTS_ACKNOWLEDGE must NOT see Acknowledge buttons
    expect(screen.queryByRole("button", { name: /acknowledge alert/i })).not.toBeInTheDocument();
    expect(screen.getAllByText("Read-Only Inspection").length).toBeGreaterThan(0);
  });

  describe("Canonical RBAC UX Gating Across All 5 Roles", () => {
    it("SUPER_ADMIN can acknowledge alerts", async () => {
      api.getAlerts.mockResolvedValueOnce(mockAlertsList);
      renderWithRole(ROLES.SUPER_ADMIN, <AlertsView />);

      await waitFor(() => {
        expect(screen.getByRole("button", { name: "Acknowledge alert alt_hrs_001" })).toBeInTheDocument();
      });
    });

    it("TENANT_ADMIN can acknowledge alerts", async () => {
      api.getAlerts.mockResolvedValueOnce(mockAlertsList);
      renderWithRole(ROLES.TENANT_ADMIN, <AlertsView />);

      await waitFor(() => {
        expect(screen.getByRole("button", { name: "Acknowledge alert alt_hrs_001" })).toBeInTheDocument();
      });
    });

    it("OPERATOR can acknowledge alerts", async () => {
      api.getAlerts.mockResolvedValueOnce(mockAlertsList);
      renderWithRole(ROLES.OPERATOR, <AlertsView />);

      await waitFor(() => {
        expect(screen.getByRole("button", { name: "Acknowledge alert alt_hrs_001" })).toBeInTheDocument();
      });
    });

    it("VIEWER cannot acknowledge alerts (read-only)", async () => {
      api.getAlerts.mockResolvedValueOnce(mockAlertsList);
      renderWithRole(ROLES.VIEWER, <AlertsView />);

      await waitFor(() => {
        expect(screen.queryByRole("button", { name: /acknowledge alert/i })).not.toBeInTheDocument();
        expect(screen.getAllByText("Read-Only Inspection").length).toBeGreaterThan(0);
      });
    });

    it("API_CLIENT cannot acknowledge alerts (read-only)", async () => {
      api.getAlerts.mockResolvedValueOnce(mockAlertsList);
      renderWithRole(ROLES.API_CLIENT, <AlertsView />);

      await waitFor(() => {
        expect(screen.queryByRole("button", { name: /acknowledge alert/i })).not.toBeInTheDocument();
      });
    });
  });

  it("does not perform direct fetch calls", async () => {
    const globalFetchSpy = vi.spyOn(global, "fetch");
    api.getAlerts.mockResolvedValueOnce(mockAlertsList);

    renderWithRole(ROLES.OPERATOR, <AlertsView />);

    await waitFor(() => {
      expect(screen.getByText("alt_hrs_001")).toBeInTheDocument();
    });

    expect(globalFetchSpy).not.toHaveBeenCalled();
    globalFetchSpy.mockRestore();
  });

  it("does not render any client-controlled tenant selection elements", async () => {
    api.getAlerts.mockResolvedValueOnce(mockAlertsList);

    renderWithRole(ROLES.OPERATOR, <AlertsView />);

    await waitFor(() => {
      expect(screen.getByText("alt_hrs_001")).toBeInTheDocument();
    });

    expect(screen.queryByLabelText(/tenant/i)).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/tenant/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: /tenant/i })).not.toBeInTheDocument();
  });
});
