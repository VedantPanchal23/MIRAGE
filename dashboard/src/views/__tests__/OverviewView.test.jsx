import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { OverviewView } from "../OverviewView";
import * as api from "../../api";

vi.mock("../../api", () => ({
  getDashboardStats: vi.fn(),
  getHealth: vi.fn(),
}));

describe("OverviewView Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getHealth.mockResolvedValue({
      circuits: {
        llm_api: { state: "closed", fail_counter: 0, fail_max: 5, reset_timeout: 60 },
      },
    });
  });

  it("renders loading state on initial mount", () => {
    api.getDashboardStats.mockReturnValue(new Promise(() => {})); // pending

    render(<OverviewView />);
    expect(screen.getByRole("status")).toHaveAttribute("aria-label", "Loading overview statistics");
  });

  it("calls centralized API client getDashboardStats rather than raw fetch", async () => {
    api.getDashboardStats.mockResolvedValueOnce({
      total_requests: 1500,
      average_hrs: 0.075,
      correction_rate: 0.03,
      tier_counts: { LOW: 1400, MEDIUM: 80, HIGH: 15, CRITICAL: 5 },
    });

    render(<OverviewView />);

    await waitFor(() => {
      expect(api.getDashboardStats).toHaveBeenCalledTimes(1);
    });
  });

  it("renders success state with KPI cards and risk tier distributions", async () => {
    api.getDashboardStats.mockResolvedValueOnce({
      total_requests: 10000,
      average_hrs: 0.082,
      correction_rate: 0.045,
      tier_counts: { LOW: 8500, MEDIUM: 1100, HIGH: 350, CRITICAL: 50 },
      drift_report: {
        psi: 0.024,
        status: "STABLE",
        ks_pvalue: 0.52,
        alert_triggered: false,
      },
    });

    render(<OverviewView />);

    await waitFor(() => {
      expect(screen.getByText("10,000")).toBeInTheDocument();
      expect(screen.getByText("0.082")).toBeInTheDocument();
      expect(screen.getAllByText("0.5%").length).toBeGreaterThan(0); // Critical rate
      expect(screen.getByText("4.5%")).toBeInTheDocument(); // Correction rate
    });

    // Check risk tier breakdown
    expect(screen.getByText("Risk Tier Distribution")).toBeInTheDocument();
    expect(screen.getByText("8,500")).toBeInTheDocument();
    expect(screen.getByText("1,100")).toBeInTheDocument();
    expect(screen.getByText("350")).toBeInTheDocument();
    expect(screen.getByText("50")).toBeInTheDocument();

    // Check drift status banner
    expect(screen.getByText("Population Stability Index:")).toBeInTheDocument();
    expect(screen.getByText("0.0240")).toBeInTheDocument();
    expect(screen.getByText("STABLE")).toBeInTheDocument();
  });

  it("renders empty state when total_requests is 0", async () => {
    api.getDashboardStats.mockResolvedValueOnce({
      total_requests: 0,
      average_hrs: 0.0,
      correction_rate: 0.0,
      tier_counts: { LOW: 0, MEDIUM: 0, HIGH: 0, CRITICAL: 0 },
    });

    render(<OverviewView />);

    await waitFor(() => {
      expect(screen.getByText("No Verification Telemetry Available")).toBeInTheDocument();
      expect(screen.getByText(/There are no recorded verification sessions/i)).toBeInTheDocument();
    });
  });

  it("renders error state when centralized API call fails and provides retry button", async () => {
    const apiError = new Error("Database query timeout");
    apiError.code = "SERVICE_DEGRADED";
    apiError.traceId = "tr_error_999";
    apiError.status = 503;

    api.getDashboardStats.mockRejectedValueOnce(apiError);

    render(<OverviewView />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
      expect(screen.getByText("Unable to Load Overview Telemetry")).toBeInTheDocument();
      expect(screen.getByText("Database query timeout")).toBeInTheDocument();
      expect(screen.getByText("Code: SERVICE_DEGRADED")).toBeInTheDocument();
      expect(screen.getByText("Trace: tr_error_999")).toBeInTheDocument();
    });

    // Verify retry button triggers refetch
    api.getDashboardStats.mockResolvedValueOnce({
      total_requests: 200,
      average_hrs: 0.05,
      correction_rate: 0.01,
      tier_counts: { LOW: 190, MEDIUM: 10, HIGH: 0, CRITICAL: 0 },
    });

    fireEvent.click(screen.getByRole("button", { name: /retry/i }));

    await waitFor(() => {
      expect(screen.getByText("200")).toBeInTheDocument();
    });
  });
});
