import React, { useCallback, useEffect, useState } from "react";

import { CurrencyToggle } from "@/components/CurrencyToggle";
import { useDisplayCurrency } from "@/context/DisplayCurrencyContext";
import { useTheme } from "@/context/ThemeContext";
import { useApiClient } from "@/hooks/useApiClient";
import { Button } from "@/components/ui/Button";

const SettingsPage: React.FC = () => {
  const { currency } = useDisplayCurrency();
  const { theme, toggleTheme } = useTheme();
  const api = useApiClient();

  const [holdings, setHoldings] = useState<Array<{
    id: number;
    source: string;
    source_type: string;
    asset_class: string;
    value_chf: number;
    label: string | null;
    last_updated: string;
  }>>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editId, setEditId] = useState<number | null>(null);
  const [editValue, setEditValue] = useState("");
  const [savingId, setSavingId] = useState<number | null>(null);

  const loadHoldings = useCallback(async () => {
    try {
      const res = await api.listHoldings();
      setHoldings(res.holdings);
      setLoadError(null);
    } catch (e) {
      setLoadError((e as Error).message);
    }
  }, [api]);

  useEffect(() => {
    loadHoldings();
  }, [loadHoldings]);

  const handleEditStart = (h: { id: number; value_chf: number }) => {
    setEditId(h.id);
    setEditValue(String(h.value_chf));
  };

  const handleEditCancel = () => {
    setEditId(null);
    setEditValue("");
  };

  const handleEditSave = async (holdingId: number) => {
    const num = parseFloat(editValue);
    if (isNaN(num)) return;
    setSavingId(holdingId);
    try {
      await api.updateHolding(holdingId, num);
      setEditId(null);
      setEditValue("");
      await loadHoldings();
    } catch (e) {
      // ignore
    } finally {
      setSavingId(null);
    }
  };

  const manualHoldings = holdings.filter((h) => h.source_type === "manual");

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold text-slate-800 dark:text-slate-100">Settings</h2>
      <div className="space-y-4">

        <div className="flex items-center justify-between rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <div>
            <p className="text-sm font-medium text-slate-800 dark:text-slate-100">Theme</p>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Current: {theme === "dark" ? "Dark" : "Light"}
            </p>
          </div>
          <Button variant="ghost" onClick={toggleTheme} className="flex items-center gap-2">
            {theme === "dark" ? (
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v2.25m6.364.386l-1.591 1.591M21 12h-2.25m-.386 6.364l-1.591-1.591M12 18.75V21m-4.773-4.227l-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0z" />
              </svg>
            ) : (
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z" />
              </svg>
            )}
            <span className="text-sm font-medium">{theme === "dark" ? "Light" : "Dark"}</span>
          </Button>
        </div>

        <div className="flex items-center justify-between rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <div>
            <p className="text-sm font-medium text-slate-800 dark:text-slate-100">Display Currency</p>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Current: {currency}
            </p>
          </div>
          <CurrencyToggle size="md" />
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <p className="text-sm font-medium text-slate-800 dark:text-slate-100 mb-3">Manual Holdings</p>
          {loadError && (
            <p className="text-sm text-red-600 dark:text-red-400">{loadError}</p>
          )}
          {!loadError && manualHoldings.length === 0 && (
            <p className="text-sm text-slate-500 dark:text-slate-400">No manual holdings yet.</p>
          )}
          {manualHoldings.length > 0 && (
            <ul className="space-y-2">
              {manualHoldings.map((h) => (
                <li key={h.id} className="flex items-center justify-between rounded-md border border-slate-100 bg-slate-50 px-3 py-2 dark:border-slate-700 dark:bg-slate-800">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-slate-800 dark:text-slate-100 truncate">
                      {h.label || h.source}
                    </p>
                    <p className="text-xs text-slate-500 dark:text-slate-400">
                      {h.asset_class} &middot; {h.source}
                    </p>
                  </div>
                  {editId === h.id ? (
                    <div className="flex items-center gap-2 shrink-0">
                      <input
                        type="text"
                        inputMode="decimal"
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        className="w-28 rounded-md border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
                      />
                      <Button size="sm" disabled={savingId === h.id} onClick={() => handleEditSave(h.id)}>
                        {savingId === h.id ? "..." : "Save"}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={handleEditCancel}>
                        Cancel
                      </Button>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                        CHF {h.value_chf.toLocaleString("de-CH", { minimumFractionDigits: 0 })}
                      </span>
                      <Button size="sm" variant="ghost" onClick={() => handleEditStart(h)}>
                        Edit
                      </Button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

      </div>
    </div>
  );
};

export default SettingsPage;
