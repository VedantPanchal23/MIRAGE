import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import { LiveStreamView } from "../LiveStreamView";
import { AuthProvider, ROLES } from "../../context/AuthContext";

/**
 * Mock WebSocket implementation for deterministic LiveStreamView tests.
 */
class MockWebSocket {
  static instances = [];

  constructor(url) {
    this.url = url;
    this.readyState = 0; // CONNECTING
    this.sent = [];
    MockWebSocket.instances.push(this);

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
 * Helper to generate valid mock JWT tokens.
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

describe("LiveStreamView Component Tests (P2.9)", () => {
  let originalWebSocket;

  beforeEach(() => {
    MockWebSocket.instances = [];
    originalWebSocket = global.WebSocket;
    global.WebSocket = MockWebSocket;
  });

  afterEach(() => {
    global.WebSocket = originalWebSocket;
    vi.restoreAllMocks();
  });

  describe("Authentication Handshake & Connection States", () => {
    it("completes two-step JWT authentication handshake over WebSocket", async () => {
      const token = createMockJwt({
        sub: "usr_operator_1",
        tenant_id: "tenant_verified",
        role: "tenant_admin",
        exp: Math.floor(Date.now() / 1000) + 3600,
      });

      render(
        <AuthProvider initialToken={token}>
          <LiveStreamView />
        </AuthProvider>
      );

      expect(screen.getByRole("heading", { name: "Live Verification Stream" })).toBeInTheDocument();
      expect(MockWebSocket.instances.length).toBe(1);
      const ws = MockWebSocket.instances[0];

      await waitFor(() => expect(ws.readyState).toBe(1));

      // 1. Server sends connection_pending_auth
      act(() => {
        ws.serverSend({
          event_type: "connection_pending_auth",
          trace_id: "trace_ws_001",
          timeout_seconds: 10.0,
        });
      });

      // Verify client dispatches first-message authentication
      expect(ws.sent.length).toBe(1);
      const authPayload = JSON.parse(ws.sent[0]);
      expect(authPayload.type).toBe("auth");
      expect(authPayload.token).toBe(token);

      // 2. Server emits connection_established
      act(() => {
        ws.serverSend({
          event_type: "connection_established",
          trace_id: "trace_ws_001",
          status: "ready",
          tenant_id: "tenant_verified",
          role: "tenant_admin",
        });
      });

      // Verify authenticated ready state displayed
      await waitFor(() => {
        expect(screen.getByText("Ready (Authenticated)")).toBeInTheDocument();
        expect(screen.getByText("tenant_verified")).toBeInTheDocument();
        expect(screen.getByText("tenant_admin")).toBeInTheDocument();
      });
    });

    it("displays error banner on auth_failure and prevents reconnect loops on close 1008", async () => {
      const token = createMockJwt({
        sub: "usr_bad",
        tenant_id: "tenant_bad",
        role: "tenant_admin",
        exp: Math.floor(Date.now() / 1000) + 3600,
      });

      render(
        <AuthProvider initialToken={token}>
          <LiveStreamView />
        </AuthProvider>
      );

      const ws = MockWebSocket.instances[0];
      await waitFor(() => expect(ws.readyState).toBe(1));

      // Server challenge
      act(() => {
        ws.serverSend({ event_type: "connection_pending_auth" });
      });

      // Server rejects auth
      act(() => {
        ws.serverSend({
          event_type: "auth_failure",
          error_code: "INVALID_TOKEN",
          message: "Token signature expired or revoked",
        });
        ws.close(1008, "Policy Violation");
      });

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeInTheDocument();
        expect(screen.getByText("Token signature expired or revoked")).toBeInTheDocument();
      });

      // Ensure no automatic reconnection loop spawned
      expect(MockWebSocket.instances.length).toBe(1);
    });
  });

  describe("Progressive Verification Streaming", () => {
    it("submits verification payload and progressively renders claims, signals, and final verdict", async () => {
      const token = createMockJwt({
        sub: "usr_lead",
        tenant_id: "enterprise_tenant",
        role: "super_admin",
        exp: Math.floor(Date.now() / 1000) + 3600,
      });

      render(
        <AuthProvider initialToken={token}>
          <LiveStreamView />
        </AuthProvider>
      );

      const ws = MockWebSocket.instances[0];
      await waitFor(() => expect(ws.readyState).toBe(1));

      // Establish authenticated session
      act(() => {
        ws.serverSend({ event_type: "connection_pending_auth" });
        ws.serverSend({
          event_type: "connection_established",
          tenant_id: "enterprise_tenant",
          role: "super_admin",
        });
      });

      await waitFor(() => {
        expect(screen.getByText("Ready (Authenticated)")).toBeInTheDocument();
      });

      // Fill in prompt and response
      fireEvent.change(screen.getByLabelText(/Prompt \/ Query/i), {
        target: { value: "Where is the Eiffel Tower located?" },
      });
      fireEvent.change(screen.getByLabelText(/LLM Response to Verify/i), {
        target: { value: "The Eiffel Tower is located in Paris, France on the Champ de Mars." },
      });

      // Submit verification form
      const submitBtn = screen.getByRole("button", { name: /verify via stream/i });
      expect(submitBtn).toBeEnabled();

      fireEvent.click(submitBtn);

      // Verify payload was transmitted via WebSocket without client tenant_id
      expect(ws.sent.length).toBe(2);
      const sentVerification = JSON.parse(ws.sent[1]);
      expect(sentVerification.prompt).toBe("Where is the Eiffel Tower located?");
      expect(sentVerification.response).toBe(
        "The Eiffel Tower is located in Paris, France on the Champ de Mars."
      );
      expect(sentVerification.model_id).toBe("gpt-4o");
      expect(sentVerification.tenant_id).toBeUndefined();

      // Progressive Stage 1: claims_extracted
      act(() => {
        ws.serverSend({
          event_type: "claims_extracted",
          claims_count: 2,
          claims: [
            {
              claim_id: "c-101",
              text: "The Eiffel Tower is located in Paris, France.",
              type: "factual",
              criticality: "HIGH",
            },
            {
              claim_id: "c-102",
              text: "It is situated on the Champ de Mars.",
              type: "factual",
              criticality: "MEDIUM",
            },
          ],
        });
      });

      expect(screen.getByText("The Eiffel Tower is located in Paris, France.")).toBeInTheDocument();
      expect(screen.getByText("It is situated on the Champ de Mars.")).toBeInTheDocument();
      expect(screen.getByText("2 claims")).toBeInTheDocument();

      // Progressive Stage 2: signals_computed (including all 5 verification signals: rav, scs, nli, ics, vgs)
      act(() => {
        ws.serverSend({
          event_type: "signals_computed",
          signal_attribution: { rav: 0.04, scs: 0.02, nli: 0.01, ics: 0.015, vgs: 0.0 },
          contradicted_claims: [],
        });
      });

      expect(screen.getByText("0.040")).toBeInTheDocument(); // rav
      expect(screen.getByText("0.020")).toBeInTheDocument(); // scs
      expect(screen.getByText("0.010")).toBeInTheDocument(); // nli
      expect(screen.getByText("0.015")).toBeInTheDocument(); // ics
      expect(screen.getByText("0.000")).toBeInTheDocument(); // vgs
      expect(screen.getByText("ics")).toBeInTheDocument();
      expect(
        screen.getByText(/All decomposed claims consistent with retrieved knowledge/i)
      ).toBeInTheDocument();

      // Progressive Stage 3: verification_complete
      act(() => {
        ws.serverSend({
          event_type: "verification_complete",
          hrs_score: 0.035,
          risk_tier: "LOW",
          conformal_interval: { lower: 0.01, upper: 0.08 },
          correction_applied: false,
          verified_response: null,
        });
      });

      await waitFor(() => {
        expect(screen.getByText("Verification Complete")).toBeInTheDocument();
        expect(screen.getByText("0.035")).toBeInTheDocument(); // HRS
        expect(screen.getByText("LOW")).toBeInTheDocument(); // Tier
        expect(screen.getByText("[0.010, 0.080]")).toBeInTheDocument(); // CI
      });
    });

    it("renders contradiction warnings and applied corrections", async () => {
      const token = createMockJwt({
        sub: "usr_tester",
        tenant_id: "tenant_audit",
        role: "tenant_admin",
        exp: Math.floor(Date.now() / 1000) + 3600,
      });

      render(
        <AuthProvider initialToken={token}>
          <LiveStreamView />
        </AuthProvider>
      );

      const ws = MockWebSocket.instances[0];
      await waitFor(() => expect(ws.readyState).toBe(1));

      act(() => {
        ws.serverSend({ event_type: "connection_pending_auth" });
        ws.serverSend({ event_type: "connection_established" });
      });

      fireEvent.change(screen.getByLabelText(/LLM Response to Verify/i), {
        target: { value: "The moon is made of green cheese." },
      });

      fireEvent.click(screen.getByRole("button", { name: /verify via stream/i }));

      // Send signals with contradicted claim
      act(() => {
        ws.serverSend({
          event_type: "signals_computed",
          signal_attribution: { rav: 0.85, scs: 0.7, nli: 0.9, vgs: 0.0 },
          contradicted_claims: ["c-moon-1"],
        });
      });

      expect(screen.getByText(/Contradictions detected in claims:/i)).toBeInTheDocument();
      expect(screen.getByText("c-moon-1")).toBeInTheDocument();

      // Send complete with correction applied
      act(() => {
        ws.serverSend({
          event_type: "verification_complete",
          hrs_score: 0.88,
          risk_tier: "CRITICAL",
          conformal_interval: { lower: 0.81, upper: 0.95 },
          correction_applied: true,
          verified_response: "The moon is a rocky celestial body composed primarily of silicate rock and metals.",
        });
      });

      await waitFor(() => {
        expect(screen.getByText("CRITICAL")).toBeInTheDocument();
        expect(screen.getByText("0.880")).toBeInTheDocument();
        expect(screen.getByText("Correction Loop Applied")).toBeInTheDocument();
        expect(
          screen.getByText(
            "The moon is a rocky celestial body composed primarily of silicate rock and metals."
          )
        ).toBeInTheDocument();
      });
    });
  });

  describe("Form Controls & Duplicate Prevention", () => {
    it("disables submit button when response is empty or when disconnected", async () => {
      const token = createMockJwt({
        sub: "usr_tester",
        tenant_id: "tenant_audit",
        role: "tenant_admin",
        exp: Math.floor(Date.now() / 1000) + 3600,
      });

      render(
        <AuthProvider initialToken={token}>
          <LiveStreamView />
        </AuthProvider>
      );

      const submitBtn = screen.getByRole("button", { name: /verify via stream/i });

      // Initially disconnected / connecting -> disabled
      expect(submitBtn).toBeDisabled();

      const ws = MockWebSocket.instances[0];
      await waitFor(() => expect(ws.readyState).toBe(1));

      act(() => {
        ws.serverSend({ event_type: "connection_pending_auth" });
        ws.serverSend({ event_type: "connection_established" });
      });

      // Still disabled because response text is empty
      expect(submitBtn).toBeDisabled();

      // Entering whitespace only remains disabled
      fireEvent.change(screen.getByLabelText(/LLM Response to Verify/i), {
        target: { value: "   " },
      });
      expect(submitBtn).toBeDisabled();

      // Entering valid response enables button
      fireEvent.change(screen.getByLabelText(/LLM Response to Verify/i), {
        target: { value: "Valid proposition." },
      });
      expect(submitBtn).toBeEnabled();
    });

    it("clears results when Reset button is clicked", async () => {
      const token = createMockJwt({
        sub: "usr_tester",
        tenant_id: "tenant_audit",
        role: "tenant_admin",
        exp: Math.floor(Date.now() / 1000) + 3600,
      });

      render(
        <AuthProvider initialToken={token}>
          <LiveStreamView />
        </AuthProvider>
      );

      const ws = MockWebSocket.instances[0];
      await waitFor(() => expect(ws.readyState).toBe(1));

      act(() => {
        ws.serverSend({ event_type: "connection_pending_auth" });
        ws.serverSend({ event_type: "connection_established" });
      });

      fireEvent.change(screen.getByLabelText(/LLM Response to Verify/i), {
        target: { value: "Test claim to reset." },
      });
      fireEvent.click(screen.getByRole("button", { name: /verify via stream/i }));

      act(() => {
        ws.serverSend({
          event_type: "claims_extracted",
          claims: [{ claim_id: "c-reset", text: "Reset me", type: "factual" }],
        });
      });

      expect(screen.getByText("Reset me")).toBeInTheDocument();

      // Click Reset
      const resetBtn = screen.getByRole("button", { name: /reset/i });
      fireEvent.click(resetBtn);

      expect(screen.queryByText("Reset me")).not.toBeInTheDocument();
    });

    it("allows manual disconnect and reconnect", async () => {
      const token = createMockJwt({
        sub: "usr_tester",
        tenant_id: "tenant_audit",
        role: "tenant_admin",
        exp: Math.floor(Date.now() / 1000) + 3600,
      });

      render(
        <AuthProvider initialToken={token}>
          <LiveStreamView />
        </AuthProvider>
      );

      const ws = MockWebSocket.instances[0];
      await waitFor(() => expect(ws.readyState).toBe(1));

      act(() => {
        ws.serverSend({ event_type: "connection_pending_auth" });
        ws.serverSend({ event_type: "connection_established" });
      });

      // Disconnect
      const disconnectBtn = screen.getByRole("button", { name: /disconnect/i });
      fireEvent.click(disconnectBtn);

      expect(screen.getByText("Disconnected")).toBeInTheDocument();

      // Reconnect
      const connectBtn = screen.getByRole("button", { name: /connect/i });
      fireEvent.click(connectBtn);

      expect(MockWebSocket.instances.length).toBe(2);
      expect(screen.getByText("Connecting...")).toBeInTheDocument();
    });
  });

  describe("Canonical RBAC UX Gating Across All 5 Roles", () => {
    it("SUPER_ADMIN: granted access (possesses VERIFY_WRITE)", () => {
      const token = createMockJwt({
        sub: "usr_super",
        tenant_id: "t_super",
        role: ROLES.SUPER_ADMIN,
        exp: Math.floor(Date.now() / 1000) + 3600,
      });

      render(
        <AuthProvider initialToken={token}>
          <LiveStreamView />
        </AuthProvider>
      );

      expect(screen.queryByText("Live Stream Access Restricted")).not.toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "Live Verification Stream" })).toBeInTheDocument();
    });

