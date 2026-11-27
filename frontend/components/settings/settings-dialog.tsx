"use client";

import { Loader2, Trash2 } from "lucide-react";
import { useTheme } from "next-themes";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  useCreateMemory,
  useDeleteMemory,
  useMemories,
  useModels,
  usePreferences,
  useUpdatePreferences,
} from "@/hooks/queries";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { formatTimestamp } from "@/lib/utils-chat";
import type { Theme, User } from "@/types/api";

const THEMES = [
  { value: "system", label: "System" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

function GeneralTab() {
  const preferences = usePreferences();
  const models = useModels();
  const update = useUpdatePreferences();
  const { setTheme } = useTheme();
  const modelItems = (models.data?.models ?? []).map((m) => ({ value: m.id, label: m.label }));
  const defaultModel = preferences.data?.default_model ?? models.data?.default_model ?? null;

  function save(body: { theme?: Theme; default_model?: string }) {
    update.mutate(body, { onError: () => toast.error("Could not save settings.") });
  }

  return (
    <div className="grid gap-5">
      <div className="grid gap-1.5">
        <Label>Theme</Label>
        <Select
          items={THEMES}
          value={preferences.data?.theme ?? "system"}
          onValueChange={(value) => {
            if (typeof value !== "string") return;
            setTheme(value);
            save({ theme: value as Theme });
          }}
        >
          <SelectTrigger className="w-full" aria-label="Theme">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {THEMES.map((t) => (
              <SelectItem key={t.value} value={t.value}>
                {t.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="grid gap-1.5">
        <Label>Default model</Label>
        <Select
          items={modelItems}
          value={defaultModel}
          onValueChange={(value) => typeof value === "string" && save({ default_model: value })}
        >
          <SelectTrigger className="w-full" aria-label="Default model">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {modelItems.map((m) => (
              <SelectItem key={m.value} value={m.value}>
                {m.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-xs text-muted-foreground">
          Used for new chats unless you pick another model in the composer.
        </p>
      </div>
    </div>
  );
}

function MemoryTab() {
  const [search, setSearch] = useState("");
  const [draft, setDraft] = useState("");
  const query = useDebouncedValue(search.trim(), 300);
  const memories = useMemories(query);
  const create = useCreateMemory();
  const remove = useDeleteMemory();

  function add(event: React.FormEvent) {
    event.preventDefault();
    if (!draft.trim()) return;
    create.mutate(draft.trim(), {
      onSuccess: (result) => {
        setDraft("");
        if (!result.created) toast.info("KayGPT already remembers that.");
      },
      onError: () => toast.error("Could not save the memory."),
    });
  }

  return (
    <div className="grid gap-3">
      <p className="text-sm text-muted-foreground">
        Facts KayGPT remembers about you across chats. Ask it to “remember …” in any chat, or add
        them here.
      </p>
      <form onSubmit={add} className="flex gap-2">
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="e.g. I prefer metric units"
          maxLength={2000}
          aria-label="New memory"
        />
        <Button type="submit" disabled={!draft.trim() || create.isPending}>
          {create.isPending && <Loader2 className="animate-spin" />}Add
        </Button>
      </form>
      <Input
        type="search"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search memories by meaning"
        aria-label="Search memories"
      />
      <ul className="max-h-72 space-y-1 overflow-y-auto" aria-label="Memories">
        {memories.data?.items.length === 0 && (
          <li className="py-2 text-sm text-muted-foreground">
            {query ? "No relevant memories." : "No memories yet."}
          </li>
        )}
        {memories.data?.items.map((memory) => (
          <li
            key={memory.id}
            className="flex items-start gap-2 rounded-md px-2 py-1.5 hover:bg-muted"
          >
            <div className="min-w-0 flex-1">
              <p className="text-sm break-words">{memory.content}</p>
              <p className="text-xs text-muted-foreground">{formatTimestamp(memory.created_at)}</p>
            </div>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={`Forget “${memory.content}”`}
              onClick={() => remove.mutate(memory.id)}
            >
              <Trash2 />
            </Button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function SettingsDialog({
  open,
  onOpenChange,
  user,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  user: User;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Settings</DialogTitle>
        </DialogHeader>
        <Tabs defaultValue="general">
          <TabsList>
            <TabsTrigger value="general">General</TabsTrigger>
            <TabsTrigger value="memory">Memory</TabsTrigger>
            <TabsTrigger value="account">Account</TabsTrigger>
          </TabsList>
          <TabsContent value="general" className="pt-3">
            <GeneralTab />
          </TabsContent>
          <TabsContent value="memory" className="pt-3">
            <MemoryTab />
          </TabsContent>
          <TabsContent value="account" className="grid gap-2 pt-3 text-sm">
            <p>
              <span className="text-muted-foreground">Email: </span>
              {user.email}
            </p>
            {user.display_name && (
              <p>
                <span className="text-muted-foreground">Name: </span>
                {user.display_name}
              </p>
            )}
            <p>
              <span className="text-muted-foreground">Member since: </span>
              {new Date(user.created_at).toLocaleDateString()}
            </p>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
