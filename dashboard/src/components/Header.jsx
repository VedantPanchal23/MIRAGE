import React from "react";
import {
  ShieldCheck,
  RefreshCw,
  LogOut,
  LogIn,
  User,
  Building,
} from "lucide-react";

/**
 * Top Application Header displaying brand, session identity, and global actions.
 *
 * Displays non-authoritative identity information (user ID, tenant, role)
 * derived from the validated JWT for UX presentation only.
 */
export function Header({
  isAuthenticated,
  user,
  tenantId,
  role,
  onLogout,
  onOpenLogin,
  onRefresh,
  isRefreshing,
  lastRefreshed,
}) {
  const roleBadgeColors = {
    super_admin: "bg-purple-50 text-purple-700 border-purple-200",
    tenant_admin: "bg-indigo-50 text-indigo-700 border-indigo-200",
    operator: "bg-sky-50 text-sky-700 border-sky-200",
    viewer: "bg-emerald-50 text-emerald-700 border-emerald-200",
    api_client: "bg-slate-100 text-slate-700 border-slate-200",
  }[role] || "bg-slate-100 text-slate-700 border-slate-200";

  return (
    <header className="border-b border-slate-200 bg-white sticky top-0 z-40 px-6 py-3 flex flex-wrap items-center justify-between gap-4 shadow-xs">
      {/* Brand & Subtitle */}
      <div className="flex items-center space-x-3">
        <div className="w-8 h-8 rounded-lg bg-sky-50 border border-sky-200 flex items-center justify-center text-sky-600 flex-shrink-0">
          <ShieldCheck className="w-5 h-5" aria-hidden="true" />
        </div>
        <div>
          <div className="flex items-center space-x-2">
            <h1 className="font-bold text-sm tracking-wide text-slate-900">MIRAGE</h1>
            <span className="text-[10px] font-mono px-1.5 py-0.5 bg-slate-100 text-slate-700 border border-slate-300 rounded font-semibold">
              v3.0.0
            </span>
          </div>
          <p className="text-[11px] text-slate-500 hidden sm:block">
            AI Execution Assurance Platform — Control AI before it acts. Verify AI after it acts.
          </p>
        </div>
      </div>

      {/* Identity & Global Actions */}
      <div className="flex items-center space-x-3 flex-wrap">
        {isAuthenticated ? (
          <div className="flex items-center space-x-2 text-xs">
            {/* Read-only Tenant Badge */}
            {tenantId && (
              <div
                title="Authoritative Tenant Scope"
                className="flex items-center space-x-1 px-2.5 py-1 rounded-md bg-slate-100 border border-slate-200 text-slate-700 font-mono text-[11px]"
              >
                <Building className="w-3.5 h-3.5 text-slate-500" aria-hidden="true" />
                <span>{tenantId}</span>
              </div>
            )}

            {/* User / Role Badge */}
            <div className="flex items-center space-x-1.5 px-2.5 py-1 rounded-md bg-slate-100 border border-slate-200 text-slate-700 text-[11px]">
              <User className="w-3.5 h-3.5 text-slate-500" aria-hidden="true" />
              <span className="font-medium text-slate-800">{user?.id || "user"}</span>
              {role && (
                <span className={`text-[10px] font-mono uppercase font-bold px-1.5 py-0.5 rounded border ${roleBadgeColors}`}>
                  {role.replace("_", " ")}
                </span>
              )}
            </div>

            {/* Logout Button */}
            <button
              onClick={onLogout}
              aria-label="Log out session"
              className="flex items-center space-x-1 px-2.5 py-1 text-xs text-rose-700 hover:text-rose-800 bg-rose-50 hover:bg-rose-100 border border-rose-200 rounded-md transition focus:outline-none focus:ring-2 focus:ring-rose-500 font-medium"
            >
              <LogOut className="w-3.5 h-3.5" aria-hidden="true" />
              <span>Logout</span>
            </button>
          </div>
        ) : (
          <button
            onClick={onOpenLogin}
            aria-label="Authenticate with access token"
            className="flex items-center space-x-1.5 px-3.5 py-1.5 text-xs font-semibold text-white bg-sky-600 hover:bg-sky-700 rounded-lg shadow-xs transition focus:outline-none focus:ring-2 focus:ring-sky-500"
          >
            <LogIn className="w-3.5 h-3.5" aria-hidden="true" />
            <span>Sign In</span>
          </button>
        )}

        {/* Global Refresh Button */}
        {onRefresh && (
          <button
            onClick={onRefresh}
            disabled={isRefreshing}
            aria-label={`Refresh data, last updated at ${lastRefreshed || "unknown"}`}
            className="flex items-center space-x-1.5 text-xs bg-white hover:bg-slate-50 disabled:opacity-50 text-slate-700 px-3 py-1.5 rounded-lg border border-slate-200 shadow-xs transition focus:outline-none focus:ring-2 focus:ring-sky-500"
          >
            <RefreshCw
              className={`w-3.5 h-3.5 ${isRefreshing ? "animate-spin text-sky-600" : "text-slate-500"}`}
              aria-hidden="true"
            />
            <span className="hidden sm:inline font-medium">Refresh</span>
            {lastRefreshed && (
              <span className="text-[10px] text-slate-500 hidden md:inline">
                ({lastRefreshed})
              </span>
            )}
          </button>
        )}
      </div>
    </header>
  );
}

export default Header;
