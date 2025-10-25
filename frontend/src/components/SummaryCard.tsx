import React from "react";
import clsx from "clsx";

interface SummaryCardProps {
  title: string;
  value: string;
  subtitle?: string;
  emphasis?: "primary" | "muted";
  icon?: React.ReactNode;
}

export const SummaryCard: React.FC<SummaryCardProps> = ({
  title,
  value,
  subtitle,
  emphasis = "primary",
  icon,
}: SummaryCardProps) => (
  <div
    className={clsx(
      "group relative overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm transition-all hover:shadow-md dark:border-slate-800 dark:bg-slate-900",
      emphasis === "primary" ? "ring-1 ring-brand-500/10" : "opacity-90"
    )}
  >
    <div className="absolute right-4 top-4 text-brand-400/20 group-hover:text-brand-400/40">{icon}</div>
    <div className="space-y-1 p-5">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">{title}</p>
      <p className="text-2xl font-semibold text-slate-900 dark:text-slate-100">{value}</p>
      {subtitle ? <p className="text-sm text-slate-500 dark:text-slate-400">{subtitle}</p> : null}
    </div>
  </div>
);
