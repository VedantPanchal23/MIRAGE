import { useState, useEffect, useRef, useCallback } from "react";
import { getStreamWebSocketUrl } from "../api/stream";
import { getApiToken } from "../api/client";
import { PERMISSIONS } from "../context/AuthContext";

/**
 * Stream lifecycle state enum.
 */
export const STREAM_STATUS = Object.freeze({
  DISCONNECTED: "disconnected",
  CONNECTING: "connecting",
  AWAITING_AUTH: "awaiting_auth",
  READY: "ready",
  STREAMING: "streaming",
  COMPLETED: "completed",
  ERROR: "error",
});

/**
 * Dedicated React hook managing the MIRAGE /v1/verify/stream WebSocket lifecycle.
 *
 * Implements Technical Architecture §3.4 & §7, and Security & Access §4.4:
 * 1. Explicit two-step authentication handshake:
 *    - Connects WebSocket transport.
 *    - Waits for server "connection_pending_auth" challenge.
 *    - Dispatches first-message JWT authentication payload: { type: "auth", token }.
 *    - Awaits "connection_established" before permitting verification submissions.
 * 2. RBAC UX authorization check:
 *    - Strictly enforces PERMISSIONS.VERIFY_WRITE before attempting connection.
 *    - Will not attempt connection if token is missing.
 * 3. Progressive event processing:
 *    - "claims_extracted": records decomposed atomic propositions.
 *    - "signals_computed": records multi-signal attribution (RAV, SCS, NLI, VGS) & contradictions.
 *    - "verification_complete": records final calibrated HRS score, risk tier, CI, and rewrite.
 * 4. Resilient close handling:
 *    - Close code 1008 (Policy Violation) blocks automated reconnection.
 *    - Clean teardown on component unmount.
 *
 * @param {object} [options={}]
 * @param {string} [options.url] - Optional custom WebSocket URL override
 * @param {string} [options.token] - Optional in-memory JWT token override
 * @param {Function} [options.hasPermission] - Optional permission check callback
 * @param {boolean} [options.autoConnect=false] - Whether to connect on mount if permitted
 */
