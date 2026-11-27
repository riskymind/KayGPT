import { Brain, Calculator, FileText, Globe } from "lucide-react";

const SUGGESTIONS = [
  {
    icon: Globe,
    label: "Search latest web info",
    prompt: "Search the web for the latest AI agent news.",
  },
  { icon: FileText, label: "Summarize a document", prompt: "Summarize the document I uploaded." },
  {
    icon: Brain,
    label: "Save something to memory",
    prompt: "Remember that I prefer concise answers.",
  },
  { icon: Calculator, label: "Use the calculator", prompt: "Calculate 125 * 48 / 6" },
];

export function EmptyState({ onPick }: { onPick: (prompt: string) => void }) {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col items-center justify-center gap-8 px-4 py-10">
      <div className="text-center">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          How can I help you today?
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Ask questions, upload documents, search the web, and chat with memory.
        </p>
      </div>
      <div className="grid w-full grid-cols-1 gap-2 sm:grid-cols-2">
        {SUGGESTIONS.map(({ icon: Icon, label, prompt }) => (
          <button
            key={label}
            type="button"
            onClick={() => onPick(prompt)}
            className="flex items-center gap-3 rounded-xl border px-4 py-3 text-left text-sm transition-colors hover:bg-muted"
          >
            <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
