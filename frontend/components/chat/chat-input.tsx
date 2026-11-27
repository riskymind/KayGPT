"use client";

import { ArrowUp, Mic, MicOff, Paperclip, Square } from "lucide-react";
import { forwardRef, useCallback, useImperativeHandle, useRef, useState } from "react";

import { ModelSelector } from "@/components/chat/model-selector";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useSpeechRecognition } from "@/hooks/use-speech-recognition";
import { ACCEPTED_UPLOADS } from "@/lib/utils-chat";

export interface ChatInputHandle {
  setText: (text: string) => void;
  focus: () => void;
}

interface Props {
  isStreaming: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
  onAttach: (file: File) => void;
  uploading?: boolean;
  attachments?: React.ReactNode;
}

const MAX_HEIGHT = 240;

export const ChatInput = forwardRef<ChatInputHandle, Props>(function ChatInput(
  { isStreaming, onSend, onStop, onAttach, uploading, attachments },
  ref,
) {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const resize = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`;
  }, []);

  const appendText = useCallback(
    (spoken: string) => {
      setText((current) => (current.trim() ? `${current.trimEnd()} ${spoken}` : spoken));
      requestAnimationFrame(resize);
    },
    [resize],
  );
  const speech = useSpeechRecognition(appendText);

  useImperativeHandle(ref, () => ({
    setText: (value: string) => {
      setText(value);
      requestAnimationFrame(() => {
        resize();
        textareaRef.current?.focus();
      });
    },
    focus: () => textareaRef.current?.focus(),
  }));

  function submit() {
    const value = text.trim();
    if (!value || isStreaming) return;
    if (speech.listening) speech.stop();
    onSend(value);
    setText("");
    requestAnimationFrame(resize);
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-3 pb-3 sm:px-4">
      {attachments}
      <div className="rounded-2xl border bg-muted/60 p-2 shadow-sm focus-within:ring-2 focus-within:ring-ring/40">
        <label htmlFor="chat-input" className="sr-only">
          Message KayGPT
        </label>
        <textarea
          id="chat-input"
          ref={textareaRef}
          value={text}
          rows={1}
          placeholder={speech.listening ? "Listening…" : "Ask anything…"}
          onChange={(e) => {
            setText(e.target.value);
            resize();
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
          className="block max-h-60 w-full resize-none bg-transparent px-2 py-1.5 text-[0.95rem] outline-none placeholder:text-muted-foreground"
        />
        {speech.interim && (
          <p className="px-2 text-xs text-muted-foreground italic" aria-live="polite">
            {speech.interim}
          </p>
        )}
        <div className="mt-1 flex items-center gap-1">
          <input
            ref={fileRef}
            type="file"
            accept={ACCEPTED_UPLOADS}
            className="hidden"
            data-testid="file-input"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) onAttach(file);
              e.target.value = "";
            }}
          />
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="Attach document"
                  disabled={uploading}
                  onClick={() => fileRef.current?.click()}
                />
              }
            >
              <Paperclip />
            </TooltipTrigger>
            <TooltipContent>Attach a document (PDF, DOCX, TXT, MD, PY, CSV)</TooltipContent>
          </Tooltip>
          {speech.supported && (
            <Tooltip>
              <TooltipTrigger
                render={
                  <Button
                    variant={speech.listening ? "secondary" : "ghost"}
                    size="icon"
                    aria-label={speech.listening ? "Stop dictation" : "Dictate"}
                    aria-pressed={speech.listening}
                    onClick={speech.listening ? speech.stop : speech.start}
                  />
                }
              >
                {speech.listening ? <MicOff className="text-destructive" /> : <Mic />}
              </TooltipTrigger>
              <TooltipContent>{speech.listening ? "Stop dictation" : "Dictate"}</TooltipContent>
            </Tooltip>
          )}
          <ModelSelector disabled={isStreaming} />
          <div className="ml-auto">
            {isStreaming ? (
              <Button size="icon" variant="secondary" onClick={onStop} aria-label="Stop generating">
                <Square className="fill-current" />
              </Button>
            ) : (
              <Button
                size="icon"
                onClick={submit}
                disabled={!text.trim()}
                aria-label="Send message"
              >
                <ArrowUp />
              </Button>
            )}
          </div>
        </div>
      </div>
      <p className="mt-2 text-center text-xs text-muted-foreground">
        KayGPT can make mistakes. Check important info.
      </p>
    </div>
  );
});
