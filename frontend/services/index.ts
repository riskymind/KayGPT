/**
 * Services layer: every call to the FastAPI backend goes through here.
 * Components and hooks never call fetch() directly.
 */
import { api, apiUrl, buildHeaders, setCsrfToken, toApiError } from "@/lib/api-client";
import { readEventStream } from "@/lib/sse";
import type {
  AuthResponse,
  ChatRequest,
  Conversation,
  DocumentInfo,
  Memory,
  MemoryCreateResult,
  MessagePage,
  ModelsResponse,
  Page,
  Preferences,
  StreamEvent,
  Theme,
} from "@/types/api";

function remember(auth: AuthResponse): AuthResponse {
  setCsrfToken(auth.csrf_token);
  return auth;
}

export const authService = {
  async me(): Promise<AuthResponse> {
    return remember(await api<AuthResponse>("/auth/me"));
  },
  async login(email: string, password: string): Promise<AuthResponse> {
    return remember(
      await api<AuthResponse>("/auth/login", { method: "POST", body: { email, password } }),
    );
  },
  async register(email: string, password: string, displayName?: string): Promise<AuthResponse> {
    return remember(
      await api<AuthResponse>("/auth/register", {
        method: "POST",
        body: { email, password, display_name: displayName || null },
      }),
    );
  },
  async logout(): Promise<void> {
    try {
      await api<void>("/auth/logout", { method: "POST" });
    } finally {
      setCsrfToken(null);
    }
  },
};

export const conversationService = {
  list(params: { q?: string; limit?: number; offset?: number } = {}) {
    return api<Page<Conversation>>("/conversations", { query: params });
  },
  get(id: string) {
    return api<Conversation>(`/conversations/${id}`);
  },
  create(body: { title?: string; model_id?: string | null } = {}) {
    return api<Conversation>("/conversations", { method: "POST", body });
  },
  rename(id: string, title: string) {
    return api<Conversation>(`/conversations/${id}`, { method: "PATCH", body: { title } });
  },
  remove(id: string) {
    return api<void>(`/conversations/${id}`, { method: "DELETE" });
  },
  messages(id: string, params: { limit?: number; before?: string } = {}) {
    return api<MessagePage>(`/conversations/${id}/messages`, { query: params });
  },
};

export const chatService = {
  /** POST /chat/stream and yield typed SSE events. Abort the signal to stop generation. */
  async *stream(body: ChatRequest, signal?: AbortSignal): AsyncGenerator<StreamEvent> {
    const response = await fetch(apiUrl("/chat/stream"), {
      method: "POST",
      credentials: "include",
      headers: buildHeaders("POST", { Accept: "text/event-stream" }),
      body: JSON.stringify(body),
      signal,
    });
    if (!response.ok) throw await toApiError(response);
    if (!response.body) throw new Error("Streaming is not supported by this browser.");
    yield* readEventStream(response.body);
  },
};

export const documentService = {
  list(conversationId?: string | null) {
    return api<DocumentInfo[]>("/documents", { query: { conversation_id: conversationId } });
  },
  get(id: string) {
    return api<DocumentInfo>(`/documents/${id}`);
  },
  upload(file: File, conversationId?: string | null) {
    const form = new FormData();
    form.append("file", file);
    if (conversationId) form.append("conversation_id", conversationId);
    return api<DocumentInfo>("/documents/upload", { method: "POST", body: form });
  },
  remove(id: string) {
    return api<void>(`/documents/${id}`, { method: "DELETE" });
  },
};

export const memoryService = {
  list(params: { q?: string; limit?: number; offset?: number } = {}) {
    return api<Page<Memory>>("/memory", { query: params });
  },
  create(content: string) {
    return api<MemoryCreateResult>("/memory", { method: "POST", body: { content } });
  },
  remove(id: string) {
    return api<void>(`/memory/${id}`, { method: "DELETE" });
  },
};

export const modelService = {
  list() {
    return api<ModelsResponse>("/models");
  },
};

export const preferenceService = {
  get() {
    return api<Preferences>("/preferences");
  },
  update(body: {
    default_model?: string | null;
    theme?: Theme;
    settings?: Record<string, unknown>;
  }) {
    return api<Preferences>("/preferences", { method: "PUT", body });
  },
};
