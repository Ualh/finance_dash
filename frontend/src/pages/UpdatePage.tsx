import React, { useCallback, useEffect, useState } from "react";
import { useApiClient } from "@/hooks/useApiClient";
import { Button } from "@/components/ui/Button";
import { formatMoney } from "@/lib/format";
import type { CashWithdrawal } from "@/lib/types";

const INPUT =
  "block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder-slate-400 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:placeholder-slate-500";
const LABEL = "mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300";
const HEADING = "text-lg font-semibold text-slate-800 dark:text-slate-100";

type Status = { ok: boolean; msg: string } | null;

const StatusLine: React.FC<{ status: Status }> = ({ status }) =>
  status ? (
    <p className={`text-sm ${status.ok ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
      {status.msg}
    </p>
  ) : null;

const todayIso = () => new Date().toLocaleDateString("sv-SE"); // YYYY-MM-DD in local time

const ASSET_CLASSES: Array<{ value: string; label: string }> = [
  { value: "cash", label: "Cash — available" },
  { value: "stock", label: "Stocks — invested" },
  { value: "etf", label: "ETF / fund — invested" },
  { value: "crypto", label: "Crypto — invested" },
  { value: "pension", label: "Pension (2nd / 3rd pillar) — locked" },
  { value: "real_estate", label: "Real estate — locked" },
  { value: "other", label: "Other — locked" },
];

const CURRENCIES = ["CHF", "USD", "EUR", "GBP"];

const UpdatePage: React.FC = () => {
  const api = useApiClient();

  const [hLabel, setHLabel] = useState("");
  const [hAssetClass, setHAssetClass] = useState("cash");
  const [hAmount, setHAmount] = useState("");
  const [hCurrency, setHCurrency] = useState("CHF");
  const [status, setStatus] = useState<Status>(null);
  const [submitting, setSubmitting] = useState(false);

  const [csvStatus, setCsvStatus] = useState<Status>(null);
  const [csvSubmitting, setCsvSubmitting] = useState(false);

  const [finpension, setFinpension] = useState("");
  const [finpensionCurrent, setFinpensionCurrent] = useState<number | null>(null);
  const [finpensionStatus, setFinpensionStatus] = useState<Status>(null);
  const [finpensionSaving, setFinpensionSaving] = useState(false);

  const [cashAmount, setCashAmount] = useState("");
  const [cashDate, setCashDate] = useState(todayIso);
  const [cashNote, setCashNote] = useState("");
  const [cashStatus, setCashStatus] = useState<Status>(null);
  const [cashSaving, setCashSaving] = useState(false);
  const [withdrawals, setWithdrawals] = useState<CashWithdrawal[]>([]);

  const loadCurrent = useCallback(async () => {
    try {
      const [holdings, cash] = await Promise.all([api.listHoldings(), api.listCashWithdrawals()]);
      const fin = holdings.holdings.find((h) => h.source === "finpension");
      setFinpensionCurrent(fin ? fin.value_chf : null);
      setWithdrawals(cash.withdrawals.slice(0, 5));
    } catch {
      // The forms still work; only the hints are missing.
    }
  }, [api]);

  useEffect(() => {
    loadCurrent();
  }, [loadCurrent]);

  const handleFinpension = async (e: React.FormEvent) => {
    e.preventDefault();
    const num = parseFloat(finpension);
    if (isNaN(num)) {
      setFinpensionStatus({ ok: false, msg: "Enter the value in CHF." });
      return;
    }
    setFinpensionSaving(true);
    setFinpensionStatus(null);
    try {
      await api.updateFinpension(num, "Finpension");
      setFinpensionStatus({ ok: true, msg: `Finpension saved: ${formatMoney(num)}.` });
      setFinpension("");
      loadCurrent();
    } catch (err) {
      setFinpensionStatus({ ok: false, msg: (err as Error).message });
    } finally {
      setFinpensionSaving(false);
    }
  };

  const handleCash = async (e: React.FormEvent) => {
    e.preventDefault();
    const num = parseFloat(cashAmount);
    if (isNaN(num) || num <= 0) {
      setCashStatus({ ok: false, msg: "Enter the amount in CHF." });
      return;
    }
    setCashSaving(true);
    setCashStatus(null);
    try {
      await api.addCashWithdrawal({ amount_chf: num, date: cashDate, note: cashNote.trim() || undefined });
      setCashStatus({ ok: true, msg: `${formatMoney(num)} cash recorded.` });
      setCashAmount("");
      setCashNote("");
      setCashDate(todayIso());
      loadCurrent();
    } catch (err) {
      setCashStatus({ ok: false, msg: (err as Error).message });
    } finally {
      setCashSaving(false);
    }
  };

  const removeCash = async (id: number) => {
    try {
      await api.deleteCashWithdrawal(id);
      loadCurrent();
    } catch (err) {
      setCashStatus({ ok: false, msg: (err as Error).message });
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const num = parseFloat(hAmount);
    if (!hLabel.trim()) {
      setStatus({ ok: false, msg: "Please enter a name for the holding." });
      return;
    }
    if (isNaN(num)) {
      setStatus({ ok: false, msg: "Please enter a valid amount." });
      return;
    }
    setSubmitting(true);
    setStatus(null);
    try {
      const res = await api.addHolding({
        label: hLabel.trim(),
        asset_class: hAssetClass,
        amount: num,
        currency: hCurrency,
      });
      const chf = res.holding.value_chf.toLocaleString("de-CH", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      const fxNote =
        hCurrency !== "CHF"
          ? ` (${hCurrency} → CHF @ ${res.fx.rate}${res.fx.stale ? ", stale rate" : ""})`
          : "";
      setStatus({ ok: true, msg: `Saved "${hLabel.trim()}" — CHF ${chf}${fxNote}.` });
      setHLabel("");
      setHAmount("");
      setHCurrency("CHF");
      setHAssetClass("cash");
    } catch (err) {
      setStatus({ ok: false, msg: (err as Error).message });
    } finally {
      setSubmitting(false);
    }
  };

  const handleCsvUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!file.name.toLowerCase().endsWith(".csv")) {
      setCsvStatus({ ok: false, msg: "Only .csv files are accepted." });
      return;
    }

    setCsvSubmitting(true);
    setCsvStatus(null);

    try {
      const res = await api.uploadNeonCsv(file);
      const chf = res.balance.toLocaleString("de-CH", { minimumFractionDigits: 2 });
      if (res.transactions_parsed === 0) {
        setCsvStatus({
          ok: true,
          msg: `This file was already imported — nothing to add. Balance unchanged at CHF ${chf}.`,
        });
        return;
      }
      setCsvStatus({
        ok: true,
        msg: `Neon CSV uploaded: ${res.transactions_parsed} new transaction(s), balance = CHF ${chf}.`,
      });
    } catch (err) {
      setCsvStatus({ ok: false, msg: (err as Error).message });
    } finally {
      setCsvSubmitting(false);
      e.target.value = "";
    }
  };

  return (
    <div className="mx-auto max-w-md space-y-10">
      <section className="space-y-4">
        <h2 className={HEADING}>This month</h2>
        <div className="space-y-2">
          <label className="flex cursor-pointer items-center justify-center rounded-lg border-2 border-dashed border-slate-300 bg-white px-4 py-6 text-sm text-slate-500 hover:border-brand-400 hover:text-brand-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400 dark:hover:border-brand-500">
            <input
              type="file"
              // Broad accept list: mobile file pickers grey out CSVs when the
              // filter is just ".csv", since the device MIME type often differs.
              accept=".csv,text/csv,text/comma-separated-values,application/csv,application/vnd.ms-excel"
              onChange={handleCsvUpload}
              disabled={csvSubmitting}
              className="sr-only"
            />
            {csvSubmitting ? "Uploading…" : "Upload Neon CSV"}
          </label>
          <StatusLine status={csvStatus} />
        </div>
        <form onSubmit={handleFinpension} className="space-y-2">
          <label className={LABEL} htmlFor="finpension">Finpension (CHF)</label>
          <div className="flex gap-2">
            <input
              id="finpension"
              type="text"
              inputMode="decimal"
              value={finpension}
              onChange={(e) => setFinpension(e.target.value)}
              placeholder={finpensionCurrent != null ? String(Math.round(finpensionCurrent)) : "e.g. 42000"}
              className={INPUT}
            />
            <Button type="submit" disabled={finpensionSaving}>
              {finpensionSaving ? "Saving…" : "Save"}
            </Button>
          </div>
          <StatusLine status={finpensionStatus} />
        </form>
      </section>

      <section className="space-y-4">
        <h2 className={HEADING}>Cash withdrawal</h2>
        <form onSubmit={handleCash} className="space-y-3">
          <div className="flex gap-2">
            <div className="flex-1">
              <label className={LABEL} htmlFor="cash-amount">Amount (CHF)</label>
              <input
                id="cash-amount"
                type="text"
                inputMode="decimal"
                value={cashAmount}
                onChange={(e) => setCashAmount(e.target.value)}
                placeholder="e.g. 200"
                className={INPUT}
              />
            </div>
            <div className="w-40">
              <label className={LABEL} htmlFor="cash-date">Date</label>
              <input id="cash-date" type="date" value={cashDate} onChange={(e) => setCashDate(e.target.value)} className={INPUT} />
            </div>
          </div>
          <div>
            <label className={LABEL} htmlFor="cash-note">Note</label>
            <input
              id="cash-note"
              type="text"
              value={cashNote}
              onChange={(e) => setCashNote(e.target.value)}
              placeholder="Optional"
              className={INPUT}
            />
          </div>
          <Button type="submit" disabled={cashSaving}>
            {cashSaving ? "Saving…" : "Record cash"}
          </Button>
          <StatusLine status={cashStatus} />
        </form>
        {withdrawals.length > 0 && (
          <ul className="divide-y divide-slate-200 text-sm dark:divide-slate-800">
            {withdrawals.map((w) => (
              <li key={w.id} className="flex items-center justify-between gap-3 py-2">
                <span className="min-w-0 truncate text-slate-600 dark:text-slate-300">
                  {w.date}
                  {w.note ? ` · ${w.note}` : ""}
                </span>
                <span className="flex items-center gap-3">
                  <span className="tabular-nums text-slate-800 dark:text-slate-100">{formatMoney(w.amount_chf)}</span>
                  <button
                    type="button"
                    onClick={() => removeCash(w.id)}
                    aria-label={`Delete ${w.date} withdrawal`}
                    className="text-slate-400 hover:text-red-600"
                  >
                    ×
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-4">
        <h2 className={HEADING}>Other holding</h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className={LABEL} htmlFor="h-label">Name</label>
            <input
              id="h-label"
              type="text"
              value={hLabel}
              onChange={(e) => setHLabel(e.target.value)}
              placeholder="e.g. UBS fund, Pillar 3a"
              className={INPUT}
            />
          </div>
          <div>
            <label className={LABEL} htmlFor="h-class">Category</label>
            <select id="h-class" value={hAssetClass} onChange={(e) => setHAssetClass(e.target.value)} className={INPUT}>
              {ASSET_CLASSES.map((ac) => (
                <option key={ac.value} value={ac.value}>
                  {ac.label}
                </option>
              ))}
            </select>
          </div>
          <div className="flex gap-2">
            <div className="flex-1">
              <label className={LABEL} htmlFor="h-amount">Amount</label>
              <input
                id="h-amount"
                type="text"
                inputMode="decimal"
                value={hAmount}
                onChange={(e) => setHAmount(e.target.value)}
                placeholder="e.g. 12000"
                className={INPUT}
              />
            </div>
            <div className="w-28">
              <label className={LABEL} htmlFor="h-currency">Currency</label>
              <select id="h-currency" value={hCurrency} onChange={(e) => setHCurrency(e.target.value)} className={INPUT}>
                {CURRENCIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <Button type="submit" disabled={submitting}>
            {submitting ? "Saving…" : "Save holding"}
          </Button>
          <StatusLine status={status} />
        </form>
      </section>
    </div>
  );
};

export default UpdatePage;
