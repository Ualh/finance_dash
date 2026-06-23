import { useMemo } from "react";

import { ApiClient } from "@/api/client";

/**
 * Hook returning a memoised {@link ApiClient} instance bound to the configured API base URL.
 */
export function useApiClient(): ApiClient {
  // Prefer an explicit override; otherwise use same-origin in production so the app
  // works from any host it was served on (LAN IP, Tailscale, hostname), and fall back
  // to the local backend only during `vite dev`.
  const baseUrl =
    import.meta.env.VITE_API_BASE_URL ??
    (import.meta.env.DEV ? "http://127.0.0.1:8000" : window.location.origin);
  return useMemo(() => new ApiClient(baseUrl), [baseUrl]);
}
