import { useMemo } from "react";

import { ApiClient } from "@/api/client";

/**
 * Hook returning a memoised {@link ApiClient} instance bound to the configured API base URL.
 */
export function useApiClient(): ApiClient {
  const baseUrl = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
  return useMemo(() => new ApiClient(baseUrl), [baseUrl]);
}
