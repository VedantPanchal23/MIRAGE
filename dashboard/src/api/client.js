/**
 * MIRAGE API Client
 * High-performance fetch wrapper configured with tenant attribution and auth tokens.
 */

export async function apiRequest(endpoint, options = {}) {
  const tenantId =
    typeof localStorage !== "undefined"
      ? localStorage.getItem("mirage_tenant_id") || "tenant_default"
      : "tenant_default";
  const token =
    typeof localStorage !== "undefined"
      ? localStorage.getItem("mirage_auth_token") || "dev_sandbox_bearer_token"
      : "dev_sandbox_bearer_token";

  const headers = {
    "Content-Type": "application/json",
    "X-Tenant-ID": tenantId,
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };

  const config = {
    ...options,
    headers,
  };

  if (config.body && typeof config.body === "object" && !(config.body instanceof FormData)) {
    config.body = JSON.stringify(config.body);
  }

  // Ensure valid URL in both browser and jsdom/test environments
  let url = endpoint;
  if (!endpoint.startsWith("http://") && !endpoint.startsWith("https://")) {
    const origin =
      typeof window !== "undefined" && window.location?.origin && window.location.origin !== "null"
        ? window.location.origin
        : "http://localhost:3000";
    url = `${origin}${endpoint.startsWith("/") ? "" : "/"}${endpoint}`;
  }

  const response = await fetch(url, config);

  if (!response.ok) {
    let errorDetail = response.statusText;
    try {
      const errorJson = await response.json();
      errorDetail = errorJson.detail || errorJson.message || JSON.stringify(errorJson);
    } catch {
      // response wasn't JSON
    }
    const error = new Error(errorDetail || `HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }

  // Handle empty responses
  const contentType = response.headers.get("content-type");
  if (contentType && contentType.includes("application/json")) {
    return await response.json();
  }
  return await response.text();
}
