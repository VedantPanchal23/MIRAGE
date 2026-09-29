import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  apiFetch,
  setApiToken,
  getApiToken,
  onUnauthorized,
  ApiError,
} from "../client";

describe("Centralized API Client (client.js)", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    setApiToken(null);
    onUnauthorized(null);
    global.fetch = vi.fn();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("maintains in-memory token state without persistence to localStorage", () => {
    expect(getApiToken()).toBeNull();
    setApiToken("test_token_123");
    expect(getApiToken()).toBe("test_token_123");

    // Strips Bearer prefix automatically
    setApiToken("Bearer prefixed_token_456");
    expect(getApiToken()).toBe("prefixed_token_456");

    setApiToken(null);
    expect(getApiToken()).toBeNull();
  });

  it("attaches Authorization Bearer header when token is present", async () => {
    setApiToken("my_jwt_token");

    global.fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ status: "ok" }),
    });

    const res = await apiFetch("/v1/health");
    expect(res).toEqual({ status: "ok" });

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [url, options] = global.fetch.mock.calls[0];
    expect(url).toBe("/v1/health");
    expect(options.headers.Authorization).toBe("Bearer my_jwt_token");
    expect(options.headers.Accept).toBe("application/json");
  });

  it("allows per-call token override", async () => {
    setApiToken("default_token");

    global.fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ status: "ok" }),
    });

    await apiFetch("/v1/health", { token: "override_token" });

    const [, options] = global.fetch.mock.calls[0];
    expect(options.headers.Authorization).toBe("Bearer override_token");
  });

  it("formats query parameters into URL correctly", async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ items: [] }),
    });

    await apiFetch("/v1/dashboard/sessions", {
      params: {
        risk_tier: "HIGH",
        page: 2,
        page_size: 25,
        empty_val: null,
        ignored_val: undefined,
      },
    });

    const [url] = global.fetch.mock.calls[0];
    expect(url).toBe("/v1/dashboard/sessions?risk_tier=HIGH&page=2&page_size=25");
  });

  it("appends query parameters when endpoint already has query string", async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({}),
    });

    await apiFetch("/v1/test?fixed=1", {
      params: { extra: "2" },
    });

    const [url] = global.fetch.mock.calls[0];
    expect(url).toBe("/v1/test?fixed=1&extra=2");
  });

  it("serializes JSON request bodies and sets Content-Type", async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ success: true }),
    });

    const bodyPayload = { operator_id: "op_007" };
    await apiFetch("/v1/alerts/alt_1/acknowledge", {
      method: "POST",
      body: bodyPayload,
    });

    const [, options] = global.fetch.mock.calls[0];
    expect(options.method).toBe("POST");
    expect(options.headers["Content-Type"]).toBe("application/json");
    expect(options.body).toBe(JSON.stringify(bodyPayload));
  });

  it("handles 204 No Content response gracefully", async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      status: 204,
      headers: new Headers(),
    });

    const res = await apiFetch("/v1/resource", { method: "DELETE" });
    expect(res).toBeNull();
  });

  it("handles binary Blob responses (PDF or ndjson)", async () => {
    const mockBlob = new Blob(["fake-pdf-content"], { type: "application/pdf" });
    global.fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/pdf" }),
      blob: async () => mockBlob,
    });

    const res = await apiFetch("/v1/reports/rep_1/pdf");
    expect(res).toBe(mockBlob);
  });

  it("surfaces structured ApiError on backend HTTP errors", async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      status: 403,
      statusText: "Forbidden",
      headers: new Headers({
        "content-type": "application/json",
        "x-trace-id": "tr_backend_123",
      }),
      json: async () => ({
        detail: "Access denied: Role 'viewer' lacks permission 'verify:write'",
        error: {
          code: "FORBIDDEN",
          message: "Access denied: Role 'viewer' lacks permission 'verify:write'",
          details: { required: "verify:write" },
          trace_id: "tr_backend_123",
          timestamp: "2026-09-28T10:00:00Z",
        },
      }),
    });

    await expect(apiFetch("/v1/verify")).rejects.toThrow(ApiError);

    try {
      global.fetch.mockResolvedValueOnce({
        ok: false,
        status: 403,
        statusText: "Forbidden",
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({
          detail: "Access denied: Role 'viewer' lacks permission 'verify:write'",
          error: {
            code: "FORBIDDEN",
            message: "Access denied: Role 'viewer' lacks permission 'verify:write'",
            details: { required: "verify:write" },
            trace_id: "tr_backend_123",
          },
        }),
      });
      await apiFetch("/v1/verify");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect(err.status).toBe(403);
      expect(err.code).toBe("FORBIDDEN");
      expect(err.message).toBe("Access denied: Role 'viewer' lacks permission 'verify:write'");
      expect(err.details).toEqual({ required: "verify:write" });
      expect(err.traceId).toBe("tr_backend_123");
    }
  });

  it("handles FastAPI validation error arrays cleanly", async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      status: 422,
      statusText: "Unprocessable Entity",
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({
        detail: [
          { loc: ["body", "start_date"], msg: "field required", type: "value_error.missing" },
        ],
        error: {
          code: "VALIDATION_ERROR",
          message: "Invalid request schema or parameters",
          details: [
            { loc: ["body", "start_date"], msg: "field required", type: "value_error.missing" },
          ],
        },
      }),
    });

    try {
      await apiFetch("/v1/reports/generate", { method: "POST", body: {} });
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect(err.status).toBe(422);
      expect(err.code).toBe("VALIDATION_ERROR");
      expect(Array.isArray(err.details)).toBe(true);
    }
  });

  it("triggers onUnauthorized callback on HTTP 401", async () => {
    const unauthorizedCallback = vi.fn();
    onUnauthorized(unauthorizedCallback);

    global.fetch.mockResolvedValueOnce({
      ok: false,
      status: 401,
      statusText: "Unauthorized",
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({
        detail: "Authentication token has expired",
        error: { code: "UNAUTHORIZED", message: "Authentication token has expired" },
      }),
    });

    await expect(apiFetch("/v1/dashboard/stats")).rejects.toThrow(ApiError);
    expect(unauthorizedCallback).toHaveBeenCalledTimes(1);
  });

  it("handles network failure by converting to ApiError with status 0", async () => {
    global.fetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    try {
      await apiFetch("/v1/health");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect(err.status).toBe(0);
      expect(err.code).toBe("NETWORK_ERROR");
      expect(err.message).toBe("Failed to fetch");
    }
  });
});
