import React from "react";

interface MetricCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  badge?: string;
  badgeColor?: "green" | "yellow" | "red" | "blue";
  icon?: React.ReactNode;
}

export const MetricCard: React.FC<MetricCardProps> = ({
  title,
  value,
  subtitle,
  badge,
  badgeColor = "blue",
  icon,
}) => {
  const badgeClasses = {
    green: "bg-emerald-950 text-emerald-400 border-emerald-800",
    yellow: "bg-amber-950 text-amber-400 border-amber-800",
    red: "bg-rose-950 text-rose-400 border-rose-800",
    blue: "bg-cyan-950 text-cyan-400 border-cyan-800",
  }[badgeColor];

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg relative overflow-hidden">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
          {title}
        </span>
        {icon && <div className="text-slate-400">{icon}</div>}
      </div>

      <div className="mt-3 flex items-baseline justify-between">
        <div className="text-3xl font-bold tracking-tight text-white">{value}</div>
        {badge && (
          <span
            className={`text-xs px-2.5 py-0.5 rounded-full font-medium border ${badgeClasses}`}
          >
            {badge}
          </span>
        )}
      </div>

      {subtitle && (
        <p className="mt-2 text-xs text-slate-400 leading-relaxed">{subtitle}</p>
      )}
    </div>
  );
};
