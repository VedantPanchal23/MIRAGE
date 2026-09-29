import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { DriftView } from "../DriftView";
import * as api from "../../api";

vi.mock("../../api", () => ({
  getDriftReport: vi.fn(),
}));

describe("DriftView Component", () => {
  const mockDriftReportSuccess = {
    tenant_id: "tenant_enterprise_01",
    days: 30,
    drift_report: {
      psi: 0.0284,
      ks_statistic: 0.124,
      ks_pvalue: 0.482,
      status: "stable",
      alert_triggered: false,
      alert_reason: null,
      baseline_sample_count: 500,
      current_sample_count: 500,
      baseline_mean_hrs: 0.084,
      current_mean_hrs: 0.088,
      rolling_7d_delta: 0.004,
      bin_proportions_baseline: [0.15, 0.20, 0.18, 0.12, 0.10, 0.08, 0.07, 0.05, 0.03, 0.02],
      bin_proportions_current: [0.14, 0.19, 0.19, 0.13, 0.11, 0.08, 0.07, 0.04, 0.03, 0.02],
    },
    time_series: [
      { date: "2026-09-01", mean_hrs: 0.082, sample_count: 50, critical_count: 0 },
      { date: "2026-09-15", mean_hrs: 0.085, sample_count: 65, critical_count: 1 },
      { date: "2026-09-28", mean_hrs: 0.088, sample_count: 70, critical_count: 2 },
    ],
  };

  beforeEach(() => {
    vi.clearAllMocks();
    api.getDriftReport.mockReset();
  });

  it("renders loading state on initial mount with accessible status role", () => {
    api.getDriftReport.mockReturnValue(new Promise(() => {})); // pending promise

    render(<DriftView />);
    expect(screen.getByRole("status")).toHaveAttribute("aria-label", "Loading drift analysis");
    expect(screen.getByText(/Loading longitudinal drift metrics/i)).toBeInTheDocument();
  });

  it("calls centralized API client getDriftReport without client-injected tenant_id", async () => {
    api.getDriftReport.mockResolvedValueOnce(mockDriftReportSuccess);

    render(<DriftView />);

    await waitFor(() => {
      expect(api.getDriftReport).toHaveBeenCalledTimes(1);
      // Strictly passes { days: 30 } and no tenant_id query override
      expect(api.getDriftReport).toHaveBeenCalledWith({ days: 30 });
    });
  });

  it("renders success state with PSI, KS test, mean HRS, and sample count cards", async () => {
    api.getDriftReport.mockResolvedValueOnce(mockDriftReportSuccess);

    render(<DriftView />);

    await waitFor(() => {
      expect(screen.getByText("Population Stability Index")).toBeInTheDocument();
    });
    expect(screen.getByText("0.0284")).toBeInTheDocument();
    expect(screen.getByText("Stable (PSI < 0.10)")).toBeInTheDocument();
    expect(screen.getByText("Two-Sample KS Test")).toBeInTheDocument();
    expect(screen.getByText("D = 0.1240")).toBeInTheDocument();
    expect(screen.getByText(/p-value: 0.4820/)).toBeInTheDocument();
    expect(screen.getByText("Consistent (p ≥ 0.05)")).toBeInTheDocument();
    expect(screen.getByText("Calibrated Mean HRS")).toBeInTheDocument();
    expect(screen.getByText("0.0880")).toBeInTheDocument();
    expect(screen.getByText(/Baseline: 0.0840/)).toBeInTheDocument();
    expect(screen.getByText(/\+0.0040/)).toBeInTheDocument();
    expect(screen.getByText("Observed Production Samples")).toBeInTheDocument();
    expect(screen.getByText("500")).toBeInTheDocument();
    expect(screen.getByText(/Baseline Reference: 500 samples/)).toBeInTheDocument();
  });

  it("renders 10-bin distribution comparison and accessible table", async () => {
    api.getDriftReport.mockResolvedValueOnce(mockDriftReportSuccess);

    render(<DriftView />);

    await waitFor(() => {
      expect(screen.getByText("Baseline vs. Current HRS Distribution")).toBeInTheDocument();
      expect(screen.getByText("Bin [0.0 - 0.1]")).toBeInTheDocument();
      expect(screen.getByText("Bin [0.9 - 1.0]")).toBeInTheDocument();
      expect(screen.getByText("Baseline (Ref)")).toBeInTheDocument();
      expect(screen.getByText("Current (Observed)")).toBeInTheDocument();
    });

    // Check table headers in accessible data table
    expect(screen.getByRole("columnheader", { name: "HRS Bin Range" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Baseline Proportion" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Current Proportion" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Shift Delta (Obs - Ref)" })).toBeInTheDocument();
  });

  it("renders longitudinal time series chart and allows switching time windows", async () => {
    api.getDriftReport.mockResolvedValue(mockDriftReportSuccess);

    render(<DriftView />);

    await waitFor(() => {
      expect(screen.getByText("Longitudinal HRS Drift Trend")).toBeInTheDocument();
      expect(screen.getByText(/Past 30 Days/i)).toBeInTheDocument();
    });

    // Click 7 Days button
    const btn7d = screen.getByRole("button", { name: "7 Days" });
    fireEvent.click(btn7d);

    await waitFor(() => {
      expect(api.getDriftReport).toHaveBeenCalledWith({ days: 7 });
    });

    // Click 90 Days button
    const btn90d = screen.getByRole("button", { name: "90 Days" });
    fireEvent.click(btn90d);

    await waitFor(() => {
      expect(api.getDriftReport).toHaveBeenCalledWith({ days: 90 });
    });
  });

  it("renders moderate_drift status badge accurately", async () => {
    const moderateDriftPayload = {
      ...mockDriftReportSuccess,
      drift_report: {
        ...mockDriftReportSuccess.drift_report,
        psi: 0.145,
        status: "moderate_drift",
      },
    };

    api.getDriftReport.mockResolvedValueOnce(moderateDriftPayload);

    render(<DriftView />);

    await waitFor(() => {
      expect(screen.getByText("Moderate Drift (0.10 ≤ PSI < 0.20)")).toBeInTheDocument();
    });
  });

  it("renders significant_drift status badge accurately", async () => {
    const significantDriftPayload = {
      ...mockDriftReportSuccess,
      drift_report: {
        ...mockDriftReportSuccess.drift_report,
        psi: 0.265,
        status: "significant_drift",
      },
    };

    api.getDriftReport.mockResolvedValueOnce(significantDriftPayload);

    render(<DriftView />);

    await waitFor(() => {
      expect(screen.getByText("Significant Drift (PSI ≥ 0.20)")).toBeInTheDocument();
    });
  });

  it("renders active operational alert banner when alert_triggered is true", async () => {
    const alertPayload = {
      ...mockDriftReportSuccess,
      drift_report: {
        ...mockDriftReportSuccess.drift_report,
        alert_triggered: true,
        alert_reason: "Critical tier rate (6.5%) exceeded threshold (5.0%)",
      },
    };

    api.getDriftReport.mockResolvedValueOnce(alertPayload);

    render(<DriftView />);

    await waitFor(() => {
      const alertBanner = screen.getByRole("alert", { name: /active drift alert/i });
      expect(alertBanner).toBeInTheDocument();
      expect(screen.getByText("Operational Drift Alert Triggered")).toBeInTheDocument();
      expect(screen.getByText("Critical tier rate (6.5%) exceeded threshold (5.0%)")).toBeInTheDocument();
    });
  });

  it("renders empty state when no samples or time series are recorded", async () => {
    api.getDriftReport.mockResolvedValueOnce({
      tenant_id: "tenant_empty",
      days: 30,
      drift_report: {
        psi: 0.0,
        ks_statistic: 0.0,
        ks_pvalue: 1.0,
        status: "stable",
        alert_triggered: false,
        alert_reason: null,
        baseline_sample_count: 0,
        current_sample_count: 0,
        baseline_mean_hrs: 0.0,
        current_mean_hrs: 0.0,
        rolling_7d_delta: null,
        bin_proportions_baseline: [],
        bin_proportions_current: [],
      },
      time_series: [],
    });

    render(<DriftView />);

    await waitFor(() => {
      expect(screen.getByText("No Drift Telemetry Available")).toBeInTheDocument();
      expect(screen.getByText(/There are no recorded drift metrics or baseline samples/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /check for updates/i })).toBeInTheDocument();
    });
  });

  it("renders error state when centralized API call fails and allows retry", async () => {
    const errorObj = new Error("Gateway connection lost");
    errorObj.code = "SERVICE_UNAVAILABLE";
    errorObj.traceId = "tr_drift_err_101";
    errorObj.status = 503;

    api.getDriftReport.mockRejectedValueOnce(errorObj);

    render(<DriftView />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
      expect(screen.getByText("Unable to Load Drift Telemetry")).toBeInTheDocument();
      expect(screen.getByText("Gateway connection lost")).toBeInTheDocument();
      expect(screen.getByText("Code: SERVICE_UNAVAILABLE")).toBeInTheDocument();
      expect(screen.getByText("Trace: tr_drift_err_101")).toBeInTheDocument();
    });

    // Verify retry button refetches
    api.getDriftReport.mockResolvedValueOnce(mockDriftReportSuccess);

    const retryBtn = screen.getByRole("button", { name: /retry/i });
    fireEvent.click(retryBtn);

    await waitFor(() => {
      expect(screen.getByText("0.0284")).toBeInTheDocument();
    });
  });
});
