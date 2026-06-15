import React, { createContext, useCallback, useContext, useMemo, useState } from "react";

export type DisplayCurrency = "CHF" | "USD";

interface DisplayCurrencyContextValue {
  currency: DisplayCurrency;
  setCurrency: (currency: DisplayCurrency) => Promise<void>;
  loading: boolean;
}

const DisplayCurrencyContext = createContext<DisplayCurrencyContextValue | undefined>(undefined);

const DEFAULT_CURRENCY: DisplayCurrency = "CHF";

type DisplayCurrencyProviderProps = {
  children: React.ReactNode;
};

export const DisplayCurrencyProvider: React.FC<DisplayCurrencyProviderProps> = ({ children }: DisplayCurrencyProviderProps) => {
  const [currency, setCurrencyState] = useState<DisplayCurrency>(DEFAULT_CURRENCY);
  const [loading, setLoading] = useState(false);

  const setCurrency = useCallback(async (value: DisplayCurrency) => {
    setLoading(true);
    try {
      // no-op in v1; USD toggle comes in slice #3
      setCurrencyState(value);
    } finally {
      setLoading(false);
    }
  }, []);

  const value = useMemo<DisplayCurrencyContextValue>(
    () => ({ currency, setCurrency, loading }),
    [currency, setCurrency, loading]
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
