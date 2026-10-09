import {
  LayoutDashboard,
  TrendingUp,
  ListTree,
  Radio,
  AlertCircle,
  Lock,
  Layers,
  Wrench,
  ShieldCheck,
  Eye,
} from "lucide-react";
import { PERMISSIONS } from "../context/AuthContext";

/**
 * Authoritative Section-to-Permission Requirements mapping.
 *
 * Directly derived from backend endpoint authorization requirements and Security & Access §13.2:
 * - overview: DASHBOARD_READ (backend GET /v1/dashboard/stats)
 * - drift: DASHBOARD_READ (backend GET /v1/drift)
 * - sessions: VERIFY_READ or AUDIT_READ (backend GET /v1/sessions/{session_id})
 * - stream: VERIFY_WRITE (backend WebSocket /v1/verify/stream)
 * - alerts: DASHBOARD_READ (backend GET /v1/alerts)
 * - context: DASHBOARD_READ (backend Gate 2 Context & Memory)
 * - actions: DASHBOARD_READ (backend Gate 3 Action Assurance & Tool Governance)
 */
export const SECTION_PERMISSIONS = Object.freeze({
  overview: [PERMISSIONS.DASHBOARD_READ],
  drift: [PERMISSIONS.DASHBOARD_READ],
  sessions: [PERMISSIONS.VERIFY_READ, PERMISSIONS.AUDIT_READ],
  stream: [PERMISSIONS.VERIFY_WRITE],
  alerts: [PERMISSIONS.DASHBOARD_READ],
  context: [PERMISSIONS.DASHBOARD_READ],
  actions: [PERMISSIONS.DASHBOARD_READ],
  output: [PERMISSIONS.DASHBOARD_READ],
  outcomes: [PERMISSIONS.DASHBOARD_READ],
});

export const NAV_ITEMS = [
  {
    id: "overview",
    label: "Overview",
    icon: LayoutDashboard,
    requiredPermissions: SECTION_PERMISSIONS.overview,
  },
  {
    id: "context",
    label: "Context Assurance",
    icon: Layers,
    requiredPermissions: SECTION_PERMISSIONS.context,
  },
  {
    id: "actions",
    label: "Action Assurance",
    icon: Wrench,
    requiredPermissions: SECTION_PERMISSIONS.actions,
  },
  {
    id: "output",
    label: "Output Assurance",
    icon: ShieldCheck,
    requiredPermissions: SECTION_PERMISSIONS.output,
  },
  {
    id: "outcomes",
    label: "Outcome Assurance",
    icon: Eye,
    requiredPermissions: SECTION_PERMISSIONS.outcomes,
  },
  {
    id: "drift",
    label: "Drift",
    icon: TrendingUp,
    requiredPermissions: SECTION_PERMISSIONS.drift,
  },
  {
    id: "sessions",
    label: "Sessions",
    icon: ListTree,
    requiredPermissions: SECTION_PERMISSIONS.sessions,
  },
  {
    id: "stream",
    label: "Live Stream",
    icon: Radio,
    requiredPermissions: SECTION_PERMISSIONS.stream,
  },
  {
    id: "alerts",
    label: "Alerts",
    icon: AlertCircle,
    requiredPermissions: SECTION_PERMISSIONS.alerts,
  },
];

/**
 * Check whether an authenticated user has UX permission to view a section.
 *
 * @param {string} sectionId - Section key ("overview", "drift", "sessions", "stream", "alerts")
 * @param {Function} hasPermission - Function from useAuth() checking permission membership
 * @returns {boolean}
 */
export function isSectionPermitted(sectionId, hasPermission) {
  if (!hasPermission || typeof hasPermission !== "function") return true;
  const required = SECTION_PERMISSIONS[sectionId];
  if (!required || required.length === 0) return true;
  // Access granted if user possesses any of the required alternative permissions
  return required.some((perm) => hasPermission(perm));
}

/**
 * Accessible Navigation bar for the MIRAGE Dashboard shell.
 *
 * Implements keyboard navigation, visible active state, and RBAC UX gating
 * derived exclusively from the authoritative permission matrix.
 */
export function Navigation({
  activeTab,
  onSelectTab,
  hasPermission,
  isAuthenticated,
}) {
  return (
    <nav
      aria-label="Dashboard Sections"
      className="border-b border-slate-800 bg-slate-900/60 backdrop-blur px-6"
    >
      <div
        role="tablist"
        aria-orientation="horizontal"
        className="flex items-center space-x-1 overflow-x-auto py-2 scrollbar-none"
      >
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const isActive = activeTab === item.id;
          const isPermitted = isAuthenticated
            ? isSectionPermitted(item.id, hasPermission)
            : true;

          const baseClasses =
            "flex items-center space-x-2 px-3.5 py-2 rounded-lg text-xs font-medium transition focus:outline-none focus:ring-2 focus:ring-sky-500 whitespace-nowrap";

          if (!isPermitted) {
            return (
              <button
                key={item.id}
                role="tab"
                id={`tab-${item.id}`}
                aria-selected={false}
                aria-disabled="true"
                disabled
                title={`Access restricted: requires permission ${item.requiredPermissions.join(" or ")}`}
                className={`${baseClasses} text-slate-400 opacity-60 cursor-not-allowed border border-transparent`}
              >
                <Icon className="w-4 h-4 text-slate-400" aria-hidden="true" />
                <span>{item.label}</span>
                <Lock className="w-3 h-3 text-slate-400 ml-1" aria-hidden="true" />
              </button>
            );
          }

          const stateClasses = isActive
            ? "bg-sky-500/10 text-sky-400 border border-sky-500/30 shadow-sm"
            : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 border border-transparent";

          return (
            <button
              key={item.id}
              role="tab"
              id={`tab-${item.id}`}
              aria-selected={isActive}
              aria-controls={`panel-${item.id}`}
              tabIndex={isActive ? 0 : -1}
              onClick={() => onSelectTab(item.id)}
              className={`${baseClasses} ${stateClasses}`}
            >
              <Icon className="w-4 h-4" aria-hidden="true" />
              <span>{item.label}</span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}

export default Navigation;
