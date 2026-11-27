"use client";

/** TanStack Query hooks for server state. Query keys live in `queryKeys`. */
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";

import { ApiError } from "@/lib/api-client";
import {
  authService,
  conversationService,
  documentService,
  memoryService,
  modelService,
  preferenceService,
} from "@/services";
import type { DocumentInfo, Message, Preferences } from "@/types/api";

export const queryKeys = {
  me: ["me"] as const,
  conversations: (q: string) => ["conversations", q] as const,
  allConversations: ["conversations"] as const,
  messages: (id: string) => ["messages", id] as const,
  documents: (conversationId: string | null) => ["documents", conversationId ?? "all"] as const,
  allDocuments: ["documents"] as const,
  memories: (q: string) => ["memories", q] as const,
  allMemories: ["memories"] as const,
  models: ["models"] as const,
  preferences: ["preferences"] as const,
};

// ---------- Auth ----------

export function useCurrentUser() {
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: () => authService.me(),
    retry: (count, error) => !(error instanceof ApiError && error.status === 401) && count < 2,
    staleTime: 5 * 60_000,
  });
}

export function useLogout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => authService.logout(),
    onSettled: () => client.clear(),
  });
}

// ---------- Conversations ----------

export function useConversations(search: string) {
  return useQuery({
    queryKey: queryKeys.conversations(search),
    queryFn: () => conversationService.list({ q: search || undefined, limit: 100 }),
    placeholderData: (previous) => previous,
  });
}

export function useRenameConversation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      conversationService.rename(id, title),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.allConversations }),
  });
}

export function useDeleteConversation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => conversationService.remove(id),
    onSuccess: (_, id) => {
      client.removeQueries({ queryKey: queryKeys.messages(id) });
      return client.invalidateQueries({ queryKey: queryKeys.allConversations });
    },
  });
}

/** Message history, newest page first; `messages` is flattened oldest → newest. */
export function useMessages(conversationId: string | null) {
  const query = useInfiniteQuery({
    queryKey: queryKeys.messages(conversationId ?? "new"),
    enabled: conversationId !== null,
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      conversationService.messages(conversationId as string, { limit: 50, before: pageParam }),
    getNextPageParam: (page) => (page.has_more ? page.items[0]?.id : undefined),
    staleTime: Infinity,
  });
  const messages = useMemo<Message[] | undefined>(
    () => (query.data ? query.data.pages.toReversed().flatMap((p) => p.items) : undefined),
    [query.data],
  );
  return { ...query, messages };
}

// ---------- Models & preferences ----------

export function useModels() {
  return useQuery({
    queryKey: queryKeys.models,
    queryFn: () => modelService.list(),
    staleTime: 60 * 60_000,
  });
}

export function usePreferences() {
  return useQuery({ queryKey: queryKeys.preferences, queryFn: () => preferenceService.get() });
}

export function useUpdatePreferences() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<Preferences>) => preferenceService.update(body),
    onSuccess: (data) => client.setQueryData(queryKeys.preferences, data),
  });
}

// ---------- Documents ----------

const isProcessing = (doc: DocumentInfo) => doc.status === "pending" || doc.status === "processing";

export function useDocuments(conversationId: string | null, enabled = true) {
  return useQuery({
    queryKey: queryKeys.documents(conversationId),
    queryFn: () => documentService.list(conversationId),
    enabled,
    // Poll while anything is still being ingested.
    refetchInterval: (query) => (query.state.data?.some(isProcessing) ? 1500 : false),
  });
}

export function useUploadDocument() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ file, conversationId }: { file: File; conversationId: string | null }) =>
      documentService.upload(file, conversationId),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.allDocuments }),
  });
}

export function useDeleteDocument() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => documentService.remove(id),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.allDocuments }),
  });
}

// ---------- Memory ----------

export function useMemories(search: string) {
  return useQuery({
    queryKey: queryKeys.memories(search),
    queryFn: () => memoryService.list({ q: search || undefined, limit: 100 }),
    placeholderData: (previous) => previous,
  });
}

export function useCreateMemory() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (content: string) => memoryService.create(content),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.allMemories }),
  });
}

export function useDeleteMemory() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => memoryService.remove(id),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.allMemories }),
  });
}
