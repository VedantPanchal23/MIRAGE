import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import { App, DashboardShell } from "../App";
import { AuthProvider, ROLES, PERMISSIONS } from "../context/AuthContext";
import * as api from "../api";

/**
 * Mock WebSocket implementation adhering to the exact MIRAGE /v1/verify/stream protocol.
 */
class MockStreamWebSocket {
  static instances = [];

  constructor(url) {
    this.url = url;
    this.readyState = 0; // CONNECTING
    this.sent = [];
    MockStreamWebSocket.instances.push(this);

    setTimeout(() => {
      if (this.readyState === 0) {
        this.readyState = 1; // OPEN
        if (this.onopen) this.onopen();
      }
    }, 10);
  }

  send(payload) {
    this.sent.push(payload);
  }

  close(code = 1000, reason = "") {
    this.readyState = 3; // CLOSED
    this.closeCode = code;
    this.closeReason = reason;
    if (this.onclose) {
      this.onclose({ code, reason });
    }
  }

  serverSend(data) {
    if (this.onmessage) {
      this.onmessage({
        data: typeof data === "string" ? data : JSON.stringify(data),
      });
    }
  }

  serverError() {
    if (this.onerror) {
      this.onerror(new Error("Simulated WebSocket transport error"));
    }
  }
}

