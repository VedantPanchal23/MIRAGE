import { describe, it, expect, vi } from "vitest";
import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { Navigation, NAV_ITEMS } from "./Navigation";

describe("Navigation Component", () => {
  it("renders all 7 canonical SaaS tabs", () => {
    const handleTabChange = vi.fn();
    render(<Navigation activeTab="overview" onTabChange={handleTabChange} />);

    expect(NAV_ITEMS).toHaveLength(7);

    expect(screen.getByText("Overview")).toBeDefined();
    expect(screen.getByText("Playground")).toBeDefined();
    expect(screen.getByText("Approvals")).toBeDefined();
    expect(screen.getByText("Knowledge Base")).toBeDefined();
    expect(screen.getByText("Developer")).toBeDefined();
    expect(screen.getByText("Plans & Billing")).toBeDefined();
    expect(screen.getByText("Audit Ledger")).toBeDefined();
  });

  it("calls onTabChange when a tab button is clicked", () => {
    const handleTabChange = vi.fn();
    render(<Navigation activeTab="overview" onTabChange={handleTabChange} />);

    const playgroundBtn = screen.getByText("Playground");
    fireEvent.click(playgroundBtn);

    expect(handleTabChange).toHaveBeenCalledWith("playground");
  });
});
