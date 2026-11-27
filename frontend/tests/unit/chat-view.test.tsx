import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ChatRequest, StreamEvent } from "@/types/api";

import { renderWithClient } from "./test-utils";

const router = { replace: vi.fn(), push: vi.fn(), refresh: vi.fn() };
let params: { id?: string } = {};

vi.mock("next/navigation", () => ({
  useRouter: () => router,
  useParams: () => params,
  usePathname: () => "/",
}));
vi.mock("@/components/app-shell", () => ({
  useShell: () => ({ setMobileOpen: vi.fn(), openDocuments: vi.fn(), openSettings: vi.fn() }),
}));

type StreamFn = (body: ChatRequest, signal?: AbortSignal) => AsyncGenerator<StreamEvent>;
const streamImpl = vi.fn<StreamFn>();
const messagesImpl = vi.fn();

vi.mock("@/services", () => ({
  chatService: { stream: (body: ChatRequest, signal?: AbortSignal) => streamImpl(body, signal) },
  conversationService: {
    messages: (...args: unknown[]) => messagesImpl(...args),
    create: vi.fn(),
    list: vi.fn(async () => ({ items: [], total: 0, limit: 100, offset: 0 })),
  },
  documentService: { list: vi.fn(async () => []), upload: vi.fn() },
  modelService: {
    list: vi.fn(async () => ({
      default_model: "gemini-3.8-flash",
      models: [
        {
          id: "gemini-3.8-flash",
          label: "gemini-3.8-flash",
          provider: "gemini",
          description: "Fast",
          is_default: true,
        },
      ],
    })),
  },
  preferenceService: {
    get: vi.fn(async () => ({ default_model: null, theme: "dark", settings: {} })),
  },
  authService: {},
  memoryService: {},
}));

const { ChatView } = await import("@/components/chat/chat-view");
const { ChatRoute } = await import("@/components/chat/chat-route");

const start: StreamEvent = {
  type: "start",
  conversation_id: "conv-1",
  user_message_id: "u1",
  model: "gemini-3.8-flash",
  title: "Hello",
};

beforeEach(() => {
  vi.clearAllMocks();
  params = {};
  messagesImpl.mockResolvedValue({ items: [], has_more: false });
});

