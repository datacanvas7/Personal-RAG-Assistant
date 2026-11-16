import { API_BASE, apiRequest, setAccessToken, uploadFile } from "./client";
import { NetworkError } from "./errors";
import type {
  DocumentList,
  DocumentRead,
  DocumentStatusRead,
  HealthResponse,
  OverviewResponse,
  SettingsRead,
  SettingsUpdate,
  TokenResponse,
  User,
} from "./types";

export const authApi = {
  /** Sign in; the access token is kept in memory and the refresh cookie is set by the server. */
  async login(email: string, password: string): Promise<void> {
    const token = await apiRequest<TokenResponse>("/auth/login", {
      method: "POST",
      json: { email, password },
      auth: false,
    });
    setAccessToken(token.access_token);
  },

  register(email: string, password: string): Promise<User> {
    return apiRequest<User>("/auth/register", {
      method: "POST",
      json: { email, password },
      auth: false,
    });
  },

  async logout(): Promise<void> {
    try {
      await apiRequest<void>("/auth/logout", { method: "POST", auth: false });
    } finally {
      setAccessToken(null);
    }
  },

  me(): Promise<User> {
    return apiRequest<User>("/users/me");
  },
};

export const documentsApi = {
  list(params: { limit?: number; offset?: number } = {}, signal?: AbortSignal): Promise<DocumentList> {
    const query = new URLSearchParams();
    if (params.limit !== undefined) query.set("limit", String(params.limit));
    if (params.offset !== undefined) query.set("offset", String(params.offset));
    const suffix = query.size ? `?${query}` : "";
    return apiRequest<DocumentList>(`/documents${suffix}`, { signal });
  },

  status(id: string, signal?: AbortSignal): Promise<DocumentStatusRead> {
    return apiRequest<DocumentStatusRead>(`/documents/${id}/status`, { signal });
  },

  upload(
    file: File,
    options?: { onProgress?: (percent: number) => void; signal?: AbortSignal },
  ): Promise<DocumentRead> {
    return uploadFile<DocumentRead>("/documents/upload", file, options);
  },

  retry(id: string): Promise<DocumentRead> {
    return apiRequest<DocumentRead>(`/documents/${id}/retry`, { method: "POST" });
  },

  remove(id: string): Promise<void> {
    return apiRequest<void>(`/documents/${id}`, { method: "DELETE" });
  },
};

export const settingsApi = {
  get(): Promise<SettingsRead> {
    return apiRequest<SettingsRead>("/settings");
  },
  update(changes: SettingsUpdate): Promise<SettingsRead> {
    return apiRequest<SettingsRead>("/settings", { method: "PATCH", json: changes });
  },
};

export const analyticsApi = {
  overview(): Promise<OverviewResponse> {
    return apiRequest<OverviewResponse>("/analytics/overview");
  },
};

/**
 * Backend health. The backend answers 503 *with a body* when a dependency is down, so both
 * 200 and 503 are parsed; anything else is a transport-level failure.
 */
export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/health`, { cache: "no-store", signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new NetworkError();
  }
  if (response.status !== 200 && response.status !== 503) {
    throw new Error(`Unexpected response: HTTP ${response.status}`);
  }
  return (await response.json()) as HealthResponse;
}
