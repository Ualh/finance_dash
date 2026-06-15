import React, { createContext, useCallback, useContext, useMemo, useState } from "react";

export type DisplayCurrency = "CHF";

interface DisplayCurrencyContextValue {
  currency: DisplayCurrency;
  setCurrency: (currency: DisplayCurrency) => Promise<void>;
}

const DisplayCurrencyContext = createContext<DisplayCurrencyContextValue | undefined>(undefined);

const DEFAULT_CURRENCY: DisplayCurrency = "CHF";

type DisplayCurrencyProviderProps = {
  children: React.ReactNode;
};

export const DisplayCurrencyProvider: React.FC<DisplayCurrencyProviderProps> = ({ children }: DisplayCurrencyProviderProps) => {
  const [currency] = useState<DisplayCurrency>(DEFAULT_CURRENCY);

  const setCurrency = useCallback(async (value: DisplayCurrency) => {
    // no-op in v1; USD toggle comes in slice #3
  }, []);

  const value = useMemo<DisplayCurrencyContextValue>(
    () => ({ currency, setCurrency }),
    [currency, setCurrency]
  );

  return <DisplayCurrencyContext.Provider value={value}>{children}</DisplayCurrencyContext.Provider>;
};

export function useDisplayCurrency(): DisplayCurrencyContextValue {
  const context = useContext(DisplayCurrencyContext);
  if (!context) {
    throw new Error("useDisplayCurrency must be used within DisplayCurrencyProvider");
  }
  return context;
}
