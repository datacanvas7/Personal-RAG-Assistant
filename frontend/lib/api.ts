/**
 * Contract types for the FastAPI backend. Kept next to the client so frontend and
 * backend schemas change together (mirrors backend/app/schemas).
 */

export type ComponentHealth = {
  status: "ok" | "error";
  detail: string | null;
};

export type HealthResponse = {
  status: "ok" | "degraded";
  version: string;
  environment: string;
  checks: Record<string, ComponentHealth>;
};

// Relative URL: the request goes to the Next.js server, which proxies /api/v1/* to the
// backend (see next.config.ts). No backend address or key is ever in browser code.
const API_BASE = "/api/v1";

/**
 * Fetch backend health. The backend answers 503 *with a body* when a dependency is
 * down, so both 200 and 503 are parsed; anything else is a transport-level failure.
 */
export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE}/health`, { cache: "no-store", signal });
  if (response.status !== 200 && response.status !== 503) {
    throw new Error(`Unexpected response: HTTP ${response.status}`);
  }
  return (await response.json()) as HealthResponse;
}
