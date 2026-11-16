/** An error answered by the API (or the network path to it), already in words for a person. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

/** The request never produced an HTTP answer (offline, server down, DNS, aborted by the browser). */
export class NetworkError extends Error {
  constructor() {
    super("Can't reach the server. Check your connection and try again.");
    this.name = "NetworkError";
  }
}

const FALLBACK_BY_STATUS: Record<number, string> = {
  400: "That request wasn't accepted.",
  401: "Your session has ended. Please sign in again.",
  403: "You don't have access to that.",
  404: "That couldn't be found.",
  413: "That file is too large.",
  415: "That kind of file isn't supported.",
  429: "Too many requests. Please wait a moment and try again.",
  500: "Something went wrong on our side. Please try again.",
  502: "The server isn't reachable right now. Please try again shortly.",
  503: "The service is unavailable right now. Please try again shortly.",
  504: "The server took too long to answer. Please try again.",
};

type ValidationDetail = { loc?: unknown[]; msg?: string };

/** Turn a failed response into an ApiError. Understands the API's own error shape
 * (`{"error": {"code", "message"}}`), FastAPI's validation shape (`{"detail": [...]}`) and
 * plain text/HTML from a proxy. */
export function parseErrorBody(status: number, body: unknown): ApiError {
  const fallback = FALLBACK_BY_STATUS[status] ?? `The request failed (HTTP ${status}).`;
  if (body && typeof body === "object") {
    const record = body as Record<string, unknown>;
    const error = record.error;
    if (error && typeof error === "object") {
      const { code, message } = error as { code?: unknown; message?: unknown };
      return new ApiError(
        status,
        typeof code === "string" ? code : "error",
        typeof message === "string" && message ? message : fallback,
      );
    }
    if (Array.isArray(record.detail)) {
      const first = record.detail[0] as ValidationDetail | undefined;
      const field = first?.loc?.filter((part) => typeof part === "string" && part !== "body").pop();
      const message = first?.msg ? `${field ? `${String(field)}: ` : ""}${first.msg}` : fallback;
      return new ApiError(status, "validation_error", message);
    }
  }
  return new ApiError(status, "error", fallback);
}

export function errorMessage(error: unknown, fallback = "Something went wrong."): string {
  if (error instanceof ApiError || error instanceof NetworkError) return error.message;
  return fallback;
}

export function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}