export function useWebSocketStream(options = {}) {
  const {
    url,
    token: propToken,
    hasPermission,
    autoConnect = false,
  } = options;

  const [status, setStatus] = useState(STREAM_STATUS.DISCONNECTED);
  const [sessionInfo, setSessionInfo] = useState(null);
  const [events, setEvents] = useState([]);
  const [claims, setClaims] = useState([]);
  const [signals, setSignals] = useState(null);
  const [verdict, setVerdict] = useState(null);
  const [error, setError] = useState(null);

  // Retrieve current in-memory token
  const effectiveToken = propToken !== undefined ? propToken : getApiToken();

  // Stable refs to prevent callback re-creation and accidental unmounts
  const tokenRef = useRef(effectiveToken);
  tokenRef.current = effectiveToken;

  const hasPermissionRef = useRef(hasPermission);
  hasPermissionRef.current = hasPermission;

  const urlRef = useRef(url);
  urlRef.current = url;

  const statusRef = useRef(status);

  // Synchronous status updater keeping statusRef strictly synchronized
  const updateStatus = useCallback((nextStatus) => {
    if (typeof nextStatus === "function") {
      setStatus((prev) => {
        const resolved = nextStatus(prev);
        statusRef.current = resolved;
        return resolved;
      });
    } else {
      statusRef.current = nextStatus;
      setStatus(nextStatus);
    }
  }, []);

  const wsRef = useRef(null);
  const reconnectBlockedRef = useRef(false);
  const isMountedRef = useRef(true);

  const addEvent = useCallback((eventType, data) => {
    if (!isMountedRef.current) return;
    const newEntry = {
      id: `${Date.now()}-${Math.random().toString(36).substr(2, 6)}`,
      timestamp: new Date().toISOString(),
      eventType,
      data,
    };
    setEvents((prev) => [...prev, newEntry]);
  }, []);

  /**
   * Close any open WebSocket cleanly.
   */
  const disconnect = useCallback(() => {
    reconnectBlockedRef.current = true;
    if (wsRef.current) {
      try {
        wsRef.current.close(1000, "User initiated disconnect");
      } catch {
        // ignore
      }
      wsRef.current = null;
    }
    if (isMountedRef.current) {
      updateStatus(STREAM_STATUS.DISCONNECTED);
    }
  }, [updateStatus]);

  /**
   * Reset all progressive verification state.
   */
  const reset = useCallback(() => {
    setEvents([]);
    setClaims([]);
    setSignals(null);
    setVerdict(null);
    setError(null);
    updateStatus((prev) =>
      prev === STREAM_STATUS.COMPLETED || prev === STREAM_STATUS.STREAMING
        ? STREAM_STATUS.READY
        : prev
    );
  }, [updateStatus]);

  /**
   * Initiate WebSocket connection and authentication handshake.
   */
  const connect = useCallback(() => {
    // Avoid double connections
    if (wsRef.current && (wsRef.current.readyState === 0 || wsRef.current.readyState === 1)) {
      return;
    }

    const currentPermissionCheck = hasPermissionRef.current;
    if (currentPermissionCheck && !currentPermissionCheck(PERMISSIONS.VERIFY_WRITE)) {
      updateStatus(STREAM_STATUS.ERROR);
      setError("Permission verify:write is required to access the verification stream");
      return;
    }

    const currentToken = tokenRef.current;
    if (!currentToken) {
      updateStatus(STREAM_STATUS.ERROR);
      setError("Authentication token required to connect to verification stream");
      return;
    }

    reconnectBlockedRef.current = false;
    updateStatus(STREAM_STATUS.CONNECTING);
    setError(null);

    const wsUrl = getStreamWebSocketUrl(urlRef.current);

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        // Transport connected, awaiting challenge
      };

      ws.onmessage = (event) => {
        if (!isMountedRef.current) return;

        let data;
        try {
          data = JSON.parse(event.data);
        } catch {
          addEvent("raw_message", { content: event.data });
          return;
        }

        const eventType = data.event_type || data.event || data.type;

        // 1. Awaiting Auth -> Server emits connection_pending_auth
        if (eventType === "connection_pending_auth") {
          updateStatus(STREAM_STATUS.AWAITING_AUTH);
          addEvent("connection_pending_auth", data);

          const tokenToSend = tokenRef.current;
          if (!tokenToSend) {
            updateStatus(STREAM_STATUS.ERROR);
            setError("No authentication token available");
            try {
              ws.close(1008, "Missing token");
            } catch {
              // ignore
            }
            return;
          }

          // First-message authentication: NEVER LOG THE TOKEN
          const authPayload = {
            type: "auth",
            token: tokenToSend,
          };
          try {
            ws.send(JSON.stringify(authPayload));
          } catch {
            updateStatus(STREAM_STATUS.ERROR);
            setError("Failed to transmit authentication message");
          }
          return;
        }

        // 2. Authentication successful
        if (eventType === "connection_established") {
          updateStatus(STREAM_STATUS.READY);
          setError(null);
          setSessionInfo({
            tenantId: data.tenant_id,
            role: data.role,
            traceId: data.trace_id,
          });
          addEvent("connection_established", data);
          return;
        }

        // 3. Authentication failed
        if (eventType === "auth_failure") {
          reconnectBlockedRef.current = true;
          updateStatus(STREAM_STATUS.ERROR);
          const errMsg = data.message || data.error_code || "Authentication failed";
          setError(errMsg);
          addEvent("auth_failure", data);
          return;
        }

        // 4. Claims extracted
        if (eventType === "claims_extracted") {
          setClaims(Array.isArray(data.claims) ? data.claims : []);
          addEvent("claims_extracted", data);
          return;
        }

        // 5. Signals computed
        if (eventType === "signals_computed") {
          setSignals({
            signalAttribution: data.signal_attribution || null,
            contradictedClaims: Array.isArray(data.contradicted_claims)
              ? data.contradicted_claims
              : [],
          });
          addEvent("signals_computed", data);
          return;
        }

        // 6. Verification completed
        if (eventType === "verification_complete") {
          const finalVerdict = {
            hrsScore: data.hrs_score !== undefined ? data.hrs_score : data.hrs,
            riskTier: data.risk_tier || data.tier || "UNKNOWN",
            conformalInterval: data.conformal_interval || null,
            correctionApplied: Boolean(data.correction_applied),
            verifiedResponse: data.verified_response || null,
            traceId: data.trace_id || null,
          };
          setVerdict(finalVerdict);
          updateStatus(STREAM_STATUS.COMPLETED);
          addEvent("verification_complete", data);
          return;
        }

        // 7. General error event
        if (eventType === "error") {
          setError(data.message || "Verification stream error occurred");
          addEvent("error", data);
          updateStatus((prev) =>
            prev === STREAM_STATUS.STREAMING ? STREAM_STATUS.READY : prev
          );
          return;
        }

        // Fallback for custom or unexpected events
        addEvent(eventType || "unknown", data);
      };

      ws.onerror = () => {
        if (!isMountedRef.current) return;
        updateStatus(STREAM_STATUS.ERROR);
        setError("WebSocket transport connection error");
      };

      ws.onclose = (closeEvent) => {
        if (!isMountedRef.current) return;

        // Policy violation 1008 indicates auth rejection/unauthorized access
        if (closeEvent.code === 1008) {
          reconnectBlockedRef.current = true;
          updateStatus(STREAM_STATUS.ERROR);
          setError((prev) => prev || "Stream authentication rejected (Policy Violation 1008)");
          return;
        }

        // Intentional disconnect or non-fatal close
        updateStatus((prev) => {
          if (prev === STREAM_STATUS.ERROR) return STREAM_STATUS.ERROR;
          return STREAM_STATUS.DISCONNECTED;
        });
      };
    } catch (initErr) {
      if (isMountedRef.current) {
        updateStatus(STREAM_STATUS.ERROR);
        setError(initErr.message || "Failed to initialize WebSocket connection");
      }
    }
  }, [addEvent, updateStatus]);

  /**
   * Submit a prompt + response pair for real-time verification.
   *
   * @param {object} payload
   * @param {string} payload.prompt - User prompt context
   * @param {string} payload.response - Model response to verify
   * @param {string} [payload.modelId="gpt-4o"] - Originating model identifier
   * @param {Array} [payload.images=[]] - Optional image references
   */
  const submitVerification = useCallback(
    ({ prompt, response, modelId = "gpt-4o", images = [] }) => {
      if (!wsRef.current || wsRef.current.readyState !== 1) {
        throw new Error("Stream connection is not active");
      }

      const currentStatus = statusRef.current;
      if (currentStatus === STREAM_STATUS.STREAMING) {
        // Prevent duplicate concurrent submissions
        return false;
      }

      if (currentStatus !== STREAM_STATUS.READY && currentStatus !== STREAM_STATUS.COMPLETED) {
        throw new Error("Verification cannot be submitted before authentication completes");
      }

      if (!response || !response.trim()) {
        throw new Error("Response text is required for verification");
      }

      // Reset prior progressive outputs for new session
      setClaims([]);
      setSignals(null);
      setVerdict(null);
      setError(null);
      updateStatus(STREAM_STATUS.STREAMING);

      // Backend verification payload shape:
      // Note: Client-supplied tenant_id is strictly omitted. Authoritative tenant derives exclusively from validated JWT.
      const payload = {
        prompt: (prompt || "").trim() || response.trim(),
        response: response.trim(),
        model_id: (modelId || "gpt-4o").trim(),
        images: Array.isArray(images) ? images : [],
      };

      wsRef.current.send(JSON.stringify(payload));
      return true;
    },
    [updateStatus]
  );

  // Lifecycle & unmount cleanup
  useEffect(() => {
    isMountedRef.current = true;

    if (autoConnect) {
      connect();
    }

    return () => {
      isMountedRef.current = false;
      if (wsRef.current) {
        try {
          wsRef.current.close(1000, "Component unmounted");
        } catch {
          // ignore
        }
        wsRef.current = null;
      }
    };
  }, [autoConnect, connect]);

  return {
    status,
    isStreaming: status === STREAM_STATUS.STREAMING,
    sessionInfo,
    events,
    claims,
    signals,
    verdict,
    error,
    connect,
    disconnect,
    submitVerification,
    reset,
  };
}

export default useWebSocketStream;
