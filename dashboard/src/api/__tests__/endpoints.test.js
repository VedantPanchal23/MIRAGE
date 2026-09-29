import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  getDashboardStats,
  getDashboardSessions,
  getSessionById,
  getDriftReport,
} from "../dashboard";
import {
  getAlerts,
  acknowledgeAlert,
} from "../alerts";
import {
  getHealth,
  getReadiness,
} from "../health";
import {
  generateReport,
  getReportById,
  getReportPdf,
  verifyAuditChain,
  getSessionAuditReport,
  getSessionCertificatePdf,
  exportAuditLogs,
  queryAuditLogs,
} from "../reports";

describe("Domain API Bindings (endpoints.test.js)", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    global.fetch = vi.fn();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  describe("Dashboard Endpoints", () => {
    it("getDashboardStats calls GET /v1/dashboard/stats", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ total_verifications: 100 }),
      });

      const res = await getDashboardStats();
      expect(res).toEqual({ total_verifications: 100 });
      expect(global.fetch).toHaveBeenCalledWith("/v1/dashboard/stats", expect.any(Object));
    });

    it("getDashboardSessions passes pagination and filter params to /v1/dashboard/sessions", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ total: 1, items: [] }),
      });

      await getDashboardSessions({ risk_tier: "LOW", page: 1, page_size: 20 });
      const [url] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/dashboard/sessions?risk_tier=LOW&page=1&page_size=20");
    });

    it("getSessionById calls GET /v1/sessions/{session_id}", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ session_id: "sess_123" }),
      });

      const res = await getSessionById("sess_123");
      expect(res.session_id).toBe("sess_123");
      const [url] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/sessions/sess_123");
    });

    it("getDriftReport calls GET /v1/drift with days param", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ drift_report: { psi: 0.05 } }),
      });

      await getDriftReport({ days: 30 });
      const [url] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/drift?days=30");
    });
  });

  describe("Alerts Endpoints", () => {
    it("getAlerts calls GET /v1/alerts with status and pagination", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ total_alerts: 5, alerts: [] }),
      });

      await getAlerts({ status: "active", limit: 10 });
      const [url] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/alerts?status=active&limit=10");
    });

    it("acknowledgeAlert calls POST /v1/alerts/{alert_id}/acknowledge", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ alert_id: "alt_99", status: "acknowledged" }),
      });

      await acknowledgeAlert("alt_99", { operator_id: "user_ops" });
      const [url, options] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/alerts/alt_99/acknowledge");
      expect(options.method).toBe("POST");
      expect(options.body).toBe(JSON.stringify({ operator_id: "user_ops" }));
    });
  });

  describe("Health Endpoints", () => {
    it("getHealth calls GET /v1/health", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ status: "healthy" }),
      });

      const res = await getHealth();
      expect(res.status).toBe("healthy");
      const [url] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/health");
    });

    it("getReadiness calls GET /v1/ready", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ status: "ready", degraded: false }),
      });

      const res = await getReadiness();
      expect(res.status).toBe("ready");
      const [url] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/ready");
    });
  });

  describe("Reports & Audit Endpoints", () => {
    it("generateReport calls POST /v1/reports/generate with payload", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 202,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ report_id: "rep_123", status: "PENDING" }),
      });

      const payload = {
        start_date: "2026-09-01T00:00:00Z",
        end_date: "2026-09-28T00:00:00Z",
      };
      const res = await generateReport(payload);
      expect(res.report_id).toBe("rep_123");
      const [url, options] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/reports/generate");
      expect(options.method).toBe("POST");
      expect(options.body).toBe(JSON.stringify(payload));
    });

    it("getReportById calls GET /v1/reports/{report_id}", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ report_id: "rep_123", status: "COMPLETED" }),
      });

      await getReportById("rep_123");
      const [url] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/reports/rep_123");
    });

    it("getReportPdf returns a Blob for PDF download", async () => {
      const mockPdfBlob = new Blob(["%PDF-1.4..."], { type: "application/pdf" });
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/pdf" }),
        blob: async () => mockPdfBlob,
      });

      const res = await getReportPdf("rep_123");
      expect(res).toBe(mockPdfBlob);
      const [url] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/reports/rep_123/pdf");
    });

    it("verifyAuditChain calls POST /v1/audit/verify-chain", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ chain_status: "VERIFIED", valid: true }),
      });

      const res = await verifyAuditChain();
      expect(res.valid).toBe(true);
      const [url, options] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/audit/verify-chain");
      expect(options.method).toBe("POST");
    });

    it("queryAuditLogs calls POST /v1/audit/query with query string", async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ total_matches: 2, results: [] }),
      });

      await queryAuditLogs("Show critical sessions");
      const [url, options] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/audit/query");
      expect(options.method).toBe("POST");
      expect(options.body).toBe(JSON.stringify({ query: "Show critical sessions" }));
    });

    it("exportAuditLogs calls GET /v1/audit/export returning ndjson Blob", async () => {
      const mockNdjsonBlob = new Blob(['{"log":"entry"}\n'], { type: "application/x-ndjson" });
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/x-ndjson" }),
        blob: async () => mockNdjsonBlob,
      });

      const res = await exportAuditLogs();
      expect(res).toBe(mockNdjsonBlob);
      const [url] = global.fetch.mock.calls[0];
      expect(url).toBe("/v1/audit/export");
    });
  });
});
