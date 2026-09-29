/**
 * WebSocket Stream API helpers for MIRAGE Gateway.
 *
 * Implements Technical Architecture §3.4 & §7, and Security & Access §4.4:
 * - Authoritative WebSocket endpoint `/v1/verify/stream`.
 * - Centralized URL resolution supporting secure (wss:) and unencrypted (ws:) protocols.
 */

/**
 * Resolve the canonical WebSocket URL for the verification stream.
 *
 * @param {string} [customUrl] - Optional explicit override URL
 * @returns {string} Fully-qualified ws:// or wss:// URL
 */
export function getStreamWebSocketUrl(customUrl) {
  if (customUrl) return customUrl;

  if (typeof import.meta !== "undefined" && import.meta.env?.VITE_WS_URL) {
    return import.meta.env.VITE_WS_URL;
  }

  if (typeof window !== "undefined" && window.location) {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    // In local development with Vite dev server (port 3000), redirect to gateway on 8000
    if (window.location.port === "3000") {
      return `${proto}//${window.location.hostname}:8000/v1/verify/stream`;
    }
    return `${proto}//${host}/v1/verify/stream`;
  }

  return "ws://localhost:8000/v1/verify/stream";
}
