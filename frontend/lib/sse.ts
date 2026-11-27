import { z } from "zod";

import type { StreamEvent } from "@/types/api";

const streamEventSchema = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("start"),
    conversation_id: z.string(),
    user_message_id: z.string(),
    model: z.string(),
    title: z.string(),
  }),
  z.object({ type: z.literal("token"), content: z.string() }),
  z.object({
    type: z.literal("tool_start"),
    id: z.string().nullable(),
    name: z.string(),
    label: z.string(),
  }),
  z.object({
    type: z.literal("tool_end"),
    id: z.string().nullable(),
    name: z.string(),
    label: z.string(),
    status: z.enum(["success", "error"]),
  }),
  z.object({ type: z.literal("error"), code: z.string(), message: z.string() }),
  z.object({
    type: z.literal("done"),
    conversation_id: z.string(),
    message_id: z.string().nullable(),
    title: z.string(),
  }),
]);

/** Parse one SSE frame (lines separated by \n). Comments (":") and unknown events yield null. */
export function parseFrame(frame: string): StreamEvent | null {
  const data = frame
    .split(/\r?\n/)
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).replace(/^ /, ""))
    .join("\n");
  if (!data) return null;
  try {
    const parsed = streamEventSchema.safeParse(JSON.parse(data));
    return parsed.success ? (parsed.data as StreamEvent) : null;
  } catch {
    return null;
  }
}

/** Incrementally decode an SSE byte stream into typed events. */
export async function* readEventStream(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<StreamEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop() ?? "";
      for (const frame of frames) {
        const event = parseFrame(frame);
        if (event) yield event;
      }
    }
    buffer += decoder.decode();
    if (buffer.trim()) {
      const event = parseFrame(buffer);
      if (event) yield event;
    }
  } finally {
    reader.releaseLock();
  }
}
