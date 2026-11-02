/**
 * @mirage-ai/sdk — Official JavaScript/Node.js SDK for MIRAGE 3.0 Execution Assurance Platform.
 *
 * Implements the Five Assurance Gates:
 * - Gate 1: Identity & Tenant Attribution
 * - Gate 2: Context Provenance & RAG Knowledge Search
 * - Gate 3: Governed Tool Action Proposal & HITL Approvals
 * - Gate 4: Syntactic & Verification Engine (HRS & Conformal Risk Bounds)
 * - Gate 5: Epistemic Independent Reality Verification
 *
 * Zero external dependencies. Uses modern native fetch and ReadableStream.
 */

export class MirageError extends Error {
  constructor(message, status = null, code = null, details = null) {
    super(message);
    this.name = "MirageError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export class MirageAuthenticationError extends MirageError {
  constructor(message, status = 401, details = null) {
    super(message, status, "AUTHENTICATION_FAILED", details);
    this.name = "MirageAuthenticationError";
  }
}

export class MirageAuthorizationError extends MirageError {
  constructor(message, status = 403, details = null) {
    super(message, status, "AUTHORIZATION_FAILED", details);
    this.name = "MirageAuthorizationError";
  }
}

export class MirageExecutionUncertainError extends MirageError {
  constructor(message, details = null) {
    super(message, 408, "EXECUTION_UNCERTAIN", details);
    this.name = "MirageExecutionUncertainError";
  }
}

export class MirageClient {
  /**
   * Initialize a new MIRAGE 3.0 client instance.
   * @param {Object} options
   * @param {string} options.apiKey - Tenant API key or service token
   * @param {string} [options.baseUrl="http://localhost:8000"] - Gateway URL
   * @param {number} [options.timeout=30000] - Request timeout in milliseconds
   * @param {string} [options.tenantId=""] - Optional tenant ID override
   */
  constructor({
    apiKey,
    baseUrl = "http://localhost:8000",
    timeout = 30000,
    tenantId = "",
  } = {}) {
    if (!apiKey || typeof apiKey !== "string" || !apiKey.trim()) {
      throw new MirageAuthenticationError("apiKey must be a non-empty string");
    }

    this.apiKey = apiKey.trim();
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.timeout = timeout;
    this.tenantId = tenantId.trim();
  }

  /**
   * Internal request dispatcher with authentication headers and timeout enforcement.
   * @private
   */
  async _request(path, { method = "GET", body = null, headers = {}, isMutating = false } = {}) {
    const url = `${this.baseUrl}${path}`;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), this.timeout);

    const mergedHeaders = {
      "X-API-Key": this.apiKey,
      "User-Agent": "@mirage-ai/sdk-js/3.0.0",
      "Accept": "application/json",
      ...(body ? { "Content-Type": "application/json" } : {}),
      ...headers,
    };

    try {
      const response = await fetch(url, {
        method,
        headers: mergedHeaders,
        body: body ? JSON.stringify(body) : null,
        signal: controller.signal,
      });

      if (!response.ok) {
        let errData = null;
        try {
          errData = await response.json();
        } catch {
          errData = { detail: await response.text() };
        }

        const msg = errData?.detail || `HTTP ${response.status} ${response.statusText}`;
        if (response.status === 401) throw new MirageAuthenticationError(msg, response.status, errData);
        if (response.status === 403) throw new MirageAuthorizationError(msg, response.status, errData);
        throw new MirageError(msg, response.status, errData?.code, errData);
      }

      return await response.json();
    } catch (err) {
      if (err.name === "AbortError") {
        if (isMutating) {
          throw new MirageExecutionUncertainError(
            `Mutating ${method} ${path} timed out after ${this.timeout}ms: execution outcome is uncertain; blind redispatch prohibited.`
          );
        }
        throw new MirageError(`Request timed out after ${this.timeout}ms`, 408, "TIMEOUT");
      }
      throw err;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  // --------------------------------------------------------------------------
  // Gate 4: Verification API (Batch & Real-Time SSE Stream)
  // --------------------------------------------------------------------------

  /**
   * Submit prompt and model response for Gate 4 factual consistency and hallucination risk evaluation.
   * @param {Object} params
   * @param {string} params.prompt
   * @param {string} params.response
   * @param {string} [params.modelId="allam-2-7b"]
   * @param {boolean} [params.autoCorrect=true]
   * @param {string} [params.knowledgeBaseId="default_kb"]
   * @returns {Promise<Object>}
   */
  async verify({
    prompt,
    response,
    modelId = "allam-2-7b",
    autoCorrect = true,
    knowledgeBaseId = "default_kb",
  }) {
    return this._request("/v1/verify", {
      method: "POST",
      isMutating: true,
      body: {
        prompt,
        response,
        model_id: modelId,
        auto_correct: autoCorrect,
        knowledge_base_id: knowledgeBaseId,
        tenant_id: this.tenantId,
      },
    });
  }

  /**
   * Stream progressive claim-by-claim verification events over Server-Sent Events (SSE).
   * Yields { event: string, data: Object }
   * @param {Object} params
   * @param {string} params.prompt
   * @param {string} params.response
   * @param {string} [params.modelId="allam-2-7b"]
   * @param {boolean} [params.autoCorrect=true]
   * @param {string} [params.knowledgeBaseId="default_kb"]
   * @returns {AsyncGenerator<{ event: string, data: any }>}
   */
  async *verifyStream({
    prompt,
    response,
    modelId = "allam-2-7b",
    autoCorrect = true,
    knowledgeBaseId = "default_kb",
  }) {
    const url = `${this.baseUrl}/v1/verify/stream`;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), this.timeout);

