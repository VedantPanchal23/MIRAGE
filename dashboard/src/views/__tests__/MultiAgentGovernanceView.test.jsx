import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MultiAgentGovernanceView } from "../MultiAgentGovernanceView";
import * as api from "../../api/multiagent";
import { AuthContext } from "../../context/AuthContext";

// Mock the API module
vi.mock("../../api/multiagent", () => ({
  listAgents: vi.fn(),
  registerAgent: vi.fn(),
  activateAgent: vi.fn(),
  suspendAgent: vi.fn(),
  revokeAgent: vi.fn(),
  listDelegations: vi.fn(),
  createDelegation: vi.fn(),
  activateDelegation: vi.fn(),
  revokeDelegation: vi.fn(),
  listHandoffs: vi.fn(),
  createHandoff: vi.fn(),
  acceptHandoff: vi.fn(),
  cancelHandoff: vi.fn(),
  completeHandoff: vi.fn(),
  listLeases: vi.fn(),
  acquireLease: vi.fn(),
  releaseLease: vi.fn(),
  renewLease: vi.fn(),
  getTransactionHierarchy: vi.fn(),
}));

const mockAuthContext = {
  role: "operator",
  tenantId: "tenant_demo",
  hasRole: vi.fn(() => true),
  hasPermission: vi.fn(() => true),
};

const mockAgents = [
  {
    id: "agt_planner_01",
    name: "Planner Agent",
    status: "active",
    max_autonomy_level: 2,
    created_at: "2026-10-15T10:00:00Z",
  },
  {
    id: "agt_executor_02",
    name: "Executor Agent",
    status: "registered",
    max_autonomy_level: 1,
    created_at: "2026-10-15T10:05:00Z",
  },
  {
    id: "agt_legacy_03",
    name: "Legacy Agent",
    status: "revoked",
    max_autonomy_level: 0,
    created_at: "2026-10-14T09:00:00Z",
    revocation_reason: "Deprecation policy",
  },
];

const mockDelegations = [
  {
    id: "del_grant_101",
    parent_transaction_id: "txn_root_001",
    child_agent_id: "agt_executor_02",
    child_transaction_id: null,
    status: "PENDING",
    max_autonomy_level: 1,
    max_turns: 4,
    purpose: "Analyze logs",
    delegated_capabilities: [{ capability_type: "tools:file_read", max_autonomy_level: 1 }],
    expires_at: "2026-10-15T12:00:00Z",
  },
  {
    id: "del_grant_102",
    parent_transaction_id: "txn_root_001",
    child_agent_id: "agt_planner_01",
    child_transaction_id: "txn_child_555",
    status: "ACTIVE",
    max_autonomy_level: 2,
    max_turns: 8,
    purpose: "Resource planning",
    delegated_capabilities: [{ capability_type: "tools:db_query", max_autonomy_level: 2 }],
    expires_at: "2026-10-15T13:00:00Z",
  },
];

const mockHandoffs = [
  {
    id: "hnd_901",
    parent_transaction_id: "txn_root_001",
    child_agent_id: "agt_executor_02",
    delegation_id: "del_grant_101",
    status: "PENDING",
    purpose: "Execute file read",
    inherited_taint_flags: ["CONFIDENTIAL"],
    expires_at: "2026-10-15T12:05:00Z",
  },
  {
    id: "hnd_902",
    parent_transaction_id: "txn_root_001",
    child_agent_id: "agt_planner_01",
    delegation_id: "del_grant_102",
    child_transaction_id: "txn_child_555",
    status: "ACCEPTED",
    purpose: "Execute planning",
    inherited_taint_flags: [],
    expires_at: "2026-10-15T12:10:00Z",
  },
];

const mockLeases = [
  {
    id: "lse_801",
    resource_uri: "db://customers/primary",
    holder_transaction_id: "txn_root_001",
    holder_agent_id: "agt_planner_01",
    concurrency_mode: "EXCLUSIVE",
    fencing_token: 42,
    status: "ACQUIRED",
    expires_at: "2026-10-15T12:15:00Z",
  },
];

const mockHierarchy = {
  parent_transaction_id: "txn_root_001",
  parent_transaction_state: "EXECUTING",
  parent_final_disposition: null,
  hierarchical_status: "AWAITING_OUTCOME_VERIFICATION",
  epistemic_confidence: 0.0,
  evaluation_hash: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  total_child_transactions: 1,
  active_child_transactions: 1,
  total_handoffs: 2,
  pending_handoffs: 1,
  parent_actions: [
    {
      action_id: "act_p_01",
      action_state: "EXECUTED",
      requires_outcome_assurance: true,
      outcome_status: "PENDING_VERIFICATION",
      epistemic_confidence: 0.0,
      target_resource: "db://records/01",
    },
  ],
  child_executions: [
    {
      transaction_id: "txn_child_555",
      agent_id: "agt_planner_01",
      state: "ACTIVE",
      execution_completed: false,
      action_summaries: [],
    },
  ],
  handoffs: [
    {
      handoff_id: "hnd_901",
      parent_transaction_id: "txn_root_001",
      child_agent_id: "agt_executor_02",
      status: "PENDING",
      purpose: "Execute file read",
    },
  ],
  discrepancies: ["Actions awaiting reality verification"],
  reconciliation_notes: ["Epistemic confidence is 0.0 pending Gate 5 reality verification."],
};

function renderWithContext(ui) {
  return render(<AuthContext.Provider value={mockAuthContext}>{ui}</AuthContext.Provider>);
}