describe("ChatView", () => {
  it("shows the empty state with suggestions that fill the composer", async () => {
    const user = userEvent.setup();
    renderWithClient(<ChatView conversationId={null} onConversationCreated={vi.fn()} />);
    expect(screen.getByText("How can I help you today?")).toBeInTheDocument();
    await user.click(screen.getByText("Use the calculator"));
    await waitFor(() =>
      expect(screen.getByLabelText("Message KayGPT")).toHaveValue("Calculate 125 * 48 / 6"),
    );
  });

  it("streams tokens, shows tool progress, renders markdown and adopts the new conversation", async () => {
    const user = userEvent.setup();
    const created = vi.fn();
    streamImpl.mockImplementation(async function* (body) {
      expect(body).toMatchObject({ message: "Hello", conversation_id: null });
      yield start;
      yield { type: "tool_start", id: "c1", name: "web_search", label: "Web search" };
      yield {
        type: "tool_end",
        id: "c1",
        name: "web_search",
        label: "Web search",
        status: "success",
      };
      yield { type: "token", content: "Here is **bold** and `code`:\n\n" };
      yield { type: "token", content: "```python\nprint('hi')\n```" };
      yield { type: "done", conversation_id: "conv-1", message_id: "a1", title: "Hello" };
    });
    renderWithClient(<ChatView conversationId={null} onConversationCreated={created} />);

    await user.type(screen.getByLabelText("Message KayGPT"), "Hello{Enter}");

    expect(await screen.findByText("bold")).toHaveProperty("tagName", "STRONG");
    expect(screen.getByText("Web search")).toBeInTheDocument();
    expect(screen.getByText("python")).toBeInTheDocument(); // code block language label
    expect(screen.getByRole("button", { name: "Copy code" })).toBeInTheDocument();
    expect(screen.getByTestId("message-user")).toHaveTextContent("Hello");
    expect(created).toHaveBeenCalledWith("conv-1");
    expect(router.replace).toHaveBeenCalledWith("/c/conv-1", { scroll: false });
    expect(screen.getByLabelText("Message KayGPT")).toHaveValue("");
  });

  it("stop aborts the stream and keeps the partial answer", async () => {
    const user = userEvent.setup();
    streamImpl.mockImplementation(async function* (_body, signal) {
      yield start;
      yield { type: "token", content: "Partial answer" };
      await new Promise((_, reject) =>
        signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError"))),
      );
    });
    renderWithClient(<ChatView conversationId={null} onConversationCreated={vi.fn()} />);
    await user.type(screen.getByLabelText("Message KayGPT"), "Long story{Enter}");
    await screen.findByText("Partial answer");

    await user.click(screen.getByRole("button", { name: "Stop generating" }));

    expect(await screen.findByText("Generation stopped")).toBeInTheDocument();
    expect(screen.getByText("Partial answer")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send message" })).toBeInTheDocument();
  });

  it("shows server errors without leaking details and offers regenerate", async () => {
    const user = userEvent.setup();
    streamImpl.mockImplementation(async function* () {
      yield start;
      yield { type: "error", code: "generation_failed", message: "Please try again." };
    });
    renderWithClient(<ChatView conversationId={null} onConversationCreated={vi.fn()} />);
    await user.type(screen.getByLabelText("Message KayGPT"), "Hi{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("Please try again.");
    expect(screen.getByRole("button", { name: "Regenerate response" })).toBeInTheDocument();
  });

  it("loads history for an existing conversation and regenerates the last answer", async () => {
    const user = userEvent.setup();
    messagesImpl.mockResolvedValue({
      has_more: false,
      items: [
        {
          id: "u1",
          conversation_id: "conv-1",
          role: "user",
          content: "What is 2+2?",
          status: "complete",
          model_id: null,
          metadata: {},
          created_at: "2026-11-23T10:00:00Z",
        },
        {
          id: "a1",
          conversation_id: "conv-1",
          role: "assistant",
          content: "Five",
          status: "complete",
          model_id: null,
          metadata: { tools: ["calculator"] },
          created_at: "2026-11-23T10:00:01Z",
        },
      ],
    });
    streamImpl.mockImplementation(async function* (body) {
      expect(body).toMatchObject({ regenerate: true, conversation_id: "conv-1" });
      yield { ...start, user_message_id: "u1" };
      yield { type: "token", content: "Four" };
      yield { type: "done", conversation_id: "conv-1", message_id: "a2", title: "t" };
    });
    renderWithClient(<ChatView conversationId="conv-1" onConversationCreated={vi.fn()} />);
    expect(await screen.findByText("Five")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Regenerate response" }));
    expect(await screen.findByText("Four")).toBeInTheDocument();
    expect(screen.queryByText("Five")).not.toBeInTheDocument();
  });
});

describe("ChatRoute conversation switching", () => {
  it("mounts a fresh view with the other conversation's history when the URL changes", async () => {
    messagesImpl.mockImplementation(async (id: string) => ({
      has_more: false,
      items: [
        {
          id: `${id}-m`,
          conversation_id: id,
          role: "user",
          content: `message in ${id}`,
          status: "complete",
          model_id: null,
          metadata: {},
          created_at: "2026-11-23T10:00:00Z",
        },
      ],
    }));
    params = { id: "conv-a" };
    const { rerender, client } = renderWithClient(<ChatRoute />);
    expect(await screen.findByText("message in conv-a")).toBeInTheDocument();

    params = { id: "conv-b" };
    const { QueryClientProvider } = await import("@tanstack/react-query");
    const { TooltipProvider } = await import("@/components/ui/tooltip");
    await act(async () => {
      rerender(
        <QueryClientProvider client={client}>
          <TooltipProvider>
            <ChatRoute />
          </TooltipProvider>
        </QueryClientProvider>,
      );
    });
    expect(await screen.findByText("message in conv-b")).toBeInTheDocument();
    expect(screen.queryByText("message in conv-a")).not.toBeInTheDocument();
  });
});
