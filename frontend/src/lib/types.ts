export interface SourceInfo {
  total_chf: number;
  last_updated: string;
  last_sync: string | null;
  sync_error: boolean;
}

export interface FxInfo {
  rate: number;
  stale: boolean;
  currency: string;
}

export interface DashboardResponse {
  total_chf: number;
  buckets: {
    available: number;
    invested: number;
    locked: number;
  };
  delta_chf: number | null;
  delta_pct: number | null;
  sources: Record<string, SourceInfo>;
  _fx?: FxInfo;
}

export interface HoldingResponse {
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
