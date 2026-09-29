import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import {
  Navigation,
  NAV_ITEMS,
  SECTION_PERMISSIONS,
  isSectionPermitted,
} from "../Navigation";
import { PERMISSIONS } from "../../context/AuthContext";

describe("Navigation Component & Section Permissions", () => {
  describe("Authoritative Section Permission Requirements", () => {
    it("directly derives section permissions from authoritative backend route contracts", () => {
      // overview: GET /v1/dashboard/stats requires DASHBOARD_READ
      expect(SECTION_PERMISSIONS.overview).toEqual([PERMISSIONS.DASHBOARD_READ]);

      // drift: GET /v1/drift requires DASHBOARD_READ (Security & Access §13.2)
      expect(SECTION_PERMISSIONS.drift).toEqual([PERMISSIONS.DASHBOARD_READ]);

      // sessions: GET /v1/sessions/{id} accepts VERIFY_READ or AUDIT_READ (gateway/routes/sessions.py)
      expect(SECTION_PERMISSIONS.sessions).toEqual([
        PERMISSIONS.VERIFY_READ,
        PERMISSIONS.AUDIT_READ,
      ]);

      // stream: WebSocket /v1/verify/stream requires VERIFY_WRITE (gateway/routes/stream.py)
      expect(SECTION_PERMISSIONS.stream).toEqual([PERMISSIONS.VERIFY_WRITE]);

      // alerts: GET /v1/alerts requires DASHBOARD_READ (gateway/routes/alerts.py)
      expect(SECTION_PERMISSIONS.alerts).toEqual([PERMISSIONS.DASHBOARD_READ]);
    });

    it("evaluates isSectionPermitted based strictly on permission checks", () => {
      // User with only DASHBOARD_READ
      const dashboardOnly = (perm) => perm === PERMISSIONS.DASHBOARD_READ;
      expect(isSectionPermitted("overview", dashboardOnly)).toBe(true);
      expect(isSectionPermitted("drift", dashboardOnly)).toBe(true);
      expect(isSectionPermitted("alerts", dashboardOnly)).toBe(true);
      expect(isSectionPermitted("stream", dashboardOnly)).toBe(false);
      expect(isSectionPermitted("sessions", dashboardOnly)).toBe(false);

      // User with only VERIFY_READ
      const verifyRead = (perm) => perm === PERMISSIONS.VERIFY_READ;
      expect(isSectionPermitted("sessions", verifyRead)).toBe(true);
      expect(isSectionPermitted("overview", verifyRead)).toBe(false);

      // User with only AUDIT_READ
      const auditRead = (perm) => perm === PERMISSIONS.AUDIT_READ;
      expect(isSectionPermitted("sessions", auditRead)).toBe(true);
      expect(isSectionPermitted("overview", auditRead)).toBe(false);

      // User with only VERIFY_WRITE
      const verifyWrite = (perm) => perm === PERMISSIONS.VERIFY_WRITE;
      expect(isSectionPermitted("stream", verifyWrite)).toBe(true);
      expect(isSectionPermitted("sessions", verifyWrite)).toBe(false);
      expect(isSectionPermitted("overview", verifyWrite)).toBe(false);
    });
  });

  describe("Navigation Rendering & Accessibility", () => {
    it("renders all 5 core navigation tabs with proper roles", () => {
      render(
        <Navigation
          activeTab="overview"
          onSelectTab={vi.fn()}
          hasPermission={() => true}
          isAuthenticated={true}
        />
      );

      expect(screen.getByRole("tab", { name: /overview/i })).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: /drift/i })).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: /sessions/i })).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: /live stream/i })).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: /alerts/i })).toBeInTheDocument();
      expect(NAV_ITEMS.length).toBe(5);
    });

    it("marks active tab with aria-selected='true'", () => {
      render(
        <Navigation
          activeTab="drift"
          onSelectTab={vi.fn()}
          hasPermission={() => true}
          isAuthenticated={true}
        />
      );

      const driftTab = screen.getByRole("tab", { name: /drift/i });
      expect(driftTab).toHaveAttribute("aria-selected", "true");

      const overviewTab = screen.getByRole("tab", { name: /overview/i });
      expect(overviewTab).toHaveAttribute("aria-selected", "false");
    });

    it("calls onSelectTab when an active tab is clicked", () => {
      const onSelectTab = vi.fn();
      render(
        <Navigation
          activeTab="overview"
          onSelectTab={onSelectTab}
          hasPermission={() => true}
          isAuthenticated={true}
        />
      );

      fireEvent.click(screen.getByRole("tab", { name: /alerts/i }));
      expect(onSelectTab).toHaveBeenCalledWith("alerts");
    });

    it("disables tabs when hasPermission returns false for required permissions", () => {
      // User lacks VERIFY_WRITE
      const hasPermission = vi.fn((perm) => perm !== PERMISSIONS.VERIFY_WRITE);

      render(
        <Navigation
          activeTab="overview"
          onSelectTab={vi.fn()}
          hasPermission={hasPermission}
          isAuthenticated={true}
        />
      );

      const streamTab = screen.getByRole("tab", { name: /live stream/i });
      expect(streamTab).toBeDisabled();
      expect(streamTab).toHaveAttribute("aria-disabled", "true");
    });
  });
});
