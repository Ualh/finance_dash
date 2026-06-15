export interface DashboardResponse {
  total_chf: number;
  buckets: {
    available: number;
    invested: number;
    locked: number;
  };
  delta_chf: number | null;
  sources: Record<string, { total_chf: number; last_updated: string }>;
}

export interface HoldingResponse {
  holding: Record<string, unknown>;
}
