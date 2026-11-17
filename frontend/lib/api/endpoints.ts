import { API_BASE, apiRequest, openStream, setAccessToken, uploadFile } from "./client";
import { ApiError, NetworkError } from "./errors";
import { readEvents } from "./sse";
import type {
  ChatExchange,
  Conversation,
  ConversationList,
  DocumentList,
  DocumentRead,
  DocumentStatusRead,
  HealthResponse,
  MessageList,
  OverviewResponse,
  SendMessageBody,
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

export const chatApi = {
  listConversations(params: { limit?: number; offset?: number } = {}, signal?: AbortSignal) {
    const query = new URLSearchParams();
    if (params.limit !== undefined) query.set("limit", String(params.limit));
    if (params.offset !== undefined) query.set("offset", String(params.offset));
    const suffix = query.size ? `?${query}` : "";
    return apiRequest<ConversationList>(`/chat/conversations${suffix}`, { signal });
  },

  createConversation(title?: string): Promise<Conversation> {
    return apiRequest<Conversation>("/chat/conversations", {
      method: "POST",
      json: title ? { title } : {},
    });
  },

  renameConversation(id: string, title: string): Promise<Conversation> {
    return apiRequest<Conversation>(`/chat/conversations/${id}`, { method: "PATCH", json: { title } });
  },

  removeConversation(id: string): Promise<void> {
    return apiRequest<void>(`/chat/conversations/${id}`, { method: "DELETE" });
  },

  listMessages(id: string, signal?: AbortSignal): Promise<MessageList> {
    return apiRequest<MessageList>(`/chat/conversations/${id}/messages?limit=200`, { signal });
  },

  /** Non-streaming fallback: waits for the whole answer. */
  send(id: string, body: SendMessageBody): Promise<ChatExchange> {
    return apiRequest<ChatExchange>(`/chat/${id}/messages`, { method: "POST", json: body });
  },

  /**
   * Ask a question and receive the answer as it is written. `onToken` gets each piece of
   * text; the promise resolves with the saved messages (with their sources) once the server
   * says it is done, and rejects with an ApiError if generation fails midway.
   */
  async stream(
    id: string,
    body: SendMessageBody,
    handlers: { onToken: (text: string) => void; signal?: AbortSignal },
  ): Promise<ChatExchange> {
    const response = await openStream(`/chat/${id}/stream`, body, handlers.signal);
    let exchange: ChatExchange | null = null;
    try {
      for await (const event of readEvents(response.body as ReadableStream<Uint8Array>)) {
        const payload = JSON.parse(event.data) as Record<string, unknown>;
        if (event.event === "token") {
          handlers.onToken(String(payload.text ?? ""));
        } else if (event.event === "done") {
          exchange = payload as unknown as ChatExchange;
        } else if (event.event === "error") {
          const error = payload.error as { code?: string; message?: string } | undefined;
          throw new ApiError(
            200,
            error?.code ?? "error",
            error?.message ?? "The answer could not be completed.",
          );
        }
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      if (error instanceof ApiError) throw error;
      throw new NetworkError();
    }
    if (!exchange) throw new NetworkError();
    return exchange;
  },
};
