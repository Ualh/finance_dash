import type { DashboardResponse, HoldingResponse, HoldingUpdateResponse, HoldingsListResponse, NeonUploadResponse, SettingResponse, SyncAllResponse } from "@/lib/types";

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

  async getDashboard(currency?: string): Promise<DashboardResponse> {
    const response = await fetch(this.url("dashboard", { currency }));
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

  async uploadNeonCsv(file: File): Promise<NeonUploadResponse> {
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch(this.url("holdings/neon/upload"), {
      method: "POST",
      body: formData,
    });
    return handleResponse<NeonUploadResponse>(response);
  }

  async getSetting(key: string): Promise<SettingResponse> {
    const response = await fetch(this.url(`settings/${key}`));
    return handleResponse<SettingResponse>(response);
  }

  async setSetting(key: string, value: string): Promise<SettingResponse> {
    const response = await fetch(this.url(`settings/${key}`), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value }),
    });
    return handleResponse<SettingResponse>(response);
  }

  async listHoldings(): Promise<HoldingsListResponse> {
    const response = await fetch(this.url("holdings"));
    return handleResponse<HoldingsListResponse>(response);
  }

  async updateHolding(holdingId: number, value_chf: number): Promise<HoldingUpdateResponse> {
    const response = await fetch(this.url(`holdings/${holdingId}`), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value_chf }),
    });
    return handleResponse<HoldingUpdateResponse>(response);
  }
}