    it("TENANT_ADMIN: granted access (possesses VERIFY_WRITE)", () => {
      const token = createMockJwt({
        sub: "usr_tenant_admin",
        tenant_id: "t_admin",
        role: ROLES.TENANT_ADMIN,
        exp: Math.floor(Date.now() / 1000) + 3600,
      });

      render(
        <AuthProvider initialToken={token}>
          <LiveStreamView />
        </AuthProvider>
      );

      expect(screen.queryByText("Live Stream Access Restricted")).not.toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "Live Verification Stream" })).toBeInTheDocument();
    });

    it("API_CLIENT: granted access (possesses VERIFY_WRITE)", () => {
      const token = createMockJwt({
        sub: "usr_api_key",
        tenant_id: "t_client",
        role: ROLES.API_CLIENT,
        exp: Math.floor(Date.now() / 1000) + 3600,
      });

      render(
        <AuthProvider initialToken={token}>
          <LiveStreamView />
        </AuthProvider>
      );

      expect(screen.queryByText("Live Stream Access Restricted")).not.toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "Live Verification Stream" })).toBeInTheDocument();
    });

    it("OPERATOR: access restricted with AccessDenied (lacks VERIFY_WRITE)", () => {
      const token = createMockJwt({
        sub: "usr_operator",
        tenant_id: "t_ops",
        role: ROLES.OPERATOR,
        exp: Math.floor(Date.now() / 1000) + 3600,
      });

      render(
        <AuthProvider initialToken={token}>
          <LiveStreamView />
        </AuthProvider>
      );

      expect(screen.getByText("Live Stream Access Restricted")).toBeInTheDocument();
      expect(screen.getByText(/verify:write/i)).toBeInTheDocument();
      expect(screen.getByText("operator")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /verify via stream/i })).not.toBeInTheDocument();
    });

    it("VIEWER: access restricted with AccessDenied (lacks VERIFY_WRITE)", () => {
      const token = createMockJwt({
        sub: "usr_viewer",
        tenant_id: "t_view",
        role: ROLES.VIEWER,
        exp: Math.floor(Date.now() / 1000) + 3600,
      });

      render(
        <AuthProvider initialToken={token}>
          <LiveStreamView />
        </AuthProvider>
      );

      expect(screen.getByText("Live Stream Access Restricted")).toBeInTheDocument();
      expect(screen.getByText(/verify:write/i)).toBeInTheDocument();
      expect(screen.getByText("viewer")).toBeInTheDocument();
    });

    it("Unauthenticated user: access restricted with AccessDenied", () => {
      render(
        <AuthProvider initialToken={null}>
          <LiveStreamView />
        </AuthProvider>
      );

      expect(screen.getByText("Live Stream Access Restricted")).toBeInTheDocument();
      expect(screen.getByText(/verify:write/i)).toBeInTheDocument();
    });
  });

  describe("Security Boundaries & Tenant Invariants", () => {
    it("does not render any client tenant selector, role dropdown, or X-Tenant-ID input", () => {
      const token = createMockJwt({
        sub: "usr_test",
        tenant_id: "sec_tenant",
        role: "super_admin",
        exp: Math.floor(Date.now() / 1000) + 3600,
      });

      render(
        <AuthProvider initialToken={token}>
          <LiveStreamView />
        </AuthProvider>
      );

      // Invariants: No tenant selection dropdown or input
      expect(screen.queryByLabelText(/select tenant/i)).not.toBeInTheDocument();
      expect(screen.queryByRole("combobox", { name: /tenant/i })).not.toBeInTheDocument();
      expect(screen.queryByLabelText(/switch role/i)).not.toBeInTheDocument();
      expect(screen.queryByPlaceholderText(/tenant_id/i)).not.toBeInTheDocument();
    });
  });

  describe("Contract Fidelity & Verification Signals (P2.9 Remediation)", () => {
    it("renders all five active verification signals (RAV, SCS, NLI, ICS, VGS) including ICS without omission", async () => {
      const token = createMockJwt({
        sub: "usr_tester_signals",
        tenant_id: "tenant_five_signals",
        role: "tenant_admin",
        exp: Math.floor(Date.now() / 1000) + 3600,
      });

      render(
        <AuthProvider initialToken={token}>
          <LiveStreamView />
        </AuthProvider>
      );

      const ws = MockWebSocket.instances[0];
      await waitFor(() => expect(ws.readyState).toBe(1));

      act(() => {
        ws.serverSend({ event_type: "connection_pending_auth" });
        ws.serverSend({ event_type: "connection_established" });
      });

      fireEvent.change(screen.getByLabelText(/LLM Response to Verify/i), {
        target: { value: "Testing five-signal attribution." },
      });
      fireEvent.click(screen.getByRole("button", { name: /verify via stream/i }));

      // Server emits signals_computed with all 5 active signals
      act(() => {
        ws.serverSend({
          event_type: "signals_computed",
          signal_attribution: {
            rav: 0.123,
            scs: 0.234,
            nli: 0.345,
            ics: 0.456,
            vgs: 0.567,
          },
          contradicted_claims: [],
        });
      });

      // Assert all 5 signals are visibly rendered with their exact scores
      expect(screen.getByText("rav")).toBeInTheDocument();
      expect(screen.getByText("0.123")).toBeInTheDocument();

      expect(screen.getByText("scs")).toBeInTheDocument();
      expect(screen.getByText("0.234")).toBeInTheDocument();

      expect(screen.getByText("nli")).toBeInTheDocument();
      expect(screen.getByText("0.345")).toBeInTheDocument();

      expect(screen.getByText("ics")).toBeInTheDocument();
      expect(screen.getByText("0.456")).toBeInTheDocument();

      expect(screen.getByText("vgs")).toBeInTheDocument();
      expect(screen.getByText("0.567")).toBeInTheDocument();
    });

    it("handles non-multimodal response where vgs is null by rendering N/A while preserving ICS", async () => {
      const token = createMockJwt({
        sub: "usr_tester_text_only",
        tenant_id: "tenant_text_only",
        role: "tenant_admin",
        exp: Math.floor(Date.now() / 1000) + 3600,
      });

      render(
        <AuthProvider initialToken={token}>
          <LiveStreamView />
        </AuthProvider>
      );

      const ws = MockWebSocket.instances[0];
      await waitFor(() => expect(ws.readyState).toBe(1));

      act(() => {
        ws.serverSend({ event_type: "connection_pending_auth" });
        ws.serverSend({ event_type: "connection_established" });
      });

      fireEvent.change(screen.getByLabelText(/LLM Response to Verify/i), {
        target: { value: "Text only without images." },
      });
      fireEvent.click(screen.getByRole("button", { name: /verify via stream/i }));

      // Server emits signals_computed with vgs: null (text-only verification)
      act(() => {
        ws.serverSend({
          event_type: "signals_computed",
          signal_attribution: {
            rav: 0.05,
            scs: 0.02,
            nli: 0.01,
            ics: 0.08,
            vgs: null,
          },
          contradicted_claims: [],
        });
      });

      expect(screen.getByText("ics")).toBeInTheDocument();
      expect(screen.getByText("0.080")).toBeInTheDocument();
      expect(screen.getByText("vgs")).toBeInTheDocument();
      expect(screen.getByText("N/A")).toBeInTheDocument();
    });

    it("verifies exact first-message authentication payload format and prevents verification before auth", async () => {
      const token = createMockJwt({
        sub: "usr_auth_verifier",
        tenant_id: "tenant_auth_check",
        role: "tenant_admin",
        exp: Math.floor(Date.now() / 1000) + 3600,
      });

      render(
        <AuthProvider initialToken={token}>
          <LiveStreamView />
        </AuthProvider>
      );

      const ws = MockWebSocket.instances[0];
      await waitFor(() => expect(ws.readyState).toBe(1));

      // Attempting to submit before connection_pending_auth and connection_established
      const submitBtn = screen.getByRole("button", { name: /verify via stream/i });
      expect(submitBtn).toBeDisabled();

      // Emit pending auth
      act(() => {
        ws.serverSend({ event_type: "connection_pending_auth" });
      });

      // Still disabled because connection_established not received yet
      expect(submitBtn).toBeDisabled();

      // Verify exact first-message shape conforms to { type: "auth", token: "<JWT>" }
      expect(ws.sent.length).toBe(1);
      const authMessage = JSON.parse(ws.sent[0]);
      expect(authMessage).toEqual({
        type: "auth",
        token: token,
      });

      // Now establish connection
      act(() => {
        ws.serverSend({
          event_type: "connection_established",
          tenant_id: "tenant_auth_check",
          role: "tenant_admin",
        });
      });

      // Entering response now enables submission
      fireEvent.change(screen.getByLabelText(/LLM Response to Verify/i), {
        target: { value: "Now authorized to submit." },
      });
      expect(submitBtn).toBeEnabled();
    });
  });
});
