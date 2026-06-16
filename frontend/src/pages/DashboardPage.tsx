import React, { useCallback, useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { useApiClient } from "@/hooks/useApiClient";
import { useDisplayCurrency } from "@/context/DisplayCurrencyContext";
import { CurrencyToggle } from "@/components/CurrencyToggle";
import type { DashboardResponse } from "@/lib/types";
import { DataState } from "@/components/DataState";
import { SummaryCard } from "@/components/SummaryCard";

const fmt = (n: number, currency = "CHF") =>
  new Intl.NumberFormat("de-CH", { style: "currency", currency, minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(n);

const DashboardPage: React.FC = () => {
  const api = useApiClient();
  const { currency } = useDisplayCurrency();
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const touchStartY = useRef(0);
  const pulling = useRef(false);

  const fetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.getDashboard(currency);
      setData(res);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [api, currency]);

  useEffect(() => {
    fetch();
  }, [fetch]);

  const doRefresh = useCallback(async () => {
    if (syncing) return;
    setSyncing(true);
    try {
      await api.syncAll();
      await fetch();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSyncing(false);
    }
  }, [api, fetch, syncing]);

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    touchStartY.current = e.touches[0].clientY;
    pulling.current = true;
  }, []);

  const handleTouchEnd = useCallback((e: React.TouchEvent) => {
    if (!pulling.current) return;
    pulling.current = false;
    const dy = e.changedTouches[0].clientY - touchStartY.current;
    if (dy > 100 && window.scrollY === 0) {
      doRefresh();
    }
  }, [doRefresh]);

  const displayCurrency = data?._fx?.currency ?? "CHF";

  const deltaColor = data?.delta_chf != null
    ? data.delta_chf >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"
    : "text-slate-500 dark:text-slate-400";

  return (
    <div
      onTouchStart={handleTouchStart}
      onTouchEnd={handleTouchEnd}
      className="space-y-6"
    >
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-slate-800 dark:text-slate-100">Dashboard</h2>
        <div className="flex items-center gap-2">
          <CurrencyToggle size="sm" />
          <button
          onClick={doRefresh}
          disabled={syncing}
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-600 shadow-sm transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
        >
          <svg className={clsx("h-4 w-4", syncing && "animate-spin")} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182" />
          </svg>
          {syncing ? "Syncing…" : "Refresh"}
        </button>
        </div>
      </div>
      <DataState loading={loading} error={error} empty={!data}>
        {data && (
          <>
            {data._fx?.stale && (
              <p className="text-xs text-amber-600 dark:text-amber-400">
                FX rate stale (last known rate used)
              </p>
            )}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <SummaryCard
                title="Net Worth"
                value={fmt(data.total_chf, displayCurrency)}
                emphasis="primary"
              />
              <SummaryCard
                title="Available"
                value={fmt(data.buckets.available, displayCurrency)}
              />
              <SummaryCard
                title="Invested"
                value={fmt(data.buckets.invested, displayCurrency)}
              />
              <SummaryCard
                title="Locked"
                value={fmt(data.buckets.locked, displayCurrency)}
              />
            </div>
            {data.delta_chf !== null && (
              <p className={clsx("text-sm", deltaColor)}>
                Delta J-1: {fmt(data.delta_chf, displayCurrency)}
                {data.delta_pct != null && ` (${data.delta_pct >= 0 ? "+" : ""}${data.delta_pct}%)`}
              </p>
            )}
            <div className="space-y-2">
              <h3 className="text-lg font-semibold text-slate-700 dark:text-slate-200">Sources</h3>
              {Object.entries(data.sources).length === 0 && (
                <p className="text-sm text-slate-400">No sources yet.</p>
              )}
              {Object.entries(data.sources).map(([source, info]) => (
                <div key={source} className="flex items-center justify-between rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
                  <div className="flex items-center gap-2">
                    {info.sync_error && (
                      <span className="inline-block h-2 w-2 rounded-full bg-red-500" title="Last sync failed" />
                    )}
                    <div>
                      <p className="text-sm font-medium text-slate-800 dark:text-slate-100 capitalize">{source}</p>
                      <p className="text-xs text-slate-500">Last updated: {info.last_updated}</p>
                    </div>
                  </div>
                  <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">{fmt(info.total_chf, displayCurrency)}</p>
                </div>
              ))}
            </div>
          </>
        )}
      </DataState>
    </div>
  );
};

export default DashboardPage;
