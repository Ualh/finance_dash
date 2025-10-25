import React from "react";

interface DataStateProps {
  loading: boolean;
  error: string | null;
  empty: boolean;
  children: React.ReactNode;
  emptyMessage?: string;
}

export const DataState: React.FC<DataStateProps> = ({
  loading,
  error,
  empty,
  children,
  emptyMessage = "No records available.",
}: DataStateProps) => {
  if (loading) {
    return (
      <div className="flex items-center justify-center rounded-lg border border-dashed border-slate-300 bg-white p-10 text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400">
        Loading…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300">
        {error}
      </div>
    );
  }

  if (empty) {
    return (
      <div className="flex items-center justify-center rounded-lg border border-dashed border-slate-300 bg-white p-10 text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400">
        {emptyMessage}
      </div>
    );
  }

  return <>{children}</>;
};
