import { describe, it, expect } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";
import App from "./App";
import { AuthProvider } from "./context/AuthContext";

describe("App Root Component", () => {
  it("renders without crashing with default Overview view", () => {
    render(
      <AuthProvider>
        <App />
      </AuthProvider>
    );

    expect(screen.getByText("MIRAGE")).toBeDefined();
    expect(screen.getByText("Workspace Overview")).toBeDefined();
    expect(screen.getByText("Total Assured Transactions")).toBeDefined();
  });
});
