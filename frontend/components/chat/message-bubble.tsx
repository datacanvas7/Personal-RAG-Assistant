"use client";

import { AlertTriangle, Check, Copy, RotateCcw, Sparkles, X } from "lucide-react";
import { useCallback, useState } from "react";
import { toast } from "sonner";

import { Markdown } from "@/components/chat/markdown";
import { SourceList } from "@/components/chat/sources";
import { Button } from "@/components/ui/button";
import type { Message, Source } from "@/lib/api/types";

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Couldn't copy to the clipboard.");
    }
  };
  return (
    <Button
      variant="ghost"
      size="icon"
      className="size-7 text-muted-foreground"
      aria-label={copied ? "Copied" : "Copy answer"}
      onClick={() => void copy()}
    >
      {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
    </Button>
  );
}

export function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end" data-testid="message" data-role="user">
      <p className="max-w-[85%] rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-sm break-words whitespace-pre-wrap text-primary-foreground">
        {text}
      </p>
    </div>
  );
}

/** A saved assistant answer, with its sources. */
export function AssistantBubble({ message }: { message: Message }) {
  return (
    <AssistantFrame
      text={message.content}
      sources={message.sources}
      actions={<CopyButton text={message.content} />}
    />
  );
}

/** The answer being written right now (or one that failed part-way). */
export function StreamingBubble({
  text,
  error,
  onRetry,
  onDismiss,
}: {
  text: string;
  error: string | null;
  onRetry: () => void;
  onDismiss: () => void;
}) {
  return (
    <AssistantFrame
      text={text}
      sources={[]}
      streaming={error === null}
      footer={
        error ? (
          <div
            role="alert"
            data-testid="chat-error"
            className="mt-3 flex flex-wrap items-center gap-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
          >
            <AlertTriangle className="size-4 shrink-0" aria-hidden />
            <span className="min-w-0 flex-1">{error}</span>
            <Button size="sm" variant="outline" onClick={onRetry}>
              <RotateCcw aria-hidden />
              Retry
            </Button>
            <Button size="icon" variant="ghost" className="size-8" aria-label="Dismiss" onClick={onDismiss}>
              <X aria-hidden />
            </Button>
          </div>
        ) : null
      }
    />
  );
}

function Dot({ delay }: { delay: string }) {
  return <span className="size-1.5 animate-bounce rounded-full bg-current" style={{ animationDelay: delay }} />;
}

function AssistantFrame({
  text,
  sources,
  streaming = false,
  actions,
  footer,
}: {
  text: string;
  sources: readonly Source[];
  streaming?: boolean;
  actions?: React.ReactNode;
  footer?: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState<number | null>(null);

  const showSource = useCallback((number: number) => {
    setOpen(true);
    setHighlighted(number);
  }, []);

  return (
    <div className="flex gap-3" data-testid="message" data-role="assistant" data-streaming={streaming}>
      <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-accent text-accent-foreground">
        <Sparkles className="size-3.5" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-sm leading-relaxed">
          {text ? (
            <Markdown text={text} sources={sources} onCite={showSource} />
          ) : streaming ? (
            <span className="inline-flex items-center gap-1 text-muted-foreground" role="status" aria-label="Thinking">
              <Dot delay="0ms" />
              <Dot delay="150ms" />
              <Dot delay="300ms" />
            </span>
          ) : null}
          {streaming && text ? (
            <span aria-hidden className="ml-0.5 inline-block h-4 w-1.5 translate-y-0.5 animate-pulse bg-foreground/70" />
          ) : null}
        </div>
        <SourceList sources={sources} open={open} onOpenChange={setOpen} highlighted={highlighted} />
        {actions ? <div className="mt-1 -ml-1.5 flex">{actions}</div> : null}
        {footer}
      </div>
    </div>
  );
}