    const headers = {
      "X-API-Key": this.apiKey,
      "User-Agent": "@mirage-ai/sdk-js/3.0.0",
      "Content-Type": "application/json",
      "Accept": "text/event-stream",
    };

    try {
      const resp = await fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify({
          prompt,
          response,
          model_id: modelId,
          auto_correct: autoCorrect,
          knowledge_base_id: knowledgeBaseId,
          tenant_id: this.tenantId,
        }),
        signal: controller.signal,
      });

      if (!resp.ok) {
        const errorText = await resp.text();
        throw new MirageError(`Streaming failed: HTTP ${resp.status} - ${errorText}`, resp.status);
      }

      const reader = resp.body.getReader();
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
            yield { event: currentEvent, data: parsedData };
          }
        }
      }
    } finally {
      clearTimeout(timeoutId);
    }
  }

  // --------------------------------------------------------------------------
  // Gate 3 & Gate 5: Governed Actions & Epistemic Reality Verification
  // --------------------------------------------------------------------------

  /**
   * Propose a tool action for Gate 3 policy authorization and lease acquisition.
   * @param {Object} proposal
   * @returns {Promise<Object>}
   */
  async proposeAction(proposal) {
    return this._request("/v1/actions/propose", {
      method: "POST",
      body: proposal,
      isMutating: true,
    });
  }

  /**
   * Execute an authorized action through Gate 3 fencer dispatch.
   * @param {string} actionId
   * @param {string} [approvalToken=null]
   * @returns {Promise<Object>}
   */
  async executeAction(actionId, approvalToken = null) {
    return this._request("/v1/actions/execute", {
      method: "POST",
      body: { action_id: actionId, approval_token: approvalToken },
      isMutating: true,
    });
  }

  /**
   * Verify real-world postconditions independently (Gate 5 Reality Verification).
   * @param {Object} payload
   * @returns {Promise<Object>}
   */
  async verifyOutcome(payload) {
    return this._request("/v1/outcomes/verify", {
      method: "POST",
      body: payload,
      isMutating: true,
    });
  }

  /**
   * List registered tools in the caller's tenant registry.
   * @returns {Promise<Array<Object>>}
   */
  async listTools() {
    return this._request("/v1/tools");
  }

  // --------------------------------------------------------------------------
  // Human-in-the-Loop (HITL) Approvals
  // --------------------------------------------------------------------------

  async getPendingApprovals() {
    return this._request("/v1/approvals/pending");
  }

  async grantApproval(approvalId, reason = "Approved via Mirage JavaScript SDK") {
    return this._request(`/v1/approvals/${approvalId}/grant`, {
      method: "POST",
      body: { reason },
      isMutating: true,
    });
  }

  async denyApproval(approvalId, reason = "Denied via Mirage JavaScript SDK") {
    return this._request(`/v1/approvals/${approvalId}/deny`, {
      method: "POST",
      body: { reason },
      isMutating: true,
    });
  }

  // --------------------------------------------------------------------------
  // Cryptographic Audit Ledger & Tenant Governance
  // --------------------------------------------------------------------------

  async getAuditIntegrity() {
    return this._request("/v1/audit/integrity");
  }

  async getTenantBudget(tenantId = null) {
    const q = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : "";
    return this._request(`/v1/budgets/tenant${q}`);
  }

  async updateTenantBudget({ totalBudgetMicros, hardLimit = true, resetPeriod = "MONTHLY" }) {
    return this._request("/v1/budgets/tenant", {
      method: "PUT",
      body: {
        total_budget_micros: totalBudgetMicros,
        hard_limit: hardLimit,
        reset_period: resetPeriod,
      },
      isMutating: true,
    });
  }

  async listResourceLeases(params = {}) {
    const searchParams = new URLSearchParams();
    if (params.resource_uri) searchParams.append("resource_uri", params.resource_uri);
    if (params.limit) searchParams.append("limit", params.limit);
    if (params.offset) searchParams.append("offset", params.offset);
    const q = searchParams.toString() ? `?${searchParams.toString()}` : "";
    return this._request(`/v1/resources/leases${q}`);
  }

  async releaseResourceLease(leaseId, fencingToken) {
    return this._request(`/v1/resources/leases/${leaseId}/release`, {
      method: "POST",
      body: { fencing_token: fencingToken },
      isMutating: true,
    });
  }
}
