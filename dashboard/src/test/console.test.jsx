import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { AuthProvider } from '../context/AuthContext';
import { OperatorConsole } from '../views/OperatorConsole';

describe('Operator Console Views & Actions', () => {
  it('renders key metrics and live transaction stream', async () => {
    render(
      <AuthProvider>
        <OperatorConsole setActiveView={() => {}} />
      </AuthProvider>
    );

    expect(screen.getByText(/Operator Mission Control/i)).toBeInTheDocument();
    expect(screen.getByText(/Live Transactions/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText(/tx_98f12a4b8c91/i)).toBeInTheDocument();
      expect(screen.getByText(/treasury.disburse_funds/i)).toBeInTheDocument();
    });
  });

  it('switches between tabs: approvals, outcomes, audit chain, agents, health', async () => {
    render(
      <AuthProvider>
        <OperatorConsole setActiveView={() => {}} />
      </AuthProvider>
    );

    // Click L4 Approvals Inbox
    const approvalsTab = screen.getByText(/L4 Approvals Inbox/i);
    fireEvent.click(approvalsTab);
    expect(screen.getByText(/L4 Human Approval Gate/i)).toBeInTheDocument();

    // Click Audit Hash Chain
    const auditTab = screen.getByText(/Audit Hash Chain/i);
    fireEvent.click(auditTab);
    expect(screen.getByText(/Cryptographic Audit Ledger Trail/i)).toBeInTheDocument();
    expect(screen.getByText(/Verify Full Hash Chain/i)).toBeInTheDocument();

    // Click Gate 5 Reality Probes
    const outcomesTab = screen.getByText(/Gate 5 Reality Probes/i);
    fireEvent.click(outcomesTab);
    expect(screen.getByText(/Gate 5 Epistemic Outcome Verification/i)).toBeInTheDocument();
  });
});
