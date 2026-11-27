"use client";

import { AlertCircle, CheckCircle2, FileText, Loader2, Trash2, Upload } from "lucide-react";
import { useRef } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useDeleteDocument, useDocuments, useUploadDocument } from "@/hooks/queries";
import { ApiError } from "@/lib/api-client";
import { ACCEPTED_UPLOADS, MAX_UPLOAD_MB, formatBytes, formatTimestamp } from "@/lib/utils-chat";
import type { DocumentInfo } from "@/types/api";

const STATUS: Record<DocumentInfo["status"], { label: string; icon: React.ReactNode }> = {
  pending: { label: "Queued", icon: <Loader2 className="size-3 animate-spin" /> },
  processing: { label: "Processing", icon: <Loader2 className="size-3 animate-spin" /> },
  ready: { label: "Ready", icon: <CheckCircle2 className="size-3 text-emerald-500" /> },
  failed: { label: "Failed", icon: <AlertCircle className="size-3 text-destructive" /> },
};

/** All of the user's documents. Uploads here are available in every conversation. */
export function DocumentsSheet({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const documents = useDocuments(null, open);
  const upload = useUploadDocument();
  const remove = useDeleteDocument();

  async function onFile(file: File) {
    if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
      toast.error(`${file.name} is larger than ${MAX_UPLOAD_MB} MB.`);
      return;
    }
    try {
      await upload.mutateAsync({ file, conversationId: null });
      toast.success(`${file.name} uploaded`);
    } catch (error) {
      toast.error(`Upload failed: ${error instanceof ApiError ? error.message : "network error"}`);
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Documents</SheetTitle>
          <SheetDescription>
            Files uploaded here can be searched in all your chats. Files attached in a chat are only
            searched in that chat.
          </SheetDescription>
        </SheetHeader>
        <div className="px-4">
          <input
            ref={fileRef}
            type="file"
            accept={ACCEPTED_UPLOADS}
            className="hidden"
            data-testid="documents-file-input"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void onFile(file);
              e.target.value = "";
            }}
          />
          <Button
            className="w-full"
            onClick={() => fileRef.current?.click()}
            disabled={upload.isPending}
          >
            {upload.isPending ? <Loader2 className="animate-spin" /> : <Upload />}
            Upload document
          </Button>
          <p className="mt-2 text-xs text-muted-foreground">
            PDF, DOCX, TXT, MD, PY or CSV · up to {MAX_UPLOAD_MB} MB
          </p>
        </div>
        <ul className="flex-1 space-y-2 overflow-y-auto px-4 pb-4" aria-label="Uploaded documents">
          {documents.isLoading && <li className="text-sm text-muted-foreground">Loading…</li>}
          {documents.data?.length === 0 && (
            <li className="text-sm text-muted-foreground">No documents uploaded yet.</li>
          )}
          {documents.data?.map((doc) => (
            <li key={doc.id} className="rounded-lg border p-3">
              <div className="flex items-start gap-3">
                <FileText className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{doc.filename}</p>
                  <p className="text-xs text-muted-foreground">
                    {formatBytes(doc.size_bytes)} · {formatTimestamp(doc.created_at)}
                    {doc.status === "ready" && ` · ${doc.chunk_count} chunks`}
                    {doc.conversation_id ? " · this chat only" : " · all chats"}
                  </p>
                  {doc.status === "failed" && doc.error_message && (
                    <p className="mt-1 text-xs text-destructive" role="alert">
                      {doc.error_message}
                    </p>
                  )}
                </div>
                <Badge variant="outline" className="gap-1">
                  {STATUS[doc.status].icon}
                  {STATUS[doc.status].label}
                </Badge>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Delete ${doc.filename}`}
                  onClick={() =>
                    remove.mutate(doc.id, {
                      onError: () => toast.error("Could not delete the document."),
                    })
                  }
                >
                  <Trash2 />
                </Button>
              </div>
            </li>
          ))}
        </ul>
      </SheetContent>
    </Sheet>
  );
}
