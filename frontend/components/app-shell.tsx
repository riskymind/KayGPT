"use client";

import { Loader2 } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { createContext, useContext, useEffect, useMemo, useState } from "react";

import { DocumentsSheet } from "@/components/documents/documents-sheet";
import { SettingsDialog } from "@/components/settings/settings-dialog";
import { AppSidebar } from "@/components/sidebar/app-sidebar";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { useCurrentUser, usePreferences } from "@/hooks/queries";
import { ApiError } from "@/lib/api-client";

interface ShellContextValue {
  setMobileOpen: (open: boolean) => void;
  openDocuments: () => void;
  openSettings: () => void;
}

const ShellContext = createContext<ShellContextValue | null>(null);

export function useShell(): ShellContextValue {
  const value = useContext(ShellContext);
  if (!value) throw new Error("useShell must be used inside <AppShell>.");
  return value;
}

/** Signed-in application frame: auth gate, sidebar (desktop + mobile), dialogs. */
export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const me = useCurrentUser();
  const preferences = usePreferences();
  const { setTheme } = useTheme();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [documentsOpen, setDocumentsOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const unauthenticated = me.error instanceof ApiError && me.error.status === 401;
  useEffect(() => {
    if (unauthenticated) {
      const next = pathname && pathname !== "/" ? `?next=${encodeURIComponent(pathname)}` : "";
      router.replace(`/login${next}`);
    }
  }, [unauthenticated, pathname, router]);

  // Apply the theme saved on the server once per session.
  const savedTheme = preferences.data?.theme;
  useEffect(() => {
    if (savedTheme) setTheme(savedTheme);
  }, [savedTheme, setTheme]);

  // Close the mobile drawer whenever the route changes.
  const [lastPath, setLastPath] = useState(pathname);
  if (pathname !== lastPath) {
    setLastPath(pathname);
    setMobileOpen(false);
  }

  const shell = useMemo<ShellContextValue>(
    () => ({
      setMobileOpen,
      openDocuments: () => setDocumentsOpen(true),
      openSettings: () => setSettingsOpen(true),
    }),
    [],
  );

  if (!me.data) {
    return (
      <div className="flex h-dvh items-center justify-center" aria-busy>
        {me.isError && !unauthenticated ? (
          <div className="text-center" role="alert">
            <p className="font-medium">Could not reach KayGPT.</p>
            <button className="text-sm underline" onClick={() => void me.refetch()}>
              Try again
            </button>
          </div>
        ) : (
          <Loader2 className="size-6 animate-spin text-muted-foreground" aria-label="Loading" />
        )}
      </div>
    );
  }

  return (
    <ShellContext.Provider value={shell}>
      <div className="flex h-dvh overflow-hidden">
        <aside className="hidden w-72 shrink-0 border-r bg-sidebar md:flex">
          <AppSidebar user={me.data.user} />
        </aside>
        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetContent side="left" className="w-80 bg-sidebar p-0" showCloseButton={false}>
            <SheetTitle className="sr-only">Navigation</SheetTitle>
            <AppSidebar user={me.data.user} />
          </SheetContent>
        </Sheet>
        <main className="flex min-w-0 flex-1">{children}</main>
      </div>
      <DocumentsSheet open={documentsOpen} onOpenChange={setDocumentsOpen} />
      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} user={me.data.user} />
    </ShellContext.Provider>
  );
}
