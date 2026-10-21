import React from "react";

export function MetricCard({ title, value, subtitle, badge, badgeColor = "blue", icon }) {
  const badgeClasses = {
    green: "bg-emerald-50 text-emerald-700 border-emerald-200",
    yellow: "bg-amber-50 text-amber-800 border-amber-200",
    red: "bg-rose-50 text-rose-700 border-rose-200",
    blue: "bg-sky-50 text-sky-700 border-sky-200",
  }[badgeColor] || "bg-sky-50 text-sky-700 border-sky-200";

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs relative overflow-hidden">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
          {title}
        </span>
        {icon && <div className="text-slate-400">{icon}</div>}
      </div>

      <div className="mt-3 flex items-baseline justify-between">
        <div className="text-3xl font-bold tracking-tight text-slate-900">{value}</div>
        {badge && (
          <span className={`text-xs px-2.5 py-0.5 rounded-full font-medium border ${badgeClasses}`}>
            {badge}
          </span>
        )}
      </div>

      {subtitle && (
        <p className="mt-2 text-xs text-slate-500 leading-relaxed">{subtitle}</p>
      )}
    </div>
  );
}
