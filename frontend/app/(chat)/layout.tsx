import { Loader2 } from "lucide-react";
import { Suspense } from "react";

import { AppShell } from "@/components/app-shell";
import { ChatRoute } from "@/components/chat/chat-route";

function ShellFallback() {
  return (
    <div className="flex h-dvh items-center justify-center">
      <Loader2 className="size-6 animate-spin text-muted-foreground" aria-label="Loading" />
    </div>
  );
}

/**
 * The chat view lives in the layout, not the pages: moving from "/" to "/c/{id}" when a new
 * conversation gets its id (mid-stream) must not remount it. Pages only define the routes.
 * Everything below is per-user and URL-dependent, so it renders on the client inside Suspense
 * (only the fallback is prerendered).
 */
export default function ChatLayout({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={<ShellFallback />}>
      <AppShell>
        <ChatRoute />
        {children}
      </AppShell>
    </Suspense>
  );
}
