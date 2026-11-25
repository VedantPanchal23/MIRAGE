/**
 * MIRAGE 3.0 API Client
 * Communicates with the FastAPI Gateway.
 * Honest error propagation in live tenant mode; simulated demo data only when explicitly in Demo Sandbox mode.
 */

const BASE_URL = '';

export function isDemoSession() {
  try {
    if (typeof window === 'undefined') return false;
    const saved = localStorage.getItem('mirage_auth_user');
    if (saved) {
      const parsed = JSON.parse(saved);
      return Boolean(parsed?.isDemo);
    }
    return localStorage.getItem('mirage_demo_mode') === 'true';
  } catch {
    return false;
  }
}

const DEMO_FALLBACKS = {
  health: () => ({
    _demo: true,
    status: 'HEALTHY',
    version: '3.0.0',
    environment: 'sandbox-demo',
    components: {
      postgres: { status: 'HEALTHY', latency_ms: 1.2 },
      redis: { status: 'HEALTHY', latency_ms: 0.4 },
      rabbitmq: { status: 'HEALTHY', queue_depth: 0 },
      qdrant: { status: 'HEALTHY', collections_count: 3 },
      audit_anchor: { status: 'HEALTHY', chain_continuity: '100%' },
    },
  }),
  stats: () => ({
    _demo: true,
    active_transactions_24h: 1428,
    assurance_verdict_rate: 99.4,
    pending_l4_approvals: 2,
    quarantined_actions: 12,
    mean_gate_latency_ms: 18.4,
    total_audit_anchors: 8492,
    epistemic_uncertainty_index: 0.02,
  }),
  transactions: () => [
    {
      id: 'tx_98f12a4b8c91',
      created_at: new Date(Date.now() - 1000 * 45).toISOString(),
      agent_id: 'agent_treasury_disburser',
      tool_name: 'treasury.disburse_funds',
      state: 'VERIFIED_SUCCESS',
      risk_score: 35,
      dollar_cost: 450.0,
      observability_class: 'OBS_DIRECT',
      epistemic_confidence: 1.0,
      gate_verdicts: {
        gate1_input: 'PASSED',
        gate2_context: 'PASSED',
        gate3_action: 'AUTHORIZED',
        gate4_output: 'PASSED',
        gate5_outcome: 'VERIFIED_SUCCESS',
      },
      target_resource: 'sql://prod_db/treasury_ledgers',
      hash: '6a4f91b72c9e38d01f92a348b6c8192a01487291a82b3c4d5e6f7a8b9c0d1e2f',
    },
    {
      id: 'tx_32e18d99c4aa',
      created_at: new Date(Date.now() - 1000 * 120).toISOString(),
      agent_id: 'agent_customer_support_l2',
      tool_name: 'crm.update_credit_limit',
      state: 'AWAITING_APPROVAL',
      risk_score: 75,
      dollar_cost: 15000.0,
      observability_class: 'OBS_DIRECT',
      epistemic_confidence: 0.0,
      gate_verdicts: {
        gate1_input: 'PASSED',
        gate2_context: 'PASSED',
        gate3_action: 'APPROVAL_REQUIRED',
        gate4_output: 'PENDING',
        gate5_outcome: 'PENDING',
      },
      target_resource: 'crm://customer/account_98214',
      hash: '1289fe4c2b9a10982348a7b9c6d1e4f28394a0293b84c7d9e1a2b3c4d5e6f7a8',
    },
  ],
  approvals: () => [
    {
      id: 'appr_8f902ac1892',
      action_id: 'act_32e18d99c4aa',
      tool_name: 'crm.update_credit_limit',
      requested_by: 'agent_customer_support_l2',
      required_role: 'OPERATOR',
      status: 'PENDING',
      estimated_dollar_cost: 15000.0,
      parameters: { account_id: 'acc_98214', requested_limit: 20000.0 },
      parameters_hash: '3439f902dfd9ce980ef597df937431d6e1289a0b1c2d3e4f5a6b7c8d9e0f1a2b',
      created_at: new Date(Date.now() - 1000 * 120).toISOString(),
      expires_at: new Date(Date.now() + 1000 * 3600 * 2).toISOString(),
    },
  ],
  audit: () => [
    {
      entry_id: 'aud_49a88e91c2b041a9',
      sequence_number: 8492,
      event_type: 'GATE5_OUTCOME_VERIFIED',
      decision: 'VERIFIED_SUCCESS',
      actor_identity_id: 'system_reality_observer',
      created_at: new Date(Date.now() - 1000 * 45).toISOString(),
      prev_hash: '9f8e7d6c5b4a3928170123456789abcdef0123456789abcdef0123456789abcd',
      chain_hash: '3439f902dfd9ce980ef597df937431d6e1289a0b1c2d3e4f5a6b7c8d9e0f1a2b',
    },
  ],
  agents: () => [
    {
      id: 'agent_treasury_disburser',
      name: 'Treasury Settlement Agent',
      status: 'ACTIVE',
      role: 'EXECUTION_AGENT',
      max_autonomy_level: 3,
      allowed_capabilities: ['cap_treasury_read', 'cap_treasury_write'],
      created_at: '2026-09-01T12:00:00Z',
      last_active_at: new Date(Date.now() - 1000 * 45).toISOString(),
    },
  ],
};

