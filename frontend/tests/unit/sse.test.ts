import { describe, expect, it } from "vitest";

import { parseFrame, readEventStream } from "@/lib/sse";
import type { StreamEvent } from "@/types/api";

function streamOf(parts: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const part of parts) controller.enqueue(encoder.encode(part));
      controller.close();
    },
  });
}

async function collect(parts: string[]): Promise<StreamEvent[]> {
  const events: StreamEvent[] = [];
  for await (const event of readEventStream(streamOf(parts))) events.push(event);
  return events;
}

describe("SSE parsing", () => {
  it("parses token frames and ignores keep-alive comments", () => {
    expect(parseFrame('data: {"type":"token","content":"Hi"}')).toEqual({
      type: "token",
      content: "Hi",
    });
    expect(parseFrame(": keep-alive")).toBeNull();
  });

  it("rejects malformed or unknown events", () => {
    expect(parseFrame("data: {not json")).toBeNull();
    expect(parseFrame('data: {"type":"tool_args","args":"secret"}')).toBeNull();
    expect(parseFrame('data: {"type":"token"}')).toBeNull();
  });

  it("reassembles frames split across network chunks (including multibyte chars)", async () => {
    const events = await collect([
      'data: {"type":"token","con',
      'tent":"héllo "}\n\n: keep-alive\n\ndata: {"type":"tok',
      'en","content":"wörld"}\n\ndata: {"type":"done","conversation_id":"c","message_id":"m","title":"t"}',
    ]);
    expect(events.map((e) => e.type)).toEqual(["token", "token", "done"]);
    expect(events[0]).toMatchObject({ content: "héllo " });
    expect(events[1]).toMatchObject({ content: "wörld" });
  });
});
