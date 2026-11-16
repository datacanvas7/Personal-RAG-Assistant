import { ApiError, NetworkError, isUnauthorized, parseErrorBody } from "./errors";
import type { TokenResponse } from "./types";

// Relative URL: the request goes to the Next.js server, which proxies /api/v1/* to the
// backend (see next.config.ts). No backend address or key is ever in browser code.
export const API_BASE = "/api/v1";

/* -----------------------------------------------------------------------------------------
   Session token
   The short-lived access token lives only in this module's memory: never in localStorage
   (any script on the page could read it) and never in a cookie of ours. The long-lived
   refresh token is an HttpOnly cookie the browser sends only to /api/v1/auth, so a page
   reload costs one silent call to /auth/refresh.
   ----------------------------------------------------------------------------------------- */

let accessToken: string | null = null;
let refreshInFlight: Promise<string | null> | null = null;
let sessionExpiredHandler: (() => void) | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

/** Called once when a request proves the session is over (the refresh cookie was refused). */
export function onSessionExpired(handler: (() => void) | null): void {
  sessionExpiredHandler = handler;
}

function expireSession(): void {
  accessToken = null;
  sessionExpiredHandler?.();
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return undefined;
  }
}

async function networkSafe(request: () => Promise<Response>): Promise<Response> {
  try {
    return await request();
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new NetworkError();
  }
}

/**
 * Exchange the refresh cookie for a new access token. Returns null when there is no valid
 * session (not an error: it is what a logged-out visitor gets). Throws on network failure
 * or a server error, so callers can tell "signed out" from "server down".
 *
 * One call at a time: the backend rotates the refresh token on every use, so two parallel
 * refreshes (React StrictMode, several requests failing together) must share one request.
 */
export function refreshAccessToken(): Promise<string | null> {
  refreshInFlight ??= (async () => {
    const response = await networkSafe(() =>
      fetch(`${API_BASE}/auth/refresh`, { method: "POST", cache: "no-store" }),
    );
    if (response.status === 401) {
      accessToken = null;
      return null;
    }
    if (!response.ok) throw parseErrorBody(response.status, await readJson(response));
    const body = (await response.json()) as TokenResponse;
    accessToken = body.access_token;
    return accessToken;
  })().finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

/**
 * Run `send` with a valid access token. On a 401 it refreshes the token once and tries
 * again; if the session is really over it tells the app (which signs the user out).
 */
export async function authorized<T>(send: (token: string) => Promise<T>): Promise<T> {
  const first = accessToken ?? (await refreshAccessToken());
  if (!first) {
    expireSession();
    throw new ApiError(401, "unauthorized", "Your session has ended. Please sign in again.");
  }
  try {
    return await send(first);
  } catch (error) {
    if (!isUnauthorized(error)) throw error;
    // Another request may already have refreshed while this one was in flight.
    const fresh = accessToken && accessToken !== first ? accessToken : await refreshAccessToken();
    if (!fresh) {
      expireSession();
      throw error;
    }
    try {
      return await send(fresh);
    } catch (retryError) {
      if (isUnauthorized(retryError)) expireSession();
      throw retryError;
    }
  }
}

/* -----------------------------------------------------------------------------------------
   Requests
   ----------------------------------------------------------------------------------------- */

type RequestOptions = {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  json?: unknown;
  signal?: AbortSignal;
  /** false for endpoints that need no token (login, register). Default true. */
  auth?: boolean;
};

async function sendOnce<T>(path: string, options: RequestOptions, token: string | null): Promise<T> {
  const headers: Record<string, string> = {};
  if (options.json !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await networkSafe(() =>
    fetch(`${API_BASE}${path}`, {
      method: options.method ?? "GET",
      headers,
      body: options.json === undefined ? undefined : JSON.stringify(options.json),
      signal: options.signal,
      cache: "no-store",
    }),
  );
  if (!response.ok) throw parseErrorBody(response.status, await readJson(response));
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Call the API and return the parsed JSON (undefined for 204). Throws ApiError / NetworkError. */
export function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  if (options.auth === false) return sendOnce<T>(path, options, null);
  return authorized((token) => sendOnce<T>(path, options, token));
}

/**
 * POST a file as multipart form data with upload progress (fetch cannot report it).
 * `onProgress` receives 0–100 while the bytes leave the browser; after that the server is
 * still working, which the caller shows as its own state.
 */
export function uploadFile<T>(
  path: string,
  file: File,
  options: { onProgress?: (percent: number) => void; signal?: AbortSignal } = {},
): Promise<T> {
  const attempt = (token: string) =>
    new Promise<T>((resolve, reject) => {
      const request = new XMLHttpRequest();
      request.open("POST", `${API_BASE}${path}`);
      request.setRequestHeader("Authorization", `Bearer ${token}`);
      request.responseType = "text";

      request.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          options.onProgress?.(Math.min(100, Math.round((event.loaded / event.total) * 100)));
        }
      };
      request.onerror = () => reject(new NetworkError());
      request.ontimeout = () => reject(new NetworkError());
      request.onabort = () => reject(new DOMException("Upload cancelled", "AbortError"));
      request.onload = () => {
        let body: unknown;
        try {
          body = JSON.parse(request.responseText);
        } catch {
          body = undefined;
        }
        if (request.status >= 200 && request.status < 300) resolve(body as T);
        else reject(parseErrorBody(request.status, body));
      };

      if (options.signal) {
        if (options.signal.aborted) {
          reject(new DOMException("Upload cancelled", "AbortError"));
          return;
        }
        options.signal.addEventListener("abort", () => request.abort(), { once: true });
      }

      const form = new FormData();
      form.append("file", file);
      request.send(form);
    });

  return authorized(attempt);
}
