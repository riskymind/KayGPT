"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";

import { ApiError } from "@/lib/api-client";
import { chatReducer, initialChatState } from "@/lib/chat-reducer";
import { chatService } from "@/services";
import type { Message, StreamEvent } from "@/types/api";

interface Options {
  conversationId: string | null;
  initialMessages: Message[] | undefined;
  /** Called once a new conversation id is known (from the `start` event). */
  onStart?: (event: Extract<StreamEvent, { type: "start" }>) => void;
  /** Called when a turn ends (done, error, stop) with the conversation id. */
  onFinish?: (conversationId: string | null) => void;
}

function tempId(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

/** Streams a chat turn, exposing optimistic messages, stop() and regenerate(). */
export function useChatStream({ conversationId, initialMessages, onStart, onFinish }: Options) {
  const [state, dispatch] = useReducer(chatReducer, initialChatState);
  const controllerRef = useRef<AbortController | null>(null);
  const conversationRef = useRef<string | null>(conversationId);
  const callbacks = useRef({ onStart, onFinish });

  useEffect(() => {
    callbacks.current = { onStart, onFinish };
  }, [onStart, onFinish]);

  useEffect(() => {
    conversationRef.current = conversationId;
  }, [conversationId]);

  useEffect(() => {
    if (initialMessages) dispatch({ type: "load", messages: initialMessages });
  }, [initialMessages]);

  // Abort an in-flight stream when the component unmounts.
  useEffect(() => () => controllerRef.current?.abort(), []);

  const run = useCallback(
    async (body: { message?: string; regenerate?: boolean; model?: string | null }) => {
      const controller = new AbortController();
      controllerRef.current = controller;
      let finished = false;
      try {
        for await (const event of chatService.stream(
          { ...body, conversation_id: conversationRef.current },
          controller.signal,
        )) {
          if (event.type === "start") {
            conversationRef.current = event.conversation_id;
            callbacks.current.onStart?.(event);
          }
          dispatch({ type: "event", event });
          if (event.type === "done" || event.type === "error") finished = true;
        }
        if (!finished) dispatch({ type: "failed", message: "The connection closed unexpectedly." });
      } catch (error) {
        if (controller.signal.aborted) {
          dispatch({ type: "stopped" });
        } else {
          const message =
            error instanceof ApiError
              ? error.message
              : "Could not reach the server. Check your connection and try again.";
          dispatch({ type: "failed", message });
        }
      } finally {
        if (controllerRef.current === controller) controllerRef.current = null;
        callbacks.current.onFinish?.(conversationRef.current);
      }
    },
    [],
  );

  const send = useCallback(
    (text: string, model?: string | null) => {
      const trimmed = text.trim();
      if (!trimmed || controllerRef.current) return;
      dispatch({
        type: "send",
        text: trimmed,
        now: new Date().toISOString(),
        userId: tempId("user"),
        assistantId: tempId("assistant"),
      });
      void run({ message: trimmed, model });
    },
    [run],
  );

  const regenerate = useCallback(
    (model?: string | null) => {
      if (controllerRef.current || !conversationRef.current) return;
      dispatch({
        type: "regenerate",
        now: new Date().toISOString(),
        assistantId: tempId("assistant"),
      });
      void run({ regenerate: true, model });
    },
    [run],
  );

  const stop = useCallback(() => controllerRef.current?.abort(), []);

  return { messages: state.messages, isStreaming: state.isStreaming, send, regenerate, stop };
}
