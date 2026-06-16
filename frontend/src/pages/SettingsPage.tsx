import React from "react";

import { CurrencyToggle } from "@/components/CurrencyToggle";
import { useDisplayCurrency } from "@/context/DisplayCurrencyContext";

const SettingsPage: React.FC = () => {
  const { currency } = useDisplayCurrency();

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold text-slate-800 dark:text-slate-100">Settings</h2>
      <div className="space-y-4">
        <div className="flex items-center justify-between rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <div>
            <p className="text-sm font-medium text-slate-800 dark:text-slate-100">Display Currency</p>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Current: {currency}
            </p>
          </div>
          <CurrencyToggle size="md" />
        </div>
      </div>
    </div>
  );
};

export default SettingsPage;
