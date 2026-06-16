import React from "react";
import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";

import DashboardPage from "@/pages/DashboardPage";
import UpdatePage from "@/pages/UpdatePage";
import SettingsPage from "@/pages/SettingsPage";
import { ThemeToggle } from "@/components/ThemeToggle";

const tabs = [
  { name: "Dashboard", to: "/", icon: "📊" },
  { name: "Update", to: "/update", icon: "✏️" },
  { name: "Settings", to: "/settings", icon: "⚙️" },
];

const App: React.FC = () => {
  return (
    <BrowserRouter>
      <div className="flex min-h-screen flex-col bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
        <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/70 backdrop-blur dark:border-slate-800 dark:bg-slate-900/70">
          <div className="flex h-14 items-center justify-between px-4">
            <h1 className="text-base font-semibold text-slate-800 dark:text-slate-100">Finance Dash</h1>
            <ThemeToggle size="md" />
          </div>
        </header>
        <main className="flex-1 p-4 pb-20 md:p-8 md:pb-8">
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/update" element={<UpdatePage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </main>
        <nav className="fixed bottom-0 left-0 right-0 z-20 border-t border-slate-200 bg-white/90 backdrop-blur dark:border-slate-800 dark:bg-slate-900/90 md:hidden">
          <div className="flex">
            {tabs.map((tab) => (
              <NavLink
                key={tab.to}
                to={tab.to}
                end={tab.to === "/"}
                className={({ isActive }) =>
                  `flex flex-1 flex-col items-center gap-0.5 py-2 text-xs font-medium transition-colors ${
                    isActive
                      ? "text-brand-600 dark:text-brand-400"
                      : "text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
                  }`
                }
              >
                <span className="text-lg">{tab.icon}</span>
                <span>{tab.name}</span>
              </NavLink>
            ))}
          </div>
        </nav>
      </div>
    </BrowserRouter>
  );
};

export default App;
