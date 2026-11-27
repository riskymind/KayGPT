import { Sparkles } from "lucide-react";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-dvh items-center justify-center bg-background px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <span className="flex size-11 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <Sparkles className="size-5" aria-hidden />
          </span>
          <h1 className="text-2xl font-semibold tracking-tight">KayGPT</h1>
          <p className="text-sm text-muted-foreground">
            Chat, search the web, ask your documents, and keep what matters in memory.
          </p>
        </div>
        {children}
      </div>
    </main>
  );
}
