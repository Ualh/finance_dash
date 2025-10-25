import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { useApiClient } from "@/hooks/useApiClient";
import type { SummaryResponse } from "@/lib/types";

export type DisplayCurrency = "CHF" | "USD";

interface DisplayCurrencyContextValue {
  currency: DisplayCurrency;
  setCurrency: (currency: DisplayCurrency) => Promise<void>;
  summary: SummaryResponse | null;
  refreshSummary: (currency?: DisplayCurrency) => Promise<void>;
  loading: boolean;
  error: string | null;
}

const DisplayCurrencyContext = createContext<DisplayCurrencyContextValue | undefined>(undefined);

const DEFAULT_CURRENCY: DisplayCurrency = "CHF";

type DisplayCurrencyProviderProps = {
  children: React.ReactNode;
};

export const DisplayCurrencyProvider: React.FC<DisplayCurrencyProviderProps> = ({ children }: DisplayCurrencyProviderProps) => {
  const api = useApiClient();
  const [currency, setCurrencyState] = useState<DisplayCurrency>(DEFAULT_CURRENCY);
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const loadInitial = useCallback(async () => {
    try {
      setLoading(true);
      const setting = await api.getDisplayCurrency();
      const selected = (setting.display_currency as DisplayCurrency) || DEFAULT_CURRENCY;
      setCurrencyState(selected);
      const data = await api.getSummary(selected);
      setSummary(data);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    void loadInitial();
  }, [loadInitial]);

  const refreshSummary = useCallback(
    async (value?: DisplayCurrency) => {
      const target = value ?? currency;
      try {
        setLoading(true);
        const data = await api.getSummary(target);
        setSummary(data);
        setError(null);
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setLoading(false);
      }
    },
    [api, currency]
  );

  const setCurrency = useCallback(
    async (value: DisplayCurrency) => {
      try {
        setLoading(true);
        await api.setDisplayCurrency(value);
        setCurrencyState(value);
        await refreshSummary(value);
        setError(null);
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setLoading(false);
      }
    },
    [api, refreshSummary]
  );

  const value = useMemo<DisplayCurrencyContextValue>(
    () => ({ currency, setCurrency, summary, refreshSummary, loading, error }),
    [currency, setCurrency, summary, refreshSummary, loading, error]
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
