"use client";

import { AlertCircle, CheckCircle2, FileText, Loader2 } from "lucide-react";

import type { DocumentInfo } from "@/types/api";

export function AttachmentList({ documents }: { documents: DocumentInfo[] }) {
  if (!documents.length) return null;
  return (
    <ul className="mb-2 flex flex-wrap gap-2" aria-label="Documents in this chat">
      {documents.map((doc) => (
        <li
          key={doc.id}
          title={doc.error_message ?? undefined}
          className="flex max-w-[16rem] items-center gap-2 rounded-lg border bg-muted px-2.5 py-1.5 text-xs"
        >
          <FileText className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
          <span className="truncate">{doc.filename}</span>
          {doc.status === "ready" ? (
            <CheckCircle2 className="size-3.5 shrink-0 text-emerald-500" aria-label="Ready" />
          ) : doc.status === "failed" ? (
            <AlertCircle className="size-3.5 shrink-0 text-destructive" aria-label="Failed" />
          ) : (
            <Loader2 className="size-3.5 shrink-0 animate-spin" aria-label="Processing" />
          )}
        </li>
      ))}
    </ul>
  );
}
