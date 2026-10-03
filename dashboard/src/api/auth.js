import { apiFetch } from "./client";

/**
 * Fetch an authoritative signed Bearer JWT access token for demonstration sessions.
 *
 * @param {string} [tenantId="tenant_demo"]
 * @param {string} [role="tenant_admin"]
 * @param {string} [userId="demo_operator"]
 * @returns {Promise<{ access_token: string, token_type: string, tenant_id: string, role: string, user_id: string, expires_in: number }>}
 */
export async function getDemoToken(
  tenantId = "tenant_demo",
  role = "tenant_admin",
  userId = "demo_operator"
) {
  return apiFetch("/v1/auth/demo-token", {
    method: "POST",
    body: {
      tenant_id: tenantId,
      role,
      user_id: userId,
    },
  });
}
