import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { SHAPWaterfall } from "../SHAPWaterfall";

describe("SHAPWaterfall Component Contract Tests (P2.7)", () => {
  it("renders explicit unavailable state when attribution is null", () => {
    render(<SHAPWaterfall attribution={null} hrsScore={0.1234} />);

    expect(screen.getByRole("status")).toHaveTextContent("Unavailable");
    expect(
      screen.getByText(/TreeSHAP feature attributions are unavailable for this verification session/i)
    ).toBeInTheDocument();
    expect(screen.getByText("HRS: 0.1234")).toBeInTheDocument();
    expect(screen.queryByText(/∑ Φ_i =/i)).not.toBeInTheDocument();
  });

  it("renders explicit unavailable state when attribution is an empty object", () => {
    render(<SHAPWaterfall attribution={{}} hrsScore={0.5} />);

    expect(screen.getByRole("status")).toHaveTextContent("Unavailable");
    expect(
      screen.getByText(/TreeSHAP feature attributions are unavailable for this verification session/i)
    ).toBeInTheDocument();
  });

  it("renders explicit unavailable state when attribution contains non-numeric values", () => {
    render(<SHAPWaterfall attribution={{ rav: "none", scs: null }} hrsScore={0.5} />);

    expect(screen.getByRole("status")).toHaveTextContent("Unavailable");
  });

  it("preserves exact backend feature names and numeric values without client modification", () => {
    const backendPayload = {
      rav: 0.35,
      scs: 0.20,
      nli: 0.30,
      ics: 0.15,
    };

    render(<SHAPWaterfall attribution={backendPayload} hrsScore={0.42} />);

    // Feature names
    expect(screen.getByText("RAV (Retrieval Support)")).toBeInTheDocument();
    expect(screen.getByText("SCS (Self-Consistency Sampling)")).toBeInTheDocument();
    expect(screen.getByText("NLI (Entailment Verifier)")).toBeInTheDocument();
    expect(screen.getByText("ICS (Internal Inconsistency)")).toBeInTheDocument();

    // Exact backend values formatted without altering underlying numbers
    expect(screen.getByText("0.3500")).toBeInTheDocument();
    expect(screen.getByText("0.2000")).toBeInTheDocument();
    expect(screen.getByText("0.3000")).toBeInTheDocument();
    expect(screen.getByText("0.1500")).toBeInTheDocument();

    // Proportional shares
    expect(screen.getByText("35.0% share")).toBeInTheDocument();
    expect(screen.getByText("20.0% share")).toBeInTheDocument();
    expect(screen.getByText("30.0% share")).toBeInTheDocument();
    expect(screen.getByText("15.0% share")).toBeInTheDocument();

    // Invariant: Missing signals (e.g. VGS) are not fabricated
    expect(screen.queryByText(/VGS \(Visual Grounding\)/i)).not.toBeInTheDocument();
  });

  it("verifies displayed additive total ∑ Φ_i is mathematically the exact sum of backend attribution values", () => {
    // 0.25 + 0.15 + 0.25 + 0.15 + 0.20 = 1.00
    const multimodalPayload = {
      rav: 0.25,
      scs: 0.15,
      nli: 0.25,
      ics: 0.15,
      vgs: 0.20,
    };

    render(<SHAPWaterfall attribution={multimodalPayload} hrsScore={0.15} />);

    expect(screen.getByText("VGS (Visual Grounding)")).toBeInTheDocument();
    expect(screen.getByText("0.2000")).toBeInTheDocument();
    expect(screen.getByText("20.0% share")).toBeInTheDocument();

    // Displayed additive total
    expect(screen.getByText("1.0000")).toBeInTheDocument();
  });

  it("handles non-normalized or signed values cleanly without assuming positive means 'increases risk'", () => {
    const signedPayload = {
      rav: -0.12,
      scs: 0.08,
      nli: -0.04,
    };

    render(<SHAPWaterfall attribution={signedPayload} hrsScore={0.30} />);

    expect(screen.getByText("-0.1200")).toBeInTheDocument();
    expect(screen.getByText("+0.0800")).toBeInTheDocument();
    expect(screen.getByText("-0.0400")).toBeInTheDocument();

    // Total: -0.12 + 0.08 - 0.04 = -0.0800
    expect(screen.getByText("-0.0800")).toBeInTheDocument();

    // Clean offset designations without speculative risk labels
    expect(screen.getAllByText("Negative (-)").length).toBe(2);
    expect(screen.getAllByText("Positive (+)").length).toBe(1);
  });
});
