import React from "react";
import { NavLink } from "react-router-dom";

import { ThemeToggle } from "@/components/ThemeToggle";
import { CurrencyToggle } from "@/components/CurrencyToggle";
import { useDisplayCurrency } from "@/context/DisplayCurrencyContext";
import { useTheme } from "@/context/ThemeContext";

const navigation = [
  { name: "Dashboard", to: "/" },
  { name: "Activity", to: "/activity" },
  { name: "Settings", to: "/settings" },
];

interface LayoutProps {
  children: React.ReactNode;
}

export const Layout: React.FC<LayoutProps> = ({ children }: LayoutProps) => {
  const { theme } = useTheme();
  const { currency } = useDisplayCurrency();

  return (
    <div className="flex min-h-screen bg-slate-50 text-slate-900 transition-colors duration-200 dark:bg-slate-950 dark:text-slate-100">
      <aside className="hidden w-64 flex-col border-r border-slate-200 bg-white/80 backdrop-blur dark:border-slate-800 dark:bg-slate-900/70 md:flex">
        <div className="flex items-center justify-between px-6 py-5">
          <div>
            <p className="text-sm font-semibold uppercase tracking-widest text-brand-500">Finance Dash</p>
            <p className="text-xs text-slate-500 dark:text-slate-400">Local-first portfolio tools</p>
          </div>
          <span className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-slate-200 text-sm font-semibold text-brand-600 dark:border-slate-700 dark:text-brand-400">
            FD
          </span>
        </div>
        <nav className="flex flex-1 flex-col gap-1 px-3 py-4">
          {navigation.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-brand-500/10 text-brand-700 dark:bg-brand-400/20 dark:text-brand-50"
                    : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                }`
              }
            >
              {item.name}
            </NavLink>
          ))}
        </nav>
        <div className="px-4 pb-6">
          <div className="space-y-2 rounded-lg border border-slate-200 p-3 dark:border-slate-800">
            <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
              <span>Theme</span>
              <ThemeToggle size="sm" />
            </div>
            <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
              <span>Display</span>
              <CurrencyToggle size="sm" />
            </div>
            <div className="text-xs text-slate-500 dark:text-slate-400">
              <p className="font-semibold">Current theme:</p>
              <p>{theme.toUpperCase()}</p>
              <p className="font-semibold">Currency:</p>
              <p>{currency}</p>
            </div>
          </div>
        </div>
      </aside>

      <div className="flex flex-1 flex-col">
        <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/70 backdrop-blur dark:border-slate-800 dark:bg-slate-900/70">
          <div className="flex h-14 items-center justify-between gap-3 px-4 md:px-8">
            <div className="flex items-center gap-2 md:hidden">
              <CurrencyToggle size="md" />
              <ThemeToggle size="md" />
            </div>
            <div className="col-span-6 flex flex-1 items-center gap-3">
              <h1 className="text-base font-semibold text-slate-800 dark:text-slate-100">Personal Finance Workspace</h1>
              <span className="rounded-full bg-brand-500/10 px-2 py-1 text-xs font-semibold text-brand-600 dark:bg-brand-400/10 dark:text-brand-300">
                Sample data
              </span>
            </div>
            <div className="hidden items-center gap-2 md:flex">
              <CurrencyToggle size="md" />
              <ThemeToggle size="md" />
            </div>
          </div>
        </header>
        <main className="flex-1 bg-slate-50/70 p-4 dark:bg-slate-950/80 md:p-8">{children}</main>
      </div>
    </div>
  );
};
