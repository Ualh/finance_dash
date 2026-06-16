import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { useApiClient } from "@/hooks/useApiClient";

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
  const api = useApiClient();
  const [currency, setCurrencyState] = useState<DisplayCurrency>(DEFAULT_CURRENCY);
  const [loading, setLoading] = useState(false);
  const [initialised, setInitialised] = useState(false);

  useEffect(() => {
    api.getSetting("display_currency").then((res) => {
      if (res.value === "CHF" || res.value === "USD") {
        setCurrencyState(res.value);
      }
    }).catch(() => {
      // ignore; use default
    }).finally(() => {
      setInitialised(true);
    });
  }, [api]);

  const setCurrency = useCallback(async (value: DisplayCurrency) => {
    setLoading(true);
    try {
      await api.setSetting("display_currency", value);
      setCurrencyState(value);
    } finally {
      setLoading(false);
    }
  }, [api]);

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
