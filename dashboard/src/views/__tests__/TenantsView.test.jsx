import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { TenantsView } from "../TenantsView";
import { AuthProvider, ROLES } from "../../context/AuthContext";
import * as tenantsApi from "../../api/tenants";
import * as apikeysApi from "../../api/apikeys";

vi.mock("../../api/tenants", () => ({
  listTenants: vi.fn(),
  createTenant: vi.fn(),
  getTenant: vi.fn(),
  updateTenant: vi.fn(),
  suspendTenant: vi.fn(),
  reactivateTenant: vi.fn(),
  offboardTenant: vi.fn(),
}));

vi.mock("../../api/apikeys", () => ({
  listApiKeys: vi.fn(),
  createApiKey: vi.fn(),
  getApiKey: vi.fn(),
  rotateApiKey: vi.fn(),
  revokeApiKey: vi.fn(),
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

describe("TenantsView Component", () => {
  const mockTenants = [
    {
      id: "acme-corp",
      name: "Acme Corporation",
      status: "ACTIVE",
      environment: "production",
      created_at: "2026-10-15T12:00:00Z",
      updated_at: "2026-10-15T12:00:00Z",
    },
    {
      id: "beta-inc",
      name: "Beta Inc",
      status: "SUSPENDED",
      suspension_reason: "Billing audit pending",
      environment: "staging",
      created_at: "2026-10-16T12:00:00Z",
      updated_at: "2026-10-17T12:00:00Z",
    },
  ];

  const mockApiKeys = [
    {
      id: "key-12345",
      name: "Production Worker",
      key_prefix: "mirage_live_prod123",
      tenant_id: "acme-corp",
      scopes: ["*"],
      is_active: true,
      last_used_at: "2026-10-18T10:00:00Z",
      expires_at: "2026-11-18T10:00:00Z",
      revoked_at: null,
      created_at: "2026-10-18T09:00:00Z",
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    tenantsApi.listTenants.mockResolvedValue({ items: mockTenants, total: 2 });
    apikeysApi.listApiKeys.mockResolvedValue({ items: mockApiKeys, total: 1 });
  });

  it("renders the view with tenants and API keys directory tabs", async () => {
    renderWithRole(ROLES.SUPER_ADMIN, <TenantsView />);

    expect(screen.getByText(/SaaS Control Plane & Security/i)).toBeInTheDocument();
    expect(screen.getByText(/Tenants Directory/i)).toBeInTheDocument();
    expect(screen.getByText(/API Credentials/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("acme-corp")).toBeInTheDocument();
      expect(screen.getByText("Acme Corporation")).toBeInTheDocument();
      expect(screen.getByText("Beta Inc")).toBeInTheDocument();
      expect(screen.getByText("ACTIVE")).toBeInTheDocument();
      expect(screen.getByText("SUSPENDED")).toBeInTheDocument();
    });
  });

  it("displays suspension reason for suspended tenants", async () => {
    renderWithRole(ROLES.SUPER_ADMIN, <TenantsView />);

    await waitFor(() => {
      expect(screen.getByText(/Reason: Billing audit pending/i)).toBeInTheDocument();
    });
  });

  it("switches to API credentials subtab and displays keys", async () => {
    renderWithRole(ROLES.SUPER_ADMIN, <TenantsView />);

    const keysTab = screen.getByText(/API Credentials/i);
    fireEvent.click(keysTab);

    await waitFor(() => {
      expect(screen.getByText("Production Worker")).toBeInTheDocument();
      expect(screen.getByText(/mirage_live_prod123/i)).toBeInTheDocument();
      expect(screen.getByText("Active")).toBeInTheDocument();
    });
  });

  it("generates an API key and displays one-time secret modal with warning", async () => {
    const rawSecret = "mirage_live_secret_high_entropy_token_12345";
    apikeysApi.createApiKey.mockResolvedValue({
      id: "key-99999",
      name: "New Integration Key",
      key_prefix: "mirage_live_secret",
      tenant_id: "acme-corp",
      scopes: ["*"],
      is_active: true,
      last_used_at: null,
      expires_at: "2026-11-18T10:00:00Z",
      revoked_at: null,
      created_at: "2026-10-18T10:00:00Z",
      key_secret: rawSecret,
    });

    renderWithRole(ROLES.SUPER_ADMIN, <TenantsView />);

    // Switch to API credentials
    fireEvent.click(screen.getByText(/API Credentials/i));

    await waitFor(() => {
      expect(screen.getByText(/Generate API Key/i)).toBeInTheDocument();
    });

    // Open generate modal
    fireEvent.click(screen.getByText(/Generate API Key/i));

    expect(screen.getByRole("heading", { name: /Generate API Key/i })).toBeInTheDocument();

    // Fill form
    const nameInput = screen.getByPlaceholderText(/e\.g\. CI\/CD Ingestion Worker/i);
    fireEvent.change(nameInput, { target: { value: "New Integration Key" } });

    // Submit form
    const submitBtn = screen.getByRole("button", { name: /^Generate Key$/i });
    fireEvent.click(submitBtn);

    // One-time secret modal must appear
    await waitFor(() => {
      expect(screen.getByText(/Save Your API Key Secret/i)).toBeInTheDocument();
      expect(screen.getByText(/This plaintext secret is displayed/i)).toBeInTheDocument();
      expect(screen.getByText(rawSecret)).toBeInTheDocument();
    });

    // Dismiss one-time secret modal
    const dismissBtn = screen.getByRole("button", { name: /I have saved this key safely/i });
    fireEvent.click(dismissBtn);

    // Secret must be wiped from the DOM
    await waitFor(() => {
      expect(screen.queryByText(rawSecret)).not.toBeInTheDocument();
    });
  });

  it("rotates an API key and displays new secret", async () => {
    const rotatedSecret = "mirage_live_rotated_token_67890";
    apikeysApi.rotateApiKey.mockResolvedValue({
      id: "key-12345-new",
      name: "Production Worker",
      key_prefix: "mirage_live_rotated",
      tenant_id: "acme-corp",
      scopes: ["*"],
      is_active: true,
      last_used_at: null,
      expires_at: "2026-11-18T10:00:00Z",
      revoked_at: null,
      created_at: "2026-10-18T10:00:00Z",
      key_secret: rotatedSecret,
    });

    renderWithRole(ROLES.SUPER_ADMIN, <TenantsView />);

    fireEvent.click(screen.getByText(/API Credentials/i));

    await waitFor(() => {
      expect(screen.getByText("Production Worker")).toBeInTheDocument();
    });

    const rotateBtn = screen.getByTitle("Rotate Key");
    fireEvent.click(rotateBtn);

    // Rotate modal appears
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /Rotate API Key/i })).toBeInTheDocument();
    });

    const confirmRotateBtn = screen.getByRole("button", { name: /Rotate Now/i });
    fireEvent.click(confirmRotateBtn);

    await waitFor(() => {
      expect(screen.getByText(rotatedSecret)).toBeInTheDocument();
    });
  });

  it("suspends a tenant after entering reason", async () => {
    tenantsApi.suspendTenant.mockResolvedValue({
      id: "acme-corp",
      name: "Acme Corporation",
      status: "SUSPENDED",
      suspension_reason: "Manual suspension test",
      environment: "production",
    });

    renderWithRole(ROLES.SUPER_ADMIN, <TenantsView />);

    await waitFor(() => {
      expect(screen.getByText("acme-corp")).toBeInTheDocument();
    });

    const suspendBtn = screen.getAllByRole("button", { name: /^Suspend$/i })[0];
    fireEvent.click(suspendBtn);

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /Suspend Tenant/i })).toBeInTheDocument();
    });

    const reasonInput = screen.getByPlaceholderText(/Billing delinquent/i);
    fireEvent.change(reasonInput, { target: { value: "Manual suspension test" } });

    const confirmBtn = screen.getByRole("button", { name: /Confirm Suspension/i });
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(tenantsApi.suspendTenant).toHaveBeenCalledWith("acme-corp", {
        reason: "Manual suspension test",
      });
    });
  });

  it("handles and displays API error banner", async () => {
    tenantsApi.listTenants.mockRejectedValue(new Error("Database connection refused"));

    renderWithRole(ROLES.SUPER_ADMIN, <TenantsView />);

    await waitFor(() => {
      expect(screen.getByText(/Operation Failed/i)).toBeInTheDocument();
      expect(screen.getByText(/Database connection refused/i)).toBeInTheDocument();
    });
  });
});
