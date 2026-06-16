import type { DashboardResponse, HoldingResponse, SyncAllResponse } from "@/lib/types";

function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    return response.json().catch(() => ({})).then((payload) => {
      const message = (payload && (payload.detail as string)) || response.statusText;
      throw new Error(message || "Unexpected API error");
    });
  }
  return response.json() as Promise<T>;
}

export class ApiClient {
  constructor(private readonly baseUrl: string) {}

  private url(path: string, params?: Record<string, string | number | undefined>): string {
    const url = new URL(path, this.baseUrl.endsWith("/") ? this.baseUrl : `${this.baseUrl}/`);
    if (params) {
      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined) {
          url.searchParams.set(key, String(value));
        }
      });
    }
    return url.toString();
  }

  async getDashboard(): Promise<DashboardResponse> {
    const response = await fetch(this.url("dashboard"));
    return handleResponse<DashboardResponse>(response);
  }

  async syncAll(): Promise<SyncAllResponse> {
    const response = await fetch(this.url("sync/all"), { method: "POST" });
    return handleResponse<SyncAllResponse>(response);
  }

  async updateFinpension(value_chf: number, label?: string): Promise<HoldingResponse> {
    const response = await fetch(this.url("holdings/finpension"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value_chf, label: label ?? null }),
    });
    return handleResponse<HoldingResponse>(response);
  }
}