export class MirageAPIClient {
  constructor(getAuthHeaders, demoResolver = isDemoSession) {
    this.getAuthHeaders = getAuthHeaders || (() => ({}));
    this.demoResolver = demoResolver;
  }

  async request(endpoint, options = {}) {
    const headers = {
      'Content-Type': 'application/json',
      ...this.getAuthHeaders(),
      ...(options.headers || {}),
    };

    const response = await fetch(`${BASE_URL}${endpoint}`, {
      ...options,
      headers,
    });

    if (!response.ok) {
      let errDetail = `HTTP ${response.status}: ${response.statusText}`;
      try {
        const body = await response.json();
        errDetail = body.detail || body?.error?.message || body.message || errDetail;
      } catch (_) {}
      const err = new Error(errDetail);
      err.status = response.status;
      throw err;
    }

    if (response.status === 204) return null;
    return await response.json();
  }

  async _withOptionalDemoFallback(fn, demoFactory) {
    try {
      return await fn();
    } catch (err) {
      if (this.demoResolver()) {
        return demoFactory();
      }
      throw err;
    }
  }

  // System Health & Public Status
  async getHealth() {
    return this._withOptionalDemoFallback(
      () => this.request('/v1/health'),
      DEMO_FALLBACKS.health
    );
  }

  async getPublicStatus() {
    return this.request('/v1/status');
  }

  // Dashboard Aggregates
  async getDashboardStats() {
    return this._withOptionalDemoFallback(
      () => this.request('/v1/dashboard/stats'),
      DEMO_FALLBACKS.stats
    );
  }

  // Transactions Feed
  async listTransactions(params = {}) {
    return this._withOptionalDemoFallback(async () => {
      const q = new URLSearchParams(params).toString();
      const res = await this.request(`/v1/sessions${q ? `?${q}` : ''}`);
      const raw = res.items || (Array.isArray(res) ? res : []);
      return raw.map((s) => ({
        id: s.session_id || s.id || `tx_${Math.random().toString(16).slice(2, 10)}`,
        created_at: s.created_at || new Date().toISOString(),
        agent_id: s.model_id || s.agent_id || 'system_orchestrator',
        tool_name: s.tool_name || 'execution.assurance_session',
        state:
          s.risk_tier === 'CRITICAL'
            ? 'BLOCKED'
            : s.risk_tier === 'HIGH'
            ? 'AWAITING_APPROVAL'
            : 'VERIFIED_SUCCESS',
        risk_score: Math.round((s.hrs_score || 0) * 100),
        dollar_cost: s.dollar_cost || 0.0,
        observability_class: s.observability_class || 'OBS_DIRECT',
        epistemic_confidence: s.hrs_score !== undefined ? 1 - s.hrs_score : 1.0,
        gate_verdicts: s.gate_verdicts || {
          gate1_input: 'PASSED',
          gate2_context: 'PASSED',
          gate3_action: s.risk_tier === 'CRITICAL' ? 'DENIED' : 'AUTHORIZED',
          gate4_output: s.risk_tier === 'CRITICAL' ? 'BLOCKED' : 'PASSED',
          gate5_outcome: s.risk_tier === 'CRITICAL' ? 'SKIPPED' : 'VERIFIED_SUCCESS',
        },
        target_resource: s.target_resource || 'sql://authoritative/sessions',
        hash: s.response_hash || s.prompt_hash || '0'.repeat(64),
      }));
    }, DEMO_FALLBACKS.transactions);
  }

