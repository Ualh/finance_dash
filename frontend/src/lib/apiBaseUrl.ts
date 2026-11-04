/**
 * Decide which origin the frontend sends API calls to.
 *
 * An explicit, non-empty `VITE_API_BASE_URL` wins. An empty or missing value means
 * "same origin" in production (the build FastAPI serves, reachable from any host:
 * LAN IP, Tailscale, hostname) and the local backend during `vite dev`.
 *
 * The empty string must fall through: the documented production build sets
 * `VITE_API_BASE_URL=""`, and treating that as a base gave `new URL("dashboard", "/")`,
 * which throws "Invalid base URL".
 */
export function resolveApiBaseUrl(envValue: string | undefined, isDev: boolean, origin: string): string {
  const explicit = envValue?.trim();
  if (explicit) {
    return explicit;
  }
  return isDev ? "http://127.0.0.1:8000" : origin;
}