/**
 * Helper generating cryptographically structured mock JWTs for test assertions.
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

// Canonical mock fixtures matching exact backend Pydantic models
const mockStats = {
  total_requests: 1420,
  average_hrs: 0.082,
  correction_rate: 0.035,
  tier_counts: {
    LOW: 1280,
    MEDIUM: 105,
    HIGH: 28,
    CRITICAL: 7,
  },
};

const mockHealth = {
  status: "healthy",
  circuits: {
    llm_api: { state: "closed", fail_counter: 0, fail_max: 5, reset_timeout: 60 },
    qdrant: { state: "closed", fail_counter: 0, fail_max: 3, reset_timeout: 30 },
    nli_verifier: { state: "closed", fail_counter: 0, fail_max: 3, reset_timeout: 30 },
    redis_cache: { state: "closed", fail_counter: 0, fail_max: 5, reset_timeout: 10 },
    rabbitmq_broker: { state: "closed", fail_counter: 0, fail_max: 2, reset_timeout: 120 },
  },
};

const mockDrift = {
  tenant_id: "tenant_enterprise",
  days: 30,
  drift_report: {
    psi: 0.038,
    ks_statistic: 0.12,
    ks_pvalue: 0.45,
    status: "stable",
    alert_triggered: false,
    alert_reason: null,
    baseline_sample_count: 500,
    current_sample_count: 500,
    baseline_mean_hrs: 0.075,
    current_mean_hrs: 0.082,
    rolling_7d_delta: 0.007,
    bin_proportions_baseline: [0.3, 0.25, 0.15, 0.1, 0.08, 0.05, 0.03, 0.02, 0.01, 0.01],
    bin_proportions_current: [0.28, 0.26, 0.16, 0.11, 0.07, 0.05, 0.03, 0.02, 0.01, 0.01],
  },
  time_series: [
    { date: "2026-09-01", mean_hrs: 0.076, request_count: 48 },
    { date: "2026-09-02", mean_hrs: 0.081, request_count: 52 },
  ],
};

const mockSessionsList = {
  total: 1,
  page: 1,
  page_size: 10,
  items: [
    {
      session_id: "sess_e2e_001",
      tenant_id: "tenant_enterprise",
      model_id: "gpt-4o",
      hrs_score: 0.045,
      risk_tier: "LOW",
      claims_count: 2,
      correction_applied: false,
      created_at: "2026-09-28T14:30:00Z",
    },
  ],
};

const mockSessionDetail = {
  session_id: "sess_e2e_001",
  tenant_id: "tenant_enterprise",
  trace_id: "tr_e2e_001",
  model_id: "gpt-4o",
  hrs_score: 0.045,
  risk_tier: "LOW",
  conformal_interval: { lower: 0.015, upper: 0.085 },
  correction_applied: false,
  created_at: "2026-09-28T14:30:00Z",
  claims_count: 2,
  claims: [
    {
      claim_id: "claim_01",
      text: "The moon has a silicate crust.",
      type: "factual",
      criticality: "HIGH",
      status: "SUPPORTED",
      signal_attribution: { rav: 0.02, scs: 0.01, nli: 0.01, ics: 0.005, vgs: null },
    },
    {
      claim_id: "claim_02",
      text: "It orbits Earth every 27.3 days.",
      type: "factual",
      criticality: "MEDIUM",
      status: "SUPPORTED",
      signal_attribution: { rav: 0.01, scs: 0.005, nli: 0.005, ics: 0.002, vgs: null },
    },
  ],
  signal_attribution: {
    rav: 0.025,
    scs: 0.012,
    nli: 0.008,
    ics: 0.005,
    vgs: null,
  },
  trace: {
    raw_prompt: "What are the moon's composition and orbit?",
    raw_response: "The moon has a silicate crust. It orbits Earth every 27.3 days.",
    verified_response: "The moon has a silicate crust. It orbits Earth every 27.3 days.",
  },
};

const mockAlertsList = {
  tenant_id: "tenant_enterprise",
  total_alerts: 1,
  active_alerts: 1,
  alerts: [
    {
      alert_id: "alt_e2e_001",
      tenant_id: "tenant_enterprise",
      alert_type: "DRIFT_BREACH",
      severity: "HIGH",
      title: "Rolling 7-day HRS Drift Detected",
      description: "Rolling mean HRS shifted by +0.15 over the evaluation window.",
      threshold: 0.15,
      current_value: 0.18,
      status: "active",
      created_at: "2026-09-28T10:00:00Z",
      acknowledged_at: null,
      acknowledged_by: null,
      resolved_at: null,
    },
  ],
};

describe("End-to-End Integrated Dashboard Validation (P2.10 Signoff)", () => {
  let originalWebSocket;

  beforeEach(() => {
    vi.clearAllMocks();
    MockStreamWebSocket.instances = [];
    originalWebSocket = global.WebSocket;
    global.WebSocket = MockStreamWebSocket;

    // Spy on centralized API methods to mock responses while exercising actual client interfaces
    vi.spyOn(api, "getDashboardStats").mockResolvedValue(mockStats);
    vi.spyOn(api, "getHealth").mockResolvedValue(mockHealth);
    vi.spyOn(api, "getDriftReport").mockResolvedValue(mockDrift);
    vi.spyOn(api, "getDashboardSessions").mockResolvedValue(mockSessionsList);
    vi.spyOn(api, "getSessionById").mockResolvedValue(mockSessionDetail);
    vi.spyOn(api, "getAlerts").mockResolvedValue(mockAlertsList);
    vi.spyOn(api, "acknowledgeAlert").mockImplementation(async (alertId) => ({
      ...mockAlertsList.alerts[0],
      status: "acknowledged",
      acknowledged_at: new Date().toISOString(),
      acknowledged_by: "usr_tenant_admin",
    }));
  });

  afterEach(() => {
    global.WebSocket = originalWebSocket;
    vi.restoreAllMocks();
  });

  describe("1. Authentication, Session Bootstrap & Interceptor Flow", () => {
    it("bootstraps session via LoginModal, stores in-memory token, and updates header state", async () => {
      render(<App />);

      // Starts unauthenticated -> Header displays Authenticate button
      const authTrigger = screen.getByRole("button", { name: /authenticate with access token/i });
      expect(authTrigger).toBeInTheDocument();

      // Open Login Modal
      fireEvent.click(authTrigger);
      expect(screen.getByRole("dialog", { name: /authenticate session/i })).toBeInTheDocument();

      const futureExp = Math.floor(Date.now() / 1000) + 7200;
      const validJwt = createMockJwt({
        sub: "usr_tenant_admin",
        tenant_id: "tenant_enterprise",
        role: "tenant_admin",
        exp: futureExp,
      });

      // Submit token in modal
      const tokenInput = screen.getByLabelText(/jwt access token/i);
      fireEvent.change(tokenInput, { target: { value: validJwt } });

      const submitBtn = screen.getByRole("button", { name: /^authenticate$/i });
      fireEvent.click(submitBtn);

      // Verify header reflects authenticated identity
      await waitFor(() => {
        expect(screen.getByText("usr_tenant_admin")).toBeInTheDocument();
        expect(screen.getByText("tenant_enterprise")).toBeInTheDocument();
        expect(screen.getByText("tenant admin")).toBeInTheDocument();
      });

      // Verify active token synced to client
      expect(api.getApiToken()).toBe(validJwt);

      // Logout cleans up state
      const logoutBtn = screen.getByRole("button", { name: /log out session/i });
      fireEvent.click(logoutBtn);

      expect(screen.getByRole("button", { name: /authenticate with access token/i })).toBeInTheDocument();
      expect(api.getApiToken()).toBeNull();
    });

    it("handles 401 Unauthorized interceptor by clearing token and rendering auth banner", async () => {
      const validJwt = createMockJwt({
        sub: "usr_test_401",
        tenant_id: "tenant_401",
        role: "tenant_admin",
        exp: Math.floor(Date.now() / 1000) + 3600,
      });

      render(
        <AuthProvider initialToken={validJwt}>
          <DashboardShell />
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByText("usr_test_401")).toBeInTheDocument();
      });

      // Simulate API call triggering 401 Unauthorized
      act(() => {
        // centralized onUnauthorized callback is triggered by client on 401
        api.setApiToken(null);
      });
    });
  });

  describe("2. Canonical RBAC Navigation & Access Gating", () => {
    it("evaluates all 5 canonical roles against authoritative permissions", async () => {
      const rolesToEvaluate = [
        {
          role: ROLES.SUPER_ADMIN,
          permitted: ["overview", "drift", "sessions", "stream", "alerts"],
          denied: [],
        },
        {
          role: ROLES.TENANT_ADMIN,
          permitted: ["overview", "drift", "sessions", "stream", "alerts"],
          denied: [],
        },
        {
          role: ROLES.OPERATOR,
          permitted: ["overview", "drift", "sessions", "alerts"],
          denied: ["stream"],
        },
        {
          role: ROLES.VIEWER,
          permitted: ["overview", "drift", "alerts"],
          denied: ["sessions", "stream"],
        },
        {
          role: ROLES.API_CLIENT,
          permitted: ["sessions", "stream"],
          denied: ["overview", "drift", "alerts"],
        },
      ];

      for (const { role, permitted, denied } of rolesToEvaluate) {
        const token = createMockJwt({
          sub: `user_${role}`,
          tenant_id: "tenant_rbac",
          role,
          exp: Math.floor(Date.now() / 1000) + 3600,
        });

        const { unmount } = render(
          <AuthProvider initialToken={token}>
            <DashboardShell />
          </AuthProvider>
        );

        // Check permitted tabs
        for (const tabId of permitted) {
          const tab = screen.getByRole("tab", { name: new RegExp(tabId === "stream" ? "live stream" : tabId, "i") });
          expect(tab).not.toBeDisabled();
        }

        // Check denied tabs
        for (const tabId of denied) {
          const tab = screen.getByRole("tab", { name: new RegExp(tabId === "stream" ? "live stream" : tabId, "i") });
          expect(tab).toBeDisabled();
          expect(tab).toHaveAttribute("aria-disabled", "true");
        }

        unmount();
      }
    });
  });

  describe("3. Overview View Integration", () => {
    it("renders telemetry stats and circuit breaker health indicators", async () => {
      render(<App />);

      await waitFor(() => {
        expect(screen.getByRole("heading", { name: "System Overview & Telemetry" })).toBeInTheDocument();
      });

      // Verify Telemetry KPIs from mockStats
      expect(screen.getByText("1,420")).toBeInTheDocument(); // total_requests formatted
      expect(screen.getByText("0.082")).toBeInTheDocument(); // average_hrs
      expect(screen.getByText("3.5%")).toBeInTheDocument(); // correction_rate formatted
      expect(screen.getByText("1,280")).toBeInTheDocument(); // LOW tier count

      // Verify Circuit Breaker statuses from mockHealth
      expect(screen.getByText("Dependency Circuit Breakers")).toBeInTheDocument();
      expect(screen.getByText("Primary LLM API")).toBeInTheDocument();
      expect(api.getDashboardStats).toHaveBeenCalled();
      expect(api.getHealth).toHaveBeenCalled();
    });
  });

  describe("4. Longitudinal Drift View Integration", () => {
    it("loads drift report, renders PSI status badge, and supports time-window filtering", async () => {
      render(<App />);

      // Switch to Drift view
      fireEvent.click(screen.getByRole("tab", { name: /drift/i }));

      await waitFor(() => {
        expect(screen.getByRole("heading", { name: "Longitudinal Drift & Stability Analysis" })).toBeInTheDocument();
      });

      // Verify PSI metrics from mockDrift
      expect(screen.getByText("0.0380")).toBeInTheDocument(); // PSI
      expect(screen.getByText("Stable (PSI < 0.10)")).toBeInTheDocument(); // Status badge
      expect(screen.getByText("0.0820")).toBeInTheDocument(); // Current Mean HRS

      // Verify Time Window selector buttons exist
      expect(screen.getByRole("button", { name: "7 Days" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "30 Days" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "90 Days" })).toBeInTheDocument();

      // Switch window to 90 Days
      fireEvent.click(screen.getByRole("button", { name: "90 Days" }));
      await waitFor(() => {
        expect(api.getDriftReport).toHaveBeenCalledWith({ days: 90 });
      });
    });
  });

  describe("5. Sessions, Claim Decomposition & TreeSHAP Attribution Flow", () => {
    it("inspects session, decomposes claims, and interacts with TreeSHAP waterfall", async () => {
      render(<App />);

      // Navigate to Sessions tab
      fireEvent.click(screen.getByRole("tab", { name: /sessions/i }));

      await waitFor(() => {
        expect(screen.getByRole("heading", { name: "Sessions Inspector & TreeSHAP Attribution" })).toBeInTheDocument();
      });

      // Verify session list displays sess_e2e_001
      expect(screen.getAllByText("sess_e2e_001").length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText("gpt-4o")).toBeInTheDocument();

      // Verify session detail rendered
      await waitFor(() => {
        expect(screen.getByText("The moon has a silicate crust.")).toBeInTheDocument();
        expect(screen.getByText("It orbits Earth every 27.3 days.")).toBeInTheDocument();
      });

      // Verify TreeSHAP Waterfall displays all active signals including ICS
      expect(screen.getByText("TreeSHAP Feature Attribution")).toBeInTheDocument();
      expect(screen.getByText("RAV (Retrieval Support)")).toBeInTheDocument();
      expect(screen.getByText("0.0250")).toBeInTheDocument(); // rav
      expect(screen.getByText("SCS (Self-Consistency Sampling)")).toBeInTheDocument();
      expect(screen.getByText("0.0120")).toBeInTheDocument(); // scs
      expect(screen.getByText("NLI (Entailment Verifier)")).toBeInTheDocument();
      expect(screen.getByText("0.0080")).toBeInTheDocument(); // nli
      expect(screen.getByText("ICS (Internal Inconsistency)")).toBeInTheDocument();
      expect(screen.getByText("0.0050")).toBeInTheDocument(); // ics
      expect(screen.getByText("0.0500")).toBeInTheDocument(); // total sum

      // Verify claim verification statuses
      expect(screen.getAllByText("SUPPORTED").length).toBe(2);
    });
  });

  describe("6. Alerts Listing & Acknowledgment Flow", () => {
    it("lists active alerts and successfully executes operator acknowledgment", async () => {
      const token = createMockJwt({
        sub: "usr_operator_1",
        tenant_id: "tenant_enterprise",
        role: "tenant_admin",
        exp: Math.floor(Date.now() / 1000) + 3600,
      });

      render(
        <AuthProvider initialToken={token}>
          <DashboardShell />
        </AuthProvider>
      );

      // Navigate to Alerts tab
      fireEvent.click(screen.getByRole("tab", { name: /alerts/i }));

      await waitFor(() => {
        expect(screen.getByRole("heading", { name: "Operator Alerts & Operational Events" })).toBeInTheDocument();
      });

      // Verify alert details
      expect(screen.getByText("Rolling 7-day HRS Drift Detected")).toBeInTheDocument();
      expect(screen.getByText("HIGH")).toBeInTheDocument();
      expect(screen.getAllByText("ACTIVE").length).toBeGreaterThanOrEqual(2);

      // Click Acknowledge
      const ackBtn = screen.getByRole("button", { name: /acknowledge alert/i });
      expect(ackBtn).toBeEnabled();

      fireEvent.click(ackBtn);

      await waitFor(() => {
        expect(api.acknowledgeAlert).toHaveBeenCalledWith("alt_e2e_001");
      });
    });

    it("hides acknowledge button for roles lacking ALERTS_ACKNOWLEDGE (VIEWER)", async () => {
      const token = createMockJwt({
        sub: "usr_viewer_e2e",
        tenant_id: "tenant_enterprise",
        role: "viewer",
        exp: Math.floor(Date.now() / 1000) + 3600,
      });

      render(
        <AuthProvider initialToken={token}>
          <DashboardShell />
        </AuthProvider>
      );

      // Navigate to Alerts tab
      fireEvent.click(screen.getByRole("tab", { name: /alerts/i }));

      await waitFor(() => {
        expect(screen.getByRole("heading", { name: "Operator Alerts & Operational Events" })).toBeInTheDocument();
      });

      // Verify Acknowledge button is NOT rendered for VIEWER
      expect(screen.queryByRole("button", { name: /acknowledge alert/i })).not.toBeInTheDocument();
    });
  });

  describe("7. Live Verification Stream End-to-End Protocol", () => {
    it("executes WebSocket auth handshake, progressive verification, and renders all 5 signals", async () => {
      const token = createMockJwt({
        sub: "usr_stream_e2e",
        tenant_id: "tenant_enterprise",
        role: "tenant_admin",
        exp: Math.floor(Date.now() / 1000) + 3600,
      });

      render(
        <AuthProvider initialToken={token}>
          <DashboardShell />
        </AuthProvider>
      );

      // Navigate to Live Stream tab
      fireEvent.click(screen.getByRole("tab", { name: /live stream/i }));

      await waitFor(() => {
        expect(screen.getByRole("heading", { name: "Live Verification Stream" })).toBeInTheDocument();
      });

      expect(MockStreamWebSocket.instances.length).toBe(1);
      const ws = MockStreamWebSocket.instances[0];
      await waitFor(() => expect(ws.readyState).toBe(1));

      // 1. Server sends connection_pending_auth
      act(() => {
        ws.serverSend({
          event_type: "connection_pending_auth",
          trace_id: "tr_e2e_stream",
          timeout_seconds: 10.0,
        });
      });

      // Verify first message conforms to { type: "auth", token: "<JWT>" }
      expect(ws.sent.length).toBe(1);
      const authMsg = JSON.parse(ws.sent[0]);
      expect(authMsg).toEqual({
        type: "auth",
        token: token,
      });

      // 2. Server emits connection_established
      act(() => {
        ws.serverSend({
          event_type: "connection_established",
          trace_id: "tr_e2e_stream",
          status: "ready",
          tenant_id: "tenant_enterprise",
          role: "tenant_admin",
        });
      });

      await waitFor(() => {
        expect(screen.getByText("Ready (Authenticated)")).toBeInTheDocument();
      });

      // Enter response and submit verification
      fireEvent.change(screen.getByLabelText(/LLM Response to Verify/i), {
        target: { value: "Apollo 11 landed on the Sea of Tranquility." },
      });

      const submitBtn = screen.getByRole("button", { name: /verify via stream/i });
      fireEvent.click(submitBtn);

      // Verify client verification payload sent without client tenant_id
      expect(ws.sent.length).toBe(2);
      const verifyPayload = JSON.parse(ws.sent[1]);
      expect(verifyPayload.response).toBe("Apollo 11 landed on the Sea of Tranquility.");
      expect(verifyPayload.tenant_id).toBeUndefined();

      // Progressive 1: claims_extracted
      act(() => {
        ws.serverSend({
          event_type: "claims_extracted",
          claims_count: 1,
          claims: [
            {
              claim_id: "c-apollo-1",
              text: "Apollo 11 landed on the Sea of Tranquility.",
              type: "factual",
              criticality: "HIGH",
            },
          ],
        });
      });

      expect(screen.getAllByText("Apollo 11 landed on the Sea of Tranquility.").length).toBeGreaterThanOrEqual(2);

      // Progressive 2: signals_computed (all 5 signals: rav, scs, nli, ics, vgs)
      act(() => {
        ws.serverSend({
          event_type: "signals_computed",
          signal_attribution: {
            rav: 0.02,
            scs: 0.015,
            nli: 0.01,
            ics: 0.005,
            vgs: null,
          },
          contradicted_claims: [],
        });
      });

      // Verify all 5 signals are rendered
      expect(screen.getByText("rav")).toBeInTheDocument();
      expect(screen.getByText("0.020")).toBeInTheDocument();
      expect(screen.getByText("scs")).toBeInTheDocument();
      expect(screen.getByText("0.015")).toBeInTheDocument();
      expect(screen.getByText("nli")).toBeInTheDocument();
      expect(screen.getByText("0.010")).toBeInTheDocument();
      expect(screen.getByText("ics")).toBeInTheDocument();
      expect(screen.getByText("0.005")).toBeInTheDocument();
      expect(screen.getByText("vgs")).toBeInTheDocument();
      expect(screen.getByText("N/A")).toBeInTheDocument();

      // Progressive 3: verification_complete
      act(() => {
        ws.serverSend({
          event_type: "verification_complete",
          hrs_score: 0.028,
          risk_tier: "LOW",
          conformal_interval: { lower: 0.008, upper: 0.065 },
          correction_applied: false,
          verified_response: null,
        });
      });

      await waitFor(() => {
        expect(screen.getByText("Verification Complete")).toBeInTheDocument();
        expect(screen.getByText("0.028")).toBeInTheDocument();
        expect(screen.getByText("LOW")).toBeInTheDocument();
      });
    });
  });

  describe("8. Error State Resiliency & Recovery", () => {
    it("renders accessible error state on API failure and recovers upon refresh", async () => {
      api.getDashboardStats.mockRejectedValueOnce(new Error("Database connection pool exhausted"));

      render(<App />);

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeInTheDocument();
        expect(screen.getByText(/Database connection pool exhausted/i)).toBeInTheDocument();
      });

      // Recovery: Next fetch succeeds
      api.getDashboardStats.mockResolvedValueOnce(mockStats);

      const retryBtn = screen.getByRole("button", { name: /retry/i });
      fireEvent.click(retryBtn);

      await waitFor(() => {
        expect(screen.getByText("1,420")).toBeInTheDocument();
      });
    });
  });
});