  // L4 Approvals
  async listPendingApprovals() {
    return this._withOptionalDemoFallback(async () => {
      const res = await this.request('/v1/approvals/pending');
      return Array.isArray(res) ? res : [];
    }, DEMO_FALLBACKS.approvals);
  }

  async grantApproval(approvalId, reason = 'Approved by Operator') {
    return this._withOptionalDemoFallback(
      () =>
        this.request(`/v1/approvals/${approvalId}/grant`, {
          method: 'POST',
          body: JSON.stringify({ decision: 'GRANT', reason }),
        }),
      () => ({
        id: approvalId,
        status: 'GRANTED',
        decision_reason: reason,
        decided_at: new Date().toISOString(),
      })
    );
  }

  async denyApproval(approvalId, reason = 'Denied by Operator') {
    return this._withOptionalDemoFallback(
      () =>
        this.request(`/v1/approvals/${approvalId}/deny`, {
          method: 'POST',
          body: JSON.stringify({ decision: 'DENY', reason }),
        }),
      () => ({
        id: approvalId,
        status: 'DENIED',
        decision_reason: reason,
        decided_at: new Date().toISOString(),
      })
    );
  }

  // Audit Ledger Trail
  async listAuditRecords() {
    return this._withOptionalDemoFallback(async () => {
      const res = await this.request('/v1/audit/events');
      return res.events || (Array.isArray(res) ? res : []);
    }, DEMO_FALLBACKS.audit);
  }

  async verifyAuditTrail() {
    return this._withOptionalDemoFallback(
      () => this.request('/v1/audit/verify-chain', { method: 'POST' }),
      () => ({
        _demo: true,
        status: 'VERIFIED_CHAIN_VALID',
        verified_blocks: 8492,
        tampering_detected: false,
      })
    );
  }

  // Autonomous Agents Management
  async listAgents() {
    return this._withOptionalDemoFallback(async () => {
      const res = await this.request('/v1/agents');
      return res.agents || (Array.isArray(res) ? res : []);
    }, DEMO_FALLBACKS.agents);
  }

  // API Keys & Team RBAC
  async listApiKeys() {
    return this.request('/v1/auth/api-keys');
  }

  async createApiKey({ name, scopes = ['*'], expiresInDays = null }) {
    return this.request('/v1/auth/api-keys', {
      method: 'POST',
      body: JSON.stringify({ name, scopes, expires_in_days: expiresInDays }),
    });
  }

  async rotateApiKey(keyId) {
    return this.request(`/v1/auth/api-keys/${keyId}/rotate`, {
      method: 'POST',
      body: JSON.stringify({ immediate_revocation: false, grace_period_seconds: 300 }),
    });
  }

  async revokeApiKey(keyId) {
    return this.request(`/v1/auth/api-keys/${keyId}/revoke`, { method: 'POST' });
  }

  async listTeamUsers() {
    return this.request('/v1/auth/users');
  }

  async createTeamUser({ email, displayName, role = 'operator' }) {
    return this.request('/v1/auth/users', {
      method: 'POST',
      body: JSON.stringify({ email, display_name: displayName, role }),
    });
  }

