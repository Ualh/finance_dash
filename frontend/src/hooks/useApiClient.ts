import { useMemo } from "react";

import { ApiClient } from "@/api/client";
import { resolveApiBaseUrl } from "@/lib/apiBaseUrl";

/**
 * Hook returning a memoised {@link ApiClient} instance bound to the configured API base URL.
 */
export function useApiClient(): ApiClient {
  const baseUrl = resolveApiBaseUrl(import.meta.env.VITE_API_BASE_URL, import.meta.env.DEV, window.location.origin);
  return useMemo(() => new ApiClient(baseUrl), [baseUrl]);
}
