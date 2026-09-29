import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useWebSocketStream, STREAM_STATUS } from "../useWebSocketStream";
import { PERMISSIONS } from "../../context/AuthContext";

/**
 * Mock WebSocket implementation for deterministic hook lifecycle tests.
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

describe("useWebSocketStream Hook Unit Tests", () => {
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

  it("initializes with DISCONNECTED status and empty state", () => {
    const { result } = renderHook(() =>
      useWebSocketStream({
        token: "test.jwt.token",
        hasPermission: () => true,
        autoConnect: false,
      })
    );

    expect(result.current.status).toBe(STREAM_STATUS.DISCONNECTED);
    expect(result.current.isStreaming).toBe(false);
    expect(result.current.claims).toEqual([]);
    expect(result.current.signals).toBeNull();
    expect(result.current.verdict).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it("does not connect if permission check fails", () => {
    const { result } = renderHook(() =>
      useWebSocketStream({
        token: "valid.token",
        hasPermission: (perm) => perm !== PERMISSIONS.VERIFY_WRITE,
        autoConnect: false,
      })
    );

    act(() => {
      result.current.connect();
    });

    expect(result.current.status).toBe(STREAM_STATUS.ERROR);
    expect(result.current.error).toContain("verify:write is required");
    expect(MockWebSocket.instances.length).toBe(0);
  });

  it("does not connect if authentication token is missing", () => {
    const { result } = renderHook(() =>
      useWebSocketStream({
        token: null,
        hasPermission: () => true,
        autoConnect: false,
      })
    );

    act(() => {
      result.current.connect();
    });

    expect(result.current.status).toBe(STREAM_STATUS.ERROR);
    expect(result.current.error).toContain("token required");
    expect(MockWebSocket.instances.length).toBe(0);
  });

  it("executes the two-step authentication handshake successfully", async () => {
    const { result } = renderHook(() =>
      useWebSocketStream({
        token: "sample.jwt.token",
        hasPermission: () => true,
        autoConnect: false,
      })
    );

    act(() => {
      result.current.connect();
    });

    expect(result.current.status).toBe(STREAM_STATUS.CONNECTING);
    expect(MockWebSocket.instances.length).toBe(1);
    const ws = MockWebSocket.instances[0];

    // Wait for transport open
    await vi.waitFor(() => {
      expect(ws.readyState).toBe(1);
    });

    // Server emits connection_pending_auth challenge
    act(() => {
      ws.serverSend({
        event_type: "connection_pending_auth",
        trace_id: "tr_auth_01",
        timeout_seconds: 10.0,
      });
    });

    expect(result.current.status).toBe(STREAM_STATUS.AWAITING_AUTH);

    // Verify client immediately dispatched first-message authentication payload
    expect(ws.sent.length).toBe(1);
    const sentAuth = JSON.parse(ws.sent[0]);
    expect(sentAuth).toEqual({
      type: "auth",
      token: "sample.jwt.token",
    });

    // Server validates and emits connection_established
    act(() => {
      ws.serverSend({
        event_type: "connection_established",
        trace_id: "tr_auth_01",
        status: "ready",
        tenant_id: "tenant_alpha",
        role: "operator",
      });
    });

    expect(result.current.status).toBe(STREAM_STATUS.READY);
    expect(result.current.sessionInfo).toEqual({
      tenantId: "tenant_alpha",
      role: "operator",
      traceId: "tr_auth_01",
    });
  });

  it("handles auth_failure and prevents reconnect loops on 1008 policy violation", async () => {
    const { result } = renderHook(() =>
      useWebSocketStream({
        token: "invalid.jwt.token",
        hasPermission: () => true,
        autoConnect: false,
      })
    );

    act(() => {
      result.current.connect();
    });

    const ws = MockWebSocket.instances[0];
    await vi.waitFor(() => expect(ws.readyState).toBe(1));

    // Server challenge
    act(() => {
      ws.serverSend({ event_type: "connection_pending_auth" });
    });

    // Server responds with auth_failure
    act(() => {
      ws.serverSend({
        event_type: "auth_failure",
        error_code: "INVALID_TOKEN",
        message: "Signature verification failed",
      });
      // Server closes with 1008 Policy Violation
      ws.close(1008, "Policy Violation");
    });

    expect(result.current.status).toBe(STREAM_STATUS.ERROR);
    expect(result.current.error).toBe("Signature verification failed");

    // Verify no automatic reconnect occurred
    expect(MockWebSocket.instances.length).toBe(1);
  });

  it("prevents verification submission before authentication succeeds", () => {
    const { result } = renderHook(() =>
      useWebSocketStream({
        token: "sample.jwt.token",
        hasPermission: () => true,
        autoConnect: false,
      })
    );

    expect(() => {
      result.current.submitVerification({
        prompt: "test",
        response: "test response",
      });
    }).toThrow(/Stream connection is not active/i);
  });

  it("streams progressive verification events (claims -> signals -> complete)", async () => {
    const { result } = renderHook(() =>
      useWebSocketStream({
        token: "valid.jwt.token",
        hasPermission: () => true,
        autoConnect: false,
      })
    );

    act(() => {
      result.current.connect();
    });

    const ws = MockWebSocket.instances[0];
    await vi.waitFor(() => expect(ws.readyState).toBe(1));

    act(() => {
      ws.serverSend({ event_type: "connection_pending_auth" });
      ws.serverSend({
        event_type: "connection_established",
        tenant_id: "tenant_authoritative",
        role: "tenant_admin",
      });
    });

    expect(result.current.status).toBe(STREAM_STATUS.READY);

    // Submit verification
    act(() => {
      const ok = result.current.submitVerification({
        prompt: "Who invented the telephone?",
        response: "Alexander Graham Bell was awarded the first US patent.",
        modelId: "gpt-4o",
      });
      expect(ok).toBe(true);
    });

    expect(result.current.status).toBe(STREAM_STATUS.STREAMING);
    expect(result.current.isStreaming).toBe(true);

    // Verify submitted payload omits client tenant_id
    expect(ws.sent.length).toBe(2); // [0] auth, [1] verification payload
    const submittedPayload = JSON.parse(ws.sent[1]);
    expect(submittedPayload.prompt).toBe("Who invented the telephone?");
    expect(submittedPayload.response).toBe(
      "Alexander Graham Bell was awarded the first US patent."
    );
    expect(submittedPayload.model_id).toBe("gpt-4o");
    expect(submittedPayload.tenant_id).toBeUndefined();

    // 1. Server emits claims_extracted
    act(() => {
      ws.serverSend({
        event_type: "claims_extracted",
        claims_count: 1,
        claims: [
          {
            claim_id: "c-001",
            text: "Alexander Graham Bell was awarded the first US patent.",
            type: "factual",
            criticality: "HIGH",
          },
        ],
      });
    });

    expect(result.current.claims.length).toBe(1);
    expect(result.current.claims[0].claim_id).toBe("c-001");

    // 2. Server emits signals_computed
    act(() => {
      ws.serverSend({
        event_type: "signals_computed",
        signal_attribution: { rav: 0.05, scs: 0.02, nli: 0.01, vgs: 0.0 },
        contradicted_claims: [],
      });
    });

    expect(result.current.signals.signalAttribution.rav).toBe(0.05);
    expect(result.current.signals.contradictedClaims).toEqual([]);

    // 3. Server emits verification_complete
    act(() => {
      ws.serverSend({
        event_type: "verification_complete",
        hrs_score: 0.045,
        risk_tier: "LOW",
        conformal_interval: { lower: 0.01, upper: 0.12 },
        correction_applied: false,
        verified_response: null,
      });
    });

    expect(result.current.status).toBe(STREAM_STATUS.COMPLETED);
    expect(result.current.isStreaming).toBe(false);
    expect(result.current.verdict.hrsScore).toBe(0.045);
    expect(result.current.verdict.riskTier).toBe("LOW");
    expect(result.current.verdict.conformalInterval).toEqual({
      lower: 0.01,
      upper: 0.12,
    });
  });

  it("prevents duplicate concurrent submissions while streaming is active", async () => {
    const { result } = renderHook(() =>
      useWebSocketStream({
        token: "valid.jwt.token",
        hasPermission: () => true,
        autoConnect: false,
      })
    );

    act(() => {
      result.current.connect();
    });

    const ws = MockWebSocket.instances[0];
    await vi.waitFor(() => expect(ws.readyState).toBe(1));

    act(() => {
      ws.serverSend({ event_type: "connection_pending_auth" });
      ws.serverSend({ event_type: "connection_established" });
    });

    await vi.waitFor(() => {
      expect(result.current.status).toBe(STREAM_STATUS.READY);
    });

    act(() => {
      result.current.submitVerification({
        prompt: "First request",
        response: "Response 1",
      });
    });

    expect(result.current.status).toBe(STREAM_STATUS.STREAMING);

    // Second submission while streaming should return false and not send another payload
    let duplicateResult;
    act(() => {
      duplicateResult = result.current.submitVerification({
        prompt: "Second request",
        response: "Response 2",
      });
    });

    expect(duplicateResult).toBe(false);
    expect(ws.sent.length).toBe(2); // auth + 1st verification only
  });

  it("cleans up WebSocket connection on component unmount", async () => {
    const { result, unmount } = renderHook(() =>
      useWebSocketStream({
        token: "token.to.unmount",
        hasPermission: () => true,
        autoConnect: true,
      })
    );

    const ws = MockWebSocket.instances[0];
    await vi.waitFor(() => expect(ws.readyState).toBe(1));

    unmount();

    expect(ws.readyState).toBe(3); // CLOSED
    expect(ws.closeCode).toBe(1000);
    expect(ws.closeReason).toBe("Component unmounted");
  });
});
