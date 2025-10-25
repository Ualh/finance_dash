import React, { useMemo } from "react";

import { Button } from "@/components/ui/Button";
import { useDisplayCurrency } from "@/context/DisplayCurrencyContext";
import type { DisplayCurrency } from "@/context/DisplayCurrencyContext";

interface CurrencyToggleProps {
  size?: "sm" | "md";
}

const options: DisplayCurrency[] = ["CHF", "USD"];

export const CurrencyToggle: React.FC<CurrencyToggleProps> = ({ size = "md" }) => {
  const { currency, setCurrency, loading } = useDisplayCurrency();

  const buttons = useMemo(
    () =>
      options.map((option) => ({
        option,
        active: option === currency,
      })),
    [currency]
  );

  return (
    <div className="inline-flex items-center gap-1 rounded-full bg-slate-100 p-1 text-xs font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
  {buttons.map(({ option, active }: { option: DisplayCurrency; active: boolean }) => (
        <Button
          key={option}
          size={size}
          variant={active ? "solid" : "ghost"}
          disabled={loading || active}
          onClick={() => {
            void setCurrency(option);
          }}
        >
          {option}
        </Button>
      ))}
    </div>
  );
};
