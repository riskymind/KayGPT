/**
 * Types mirroring the FastAPI schemas (backend/app/schemas/__init__.py).
 * Keep in sync with docs/api-specification.md.
 */

export interface User {
  id: string;
  email: string;
  display_name: string | null;
  created_at: string;
}

export interface AuthResponse {
  user: User;
  csrf_token: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface Conversation {
  id: string;
  title: string;
  model_id: string | null;
  created_at: string;
  updated_at: string;
}

export type MessageRole = "user" | "assistant";
export type MessageStatus = "complete" | "stopped" | "error";

export interface Message {
  id: string;
  conversation_id: string;
  role: MessageRole;
  content: string;
  status: MessageStatus;
  model_id: string | null;
  metadata: { tools?: string[] } & Record<string, unknown>;
  created_at: string;
}

export interface MessagePage {
  items: Message[];
  has_more: boolean;
}

export interface ModelInfo {
  id: string;
  label: string;
  provider: string;
  description: string;
  is_default: boolean;
}

export interface ModelsResponse {
  models: ModelInfo[];
  default_model: string;
}

export type DocumentStatus = "pending" | "processing" | "ready" | "failed";

export interface DocumentInfo {
  id: string;
  conversation_id: string | null;
  filename: string;
  content_type: string;
  size_bytes: number;
  status: DocumentStatus;
  error_message: string | null;
  chunk_count: number;
  created_at: string;
  updated_at: string;
}

export interface Memory {
  id: string;
  content: string;
  source: string;
  conversation_id: string | null;
  created_at: string;
  score: number | null;
}

export interface MemoryCreateResult {
  memory: Memory;
  created: boolean;
}

export type Theme = "system" | "light" | "dark";

export interface Preferences {
  default_model: string | null;
  theme: Theme;
  settings: Record<string, unknown>;
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: unknown; request_id?: string };
}

/** SSE events from POST /api/v1/chat/stream. */
export type StreamEvent =
  | {
      type: "start";
      conversation_id: string;
      user_message_id: string;
      model: string;
      title: string;
    }
  | { type: "token"; content: string }
  | { type: "tool_start"; id: string | null; name: string; label: string }
  | {
      type: "tool_end";
      id: string | null;
      name: string;
      label: string;
      status: "success" | "error";
    }
  | { type: "error"; code: string; message: string }
  | { type: "done"; conversation_id: string; message_id: string | null; title: string };

export interface ChatRequest {
  conversation_id?: string | null;
  message?: string;
  model?: string | null;
  regenerate?: boolean;
}
