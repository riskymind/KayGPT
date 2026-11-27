import type { Message, StreamEvent } from "@/types/api";

export interface ToolActivity {
  id: string;
  name: string;
  label: string;
  status: "running" | "success" | "error";
}

export interface UIMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: "complete" | "stopped" | "error" | "streaming";
  createdAt: string;
  tools: ToolActivity[];
  error?: string;
}

export interface ChatState {
  messages: UIMessage[];
  isStreaming: boolean;
}

export type ChatAction =
  | { type: "load"; messages: Message[] }
  | { type: "send"; text: string; now: string; userId: string; assistantId: string }
  | { type: "regenerate"; now: string; assistantId: string }
  | { type: "event"; event: StreamEvent }
  | { type: "stopped" }
  | { type: "failed"; message: string };

export const initialChatState: ChatState = { messages: [], isStreaming: false };

/** Display labels for tool names stored in message metadata (mirrors backend TOOL_LABELS). */
export const TOOL_LABELS: Record<string, string> = {
  calculator: "Calculator",
  web_search: "Web search",
  search_uploaded_documents: "Document search",
  remember_this: "Saving to memory",
  recall_memory: "Recalling memory",
};

export function fromApiMessage(message: Message): UIMessage {
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    status: message.status,
    createdAt: message.created_at,
    tools: (message.metadata.tools ?? []).map((name) => ({
      id: name,
      name,
      label: TOOL_LABELS[name] ?? name,
      status: "success" as const,
    })),
  };
}

function updateLastAssistant(state: ChatState, update: (m: UIMessage) => UIMessage): ChatState {
  const index = state.messages.findLastIndex((m) => m.role === "assistant");
  if (index === -1) return state;
  const messages = state.messages.slice();
  messages[index] = update(messages[index]);
  return { ...state, messages };
}

function finishTools(tools: ToolActivity[]): ToolActivity[] {
  return tools.map((t) => (t.status === "running" ? { ...t, status: "error" } : t));
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "load": {
      // First load: take the server history as is.
      if (state.messages.length === 0) {
        return { ...state, messages: action.messages.map(fromApiMessage) };
      }
      // Afterwards local state is authoritative (it holds streaming, stopped and error states the
      // server may not have). Only prepend older messages, e.g. from "Load earlier messages".
      const anchor = action.messages.findIndex((m) => m.id === state.messages[0].id);
      if (anchor <= 0) return state;
      return {
        ...state,
        messages: [...action.messages.slice(0, anchor).map(fromApiMessage), ...state.messages],
      };
    }

    case "send":
      return {
        isStreaming: true,
        messages: [
          ...state.messages,
          {
            id: action.userId,
            role: "user",
            content: action.text,
            status: "complete",
            createdAt: action.now,
            tools: [],
          },
          {
            id: action.assistantId,
            role: "assistant",
            content: "",
            status: "streaming",
            createdAt: action.now,
            tools: [],
          },
        ],
      };

    case "regenerate": {
      const messages = state.messages.slice();
      if (messages.at(-1)?.role === "assistant") messages.pop();
      messages.push({
        id: action.assistantId,
        role: "assistant",
        content: "",
        status: "streaming",
        createdAt: action.now,
        tools: [],
      });
      return { isStreaming: true, messages };
    }

    case "event": {
      const event = action.event;
      switch (event.type) {
        case "start": {
          // Replace the optimistic user message id with the server id.
          const index = state.messages.findLastIndex((m) => m.role === "user");
          if (index === -1) return state;
          const messages = state.messages.slice();
          messages[index] = { ...messages[index], id: event.user_message_id };
          return { ...state, messages };
        }
        case "token":
          return updateLastAssistant(state, (m) => ({ ...m, content: m.content + event.content }));
        case "tool_start":
          return updateLastAssistant(state, (m) => ({
            ...m,
            tools: [
              ...m.tools,
              {
                id: event.id ?? `${event.name}-${m.tools.length}`,
                name: event.name,
                label: event.label,
                status: "running",
              },
            ],
          }));
        case "tool_end":
          return updateLastAssistant(state, (m) => {
            const id = event.id ?? m.tools.findLast((t) => t.name === event.name)?.id;
            return {
              ...m,
              tools: m.tools.map((t) => (t.id === id ? { ...t, status: event.status } : t)),
            };
          });
        case "error":
          return {
            isStreaming: false,
            messages: updateLastAssistant(state, (m) => ({
              ...m,
              status: "error",
              error: event.message,
              tools: finishTools(m.tools),
            })).messages,
          };
        case "done":
          return {
            isStreaming: false,
            messages: updateLastAssistant(state, (m) => ({
              ...m,
              id: event.message_id ?? m.id,
              status: "complete",
            })).messages,
          };
      }
      return state;
    }

    case "stopped":
      return {
        isStreaming: false,
        messages: updateLastAssistant(state, (m) =>
          m.status === "streaming" ? { ...m, status: "stopped", tools: finishTools(m.tools) } : m,
        ).messages,
      };

    case "failed":
      return {
        isStreaming: false,
        messages: updateLastAssistant(state, (m) =>
          m.status === "streaming"
            ? { ...m, status: "error", error: action.message, tools: finishTools(m.tools) }
            : m,
        ).messages,
      };
  }
}
