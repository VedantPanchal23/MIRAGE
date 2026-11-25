import React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { AuthProvider } from '../context/AuthContext';
import { OperatorConsole } from '../views/OperatorConsole';

describe('Operator Console Views & Actions', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders live telemetry metrics, onboarding checklist, and transactions without mock fallback errors when backend responds', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url) => {
        const path = String(url);
        if (path.includes('/v1/dashboard/stats')) {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              active_transactions_24h: 42,
              assurance_verdict_rate: 98.5,
              pending_l4_approvals: 1,
              mean_gate_latency_ms: 14.2,
              total_audit_anchors: 100,
            }),
          };
        }
        if (path.includes('/v1/sessions')) {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              items: [
                {
                  session_id: 'tx_live_98f12a4b',
                  model_id: 'agent_treasury_disburser',
                  tool_name: 'treasury.disburse_funds',
                  risk_tier: 'LOW',
                  hrs_score: 0.05,
                },
              ],
            }),
          };
        }
        if (path.includes('/v1/health')) {
          return {
            ok: true,
            status: 200,
            json: async () => ({ status: 'healthy', components: { postgres: { status: 'healthy' } } }),
          };
        }
        return {
          ok: true,
          status: 200,
          json: async () => [],
        };
      })
    );

    localStorage.setItem(
      'mirage_auth_user',
      JSON.stringify({ name: 'Vedant', role: 'TENANT_ADMIN', tenant_id: 'tenant_live', isDemo: false, apiKey: 'mirage_live_test' })
    );

    render(
      <AuthProvider>
        <OperatorConsole setActiveView={() => {}} />
      </AuthProvider>
    );

    expect(screen.getByText(/Operator Mission Control/i)).toBeInTheDocument();
    expect(screen.getByText(/Production Quickstart Checklist/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText(/tx_live_98f12a4b/i)).toBeInTheDocument();
      expect(screen.getByText(/treasury.disburse_funds/i)).toBeInTheDocument();
    });
  });

  it('refuses silent fake telemetry and surfaces alert banner when live tenant API fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 503,
        statusText: 'Service Unavailable',
        json: async () => ({ detail: 'PostgreSQL primary unavailable' }),
      }))
    );

    localStorage.setItem(
      'mirage_auth_user',
      JSON.stringify({ name: 'Vedant', role: 'OPERATOR', tenant_id: 'tenant_live', isDemo: false, apiKey: 'mirage_live_test' })
    );

    render(
      <AuthProvider>
        <OperatorConsole setActiveView={() => {}} />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/Live Gateway telemetry unavailable/i);
      expect(screen.queryByText('1,428')).not.toBeInTheDocument();
    });
  });

  it('switches between all tabs including MCP & Tools, Keys & Team, and Governance & Billing', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url) => {
        const path = String(url);
        if (path.includes('/v1/auth/api-keys')) {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              keys: [{ id: 'key_1', name: 'Primary Worker', key_prefix: 'mirage_live_abc', is_active: true }],
            }),
          };
        }
        if (path.includes('/v1/auth/users')) return { ok: true, status: 200, json: async () => ({ users: [] }) };
        if (path.includes('/v1/mcp/servers')) {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              items: [{ id: 'mcp_1', name: 'stripe-mcp', transport_type: 'HTTP_STREAM', trust_status: 'TRUSTED' }],
              total: 1,
            }),
          };
        }
        if (path.includes('/v1/knowledge-base')) return { ok: true, status: 200, json: async () => ({ documents: [] }) };
        if (path.includes('/v1/webhooks')) return { ok: true, status: 200, json: async () => ({ webhooks: [] }) };
        if (path.includes('/v1/billing/subscription')) {
          return {
            ok: true,
            status: 200,
            json: async () => ({ current_tier: 'business', monthly_budget_usd: 150, remaining_headroom_usd: 140 }),
          };
        }
        return { ok: true, status: 200, json: async () => [] };
      })
    );

    localStorage.setItem(
      'mirage_auth_user',
      JSON.stringify({ name: 'Vedant', role: 'OPERATOR', tenant_id: 'tenant_demo', isDemo: true })
    );

    render(
      <AuthProvider>
        <OperatorConsole setActiveView={() => {}} />
      </AuthProvider>
    );

    fireEvent.click(screen.getByText(/L4 Approvals Inbox/i));
    expect(screen.getByText(/L4 Human Approval Gate/i)).toBeInTheDocument();

    fireEvent.click(screen.getByText(/Audit Hash Chain/i));
    expect(screen.getByText(/Cryptographic Audit Ledger Trail/i)).toBeInTheDocument();

    fireEvent.click(screen.getByText(/MCP & Tools/i));
    await waitFor(() => expect(screen.getByText(/Governed MCP Servers/i)).toBeInTheDocument());
    expect(screen.getByText(/stripe-mcp/i)).toBeInTheDocument();

    fireEvent.click(screen.getByText(/Keys & Team/i));
    await waitFor(() => expect(screen.getByText(/Tenant API Keys/i)).toBeInTheDocument());
    expect(screen.getByText(/Primary Worker/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Rotate' })).toBeInTheDocument();

    fireEvent.click(screen.getByText(/Governance & Billing/i));
    await waitFor(() => expect(screen.getByText(/Stranded Execution Reconciliation Queue/i)).toBeInTheDocument());
  });
});
