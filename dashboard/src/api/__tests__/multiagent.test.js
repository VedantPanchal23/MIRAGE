import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  listAgents,
  getAgent,
  registerAgent,
  activateAgent,
  suspendAgent,
  revokeAgent,
  listDelegations,
  getDelegation,
  createDelegation,
  activateDelegation,
  revokeDelegation,
  validateDelegation,
  listHandoffs,
  getHandoff,
  createHandoff,
  acceptHandoff,
  cancelHandoff,
  completeHandoff,
  listLeases,
  acquireLease,
  releaseLease,
  renewLease,
  getTransactionHierarchy,
} from "../multiagent";

describe("Phase 8 Multi-Agent API Client (multiagent.test.js)", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    global.fetch = vi.fn();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  describe("Agent Lifecycle Endpoints", () => {
    it("listAgents calls GET /v1/agents with pagination and status", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ agents: [], total: 0 }),
      });

      await listAgents({ status: "active", limit: 50 });
      const [url] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/agents?status=active&limit=50");
    });

    it("registerAgent calls POST /v1/agents", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 201,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ id: "agt_01", name: "Agent 01" }),
      });

      const payload = { name: "Agent 01", max_autonomy_level: 2 };
      const res = await registerAgent(payload);
      expect(res.id).toBe("agt_01");
      const [url, options] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/agents");
      expect(options.method).toBe("POST");
      expect(options.body).toBe(JSON.stringify(payload));
    });

    it("activateAgent calls POST /v1/agents/{id}/activate", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ id: "agt_01", status: "active" }),
      });

      await activateAgent("agt_01", "Ready");
      const [url, options] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/agents/agt_01/activate");
      expect(options.method).toBe("POST");
      expect(options.body).toBe(JSON.stringify({ reason: "Ready" }));
    });

    it("suspendAgent calls POST /v1/agents/{id}/suspend", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ id: "agt_01", status: "suspended" }),
      });

      await suspendAgent("agt_01", "Maintenance");
      const [url, options] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/agents/agt_01/suspend");
      expect(options.method).toBe("POST");
      expect(options.body).toBe(JSON.stringify({ reason: "Maintenance" }));
    });

    it("revokeAgent calls POST /v1/agents/{id}/revoke", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ id: "agt_01", status: "revoked" }),
      });

      await revokeAgent("agt_01", "Compromised");
      const [url, options] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/agents/agt_01/revoke");
      expect(options.method).toBe("POST");
      expect(options.body).toBe(JSON.stringify({ reason: "Compromised" }));
    });
  });

  describe("Delegation Grant Endpoints", () => {
    it("listDelegations calls GET /v1/delegations with filters", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => [],
      });

      await listDelegations({ status: "ACTIVE", child_agent_id: "agt_02" });
      const [url] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/delegations?status=ACTIVE&child_agent_id=agt_02");
    });

    it("createDelegation calls POST /v1/delegations", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 201,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ id: "del_01", status: "PENDING" }),
      });

      const payload = { parent_transaction_id: "txn_01", delegatee_agent_id: "agt_02" };
      await createDelegation(payload);
      const [url, options] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/delegations");
      expect(options.method).toBe("POST");
    });

    it("activateDelegation calls POST /v1/delegations/{id}/activate", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ id: "del_01", status: "ACTIVE" }),
      });

      await activateDelegation("del_01", "txn_child_99");
      const [url, options] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/delegations/del_01/activate");
      expect(options.method).toBe("POST");
      expect(options.body).toBe(JSON.stringify({ child_transaction_id: "txn_child_99" }));
    });

    it("revokeDelegation calls POST /v1/delegations/{id}/revoke", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ id: "del_01", status: "REVOKED" }),
      });

      await revokeDelegation("del_01", "Scope breach");
      const [url, options] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/delegations/del_01/revoke");
      expect(options.method).toBe("POST");
      expect(options.body).toBe(JSON.stringify({ reason: "Scope breach" }));
    });
  });

  describe("Governed Handoff Endpoints", () => {
    it("listHandoffs calls GET /v1/handoffs", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => [],
      });

      await listHandoffs({ status: "PENDING" });
      const [url] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/handoffs?status=PENDING");
    });

    it("createHandoff calls POST /v1/handoffs", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 201,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ id: "hnd_01", status: "PENDING" }),
      });

      const payload = { parent_transaction_id: "txn_01", child_agent_id: "agt_02" };
      await createHandoff(payload);
      const [url, options] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/handoffs");
      expect(options.method).toBe("POST");
    });

    it("acceptHandoff calls POST /v1/handoffs/{id}/accept", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ child_transaction_id: "txn_child_01" }),
      });

      await acceptHandoff("hnd_01", { input_context: { query: "test" } });
      const [url, options] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/handoffs/hnd_01/accept");
      expect(options.method).toBe("POST");
    });

    it("completeHandoff calls POST /v1/handoffs/{id}/complete", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ id: "hnd_01", status: "COMPLETED" }),
      });

      await completeHandoff("hnd_01");
      const [url, options] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/handoffs/hnd_01/complete");
      expect(options.method).toBe("POST");
    });

    it("cancelHandoff calls POST /v1/handoffs/{id}/cancel", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ id: "hnd_01", status: "CANCELLED" }),
      });

      await cancelHandoff("hnd_01", "Parent cancelled");
      const [url, options] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/handoffs/hnd_01/cancel");
      expect(options.method).toBe("POST");
      expect(options.body).toBe(JSON.stringify({ reason: "Parent cancelled" }));
    });
  });

  describe("Resource Concurrency Endpoints", () => {
    it("listLeases calls GET /v1/resources/leases", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => [],
      });

      await listLeases({ status: "ACQUIRED" });
      const [url] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/resources/leases?status=ACQUIRED");
    });

    it("acquireLease calls POST /v1/resources/leases/acquire", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 201,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ id: "lse_01", fencing_token: 1 }),
      });

      const payload = { resource_uri: "db://record", transaction_id: "t_01", agent_id: "a_01" };
      await acquireLease(payload);
      const [url, options] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/resources/leases/acquire");
      expect(options.method).toBe("POST");
    });

    it("releaseLease calls POST /v1/resources/leases/{id}/release", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ id: "lse_01", status: "RELEASED" }),
      });

      const payload = { transaction_id: "t_01", agent_id: "a_01", fencing_token: 1 };
      await releaseLease("lse_01", payload);
      const [url, options] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/resources/leases/lse_01/release");
      expect(options.method).toBe("POST");
    });
  });

  describe("Hierarchical Outcome Assurance Endpoint", () => {
    it("getTransactionHierarchy calls GET /v1/transactions/{id}/hierarchy", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ parent_transaction_id: "txn_root_01" }),
      });

      const res = await getTransactionHierarchy("txn_root_01");
      expect(res.parent_transaction_id).toBe("txn_root_01");
      const [url] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/transactions/txn_root_01/hierarchy");
    });
  });
});
