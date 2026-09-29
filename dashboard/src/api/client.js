/**
 * Centralized API Client for MIRAGE Gateway.
 *
 * Implements Technical Architecture §8, Security & Access §3, and PRD FR-DFT-01:
 * - Centralized fetch wrapper communicating with `/v1/*` endpoints.
 * - Attaches Bearer JWT authentication header when a token is present.
 * - Normalizes backend error responses (ApiError) preserving code, message, and trace_id.
 * - Handles 401 Unauthorized globally for proactive session invalidation.
 * - Supports JSON, void (204), and Blob (PDF/ndjson export) response payloads.
 *
 * SECURITY NOTICE:
 * Client-side token management is for session tracking only. The frontend is NEVER
 * the security authority; backend authorization and tenant isolation are authoritative.
 */

export class ApiError extends Error {
  constructor({ message, status, code, details = null, traceId = null }) {
    super(message || `API request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.code = code || (status ? `HTTP_${status}` : "UNKNOWN_ERROR");
    this.details = details;
    this.traceId = traceId;
  }
}

let activeToken = null;
let unauthorizedHandler = null;

/**
 * Update the in-memory active authentication token for all subsequent requests.
 * @param {string|null} token - JWT bearer token or null to clear
 */
export function setApiToken(token) {
  activeToken = token ? token.trim().replace(/^Bearer\s+/i, "") : null;
}

/**
 * Retrieve the current in-memory token.
 * @returns {string|null}
 */
export function getApiToken() {
  return activeToken;
}

/**
 * Register a callback to execute when the backend returns 401 Unauthorized.
 * @param {Function|null} handler - Function to invoke on 401
 */
export function onUnauthorized(handler) {
  unauthorizedHandler = typeof handler === "function" ? handler : null;
}

/**
 * Execute an HTTP request against the MIRAGE API.
 *
 * @param {string} endpoint - API path (e.g. "/v1/dashboard/stats")
 * @param {object} [options={}] - Fetch configuration options
 * @param {string} [options.method="GET"] - HTTP method
 * @param {object} [options.params] - URL query parameters
 * @param {*} [options.body] - Request body (JSON-serializable object, FormData, or Blob)
 * @param {object} [options.headers] - Additional HTTP headers
 * @param {string} [options.token] - Override token for this specific call
 * @returns {Promise<*>} Parsed response data, Blob, or null
 */
export async function apiFetch(endpoint, options = {}) {
  const {
    method = "GET",
    body,
    headers = {},
    params,
    token = activeToken,
    ...rest
  } = options;

  let url = endpoint;
  if (params && typeof params === "object") {
    const queryParams = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== "") {
        queryParams.append(key, String(value));
      }
    }
    const queryString = queryParams.toString();
    if (queryString) {
      url += (url.includes("?") ? "&" : "?") + queryString;
    }
  }

  const reqHeaders = {
    Accept: "application/json",
    ...headers,
  };

  const effectiveToken = token ? token.trim().replace(/^Bearer\s+/i, "") : null;
  if (effectiveToken) {
    reqHeaders.Authorization = `Bearer ${effectiveToken}`;
  }

  const fetchOptions = {
    method,
    headers: reqHeaders,
    ...rest,
  };

  if (body !== undefined) {
    if (typeof FormData !== "undefined" && body instanceof FormData) {
      delete reqHeaders["Content-Type"];
      fetchOptions.body = body;
    } else if (typeof Blob !== "undefined" && body instanceof Blob) {
      fetchOptions.body = body;
    } else if (typeof body === "object") {
      reqHeaders["Content-Type"] = "application/json";
      fetchOptions.body = JSON.stringify(body);
    } else {
      fetchOptions.body = body;
    }
  }

  let response;
  try {
    response = await fetch(url, fetchOptions);
  } catch (err) {
    throw new ApiError({
      message: err.message || "Network connection failed",
      status: 0,
      code: "NETWORK_ERROR",
    });
  }

  // Handle 401 Unauthorized hook (session expired / revoked)
  if (response.status === 401 && unauthorizedHandler) {
    try {
      unauthorizedHandler();
    } catch {
      // Prevent callback errors from masking the underlying API failure
    }
  }

  // Handle HTTP error responses
  if (!response.ok) {
    let errorData = null;
    try {
      errorData = await response.json();
    } catch {
      // Non-JSON or empty body
    }

    const traceId =
      errorData?.error?.trace_id ||
      response.headers.get("x-trace-id") ||
      null;

    const message =
      errorData?.error?.message ||
      (typeof errorData?.detail === "string" ? errorData.detail : null) ||
      response.statusText ||
      `Request failed with status ${response.status}`;

    const code =
      errorData?.error?.code ||
      `HTTP_${response.status}`;

    const details =
      errorData?.error?.details ||
      (Array.isArray(errorData?.detail) ? errorData.detail : null);

    throw new ApiError({
      message,
      status: response.status,
      code,
      details,
      traceId,
    });
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return null;
  }

  // Handle binary / streaming document formats (PDF, JSONL)
  const contentType = response.headers.get("content-type") || "";
  if (
    contentType.includes("application/pdf") ||
    contentType.includes("application/octet-stream") ||
    contentType.includes("application/x-ndjson")
  ) {
    return response.blob();
  }

  // Handle standard JSON response
  try {
    return await response.json();
  } catch {
    return null;
  }
}
