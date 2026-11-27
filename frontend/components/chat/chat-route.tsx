"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { ChatView } from "@/components/chat/chat-view";

/**
 * Maps the URL to a ChatView instance. When the view itself creates a conversation (first
 * message or first upload), the URL changes to /c/{id} but the same instance is kept, so an
 * in-flight stream is not interrupted. Any other navigation mounts a fresh view.
 */
export function ChatRoute() {
  const params = useParams<{ id?: string }>();
  const id = typeof params.id === "string" ? params.id : null;

  const [createdId, setCreatedId] = useState<string | null>(null);
  const [viewKey, setViewKey] = useState(0);
  const [previousId, setPreviousId] = useState(id);

  if (id !== previousId) {
    setPreviousId(id);
    if (!(id !== null && id === createdId)) {
      setCreatedId(null);
      setViewKey((k) => k + 1);
    }
  }

  return <ChatView key={viewKey} conversationId={id} onConversationCreated={setCreatedId} />;
}
