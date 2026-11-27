"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowDown, FileText, Loader2, Menu } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";

import { useShell } from "@/components/app-shell";
import { AttachmentList } from "@/components/chat/attachment-list";
import { ChatInput, type ChatInputHandle } from "@/components/chat/chat-input";
import { EmptyState } from "@/components/chat/empty-state";
import { MessageItem } from "@/components/chat/message-item";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { queryKeys, useDocuments, useMessages, useUploadDocument } from "@/hooks/queries";
import { useAutoScroll } from "@/hooks/use-auto-scroll";
import { useChatStream } from "@/hooks/use-chat-stream";
import { useSelectedModel } from "@/hooks/use-selected-model";
import { ApiError } from "@/lib/api-client";
import { MAX_UPLOAD_MB } from "@/lib/utils-chat";
import { conversationService } from "@/services";

interface Props {
  conversationId: string | null;
  onConversationCreated: (id: string) => void;
}

export function ChatView({ conversationId: initialId, onConversationCreated }: Props) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const shell = useShell();
  const inputRef = useRef<ChatInputHandle>(null);
  const [conversationId, setConversationId] = useState(initialId);
  const { selected: model } = useSelectedModel();

  const history = useMessages(conversationId);
  const documents = useDocuments(conversationId, conversationId !== null);
  const upload = useUploadDocument();

  const adopt = useCallback(
    (id: string) => {
      setConversationId(id);
      onConversationCreated(id);
      router.replace(`/c/${id}`, { scroll: false });
    },
    [onConversationCreated, router],
  );

  const chat = useChatStream({
    conversationId,
    initialMessages: history.messages,
    onStart: (event) => {
      if (!conversationId) adopt(event.conversation_id);
      void queryClient.invalidateQueries({ queryKey: queryKeys.allConversations });
    },
    onFinish: (id) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.allConversations });
      // Local state already holds this turn (including error/stopped states), so don't refetch
      // now; just mark the cached history stale so it reloads next time the chat is opened.
      if (id) {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.messages(id),
          refetchType: "none",
        });
      }
    },
  });

  const {
    ref: scrollRef,
    onScroll,
    atBottom,
    scrollToBottom,
  } = useAutoScroll<HTMLDivElement>(chat.messages);

  const send = useCallback(
    (text: string) => {
      chat.send(text, model);
      requestAnimationFrame(() => scrollToBottom("auto"));
    },
    [chat, model, scrollToBottom],
  );

  async function attach(file: File) {
    if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
      toast.error(`${file.name} is larger than ${MAX_UPLOAD_MB} MB.`);
      return;
    }
    try {
      let id = conversationId;
      if (!id) {
        id = (await conversationService.create({ model_id: model })).id;
        adopt(id);
        void queryClient.invalidateQueries({ queryKey: queryKeys.allConversations });
      }
      await upload.mutateAsync({ file, conversationId: id });
      toast.success(`${file.name} uploaded`, {
        description: "Indexing now. You can ask about it once it shows a check mark.",
      });
    } catch (error) {
      toast.error(`Upload failed: ${error instanceof ApiError ? error.message : "network error"}`);
    }
  }

  const lastIndex = chat.messages.length - 1;
  const notFound = history.error instanceof ApiError && history.error.status === 404;

  return (
    <div className="flex h-dvh min-w-0 flex-1 flex-col">
      <header className="flex h-12 shrink-0 items-center gap-2 px-3">
        <Button
          variant="ghost"
          size="icon"
          className="md:hidden"
          aria-label="Open sidebar"
          onClick={() => shell.setMobileOpen(true)}
        >
          <Menu />
        </Button>
        <span className="text-sm font-medium md:hidden">KayGPT</span>
        <div className="ml-auto flex items-center gap-1">
          <Button variant="ghost" size="sm" onClick={() => shell.openDocuments()}>
            <FileText /> Documents
          </Button>
        </div>
      </header>

      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="relative flex flex-1 flex-col overflow-y-auto"
        data-testid="chat-scroll"
      >
        {notFound ? (
          <div className="m-auto text-center">
            <p className="font-medium">This conversation does not exist.</p>
            <Button variant="link" onClick={() => router.push("/")}>
              Start a new chat
            </Button>
          </div>
        ) : conversationId && history.isLoading ? (
          <div
            className="mx-auto w-full max-w-3xl space-y-6 px-4 py-6"
            aria-label="Loading messages"
          >
            <Skeleton className="ml-auto h-10 w-1/2" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="ml-auto h-10 w-1/3" />
          </div>
        ) : history.isError ? (
          <div className="m-auto text-center" role="alert">
            <p className="font-medium">Could not load this conversation.</p>
            <Button variant="link" onClick={() => void history.refetch()}>
              Try again
            </Button>
          </div>
        ) : chat.messages.length === 0 ? (
          <EmptyState onPick={(prompt) => inputRef.current?.setText(prompt)} />
        ) : (
          <div className="mx-auto w-full max-w-3xl space-y-6 px-4 py-6" aria-live="polite">
            {history.hasNextPage && (
              <div className="flex justify-center">
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={history.isFetchingNextPage}
                  onClick={() => void history.fetchNextPage()}
                >
                  {history.isFetchingNextPage && <Loader2 className="animate-spin" />}
                  Load earlier messages
                </Button>
              </div>
            )}
            {chat.messages.map((message, index) => (
              <MessageItem
                key={message.id}
                message={message}
                isLast={index === lastIndex}
                canRegenerate={!chat.isStreaming && conversationId !== null}
                onRegenerate={() => chat.regenerate(model)}
              />
            ))}
          </div>
        )}
        {!atBottom && (
          <Button
            variant="secondary"
            size="icon"
            aria-label="Scroll to latest"
            className="sticky bottom-3 mx-auto mt-auto shrink-0 rounded-full shadow"
            onClick={() => scrollToBottom()}
          >
            <ArrowDown />
          </Button>
        )}
      </div>

      <ChatInput
        ref={inputRef}
        isStreaming={chat.isStreaming}
        onSend={send}
        onStop={chat.stop}
        onAttach={(file) => void attach(file)}
        uploading={upload.isPending}
        attachments={<AttachmentList documents={documents.data ?? []} />}
      />
    </div>
  );
}
