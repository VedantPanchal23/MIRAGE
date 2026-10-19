import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MCPServersView } from "../MCPServersView";
import { AuthProvider, ROLES } from "../../context/AuthContext";
import * as mcpApi from "../../api/mcp";

vi.mock("../../api/mcp", () => ({
  listMCPServers: vi.fn(),
  registerMCPServer: vi.fn(),
  getMCPServer: vi.fn(),
  updateMCPServerTrust: vi.fn(),
  discoverMCPTools: vi.fn(),
}));

function createMockJwt(payload) {
  const header = { alg: "HS256", typ: "JWT" };
  const toBase64Url = (obj) =>
    btoa(unescape(encodeURIComponent(JSON.stringify(obj))))
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");
  return `${toBase64Url(header)}.${toBase64Url(payload)}.mock_sig`;
}

function renderWithRole(role, ui) {
  const token = createMockJwt({
    sub: `usr_${role}`,
    tenant_id: "tenant_corp",
    role,
    exp: Math.floor(Date.now() / 1000) + 3600,
  });

  return render(
    <AuthProvider initialToken={token}>
      {ui}
    </AuthProvider>
  );
}

describe("MCPServersView Component", () => {
  const mockServers = [
    {
      id: "mcp_srv_local_01",
      tenant_id: "tenant_corp",
      name: "Local Python Tools",
      description: "Local data analysis tools",
      transport_type: "STDIO",
      connection_config: { command: "python", args: ["-m", "my_pkg"] },
      trust_status: "TRUSTED",
      permitted_capabilities: ["analysis:run"],
      egress_allowlist: [],
      timeout_seconds: 30,
      tool_count: 3,
      created_at: "2026-10-18T10:00:00Z",
      updated_at: "2026-10-18T10:00:00Z",
    },
    {
      id: "mcp_srv_remote_02",
      tenant_id: "tenant_corp",
      name: "Remote SQL Gateway",
      description: "External cloud MCP SQL adapter",
      transport_type: "HTTP_STREAM",
      connection_config: { url: "https://sql.external-cloud.com/mcp" },
      trust_status: "PENDING_APPROVAL",
      permitted_capabilities: ["sql:query"],
      egress_allowlist: ["sql.external-cloud.com"],
      timeout_seconds: 45,
      tool_count: 0,
      created_at: "2026-10-19T08:00:00Z",
      updated_at: "2026-10-19T08:00:00Z",
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    mcpApi.listMCPServers.mockResolvedValue({ items: mockServers, total: 2 });
  });

  it("renders the MCP registry header and server list", async () => {
    renderWithRole(ROLES.SUPER_ADMIN, <MCPServersView />);

    expect(screen.getByText(/Governed MCP Server Registry/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("Local Python Tools")).toBeInTheDocument();
      expect(screen.getByText("Remote SQL Gateway")).toBeInTheDocument();
      expect(screen.getByText("TRUSTED")).toBeInTheDocument();
      expect(screen.getByText("PENDING APPROVAL")).toBeInTheDocument();
    });
  });

  it("opens registration modal and registers a new MCP server", async () => {
    mcpApi.registerMCPServer.mockResolvedValue({
      id: "mcp_srv_new_03",
      tenant_id: "tenant_corp",
      name: "New Weather Server",
      transport_type: "HTTP_STREAM",
      trust_status: "PENDING_APPROVAL",
      tool_count: 0,
      created_at: "2026-10-19T12:00:00Z",
      updated_at: "2026-10-19T12:00:00Z",
    });

    renderWithRole(ROLES.SUPER_ADMIN, <MCPServersView />);

    await waitFor(() => {
      expect(screen.getByText("Register Server")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Register Server"));

    expect(screen.getByText("Register External MCP Server")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/e\.g\. production-database-mcp/i), {
      target: { value: "New Weather Server" },
    });

    // Select HTTP_STREAM
    fireEvent.change(screen.getByDisplayValue("STDIO (Local Subprocess)"), {
      target: { value: "HTTP_STREAM" },
    });

    fireEvent.change(screen.getByPlaceholderText(/https:\/\/mcp\.external-service\.com\/rpc/i), {
      target: { value: "https://weather.external-api.com/mcp" },
    });

    // Submit form
    const submitBtn = screen.getByRole("button", { name: /^Submit Registration$/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(mcpApi.registerMCPServer).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "New Weather Server",
          transport_type: "HTTP_STREAM",
          connection_config: { url: "https://weather.external-api.com/mcp" },
        })
      );
    });
  });

  it("triggers tool discovery for trusted server and displays results modal", async () => {
    mcpApi.discoverMCPTools.mockResolvedValue({
      server_id: "mcp_srv_local_01",
      server_name: "Local Python Tools",
      tools_discovered: [
        {
          name: "calculate_stats",
          namespaced_name: "mcp_srv_local_01:calculate_stats",
          description: "Compute mean and variance",
          input_schema: { type: "object" },
          schema_fingerprint: "abc123fingerprint",
          required_capability: "analysis:run",
        },
      ],
      tools_registered: 1,
    });

    renderWithRole(ROLES.SUPER_ADMIN, <MCPServersView />);

    await waitFor(() => {
      expect(screen.getByText("Local Python Tools")).toBeInTheDocument();
    });

    const discoverButtons = screen.getAllByRole("button", { name: /Discover Tools/i });
    fireEvent.click(discoverButtons[0]);

    await waitFor(() => {
      expect(mcpApi.discoverMCPTools).toHaveBeenCalledWith("mcp_srv_local_01");
      expect(screen.getByText(/Tool Discovery: Local Python Tools/i)).toBeInTheDocument();
      expect(screen.getByText("mcp_srv_local_01:calculate_stats")).toBeInTheDocument();
      expect(screen.getByText("Compute mean and variance")).toBeInTheDocument();
    });
  });

  it("handles trust status approval transition", async () => {
    mcpApi.updateMCPServerTrust.mockResolvedValue({
      id: "mcp_srv_remote_02",
      trust_status: "TRUSTED",
    });

    renderWithRole(ROLES.SUPER_ADMIN, <MCPServersView />);

    await waitFor(() => {
      expect(screen.getByText("Remote SQL Gateway")).toBeInTheDocument();
    });

    const approveButton = screen.getByRole("button", { name: /Approve/i });
    fireEvent.click(approveButton);

    expect(screen.getByText(/Transition Server Trust to TRUSTED/i)).toBeInTheDocument();

    const confirmButton = screen.getByRole("button", { name: /Confirm Transition/i });
    fireEvent.click(confirmButton);

    await waitFor(() => {
      expect(mcpApi.updateMCPServerTrust).toHaveBeenCalledWith(
        "mcp_srv_remote_02",
        expect.objectContaining({
          trust_status: "TRUSTED",
        })
      );
    });
  });
});
