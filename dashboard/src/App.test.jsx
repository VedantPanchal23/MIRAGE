import { describe, it, expect } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import App from "./App";
import { AuthProvider } from "./context/AuthContext";

describe("App Root Component", () => {
  it("renders commercial storefront landing view by default", async () => {
    render(
      <AuthProvider>
        <App />
      </AuthProvider>
    );

    // Header brand
    expect(screen.getAllByText("MIRAGE").length).toBeGreaterThan(0);

    // Hero title and CTA
    await waitFor(() => {
      expect(screen.getByText(/Control AI Before It Acts/i)).toBeDefined();
    });

    expect(screen.getByText(/Start Governed Execution Free/i)).toBeDefined();
    expect(screen.getByText(/The Five Assurance Gates/i)).toBeDefined();
  });
});
