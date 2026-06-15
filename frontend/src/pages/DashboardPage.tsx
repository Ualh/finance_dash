import React, { useCallback, useEffect, useState } from "react";
import { useApiClient } from "@/hooks/useApiClient";
import type { DashboardResponse } from "@/lib/types";
import { DataState } from "@/components/DataState";
import { SummaryCard } from "@/components/SummaryCard";

const fmt = (n: number) =>
  new Intl.NumberFormat("de-CH", { style: "currency", currency: "CHF", minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(n);

const DashboardPage: React.FC = () => {
  const api = useApiClient();
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.getDashboard();
      setData(res);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    fetch();
  }, [fetch]);

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold text-slate-800 dark:text-slate-100">Dashboard</h2>
      <DataState loading={loading} error={error} empty={!data}>
        {data && (
          <>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <SummaryCard
                title="Net Worth"
                value={fmt(data.total_chf)}
                emphasis="primary"
              />
              <SummaryCard
                title="Available"
                value={fmt(data.buckets.available)}
              />
              <SummaryCard
                title="Invested"
                value={fmt(data.buckets.invested)}
              />
              <SummaryCard
                title="Locked"
                value={fmt(data.buckets.locked)}
              />
            </div>
            {data.delta_chf !== null && (
              <p className="text-sm text-slate-500 dark:text-slate-400">
                Delta J-1: {fmt(data.delta_chf)}
              </p>
            )}
            <div className="space-y-2">
              <h3 className="text-lg font-semibold text-slate-700 dark:text-slate-200">Sources</h3>
              {Object.entries(data.sources).length === 0 && (
                <p className="text-sm text-slate-400">No sources yet.</p>
              )}
              {Object.entries(data.sources).map(([source, info]) => (
                <div key={source} className="flex items-center justify-between rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
                  <div>
                    <p className="text-sm font-medium text-slate-800 dark:text-slate-100 capitalize">{source}</p>
                    <p className="text-xs text-slate-500">Last updated: {info.last_updated}</p>
                  </div>
                  <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">{fmt(info.total_chf)}</p>
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
