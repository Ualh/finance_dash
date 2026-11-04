import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import clsx from "clsx";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useApiClient } from "@/hooks/useApiClient";
import { useDisplayCurrency } from "@/context/DisplayCurrencyContext";
import { CurrencyToggle } from "@/components/CurrencyToggle";
import { DataState } from "@/components/DataState";
import { daysAgo, formatChange, formatDay, formatMoment, formatMoney, formatMonthLong, formatMonthShort } from "@/lib/format";
import type { DashboardResponse, MonthPoint, SourceInfo } from "@/lib/types";

const Curve: React.FC<{ points: MonthPoint[]; currency: string }> = ({ points, currency }) => (
  <div className="h-44 w-full">
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={points} margin={{ top: 8, right: 4, bottom: 0, left: 4 }}>
        <defs>
          <linearGradient id="nw-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#2563eb" stopOpacity={0.25} />
            <stop offset="100%" stopColor="#2563eb" stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis
          dataKey="month"
          tickFormatter={formatMonthShort}
          tickLine={false}
          axisLine={false}
          interval="preserveStartEnd"
          tick={{ fontSize: 12, fill: "#94a3b8" }}
        />
        <YAxis hide domain={["dataMin", "dataMax"]} />
        <Tooltip
          formatter={(value: number) => [formatMoney(value, currency), "Net worth"]}
          labelFormatter={(month: string) => formatMonthLong(month)}
          contentStyle={{ borderRadius: 8, fontSize: 13 }}
        />
        <Area type="monotone" dataKey="total_chf" stroke="#2563eb" strokeWidth={2} fill="url(#nw-fill)" />
      </AreaChart>
    </ResponsiveContainer>
  </div>
);

const SourceRow: React.FC<{ info: SourceInfo; currency: string; year: number }> = ({ info, currency, year }) => {
  const date = info.as_of ? formatDay(info.as_of, year) : "Never";
  const row = (
    <div className="flex items-center justify-between gap-3 py-3">
      <div className="min-w-0">
        <p className="flex items-center gap-2 text-sm font-medium text-slate-800 dark:text-slate-100">
          {info.label}
          {info.sync_error && (
            <span className="h-2 w-2 rounded-full bg-red-500" title={info.sync_message ?? "Last sync failed"} />
          )}
        </p>
        <p
          className={clsx(
            "text-xs",
            info.stale ? "font-medium text-amber-600 dark:text-amber-400" : "text-slate-500 dark:text-slate-400"
          )}
          title={info.stale ? info.action : undefined}
        >
          {date}
        </p>
      </div>
      <p className="text-sm font-semibold tabular-nums text-slate-800 dark:text-slate-100">
        {info.total_chf == null ? "—" : formatMoney(info.total_chf, currency)}
      </p>
    </div>
  );
  // A stale manual source is fixed on the Update page: the row takes you there.
  return info.stale && info.kind === "manual" ? <Link to="/update">{row}</Link> : row;
};

// The daily sync runs at 06:00; missing more than one run means it has stopped.
const SYNC_LATE_AFTER_DAYS = 2;

/** "Synced today 06:00 · Neon CSV imported 26 Jun": orange when the moment is missing or too old. */
const LastUpdates: React.FC<{ data: DashboardResponse }> = ({ data }) => {
  const now = new Date();
  const items = [
    { label: "Synced", at: data.last_sync_at, lateAfter: SYNC_LATE_AFTER_DAYS },
    { label: "Neon CSV imported", at: data.last_neon_import_at, lateAfter: data.stale_after_days },
  ];
  return (
    <p className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
      {items.map(({ label, at, lateAfter }, i) => (
        <span key={label} className="flex gap-x-3">
          {i > 0 && <span aria-hidden="true">·</span>}
          <span
            className={clsx((!at || daysAgo(at, now) > lateAfter) && "font-medium text-amber-600 dark:text-amber-400")}
            title={at ? new Date(at).toLocaleString("en-GB") : undefined}
          >
            {label} {at ? formatMoment(at, now) : "never"}
          </span>
        </span>
      ))}
    </p>
  );
};

