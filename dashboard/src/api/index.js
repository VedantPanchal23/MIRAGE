import { apiRequest } from "./client";

export const api = {
  // 1. Dashboard Stats & Sessions
  async getDashboardStats(tenantId) {
    const q = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : "";
    return apiRequest(`/v1/dashboard/stats${q}`);
  },

  async getSessions(params = {}) {
    const searchParams = new URLSearchParams();
    if (params.risk_tier) searchParams.append("risk_tier", params.risk_tier);
    if (params.page) searchParams.append("page", params.page);
    if (params.page_size) searchParams.append("page_size", params.page_size);
    const q = searchParams.toString() ? `?${searchParams.toString()}` : "";
    return apiRequest(`/v1/dashboard/sessions${q}`);
  },

  // 2. Interactive Assurance Playground (Gate 1 - 4 + Verification Orchestrator)
  async verifyCompletion(payload) {
    return apiRequest("/v1/verify", {
      method: "POST",
      body: payload,
    });
  },

  async proposeAction(payload) {
    return apiRequest("/v1/actions/propose", {
      method: "POST",
      body: payload,
    });
  },

  // 3. HITL Approvals Queue (Gate 3 L4)
  async getPendingApprovals() {
    return apiRequest("/v1/approvals/pending");
  },

  async grantApproval(approvalId, reason = "Approved via Operator Dashboard") {
    return apiRequest(`/v1/approvals/${approvalId}/grant`, {
      method: "POST",
      body: { reason },
    });
  },

  async denyApproval(approvalId, reason = "Denied via Operator Dashboard") {
    return apiRequest(`/v1/approvals/${approvalId}/deny`, {
      method: "POST",
      body: { reason },
    });
  },

  // 4. Knowledge Base (Gate 2 RAG)
  async getKBDocuments() {
    return apiRequest("/v1/kb/documents");
  },

  async uploadKBDocument(filename, content, collectionName = "default_kb") {
    return apiRequest("/v1/kb/upload", {
      method: "POST",
      body: {
        filename,
        content,
        collection_name: collectionName,
      },
    });
  },

  async deleteKBDocument(documentId) {
    return apiRequest(`/v1/kb/documents/${documentId}`, {
      method: "DELETE",
    });
  },

  async searchKB(query, collectionName = "default_kb", limit = 5) {
    return apiRequest("/v1/kb/search", {
      method: "POST",
      body: {
        query,
        collection_name: collectionName,
        limit,
      },
    });
  },

  // 5. Developer Console (API Keys & Integrations)
  async getApiKeys() {
    return apiRequest("/v1/auth/api-keys");
  },

  async createApiKey(name, description = "", role = "admin") {
    return apiRequest("/v1/auth/api-keys", {
      method: "POST",
      body: {
        name,
        description,
        role,
      },
    });
  },

  async revokeApiKey(keyId) {
    return apiRequest(`/v1/auth/api-keys/${keyId}`, {
      method: "DELETE",
    });
  },

  // 6. Subscriptions & Billing (Stripe USD Checkout)
  async getBillingPlans() {
    return apiRequest("/v1/billing/plans");
  },

  async getSubscription() {
    return apiRequest("/v1/billing/subscription");
  },

  async getBillingUsage() {
    return apiRequest("/v1/billing/usage");
  },

  async createStripeCheckoutSession(tier) {
    return apiRequest("/v1/billing/stripe/create-checkout-session", {
      method: "POST",
      body: { tier },
    });
  },

  async verifyStripePayment(sessionId, tier, paymentIntentId = null) {
    return apiRequest("/v1/billing/stripe/verify-payment", {
      method: "POST",
      body: {
        session_id: sessionId,
        tier: tier,
        payment_intent_id: paymentIntentId,
      },
    });
  },

  async createRazorpayOrder(planId) {
    return apiRequest("/v1/billing/razorpay/create-order", {
      method: "POST",
      body: { plan_id: planId },
    });
  },

  async verifyRazorpayPayment(orderId, paymentId, signature, planId) {
    return apiRequest("/v1/billing/razorpay/verify-payment", {
      method: "POST",
      body: {
        razorpay_order_id: orderId,
        razorpay_payment_id: paymentId,
        razorpay_signature: signature,
        plan_id: planId,
      },
    });
  },

  // 7. Cryptographic Audit Ledger
  async getAuditIntegrity() {
    return apiRequest("/v1/audit/integrity");
  },

  async getAuditEvents(params = {}) {
    const searchParams = new URLSearchParams();
    if (params.event_type) searchParams.append("event_type", params.event_type);
    if (params.limit) searchParams.append("limit", params.limit);
    if (params.offset) searchParams.append("offset", params.offset);
    const q = searchParams.toString() ? `?${searchParams.toString()}` : "";
    return apiRequest(`/v1/audit/events${q}`);
  },

  async exportAuditJsonl() {
    return apiRequest("/v1/audit/export");
  },

  // System Health
  async getSystemHealth() {
    return apiRequest("/v1/health");
  },

  // 8. Public Inquiries & Lead Capture
  async createInquiry(payload) {
    return apiRequest("/v1/inquiries", {
      method: "POST",
      body: payload,
    });
  },

  // 9. Tenant Registration & Auth
  async registerTenant(payload) {
    return apiRequest("/v1/auth/register-tenant", {
      method: "POST",
      body: payload,
    });
  },

  // 10. Action Assurance & Reality Verification (Gate 3 & 5)
  async executeAction(actionId, approvalToken = null) {
    return apiRequest("/v1/actions/execute", {
      method: "POST",
      body: { action_id: actionId, approval_token: approvalToken },
    });
  },

  async verifyOutcome(payload) {
    return apiRequest("/v1/outcomes/verify", {
      method: "POST",
      body: payload,
    });
  },

  async listTools() {
    return apiRequest("/v1/tools");
  },

  // 11. Governed MCP Integration
  async executeMcpRpc(rpcPayload) {
    return apiRequest("/v1/mcp/rpc", {
      method: "POST",
      body: rpcPayload,
    });
  },

  // 12. Outbound Webhook Alerting
  async listWebhooks() {
    return apiRequest("/v1/webhooks");
  },

  async createWebhook(payload) {
    return apiRequest("/v1/webhooks", {
      method: "POST",
      body: payload,
    });
  },

  async deleteWebhook(webhookId) {
    return apiRequest(`/v1/webhooks/${webhookId}`, {
      method: "DELETE",
    });
  },

  async testWebhook(webhookId) {
    return apiRequest(`/v1/webhooks/${webhookId}/test`, {
      method: "POST",
    });
  },

  // 13. Regulatory Compliance Dossier (EU AI Act & SOC2)
  async downloadComplianceDossier() {
    const token = (
      typeof localStorage !== "undefined"
        ? localStorage.getItem("mirage_auth_token") || localStorage.getItem("mirage_token") || ""
        : ""
    ).trim();
    const apiKey = (
      typeof localStorage !== "undefined"
        ? localStorage.getItem("mirage_api_key") || ""
        : ""
    ).trim();
    const headers = {
      ...(apiKey ? { "X-API-Key": apiKey } : {}),
      ...(token
        ? { Authorization: `Bearer ${token}` }
        : apiKey
        ? { Authorization: `Bearer ${apiKey}` }
        : {}),
    };
    const response = await fetch("/v1/reports/dossier", { headers });
    if (!response.ok) {
      throw new Error(`Failed to download dossier: HTTP ${response.status}`);
    }
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `mirage_compliance_dossier_${Date.now()}.zip`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  },

  // 14. Real-Time Streaming Verification (Gate 4 SSE)
  async verifyCompletionStream(payload, { onEvent, onError, onComplete, signal } = {}) {
    const token = (
      typeof localStorage !== "undefined"
        ? localStorage.getItem("mirage_auth_token") || localStorage.getItem("mirage_token") || ""
        : ""
    ).trim();
    const apiKey = (
      typeof localStorage !== "undefined"
        ? localStorage.getItem("mirage_api_key") || ""
        : ""
    ).trim();

    const headers = {
      "Content-Type": "application/json",
      "Accept": "text/event-stream",
      ...(apiKey ? { "X-API-Key": apiKey } : {}),
      ...(token
        ? { Authorization: `Bearer ${token}` }
        : apiKey
        ? { Authorization: `Bearer ${apiKey}` }
        : {}),
    };

    try {
      const response = await fetch("/v1/verify/stream", {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
        signal,
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Streaming failed: HTTP ${response.status} - ${errorText}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      let currentEvent = "message";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) continue;

          if (trimmed.startsWith("event:")) {
            currentEvent = trimmed.slice(6).trim();
          } else if (trimmed.startsWith("data:")) {
            const rawData = trimmed.slice(5).trim();
            let parsedData;
            try {
              parsedData = JSON.parse(rawData);
            } catch {
              parsedData = rawData;
            }
            if (onEvent) onEvent(currentEvent, parsedData);
          }
        }
      }

      if (onComplete) onComplete();
    } catch (err) {
      if (err.name === "AbortError") {
        return;
      }
      if (onError) onError(err);
      else throw err;
    }
  },

  // 15. Tenant Spend Ceilings & Micro-Budgets
  async getTenantBudget(tenantId = null) {
    const q = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : "";
    return apiRequest(`/v1/budgets/tenant${q}`);
  },

  async updateTenantBudget({ totalBudgetMicros, hardLimit = true, resetPeriod = "MONTHLY", tenantId = null }) {
    const q = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : "";
    return apiRequest(`/v1/budgets/tenant${q}`, {
      method: "PUT",
      body: {
        total_budget_micros: totalBudgetMicros,
        hard_limit: hardLimit,
        reset_period: resetPeriod,
      },
    });
  },

  async reconcileBudgetReservations() {
    return apiRequest("/v1/budgets/reconcile", {
      method: "POST",
    });
  },

  // 16. Distributed Concurrency Leases & Fencing Tokens
  async listResourceLeases(params = {}) {
    const searchParams = new URLSearchParams();
    if (params.resource_uri) searchParams.append("resource_uri", params.resource_uri);
    if (params.status) searchParams.append("status", params.status);
    if (params.limit) searchParams.append("limit", params.limit);
    if (params.offset) searchParams.append("offset", params.offset);
    const q = searchParams.toString() ? `?${searchParams.toString()}` : "";
    return apiRequest(`/v1/resources/leases${q}`);
  },

  async releaseResourceLease(leaseId, fencingToken) {
    return apiRequest(`/v1/resources/leases/${leaseId}/release`, {
      method: "POST",
      body: { fencing_token: fencingToken },
    });
  },
};