describe("MultiAgentGovernanceView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listAgents.mockResolvedValue({ agents: mockAgents, total: 3, limit: 100, offset: 0 });
    api.listDelegations.mockResolvedValue(mockDelegations);
    api.listHandoffs.mockResolvedValue(mockHandoffs);
    api.listLeases.mockResolvedValue(mockLeases);
    api.getTransactionHierarchy.mockResolvedValue(mockHierarchy);
  });

  it("renders global metrics and sub-navigation tabs", async () => {
    renderWithContext(<MultiAgentGovernanceView />);

    expect(await screen.findByText(/Governed Multi-Agent Coordination & Assurance/i)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Agents & Lifecycle/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Delegation Grants/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Governed Handoffs/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Resource Leases/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Hierarchical Assurance/i })).toBeInTheDocument();

    // Verify stats
    expect(screen.getByText(/Active Governed Agents/i)).toBeInTheDocument();
    expect(screen.getByText(/Pending Handoffs/i)).toBeInTheDocument();
  });

  it("displays agent list and filters by status", async () => {
    renderWithContext(<MultiAgentGovernanceView />);

    expect(await screen.findByText("Planner Agent")).toBeInTheDocument();
    expect(screen.getByText("Executor Agent")).toBeInTheDocument();
    expect(screen.getByText("Legacy Agent")).toBeInTheDocument();
    expect(screen.getByText(/Revoked \(Terminal\)/i)).toBeInTheDocument();

    // Filter by Active status
    const filterSelect = screen.getByLabelText(/Filter agents by status/i);
    fireEvent.change(filterSelect, { target: { value: "active" } });

    expect(screen.getByText("Planner Agent")).toBeInTheDocument();
    expect(screen.queryByText("Executor Agent")).not.toBeInTheDocument();
  });

  it("opens register agent modal and submits registration", async () => {
    api.registerAgent.mockResolvedValue({
      id: "agt_new_01",
      name: "New Sentinel Agent",
      status: "registered",
      max_autonomy_level: 2,
    });

    renderWithContext(<MultiAgentGovernanceView />);
    await screen.findByText("Planner Agent");

    fireEvent.click(screen.getByRole("button", { name: /Register Agent/i }));
    expect(screen.getByText(/Register New Governed Agent/i)).toBeInTheDocument();

    const nameInput = screen.getByPlaceholderText(/e\.g\. data_analyst_agent/i);
    fireEvent.change(nameInput, { target: { value: "New Sentinel Agent" } });

    fireEvent.click(screen.getByRole("button", { name: /Submit Registration/i }));

    await waitFor(() => {
      expect(api.registerAgent).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "New Sentinel Agent",
        })
      );
    });
  });

  it("switches to Delegation Grants tab and displays grants", async () => {
    renderWithContext(<MultiAgentGovernanceView />);
    await screen.findByText("Planner Agent");

    fireEvent.click(screen.getByRole("tab", { name: /Delegation Grants/i }));

    expect(await screen.findByText("del_grant_101")).toBeInTheDocument();
    expect(screen.getByText("del_grant_102")).toBeInTheDocument();
    expect(screen.getByText(/tools:file_read/i)).toBeInTheDocument();
  });

  it("switches to Governed Handoffs tab and completes an accepted handoff", async () => {
    api.completeHandoff.mockResolvedValue({ id: "hnd_902", status: "COMPLETED" });

    renderWithContext(<MultiAgentGovernanceView />);
    await screen.findByText("Planner Agent");

    fireEvent.click(screen.getByRole("tab", { name: /Governed Handoffs/i }));

    expect(await screen.findByText("hnd_901")).toBeInTheDocument();
    expect(screen.getByText("hnd_902")).toBeInTheDocument();

    const completeBtn = screen.getByRole("button", { name: /^Complete$/i });
    fireEvent.click(completeBtn);

    await waitFor(() => {
      expect(api.completeHandoff).toHaveBeenCalledWith("hnd_902");
    });
  });

  it("switches to Resource Leases tab, displays notice and leases", async () => {
    renderWithContext(<MultiAgentGovernanceView />);
    await screen.findByText("Planner Agent");

    fireEvent.click(screen.getByRole("tab", { name: /Resource Leases/i }));

    expect(await screen.findByText(/Distributed Resource Concurrency & Fencing Coordination Notice/i)).toBeInTheDocument();
    expect(screen.getByText("db://customers/primary")).toBeInTheDocument();
    expect(screen.getByText(/Token #42/i)).toBeInTheDocument();
  });

  it("switches to Hierarchical Assurance tab and audits transaction lineage", async () => {
    renderWithContext(<MultiAgentGovernanceView />);
    await screen.findByText("Planner Agent");

    fireEvent.click(screen.getByRole("tab", { name: /Hierarchical Assurance/i }));

    const input = screen.getByLabelText(/Enter Root or Parent Transaction ID:/i);
    fireEvent.change(input, { target: { value: "txn_root_001" } });

    fireEvent.click(screen.getByRole("button", { name: /Audit Lineage/i }));

    expect(await screen.findByText(/AWAITING OUTCOME VERIFICATION \(Executed != Verified\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Weakest-Link Epistemic Confidence:/i)).toBeInTheDocument();
    expect(screen.getByText(/Parent Consequential Actions/i)).toBeInTheDocument();
    expect(screen.getByText("act_p_01")).toBeInTheDocument();
    expect(screen.getByText(/Child Transaction Lineage/i)).toBeInTheDocument();
    expect(screen.getByText("txn_child_555")).toBeInTheDocument();
  });
});
