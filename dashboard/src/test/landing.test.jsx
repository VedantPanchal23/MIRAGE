import React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import App from '../App.jsx';

describe('Enterprise Authentication Portal, Pricing, Legal & Console Access', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url) => {
        const path = String(url);
        if (path.includes('/v1/billing/plans')) {
          return {
            ok: true,
            status: 200,
            json: async () => [
              {
                tier: 'developer',
                name: 'Developer Sandbox',
                tagline: 'Sandbox evaluation',
                price_dollars_monthly: 0,
                price_inr_monthly: 0,
                request_quota_monthly: 10000,
                max_concurrent_leases: 2,
                budget_ceiling_usd: 10,
              },
              {
                tier: 'business',
                name: 'Pro / Starter',
                tagline: 'Production assurance',
                price_dollars_monthly: 29,
                price_inr_monthly: 1999,
                request_quota_monthly: 75000,
                max_concurrent_leases: 10,
                budget_ceiling_usd: 150,
              },
            ],
          };
        }
        if (path.includes('/v1/status')) {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              service: 'MIRAGE Execution Assurance Platform',
              status: 'operational',
              gates: { gate1_input: 'operational', gate5_outcome: 'operational' },
            }),
          };
        }
        return { ok: true, status: 200, json: async () => ({ status: 'healthy', items: [] }) };
      })
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders enterprise portal with promise, pricing tiers, comparison table, and cookie consent', async () => {
    render(<App />);
    expect(screen.getAllByText(/Control AI before it acts/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Charter Specification 3.0/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Provision Enterprise Tenant/i)).toBeInTheDocument();
    expect(screen.getByText(/Transparent Commercial Tiers/i)).toBeInTheDocument();
    expect(screen.getByText(/Why Execution Assurance Beats Prompt-Only Guardrails/i)).toBeInTheDocument();
    expect(screen.getByText(/Privacy & Cookie Controls/i)).toBeInTheDocument();
  });

  it('opens Legal Privacy Policy and System Status modals from footer', async () => {
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: 'Trust Center' }));
    expect(screen.getByText(/Security & Compliance Trust Center/i)).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/Close legal and compliance dialog/i));
    fireEvent.click(screen.getByRole('button', { name: 'System Status' }));
    await waitFor(() => {
      expect(screen.getByText(/MIRAGE Operational System Status/i)).toBeInTheDocument();
      expect(screen.getByText(/operational/i)).toBeInTheDocument();
    });
  });

  it('allows 1-click sandbox demonstrator access into Operator Console and Live Assurance Lab', async () => {
    render(<App />);
    fireEvent.click(screen.getByText('Level 3 Autonomy'));

    await waitFor(() => {
      expect(screen.getByText(/Operator Mission Control/i)).toBeInTheDocument();
      expect(screen.getByText(/Live Assurance Lab \(Grok\)/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText(/Live Assurance Lab \(Grok\)/i));
    expect(screen.getByText(/Live Assurance Lab & Grok Evaluation Studio/i)).toBeInTheDocument();

    fireEvent.click(screen.getByText('+ Hallucination'));
    expect(screen.getByDisplayValue(/According to EU AI Act Section 99/i)).toBeInTheDocument();
  });
});