  async updateTeamUser(userId, payload) {
    return this.request(`/v1/auth/users/${userId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  }

  // MCP Servers & Tool Governance
  async listMcpServers() {
    return this.request('/v1/mcp/servers');
  }

  async registerMcpServer(payload) {
    return this.request('/v1/mcp/servers', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async updateMcpTrust(serverId, trustStatus, reason = 'Updated via Operator Console') {
    return this.request(`/v1/mcp/servers/${serverId}/trust`, {
      method: 'PUT',
      body: JSON.stringify({ trust_status: trustStatus, reason }),
    });
  }

  async discoverMcpTools(serverId) {
    return this.request(`/v1/mcp/servers/${serverId}/discover`, { method: 'POST' });
  }

  async listTools() {
    return this.request('/v1/tools');
  }

  // Stranded Actions Reconciliation
  async listStrandedActions(olderThanSeconds = 60) {
    return this.request(`/v1/actions/stranded?older_than_seconds=${Number(olderThanSeconds)}`);
  }

  async reconcileAction(actionId, { resolution, notes }) {
    return this.request(`/v1/actions/${actionId}/reconcile`, {
      method: 'POST',
      body: JSON.stringify({ action_id: actionId, resolution, notes }),
    });
  }

  // Knowledge Base
  async listKbDocuments() {
    return this.request('/v1/knowledge-base/documents');
  }

  async uploadKbDocument({ filename, content, collectionName = 'default_kb' }) {
    return this.request('/v1/knowledge-base/upload', {
      method: 'POST',
      body: JSON.stringify({ filename, content, collection_name: collectionName }),
    });
  }

  async deleteKbDocument(documentId) {
    return this.request(`/v1/knowledge-base/documents/${documentId}`, { method: 'DELETE' });
  }

  // Budgets, Billing, Webhooks & Privacy DSAR
  async getTenantBudget() {
    return this.request('/v1/budgets/tenant');
  }

  async getBillingPlans() {
    return this.request('/v1/billing/plans');
  }

  async getSubscription() {
    return this.request('/v1/billing/subscription');
  }

  async createStripeCheckout(tier) {
    return this.request('/v1/billing/stripe/create-checkout-session', {
      method: 'POST',
      body: JSON.stringify({ tier }),
    });
  }

  async createRazorpayOrder(tier) {
    return this.request('/v1/billing/razorpay/create-order', {
      method: 'POST',
      body: JSON.stringify({ tier }),
    });
  }

  async listWebhooks() {
    return this.request('/v1/webhooks');
  }

  async registerWebhook({ url, events, description = '' }) {
    return this.request('/v1/webhooks', {
      method: 'POST',
      body: JSON.stringify({ url, event_types: events, description }),
    });
  }

  async deleteWebhook(webhookId) {
    return this.request(`/v1/webhooks/${webhookId}`, { method: 'DELETE' });
  }

  async exportPrivacyDossier() {
    return this.request('/v1/privacy/export');
  }

  async getPrivacyRetention() {
    return this.request('/v1/privacy/retention');
  }

  async submitInquiry(payload) {
    return this.request('/v1/inquiries', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  // Tenant Self-Service Onboarding & Real Credential Validation
  async registerTenant({ name, email, tier = 'business' }) {
    return await this.request('/v1/auth/register-tenant', {
      method: 'POST',
      body: JSON.stringify({
        name,
        admin_email: email,
        tier: tier.toLowerCase(),
      }),
    });
  }

  async validateCredentials({ apiKey = '', token = '', tenantId = '' }) {
    const authHeaders = {};
    if (token.trim()) {
      authHeaders.Authorization = `Bearer ${token.trim()}`;
    } else if (apiKey.trim()) {
      authHeaders['X-API-Key'] = apiKey.trim();
    }
    if (tenantId.trim()) {
      authHeaders['X-Tenant-ID'] = tenantId.trim();
    }
    return await this.request('/v1/auth/me', { headers: authHeaders });
  }

  async getCurrentAuth() {
    return await this.request('/v1/auth/me');
  }
}

export const api = new MirageAPIClient(() => {
  try {
    const saved = typeof window !== 'undefined' ? localStorage.getItem('mirage_auth_user') : null;
    if (saved) {
      const u = JSON.parse(saved);
      const headers = {};
      if (u.token || u.access_token) {
        headers.Authorization = `Bearer ${u.token || u.access_token}`;
      } else if (u.apiKey || u.api_key) {
        headers['X-API-Key'] = u.apiKey || u.api_key;
      }
      if (u.tenant_id) {
        headers['X-Tenant-ID'] = u.tenant_id;
      }
      return headers;
    }
  } catch (_) {}
  return {};
});
