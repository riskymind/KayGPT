import { describe, expect, it } from "vitest";

import { chatReducer, initialChatState, type ChatState } from "@/lib/chat-reducer";
import type { Message, StreamEvent } from "@/types/api";

const now = "2026-11-23T10:00:00Z";

function send(state: ChatState = initialChatState): ChatState {
  return chatReducer(state, {
    type: "send",
    text: "Hi",
    now,
    userId: "u-tmp",
    assistantId: "a-tmp",
  });
}

function apply(state: ChatState, ...events: StreamEvent[]): ChatState {
  return events.reduce((s, event) => chatReducer(s, { type: "event", event }), state);
}

describe("chatReducer", () => {
  it("adds optimistic messages and accumulates streamed tokens", () => {
    let state = send();
    expect(state.isStreaming).toBe(true);
    state = apply(
      state,
      { type: "start", conversation_id: "c1", user_message_id: "u1", model: "m", title: "Hi" },
      { type: "token", content: "Hello" },
      { type: "token", content: " world" },
      { type: "done", conversation_id: "c1", message_id: "a1", title: "Hi" },
    );
    expect(state.isStreaming).toBe(false);
    expect(state.messages.map((m) => [m.id, m.role, m.content, m.status])).toEqual([
      ["u1", "user", "Hi", "complete"],
      ["a1", "assistant", "Hello world", "complete"],
    ]);
  });

  it("tracks tool activity by call id", () => {
    let state = apply(send(), {
      type: "tool_start",
      id: "call-1",
      name: "web_search",
      label: "Web search",
    });
    expect(state.messages[1].tools).toEqual([
      { id: "call-1", name: "web_search", label: "Web search", status: "running" },
    ]);
    state = apply(state, {
      type: "tool_end",
      id: "call-1",
      name: "web_search",
      label: "Web search",
      status: "success",
    });
    expect(state.messages[1].tools[0].status).toBe("success");
  });

  it("marks the answer stopped and running tools finished when aborted", () => {
    let state = apply(send(), { type: "tool_start", id: "t", name: "calculator", label: "Calc" });
    state = chatReducer(apply(state, { type: "token", content: "Partial" }), { type: "stopped" });
    expect(state.isStreaming).toBe(false);
    expect(state.messages[1]).toMatchObject({ status: "stopped", content: "Partial" });
    expect(state.messages[1].tools[0].status).toBe("error");
  });

  it("surfaces server error events", () => {
    const state = apply(send(), { type: "error", code: "generation_failed", message: "Try again" });
    expect(state.messages[1]).toMatchObject({ status: "error", error: "Try again" });
    expect(state.isStreaming).toBe(false);
  });

  it("regenerate replaces only the last assistant message", () => {
    let state = apply(
      send(),
      { type: "token", content: "Old" },
      {
        type: "done",
        conversation_id: "c",
        message_id: "a1",
        title: "t",
      },
    );
    state = chatReducer(state, { type: "regenerate", now, assistantId: "a-new" });
    expect(state.messages.map((m) => m.id)).toEqual(["u-tmp", "a-new"]);
    expect(state.messages[1]).toMatchObject({ content: "", status: "streaming" });
  });

  it("prepends older pages without touching local messages", () => {
    const msg = (id: string): Message => ({
      id,
      conversation_id: "c",
      role: "user",
      content: id,
      status: "complete",
      model_id: null,
      metadata: {},
      created_at: now,
    });
    let state = chatReducer(initialChatState, { type: "load", messages: [msg("m3"), msg("m4")] });
    state = apply(send(state), { type: "error", code: "x", message: "failed" });
    state = chatReducer(state, {
      type: "load",
      messages: [msg("m1"), msg("m2"), msg("m3"), msg("m4")],
    });
    expect(state.messages.map((m) => m.id)).toEqual(["m1", "m2", "m3", "m4", "u-tmp", "a-tmp"]);
    expect(state.messages.at(-1)?.status).toBe("error");
  });

  it("does not let history reloads clobber an in-flight answer", () => {
    const history: Message[] = [
      {
        id: "x",
        conversation_id: "c",
        role: "user",
        content: "older",
        status: "complete",
        model_id: null,
        metadata: {},
        created_at: now,
      },
    ];
    const streaming = send();
    expect(chatReducer(streaming, { type: "load", messages: history })).toBe(streaming);
    const idle = chatReducer(initialChatState, { type: "load", messages: history });
    expect(idle.messages[0].content).toBe("older");
  });
});