const DashboardPage: React.FC = () => {
  const api = useApiClient();
  const { currency } = useDisplayCurrency();
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const touchStartY = useRef(0);
  const pulling = useRef(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await api.getDashboard(currency));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [api, currency]);

  useEffect(() => {
    load();
  }, [load]);

  const refresh = useCallback(async () => {
    if (syncing) return;
    setSyncing(true);
    try {
      await api.syncAll();
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSyncing(false);
    }
  }, [api, load, syncing]);

  const onTouchStart = useCallback((e: React.TouchEvent) => {
    touchStartY.current = e.touches[0].clientY;
    pulling.current = true;
  }, []);

  const onTouchEnd = useCallback(
    (e: React.TouchEvent) => {
      if (!pulling.current) return;
      pulling.current = false;
      if (e.changedTouches[0].clientY - touchStartY.current > 100 && window.scrollY === 0) {
        refresh();
      }
    },
    [refresh]
  );

  const cur = data?._fx?.currency ?? "CHF";
  const change = data?.change_since_last_month ?? null;
  const year = new Date().getFullYear();

  return (
    <div onTouchStart={onTouchStart} onTouchEnd={onTouchEnd} className="mx-auto max-w-xl space-y-8">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-slate-500 dark:text-slate-400">Net worth</h2>
        <div className="flex items-center gap-2">
          <CurrencyToggle size="sm" />
          <button
            onClick={refresh}
            disabled={syncing}
            aria-label="Sync now"
            title="Sync now"
            className="inline-flex h-8 w-8 items-center justify-center rounded-full text-slate-500 transition-colors hover:bg-slate-200 disabled:opacity-50 dark:text-slate-400 dark:hover:bg-slate-800"
          >
            <svg className={clsx("h-4 w-4", syncing && "animate-spin")} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182" />
            </svg>
          </button>
        </div>
      </div>

      <DataState loading={loading && !data} error={error} empty={!data}>
        {data && (
          <>
            <section>
              <p className="text-4xl font-semibold tracking-tight tabular-nums text-slate-900 dark:text-slate-50">
                {formatMoney(data.total_chf, cur)}
              </p>
              {change && (
                <p
                  className={clsx(
                    "mt-1 text-sm font-medium",
                    change.amount_chf > 0 && "text-green-600 dark:text-green-400",
                    change.amount_chf < 0 && "text-red-600 dark:text-red-400",
                    change.amount_chf === 0 && "text-slate-500 dark:text-slate-400"
                  )}
                >
                  {formatChange(change.amount_chf, cur)} since last month
                </p>
              )}
              {data._fx?.stale && <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">Old exchange rate</p>}
              <div className="mt-2">
                <LastUpdates data={data} />
              </div>
              {data.history.length > 1 && (
                <div className="mt-4">
                  <Curve points={data.history} currency={cur} />
                </div>
              )}
            </section>

            <section className="divide-y divide-slate-200 dark:divide-slate-800">
              {Object.values(data.sources).map((info) => (
                <SourceRow key={info.source} info={info} currency={cur} year={year} />
              ))}
            </section>

            <section className="space-y-1">
              {data.spending.map((m) => (
                <div key={m.month} className="flex items-baseline justify-between text-sm">
                  <span className="text-slate-500 dark:text-slate-400">Spent in {formatMonthLong(m.month).split(" ")[0]}</span>
                  <span className="tabular-nums text-slate-800 dark:text-slate-100">
                    {formatMoney(m.total_chf, cur)}
                    {m.cash_chf > 0 && (
                      <span className="ml-2 text-xs text-slate-500 dark:text-slate-400">{formatMoney(m.cash_chf, cur)} cash</span>
                    )}
                  </span>
                </div>
              ))}
            </section>
          </>
        )}
      </DataState>
    </div>
  );
};

export default DashboardPage;
