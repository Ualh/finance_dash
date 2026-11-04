export interface SourceInfo {
  source: string;
  label: string;
  kind: "manual" | "automatic";
  /** Date the figure is valid for (Neon: latest transaction; automatic: last good sync). */
  as_of: string | null;
  age_days: number | null;
  stale: boolean;
  action: string;
  total_chf: number | null;
  last_updated: string | null;
  last_sync: string | null;
  sync_error: boolean;
  sync_message: string | null;
}

export interface FxInfo {
  rate: number;
  stale: boolean;
  currency: string;
}

export interface MonthPoint {
  month: string;
  date: string;
  total_chf: number;
}

export interface MonthSpending {
  month: string;
  total_chf: number;
  cash_chf: number;
}

export interface DashboardResponse {
  total_chf: number;
  buckets: {
    available: number;
    invested: number;
    locked: number;
  };
  change_since_last_month: { amount_chf: number; since: string; pct: number | null } | null;
  history: MonthPoint[];
  spending: MonthSpending[];
  sources: Record<string, SourceInfo>;
  stale_after_days: number;
  /** When the latest sync of an automatic source ran (ISO timestamp, UTC), whatever its outcome. */
  last_sync_at: string | null;
  /** When a Neon CSV was last uploaded (ISO timestamp, UTC). */
  last_neon_import_at: string | null;
  _fx?: FxInfo;
}

export interface CashWithdrawal {
  id: number;
  date: string;
  amount_chf: number;
  note: string | null;
  created_at: string;
}

export interface CashWithdrawalInput {
  amount_chf: number;
  date: string;
  note?: string;
}

export interface HoldingResponse {
  holding: Record<string, unknown>;
}

export interface NeonUploadResponse {
  balance: number;
  transactions_parsed: number;
  total_transactions: number;
  holding: Record<string, unknown>;
}

export interface SyncAllResponse {
  ok: string[];
  error: string[];
}

export interface SettingResponse {
  key: string;
  value: string | null;
}

export interface HoldingsListResponse {
  holdings: Array<{
    id: number;
    source: string;
    source_type: string;
    asset_class: string;
    value_chf: number;
    label: string | null;
    native_amount: number | null;
    native_currency: string | null;
    last_updated: string;
  }>;
}

export interface AddHoldingInput {
  label: string;
  asset_class: string;
  amount: number;
  currency: string;
}

export interface AddHoldingResponse {
  holding: {
    id: number;
    source: string;
    source_type: string;
    asset_class: string;
    value_chf: number;
    label: string | null;
    native_amount: number | null;
    native_currency: string | null;
    last_updated: string;
  };
  fx: { rate: number; stale: boolean; currency: string };
}

export interface NeonRecomputeResponse {
  balance: number;
  total_transactions: number;
  holding: Record<string, unknown>;
}

export interface HoldingUpdateResponse {
  holding: {
    id: number;
    source: string;
    source_type: string;
    asset_class: string;
    value_chf: number;
    label: string | null;
    last_updated: string;
  };
}
