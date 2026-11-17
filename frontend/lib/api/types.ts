/**
 * Contract types for the FastAPI backend. Kept next to the client so frontend and backend
 * schemas change together (they mirror backend/app/schemas).
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

export type User = {
  id: string;
  email: string;
  created_at: string;
};

export type TokenResponse = {
  access_token: string;
  token_type: string;
  expires_in: number;
};

export type DocumentStatus = "pending" | "processing" | "ready" | "failed";

export type DocumentRead = {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  status: DocumentStatus;
  error_message: string | null;
  total_pages: number | null;
  total_chunks: number | null;
  created_at: string;
  updated_at: string;
};

export type DocumentList = {
  items: DocumentRead[];
  total: number;
  limit: number;
  offset: number;
};

export type DocumentStatusRead = Pick<
  DocumentRead,
  "id" | "status" | "error_message" | "total_pages" | "total_chunks"
>;

export type Theme = "light" | "dark" | "system";

export type SettingsRead = {
  theme: Theme;
  /** The user's own value; null means the server default applies. */
  retrieval_top_k: number | null;
  retrieval_score_threshold: number | null;
  defaults: { top_k: number; score_threshold: number };
  server: {
    llm_model: string;
    llm_configured: boolean;
    embedding_provider: string;
    embedding_model: string;
    chunk_size_chars: number;
    chunk_overlap_chars: number;
    max_upload_bytes: number;
  };
};

/** A partial update; `null` on a retrieval value resets it to the server default. */
export type SettingsUpdate = {
  theme?: Theme;
  retrieval_top_k?: number | null;
  retrieval_score_threshold?: number | null;
};

export type OverviewResponse = {
  documents: { total: number; ready: number; processing: number; failed: number };
  chunks: number;
  conversations: number;
  messages: number;
  questions: number;
  answers: number;
  cited_answers: number;
  recent_activity: {
    days: number;
    documents_uploaded: number;
    conversations_started: number;
    questions_asked: number;
  };
};

/* ---- Chat ---- */

export type Conversation = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type ConversationList = {
  items: Conversation[];
  total: number;
  limit: number;
  offset: number;
};

/** One passage an answer relied on. `number` is the [n] marker in the answer text. */
export type Source = {
  number: number;
  document_id: string | null;
  chunk_id: string | null;
  filename: string;
  page_number: number | null;
  score: number;
};

export type ChatRole = "user" | "assistant";

export type Message = {
  id: string;
  role: ChatRole;
  content: string;
  created_at: string;
  sources: Source[];
};

export type MessageList = {
  items: Message[];
  total: number;
  limit: number;
  offset: number;
};

/** The saved pair of messages an answered question produces. */
export type ChatExchange = {
  user_message: Message;
  assistant_message: Message;
  grounded: boolean;
};

export type SendMessageBody = {
  content: string;
  /** Restrict retrieval to these documents; null/absent searches the whole library. */
  document_ids?: string[] | null;
};
