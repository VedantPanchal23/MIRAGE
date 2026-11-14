import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import App from '../App.jsx';

describe('Enterprise Authentication Portal & Console Access', () => {
  beforeEach(() => {
    localStorage.clear();
  });
  it('renders enterprise portal with assurance promise and charter tag', () => {
    render(<App />);
    const controlAiHeadings = screen.getAllByText(/Control AI before it acts/i);
    expect(controlAiHeadings.length).toBeGreaterThan(0);
    const charterBadges = screen.getAllByText(/Charter Specification 3.0/i);
    expect(charterBadges.length).toBeGreaterThan(0);
    expect(screen.getByText(/Provision Enterprise Tenant/i)).toBeInTheDocument();
  });

  it('allows 1-click demonstrator access into Operator Console and Live Assurance Lab', async () => {
    render(<App />);
    
    // Click Operator 1-Click Demo Access
    const operatorButton = screen.getByText('Level 3 Autonomy');
    fireEvent.click(operatorButton);

    await waitFor(() => {
      expect(screen.getByText(/Operator Mission Control/i)).toBeInTheDocument();
      expect(screen.getByText(/Live Transactions/i)).toBeInTheDocument();
      expect(screen.getByText(/Live Assurance Lab \(Grok\)/i)).toBeInTheDocument();
    });

    // Switch to Live Assurance Lab tab
    const labTab = screen.getByText(/Live Assurance Lab \(Grok\)/i);
    fireEvent.click(labTab);

    expect(screen.getByText(/Live Assurance Lab & Grok Evaluation Studio/i)).toBeInTheDocument();
    expect(screen.getByText(/Generate Answer with Grok/i)).toBeInTheDocument();
    expect(screen.getByText(/Run MIRAGE Assurance Pipeline/i)).toBeInTheDocument();
    expect(screen.getByText(/Type \/ Adversarial/i)).toBeInTheDocument();
  });

  it('supports adversarial injection in Live Assurance Lab', async () => {
    render(<App />);
    
    const operatorButton = screen.getByText('Level 3 Autonomy');
    fireEvent.click(operatorButton);

    await waitFor(() => {
      expect(screen.getByText(/Live Assurance Lab \(Grok\)/i)).toBeInTheDocument();
    });

    const labTab = screen.getByText(/Live Assurance Lab \(Grok\)/i);
    fireEvent.click(labTab);

    // Click Inject Hallucination
    const hallucinationBtn = screen.getByText('+ Hallucination');
    fireEvent.click(hallucinationBtn);

    const textarea = screen.getByDisplayValue(/According to EU AI Act Section 99/i);
    expect(textarea).toBeInTheDocument();
  });
});
