import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import App from '../App.jsx';

describe('Landing Page & Public Experience', () => {
  it('renders hero title with Five Gates promise and architectural tag', () => {
    render(<App />);
    const controlAiHeadings = screen.getAllByText(/Control AI/i);
    expect(controlAiHeadings.length).toBeGreaterThan(0);
    const charterBadges = screen.getAllByText(/Charter Specification 3.0/i);
    expect(charterBadges.length).toBeGreaterThan(0);
    const gateHeadings = screen.getAllByText(/The Five Assurance Gates/i);
    expect(gateHeadings.length).toBeGreaterThan(0);
  });

  it('renders interactive simulator with scenario options', () => {
    render(<App />);
    expect(screen.getByText(/Interactive Execution Simulator/i)).toBeInTheDocument();
    const scenario1 = screen.getAllByText(/1. Safe Treasury Mutation/i);
    expect(scenario1.length).toBeGreaterThan(0);
    const scenario2 = screen.getAllByText(/2. Indirect Injection Attack/i);
    expect(scenario2.length).toBeGreaterThan(0);
  });

  it('navigates to Operator Console view upon clicking Launch Console', async () => {
    render(<App />);
    const launchButtons = screen.getAllByText(/Launch Console/i);
    expect(launchButtons.length).toBeGreaterThan(0);
    fireEvent.click(launchButtons[0]);

    await waitFor(() => {
      expect(screen.getByText(/Operator Mission Control/i)).toBeInTheDocument();
      expect(screen.getByText(/Live Transactions/i)).toBeInTheDocument();
    });
  });
});
