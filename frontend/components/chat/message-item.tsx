"use client";

import {
  AlertCircle,
  Check,
  CircleStop,
  Copy,
  Loader2,
  RefreshCw,
  Sparkles,
  Wrench,
} from "lucide-react";
import { memo, useState } from "react";

import { Markdown } from "@/components/chat/markdown";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { ToolActivity, UIMessage } from "@/lib/chat-reducer";
import { cn } from "@/lib/utils";
import { copyText, formatTimestamp } from "@/lib/utils-chat";

function ToolChips({ tools }: { tools: ToolActivity[] }) {
  if (!tools.length) return null;
  return (
    <ul className="mb-2 flex flex-wrap gap-1.5" aria-label="Tools used">
      {tools.map((tool) => (
        <li
          key={tool.id}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full bg-muted px-2.5 py-1 text-xs text-muted-foreground",
            tool.status === "error" && "text-destructive",
          )}
        >
          {tool.status === "running" ? (
            <Loader2 className="size-3 animate-spin" aria-hidden />
          ) : tool.status === "error" ? (
            <AlertCircle className="size-3" aria-hidden />
          ) : (
            <Wrench className="size-3" aria-hidden />
          )}
          {tool.status === "running" ? `${tool.label}…` : tool.label}
        </li>
      ))}
    </ul>
  );
}

function IconAction({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={onClick}
            aria-label={label}
            className="text-muted-foreground"
          />
        }
      >
        {children}
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

interface Props {
  message: UIMessage;
  isLast: boolean;
  canRegenerate: boolean;
  onRegenerate: () => void;
}

export const MessageItem = memo(function MessageItem({
  message,
  isLast,
  canRegenerate,
  onRegenerate,
}: Props) {
  const [copied, setCopied] = useState(false);
  const isUser = message.role === "user";
  const streaming = message.status === "streaming";

  async function onCopy() {
    if (await copyText(message.content)) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  }

  if (isUser) {
    return (
      <div className="group flex flex-col items-end gap-1" data-testid="message-user">
        <div className="max-w-[85%] rounded-2xl bg-muted px-4 py-2.5 break-words whitespace-pre-wrap">
          {message.content}
        </div>
        <time
          dateTime={message.createdAt}
          className="px-1 text-xs text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
        >
          {formatTimestamp(message.createdAt)}
        </time>
      </div>
    );
  }

  return (
    <div className="group flex gap-3" data-testid="message-assistant" aria-busy={streaming}>
      <span className="mt-1 flex size-7 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
        <Sparkles className="size-3.5" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <ToolChips tools={message.tools} />
        {message.content ? (
          <Markdown content={message.content} />
        ) : streaming ? (
          <span className="inline-flex items-center gap-2 text-sm text-muted-foreground">
            <span className="flex gap-1" aria-label="Thinking">
              <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.3s]" />
              <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.15s]" />
              <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground" />
            </span>
          </span>
        ) : null}
        {streaming && message.content && (
          <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-foreground align-middle" />
        )}

        {message.status === "stopped" && (
          <p className="mt-2 inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            <CircleStop className="size-3.5" aria-hidden /> Generation stopped
          </p>
        )}
        {message.status === "error" && (
          <p
            role="alert"
            className="mt-2 flex items-center gap-2 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive"
          >
            <AlertCircle className="size-4 shrink-0" aria-hidden />
            {message.error ?? "This response did not complete."}
          </p>
        )}

        {!streaming && (
          <div className="mt-1 flex items-center gap-0.5 opacity-100 transition-opacity md:opacity-0 md:group-focus-within:opacity-100 md:group-hover:opacity-100">
            {message.content && (
              <IconAction label={copied ? "Copied" : "Copy"} onClick={onCopy}>
                {copied ? <Check /> : <Copy />}
              </IconAction>
            )}
            {isLast && canRegenerate && (
              <IconAction label="Regenerate response" onClick={onRegenerate}>
                <RefreshCw />
              </IconAction>
            )}
            <time dateTime={message.createdAt} className="ml-1 text-xs text-muted-foreground">
              {formatTimestamp(message.createdAt)}
            </time>
          </div>
        )}
      </div>
    </div>
  );
});
