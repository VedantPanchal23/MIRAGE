import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { SessionsView } from "../SessionsView";
import { ROLE_PERMISSIONS, PERMISSIONS } from "../../context/AuthContext";
import * as api from "../../api";

vi.mock("../../api", () => ({
  getDashboardSessions: vi.fn(),
  getSessionById: vi.fn(),
}));

describe("SessionsView Component (P2.7)", () => {
  const mockSessionsList = {
    total: 25,
    page: 1,
    page_size: 10,
    items: [
      {
        session_id: "sess_test_101",
        tenant_id: "tenant_corp",
        trace_id: "tr_abc_1",
        model_id: "gpt-4o",
        prompt_hash: "p_hash_1",
        response_hash: "r_hash_1",
        hrs_score: 0.0825,
        risk_tier: "LOW",
        ci_lower: 0.045,
        ci_upper: 0.120,
        claims_count: 2,
        contradicted_count: 0,
        correction_applied: false,
        created_at: "2026-09-28T10:15:00Z",
      },
      {
        session_id: "sess_test_102",
        tenant_id: "tenant_corp",
        trace_id: "tr_abc_2",
        model_id: "claude-3-5-sonnet",
        prompt_hash: "p_hash_2",
        response_hash: "r_hash_2",
        hrs_score: 0.7650,
        risk_tier: "HIGH",
        ci_lower: 0.650,
        ci_upper: 0.880,
        claims_count: 3,
        contradicted_count: 2,
        correction_applied: true,
        created_at: "2026-09-28T11:20:00Z",
      },
    ],
  };

  const mockSessionDetailsWithTreeShap = {
    session_id: "sess_test_101",
    tenant_id: "tenant_corp",
    trace_id: "tr_abc_1",
    model_id: "gpt-4o",
    prompt_hash: "p_hash_1",
    response_hash: "r_hash_1",
    hrs_score: 0.0825,
    risk_tier: "LOW",
    correction_applied: false,
    created_at: "2026-09-28T10:15:00Z",
    signal_attribution: {
      rav: 0.3500, // Normalized TreeSHAP attribution: 35.0%
      scs: 0.2000, // Normalized TreeSHAP attribution: 20.0%
      nli: 0.3000, // Normalized TreeSHAP attribution: 30.0%
      ics: 0.1500, // Normalized TreeSHAP attribution: 15.0%
    },
    claims: [
      {
        id: "clm_01",
        session_id: "sess_test_101",
        claim_text: "The capital of France is Paris.",
        claim_type: "FACTUAL",
        criticality: "HIGH",
        status: "SUPPORTED",
        risk_score: 0.025,
        rav_score: 0.95,
        scs_score: 0.92,
        nli_score: 0.98,
        ics_score: 0.01,
      },
      {
        id: "clm_02",
        session_id: "sess_test_101",
        claim_text: "Paris hosted the Olympic Games in 2024.",
        claim_type: "TEMPORAL",
        criticality: "MEDIUM",
        status: "SUPPORTED",
        risk_score: 0.035,
        rav_score: 0.91,
        scs_score: 0.88,
        nli_score: 0.94,
        ics_score: 0.02,
      },
    ],
    trace: {
      prompt: "Tell me about Paris.",
      response: "Paris is the capital of France and hosted the 2024 Olympic Games.",
    },
  };

  const mockSessionDetailsWithoutTreeShap = {
    session_id: "sess_test_102",
    tenant_id: "tenant_corp",
    trace_id: "tr_abc_2",
    model_id: "claude-3-5-sonnet",
    prompt_hash: "p_hash_2",
    response_hash: "r_hash_2",
    hrs_score: 0.7650,
    risk_tier: "HIGH",
    correction_applied: true,
    created_at: "2026-09-28T11:20:00Z",
    signal_attribution: null, // Explicitly absent TreeSHAP
    claims: [
      {
        id: "clm_03",
        session_id: "sess_test_102",
        claim_text: "The moon is made of blue cheese.",
        claim_type: "FACTUAL",
        criticality: "CRITICAL",
        status: "CONTRADICTED",
        risk_score: 0.890,
      },
    ],
    trace: null,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    api.getDashboardSessions.mockReset();
    api.getSessionById.mockReset();
  });

  it("renders loading state on initial mount with accessible status role", () => {
    api.getDashboardSessions.mockReturnValue(new Promise(() => {})); // pending

    render(<SessionsView />);
    expect(screen.getByRole("status")).toHaveAttribute("aria-label", "Loading verification sessions");
    expect(screen.getByText(/Loading verification sessions/i)).toBeInTheDocument();
  });

  it("calls centralized API client getDashboardSessions without client-injected tenant_id", async () => {
    api.getDashboardSessions.mockResolvedValueOnce(mockSessionsList);
    api.getSessionById.mockResolvedValueOnce(mockSessionDetailsWithTreeShap);

    render(<SessionsView />);

    await waitFor(() => {
      expect(api.getDashboardSessions).toHaveBeenCalledTimes(1);
      // Strictly passes pagination without client tenant_id override
      expect(api.getDashboardSessions).toHaveBeenCalledWith({ page: 1, page_size: 10 });
    });
  });

  it("renders successful session list with session identifiers, risk badges, and HRS scores", async () => {
    api.getDashboardSessions.mockResolvedValueOnce(mockSessionsList);
    api.getSessionById.mockResolvedValueOnce(mockSessionDetailsWithTreeShap);

    render(<SessionsView />);

    await waitFor(() => {
      expect(screen.getAllByText("sess_test_101").length).toBeGreaterThan(0);
      expect(screen.getByText("sess_test_102")).toBeInTheDocument();
      expect(screen.getAllByText("0.0825").length).toBeGreaterThan(0);
      expect(screen.getByText("0.7650")).toBeInTheDocument();
      expect(screen.getAllByText("LOW").length).toBeGreaterThan(0);
      expect(screen.getAllByText("HIGH").length).toBeGreaterThan(0);
      expect(screen.getByText("Applied")).toBeInTheDocument();
    });
  });

  it("supports pagination controls and requests subsequent pages", async () => {
    api.getDashboardSessions.mockResolvedValue(mockSessionsList);
    api.getSessionById.mockResolvedValue(mockSessionDetailsWithTreeShap);

    render(<SessionsView />);

    await waitFor(() => {
      expect(screen.getAllByText("sess_test_101").length).toBeGreaterThan(0);
    });

    const nextBtn = screen.getByRole("button", { name: /next page/i });
    expect(nextBtn).not.toBeDisabled();

    fireEvent.click(nextBtn);

    await waitFor(() => {
      expect(api.getDashboardSessions).toHaveBeenCalledWith({ page: 2, page_size: 10 });
    });
  });

  it("supports risk tier filtering and passes selected filter to backend", async () => {
    api.getDashboardSessions.mockResolvedValue(mockSessionsList);
    api.getSessionById.mockResolvedValue(mockSessionDetailsWithTreeShap);

    render(<SessionsView />);

    await waitFor(() => {
      expect(screen.getAllByText("sess_test_101").length).toBeGreaterThan(0);
    });

    // Click HIGH tier filter button
    const highBtn = screen.getByRole("button", { name: "HIGH" });
    fireEvent.click(highBtn);

    await waitFor(() => {
      expect(api.getDashboardSessions).toHaveBeenCalledWith({ page: 1, page_size: 10, risk_tier: "HIGH" });
    });
  });

  it("renders empty state when no sessions are found", async () => {
    api.getDashboardSessions.mockResolvedValueOnce({
      total: 0,
      page: 1,
      page_size: 10,
      items: [],
    });

    render(<SessionsView />);

    await waitFor(() => {
      expect(screen.getByText("No Verification Sessions Found")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /check for updates/i })).toBeInTheDocument();
    });
  });

  it("renders error state when centralized API call fails and provides retry button", async () => {
    const errorObj = new Error("PostgreSQL pool connection timeout");
    errorObj.code = "SERVICE_UNAVAILABLE";
    errorObj.traceId = "tr_sess_err_500";
    errorObj.status = 503;

    api.getDashboardSessions.mockRejectedValueOnce(errorObj);

    render(<SessionsView />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
      expect(screen.getByText("Unable to Load Verification Sessions")).toBeInTheDocument();
      expect(screen.getByText("PostgreSQL pool connection timeout")).toBeInTheDocument();
      expect(screen.getByText("Code: SERVICE_UNAVAILABLE")).toBeInTheDocument();
      expect(screen.getByText("Trace: tr_sess_err_500")).toBeInTheDocument();
    });

    // Test retry
    api.getDashboardSessions.mockResolvedValueOnce(mockSessionsList);
    api.getSessionById.mockResolvedValueOnce(mockSessionDetailsWithTreeShap);

    fireEvent.click(screen.getByRole("button", { name: /retry/i }));

    await waitFor(() => {
      expect(screen.getAllByText("sess_test_101").length).toBeGreaterThan(0);
    });
  });

  it("selects a session and calls getSessionById to render claims breakdown", async () => {
    api.getDashboardSessions.mockResolvedValueOnce(mockSessionsList);
    api.getSessionById.mockResolvedValueOnce(mockSessionDetailsWithTreeShap);

    render(<SessionsView />);

    await waitFor(() => {
      expect(api.getSessionById).toHaveBeenCalledWith("sess_test_101");
      expect(screen.getByText("The capital of France is Paris.")).toBeInTheDocument();
      expect(screen.getByText("Paris hosted the Olympic Games in 2024.")).toBeInTheDocument();
      expect(screen.getAllByText("SUPPORTED").length).toBeGreaterThan(0);
      expect(screen.getByText("clm_01")).toBeInTheDocument();
      expect(screen.getByText("clm_02")).toBeInTheDocument();
    });

    // Verify sub-signal scores rendered on claims
    expect(screen.getByText("0.950")).toBeInTheDocument(); // RAV
    expect(screen.getByText("0.920")).toBeInTheDocument(); // SCS
  });

  it("renders TreeSHAP feature attributions preserving verified backend contract and additive total", async () => {
    api.getDashboardSessions.mockResolvedValueOnce(mockSessionsList);
    api.getSessionById.mockResolvedValueOnce(mockSessionDetailsWithTreeShap);

    render(<SessionsView />);

    await waitFor(() => {
      expect(screen.getByText("TreeSHAP Feature Attribution")).toBeInTheDocument();
      // Verifies exact feature names
      expect(screen.getByText("RAV (Retrieval Support)")).toBeInTheDocument();
      expect(screen.getByText("SCS (Self-Consistency Sampling)")).toBeInTheDocument();
      expect(screen.getByText("NLI (Entailment Verifier)")).toBeInTheDocument();
      expect(screen.getByText("ICS (Internal Inconsistency)")).toBeInTheDocument();

      // Verifies exact backend values preserved without modification
      expect(screen.getByText("0.3500")).toBeInTheDocument();
      expect(screen.getByText("0.2000")).toBeInTheDocument();
      expect(screen.getByText("0.3000")).toBeInTheDocument();
      expect(screen.getByText("0.1500")).toBeInTheDocument();

      // Verifies percentage shares
      expect(screen.getByText("35.0% share")).toBeInTheDocument();
      expect(screen.getByText("20.0% share")).toBeInTheDocument();
      expect(screen.getByText("30.0% share")).toBeInTheDocument();
      expect(screen.getByText("15.0% share")).toBeInTheDocument();

      // Mathematical invariant: displayed additive total equals sum of supplied values (1.0000)
      expect(screen.getByText("1.0000")).toBeInTheDocument();

      // Invariant: Missing signals (e.g. VGS when no image) are NOT fabricated
      expect(screen.queryByText(/VGS \(Visual Grounding\)/i)).not.toBeInTheDocument();
    });
  });

  it("resolves TreeSHAP attribution from trace.hrs_result when present in MongoDB trace", async () => {
    const sessionWithTraceTreeShap = {
      ...mockSessionDetailsWithoutTreeShap,
      signal_attribution: null,
      trace: {
        hrs_result: {
          signal_attribution: {
            rav: 0.4000,
            nli: 0.6000,
          },
        },
      },
    };
    api.getDashboardSessions.mockResolvedValueOnce(mockSessionsList);
    api.getSessionById.mockResolvedValueOnce(sessionWithTraceTreeShap);

    render(<SessionsView />);

    await waitFor(() => {
      expect(screen.getByText("RAV (Retrieval Support)")).toBeInTheDocument();
      expect(screen.getByText("NLI (Entailment Verifier)")).toBeInTheDocument();
      expect(screen.getByText("0.4000")).toBeInTheDocument();
      expect(screen.getByText("0.6000")).toBeInTheDocument();
      expect(screen.getByText("1.0000")).toBeInTheDocument();
    });
  });

  it("renders explicit unavailable state when TreeSHAP data is absent from backend", async () => {
    api.getDashboardSessions.mockResolvedValueOnce(mockSessionsList);
    // Return session where signal_attribution is null/absent
    api.getSessionById.mockResolvedValueOnce(mockSessionDetailsWithoutTreeShap);

    render(<SessionsView />);

    await waitFor(() => {
      expect(screen.getByText("TreeSHAP Feature Attribution")).toBeInTheDocument();
      // Explicit status badge and message
      expect(screen.getByText("Unavailable")).toBeInTheDocument();
      expect(
        screen.getByText(/TreeSHAP feature attributions are unavailable for this verification session/i)
      ).toBeInTheDocument();
    });

    // Invariant: Do not calculate or fabricate SHAP percentage bars
    expect(screen.queryByText("∑ Φ_i =")).not.toBeInTheDocument();
  });

  it("does not render any client-controlled tenant switching elements", async () => {
    api.getDashboardSessions.mockResolvedValueOnce(mockSessionsList);
    api.getSessionById.mockResolvedValueOnce(mockSessionDetailsWithTreeShap);

    render(<SessionsView />);

    await waitFor(() => {
      expect(screen.getAllByText("sess_test_101").length).toBeGreaterThan(0);
    });

    expect(screen.queryByLabelText(/select tenant/i)).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/switch tenant/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: /tenant/i })).not.toBeInTheDocument();
  });

  describe("Authoritative RBAC Invariant Across Canonical Roles", () => {
    it("strictly grants sessions access to roles possessing VERIFY_READ or AUDIT_READ and denies VIEWER", () => {
      // Canonical 5 roles evaluation:
      // SUPER_ADMIN: has VERIFY_READ & AUDIT_READ
      const superAdminPerms = ROLE_PERMISSIONS.super_admin;
      expect(
        superAdminPerms.has(PERMISSIONS.VERIFY_READ) ||
        superAdminPerms.has(PERMISSIONS.AUDIT_READ)
      ).toBe(true);

      // TENANT_ADMIN: has VERIFY_READ & AUDIT_READ
      const tenantAdminPerms = ROLE_PERMISSIONS.tenant_admin;
      expect(
        tenantAdminPerms.has(PERMISSIONS.VERIFY_READ) ||
        tenantAdminPerms.has(PERMISSIONS.AUDIT_READ)
      ).toBe(true);

      // OPERATOR: has AUDIT_READ
      const operatorPerms = ROLE_PERMISSIONS.operator;
      expect(
        operatorPerms.has(PERMISSIONS.VERIFY_READ) ||
        operatorPerms.has(PERMISSIONS.AUDIT_READ)
      ).toBe(true);

      // API_CLIENT: has VERIFY_READ
      const apiClientPerms = ROLE_PERMISSIONS.api_client;
      expect(
        apiClientPerms.has(PERMISSIONS.VERIFY_READ) ||
        apiClientPerms.has(PERMISSIONS.AUDIT_READ)
      ).toBe(true);

      // VIEWER: lacks both VERIFY_READ and AUDIT_READ
      const viewerPerms = ROLE_PERMISSIONS.viewer;
      expect(
        viewerPerms.has(PERMISSIONS.VERIFY_READ) ||
        viewerPerms.has(PERMISSIONS.AUDIT_READ)
      ).toBe(false);
    });
  });
});
