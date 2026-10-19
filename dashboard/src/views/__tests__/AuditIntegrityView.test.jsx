import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { AuditIntegrityView } from "../AuditIntegrityView";
import * as auditApi from "../../api/audit";

vi.mock("../../api/audit", () => ({
  getAuditEvents: vi.fn(),
  getAuditIntegrity: vi.fn(),
  exportEvidenceBundle: vi.fn(),
  commitAuditAnchor: vi.fn(),
}));

describe("AuditIntegrityView Component", () => {
  const mockIntegrityReport = {
    tenant_id: "tenant_corp",
    status: "ANCHORED",
    chain_valid: true,
    total_records: 42,
    head_sequence: 42,
    head_chain_hash: "abcd1234ef567890abcd1234ef567890abcd1234ef567890abcd1234ef567890",
    latest_anchor: {
      anchor_id: "anc_chk123_20261019",
      tenant_id: "tenant_corp",
      sequence_number: 42,
      checkpoint_hash: "abcd1234ef567890abcd1234ef567890abcd1234ef567890abcd1234ef567890",
      signer_identity: "notary:system_primary",
      trust_tier: "LOCAL_UNANCHORED",
    },
    defects: [],
  };

  const mockEventsResponse = {
    tenant_id: "tenant_corp",
    total_count: 2,
    limit: 25,
    offset: 0,
    next_offset: null,
    events: [
      {
        entry_id: "aud_001",
        sequence_number: 42,
        event_type: "OUTCOME_VERIFICATION",
        transaction_id: "tx_999",
        session_id: "sess_999",
        actor_identity_id: "agent_qa",
        decision: "ALLOW",
        hrs_score: 0.95,
        chain_hash: "hash_42",
        created_at: "2026-10-19T12:00:00Z",
      },
      {
        entry_id: "aud_002",
        sequence_number: 41,
        event_type: "ACTION_LIFECYCLE",
        transaction_id: "tx_998",
        session_id: "sess_998",
        actor_identity_id: "agent_dev",
        decision: "DENY",
        hrs_score: 0.0,
        chain_hash: "hash_41",
        created_at: "2026-10-19T11:55:00Z",
      },
    ],
  };

  beforeEach(() => {
    vi.clearAllMocks();
    auditApi.getAuditIntegrity.mockResolvedValue(mockIntegrityReport);
    auditApi.getAuditEvents.mockResolvedValue(mockEventsResponse);
  });

  it("renders audit integrity status and head hash", async () => {
    render(<AuditIntegrityView />);

    await waitFor(() => {
      expect(screen.getByText("Audit Ledger & Cryptographic Integrity")).toBeInTheDocument();
      expect(screen.getByText("Anchored (Synchronized with External Notary)")).toBeInTheDocument();
      expect(screen.getByText("42")).toBeInTheDocument();
      expect(screen.getAllByText("#42").length).toBeGreaterThan(0);
    });
  });

  it("renders audit events table correctly", async () => {
    render(<AuditIntegrityView />);

    await waitFor(() => {
      expect(screen.getByText("tx_999")).toBeInTheDocument();
      expect(screen.getByText("tx_998")).toBeInTheDocument();
      expect(screen.getAllByText("OUTCOME_VERIFICATION").length).toBeGreaterThan(0);
      expect(screen.getAllByText("ACTION_LIFECYCLE").length).toBeGreaterThan(0);
    });
  });

  it("displays defects when integrity failure is detected", async () => {
    auditApi.getAuditIntegrity.mockResolvedValueOnce({
      ...mockIntegrityReport,
      status: "INTEGRITY_FAILURE",
      chain_valid: false,
      defects: [
        "Sequence break at index 5: expected sequence 6, found 8",
        "Ledger truncation detected: head sequence 40 < anchor sequence 42",
      ],
    });

    render(<AuditIntegrityView />);

    await waitFor(() => {
      expect(screen.getByText(/Integrity Failure/)).toBeInTheDocument();
      expect(screen.getByText(/Sequence break at index 5/)).toBeInTheDocument();
      expect(screen.getByText(/Ledger truncation detected/)).toBeInTheDocument();
    });
  });

  it("handles commit anchor action successfully", async () => {
    auditApi.commitAuditAnchor.mockResolvedValueOnce({
      status: "ANCHORED",
      checkpoint: { sequence_number: 43 },
      anchor: { anchor_id: "anc_new" },
    });

    render(<AuditIntegrityView />);

    await waitFor(() => {
      expect(screen.getByText("Commit Anchor")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Commit Anchor"));

    await waitFor(() => {
      expect(auditApi.commitAuditAnchor).toHaveBeenCalledTimes(1);
      expect(screen.getByText(/Anchor successfully committed/)).toBeInTheDocument();
    });
  });

  it("handles compliance evidence bundle export modal", async () => {
    auditApi.exportEvidenceBundle.mockResolvedValueOnce({
      bundle_id: "bnd_abc123",
      tenant_id: "tenant_corp",
      event_count: 2,
      bundle_digest: "digest_999888777",
      chain_verification: { chain_valid: true, status: "ANCHORED" },
    });

    render(<AuditIntegrityView />);

    await waitFor(() => {
      expect(screen.getByText("Export Bundle")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Export Bundle"));

    await waitFor(() => {
      expect(auditApi.exportEvidenceBundle).toHaveBeenCalledTimes(1);
      expect(screen.getByText("Sealed Compliance Evidence Bundle")).toBeInTheDocument();
      expect(screen.getByText("bnd_abc123")).toBeInTheDocument();
      expect(screen.getByText("digest_999888777")).toBeInTheDocument();
    });
  });
});
