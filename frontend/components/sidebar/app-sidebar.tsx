"use client";

import {
  FileText,
  LogOut,
  MoreHorizontal,
  Pencil,
  Search,
  Settings,
  SquarePen,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { useShell } from "@/components/app-shell";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useConversations,
  useDeleteConversation,
  useLogout,
  useRenameConversation,
} from "@/hooks/queries";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { cn } from "@/lib/utils";
import type { Conversation, User } from "@/types/api";

export function AppSidebar({ user }: { user: User }) {
  const router = useRouter();
  const params = useParams<{ id?: string }>();
  const shell = useShell();
  const [search, setSearch] = useState("");
  const query = useDebouncedValue(search.trim(), 250);
  const conversations = useConversations(query);
  const rename = useRenameConversation();
  const remove = useDeleteConversation();
  const logout = useLogout();

  const [renaming, setRenaming] = useState<Conversation | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [deleting, setDeleting] = useState<Conversation | null>(null);

  async function confirmDelete() {
    if (!deleting) return;
    const target = deleting;
    setDeleting(null);
    try {
      await remove.mutateAsync(target.id);
      if (params.id === target.id) router.push("/");
      toast.success("Conversation deleted");
    } catch {
      toast.error("Could not delete the conversation.");
    }
  }

  async function confirmRename(event: React.FormEvent) {
    event.preventDefault();
    if (!renaming || !newTitle.trim()) return;
    try {
      await rename.mutateAsync({ id: renaming.id, title: newTitle.trim() });
      setRenaming(null);
    } catch {
      toast.error("Could not rename the conversation.");
    }
  }

  async function signOut() {
    await logout.mutateAsync().catch(() => undefined);
    router.replace("/login");
    router.refresh();
  }

  const items = conversations.data?.items ?? [];

  return (
    <nav
      className="flex h-full w-full flex-col gap-2 p-3 text-sidebar-foreground"
      aria-label="Sidebar"
    >
      <div className="flex items-center justify-between px-1 py-1">
        <Link href="/" className="text-base font-semibold">
          KayGPT
        </Link>
      </div>

      <Button variant="outline" className="h-9 justify-start" onClick={() => router.push("/")}>
        <SquarePen /> New chat
      </Button>

      <div className="relative">
        <Search
          className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <Input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search chats"
          aria-label="Search conversations"
          className="h-9 pl-8"
        />
      </div>

      <p className="mt-2 px-2 text-xs font-medium text-muted-foreground">Recent chats</p>
      <ul className="-mx-1 flex-1 overflow-y-auto px-1" aria-label="Conversations">
        {conversations.isLoading &&
          Array.from({ length: 6 }, (_, i) => (
            <li key={i} className="px-2 py-1.5">
              <Skeleton className="h-5 w-full" />
            </li>
          ))}
        {conversations.isError && (
          <li className="px-2 py-1.5 text-sm text-destructive">Could not load chats.</li>
        )}
        {!conversations.isLoading && items.length === 0 && (
          <li className="px-2 py-1.5 text-sm text-muted-foreground">
            {query ? "No matching chats." : "No chats yet."}
          </li>
        )}
        {items.map((conv) => (
          <li key={conv.id} className="group relative">
            <Link
              href={`/c/${conv.id}`}
              aria-current={params.id === conv.id ? "page" : undefined}
              className={cn(
                "block truncate rounded-lg py-2 pr-9 pl-2.5 text-sm hover:bg-sidebar-accent",
                params.id === conv.id && "bg-sidebar-accent font-medium",
              )}
            >
              {conv.title}
            </Link>
            <DropdownMenu>
              <DropdownMenuTrigger
                render={
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Actions for ${conv.title}`}
                    className="absolute top-1/2 right-1 -translate-y-1/2 opacity-100 aria-expanded:opacity-100 md:opacity-0 md:group-focus-within:opacity-100 md:group-hover:opacity-100"
                  />
                }
              >
                <MoreHorizontal />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem
                  onClick={() => {
                    setRenaming(conv);
                    setNewTitle(conv.title);
                  }}
                >
                  <Pencil /> Rename
                </DropdownMenuItem>
                <DropdownMenuItem variant="destructive" onClick={() => setDeleting(conv)}>
                  <Trash2 /> Delete
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </li>
        ))}
      </ul>

      <div className="flex flex-col gap-1 border-t pt-2">
        <Button variant="ghost" className="h-9 justify-start" onClick={shell.openDocuments}>
          <FileText /> Documents
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger
            render={<Button variant="ghost" className="h-auto justify-start py-2" />}
          >
            <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
              {(user.display_name ?? user.email).slice(0, 1).toUpperCase()}
            </span>
            <span className="min-w-0 text-left">
              <span className="block truncate text-sm">{user.display_name ?? user.email}</span>
              {user.display_name && (
                <span className="block truncate text-xs text-muted-foreground">{user.email}</span>
              )}
            </span>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" side="top" className="w-56">
            <DropdownMenuItem onClick={shell.openSettings}>
              <Settings /> Settings
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => void signOut()}>
              <LogOut /> Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <Dialog open={renaming !== null} onOpenChange={(open) => !open && setRenaming(null)}>
        <DialogContent>
          <form onSubmit={confirmRename} className="grid gap-4">
            <DialogHeader>
              <DialogTitle>Rename chat</DialogTitle>
            </DialogHeader>
            <Input
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              maxLength={200}
              aria-label="Chat title"
              autoFocus
            />
            <DialogFooter>
              <Button type="submit" disabled={!newTitle.trim() || rename.isPending}>
                Save
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <AlertDialog open={deleting !== null} onOpenChange={(open) => !open && setDeleting(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this chat?</AlertDialogTitle>
            <AlertDialogDescription>
              “{deleting?.title}” and its uploaded documents will be permanently deleted.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => void confirmDelete()}>
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </nav>
  );
}
