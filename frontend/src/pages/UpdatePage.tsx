import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useApiClient } from "@/hooks/useApiClient";
import { Button } from "@/components/ui/Button";

const UpdatePage: React.FC = () => {
  const api = useApiClient();
  const navigate = useNavigate();

  const [value, setValue] = useState("");
  const [label, setLabel] = useState("");
  const [status, setStatus] = useState<{ ok: boolean; msg: string } | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const [anchorDate, setAnchorDate] = useState("");
  const [anchorAmount, setAnchorAmount] = useState("");
  const [anchorStatus, setAnchorStatus] = useState<{ ok: boolean; msg: string } | null>(null);
  const [anchorSubmitting, setAnchorSubmitting] = useState(false);

  const [csvStatus, setCsvStatus] = useState<{ ok: boolean; msg: string } | null>(null);
  const [csvSubmitting, setCsvSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const num = parseFloat(value);
    if (isNaN(num)) {
      setStatus({ ok: false, msg: "Please enter a valid number." });
      return;
    }
    setSubmitting(true);
    setStatus(null);
    try {
      await api.updateFinpension(num, label || undefined);
      setStatus({ ok: true, msg: "Finpension holding updated." });
      setValue("");
      setLabel("");
    } catch (err) {
      setStatus({ ok: false, msg: (err as Error).message });
    } finally {
      setSubmitting(false);
    }
  };

  const handleAnchorSave = async (e: React.FormEvent) => {
    e.preventDefault();
    const num = parseFloat(anchorAmount);
    if (!anchorDate || isNaN(num)) {
      setAnchorStatus({ ok: false, msg: "Please enter a valid date and amount." });
      return;
    }
    setAnchorSubmitting(true);
    setAnchorStatus(null);
    try {
      await api.setSetting("neon_anchor_date", anchorDate);
      await api.setSetting("neon_anchor_amount", anchorAmount);
      setAnchorStatus({ ok: true, msg: "Anchor balance saved." });
    } catch (err) {
      setAnchorStatus({ ok: false, msg: (err as Error).message });
    } finally {
      setAnchorSubmitting(false);
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
      setCsvStatus({
        ok: true,
        msg: `Neon CSV uploaded: ${res.transactions_parsed} transaction(s) parsed, balance = CHF ${res.balance.toLocaleString("de-CH", { minimumFractionDigits: 2 })}.`,
      });
      setTimeout(() => navigate("/"), 2000);
    } catch (err) {
      setCsvStatus({ ok: false, msg: (err as Error).message });
    } finally {
      setCsvSubmitting(false);
      e.target.value = "";
    }
  };

  return (
    <div className="space-y-8">
      <section>
        <h2 className="text-xl font-semibold text-slate-800 dark:text-slate-100">Update Finpension</h2>
        <form onSubmit={handleSubmit} className="mt-4 max-w-md space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              Value (CHF)
            </label>
            <input
              type="text"
              inputMode="decimal"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="e.g. 123456"
              className="block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder-slate-400 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:placeholder-slate-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              Label (optional)
            </label>
            <input
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="e.g. Pillar 3a"
              className="block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder-slate-400 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:placeholder-slate-500"
            />
          </div>
          <Button type="submit" disabled={submitting}>
            {submitting ? "Saving..." : "Save"}
          </Button>
          {status && (
            <p className={`text-sm ${status.ok ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
              {status.msg}
            </p>
          )}
        </form>
      </section>

      <section>
        <h2 className="text-xl font-semibold text-slate-800 dark:text-slate-100">Neon CSV Anchor Balance</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
          Enter the last known balance and its date. Subsequent CSV uploads will derive the current balance from this anchor.
        </p>
        <form onSubmit={handleAnchorSave} className="mt-4 max-w-md space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              Anchor Date
            </label>
            <input
              type="date"
              value={anchorDate}
              onChange={(e) => setAnchorDate(e.target.value)}
              className="block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              Anchor Amount (CHF)
            </label>
            <input
              type="text"
              inputMode="decimal"
              value={anchorAmount}
              onChange={(e) => setAnchorAmount(e.target.value)}
              placeholder="e.g. 5000.00"
              className="block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder-slate-400 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:placeholder-slate-500"
            />
          </div>
          <Button type="submit" disabled={anchorSubmitting}>
            {anchorSubmitting ? "Saving..." : "Save Anchor"}
          </Button>
          {anchorStatus && (
            <p className={`text-sm ${anchorStatus.ok ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
              {anchorStatus.msg}
            </p>
          )}
        </form>
      </section>

      <section>
        <h2 className="text-xl font-semibold text-slate-800 dark:text-slate-100">Upload Neon CSV</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
          Upload a Neon account statement CSV file. It will be archived and used to derive the current balance.
        </p>
        <div className="mt-4 max-w-md">
          <label className="flex cursor-pointer items-center justify-center rounded-lg border-2 border-dashed border-slate-300 bg-white px-4 py-6 text-sm text-slate-500 hover:border-brand-400 hover:text-brand-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400 dark:hover:border-brand-500">
            <input
              type="file"
              accept=".csv"
              onChange={handleCsvUpload}
              disabled={csvSubmitting}
              className="sr-only"
            />
            {csvSubmitting ? "Uploading…" : "Choose a CSV file or tap to browse"}
          </label>
          {csvStatus && (
            <p className={`mt-2 text-sm ${csvStatus.ok ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
              {csvStatus.msg}
            </p>
          )}
        </div>
      </section>
    </div>
  );
};

export default UpdatePage;
