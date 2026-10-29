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

  // 13. Regulatory Compliance Dossier (EU AI Act & SOC2)
  async downloadComplianceDossier() {
    const token = localStorage.getItem("mirage_auth_token") || "mock_super_admin_jwt";
    const apiKey = localStorage.getItem("mirage_api_key") || "mirage_live_default";
    const headers = {
      Authorization: `Bearer ${token}`,
      "X-API-Key": apiKey,
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
};
