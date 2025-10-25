import type {
  FxRefreshResponse,
  ImportResponse,
  QuoteResponse,
  SummaryResponse,
  TransactionsResponse,
  DisplayCurrencyResponse,
  DisplayCurrencyRequest,
} from "@/lib/types";

function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    return response.json().catch(() => ({})).then((payload) => {
      const message = (payload && (payload.detail as string)) || response.statusText;
      throw new Error(message || "Unexpected API error");
    });
  }
  return response.json() as Promise<T>;
}

/**
 * Minimal REST client talking to the FastAPI backend.
 */
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

  async getSummary(currency: string): Promise<SummaryResponse> {
    const response = await fetch(this.url("summary", { display_currency: currency }));
    return handleResponse<SummaryResponse>(response);
  }

  async getTransactions(limit = 200): Promise<TransactionsResponse> {
    const response = await fetch(this.url("transactions", { limit }));
    return handleResponse<TransactionsResponse>(response);
  }

  async importWorkbook(sheets?: string[]): Promise<ImportResponse> {
    const params: Record<string, string> = {};
    sheets?.forEach((sheet) => {
      params["sheet_names"] = sheet; // FastAPI accepts repeated query params.
    });
    const response = await fetch(this.url("import", params), { method: "POST" });
    return handleResponse<ImportResponse>(response);
  }

  async refreshFx(base: string, quote: string): Promise<FxRefreshResponse> {
    const response = await fetch(this.url("fx/refresh", { base, quote }), { method: "POST" });
    return handleResponse<FxRefreshResponse>(response);
  }

  async refreshEquity(symbol: string): Promise<QuoteResponse> {
    const response = await fetch(this.url(`quotes/equity/${symbol}`), { method: "POST" });
    return handleResponse<QuoteResponse>(response);
  }

  async refreshCrypto(uuid: string): Promise<QuoteResponse> {
    const response = await fetch(this.url(`quotes/crypto/${uuid}`), { method: "POST" });
    return handleResponse<QuoteResponse>(response);
  }

  async getDisplayCurrency(): Promise<DisplayCurrencyResponse> {
    const response = await fetch(this.url("settings/display-currency"));
    return handleResponse<DisplayCurrencyResponse>(response);
  }

  async setDisplayCurrency(currency: string): Promise<DisplayCurrencyResponse> {
    const params: DisplayCurrencyRequest = { currency };
    const response = await fetch(this.url("settings/display-currency", params), { method: "PUT" });
    return handleResponse<DisplayCurrencyResponse>(response);
  }
}
