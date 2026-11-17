"use client";

import { ArrowUp, Square } from "lucide-react";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { MAX_QUESTION_CHARS } from "@/lib/chat";
import { cn } from "@/lib/utils";

/**
 * The message box. Enter sends, Shift+Enter adds a line. While an answer is being written
 * the send button becomes Stop.
 */
export function Composer({
  onSend,
  onStop,
  busy,
  disabled,
  disabledReason,
  scope,
}: {
  onSend: (text: string) => void;
  onStop: () => void;
  busy: boolean;
  disabled?: boolean;
  disabledReason?: string;
  scope?: React.ReactNode;
}) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  const trimmed = text.trim();
  const tooLong = text.length > MAX_QUESTION_CHARS;
  const canSend = !disabled && !busy && trimmed.length > 0 && !tooLong;

  const resize = () => {
    const element = ref.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 200)}px`;
  };

  const submit = () => {
    if (!canSend) return;
    onSend(trimmed);
    setText("");
    requestAnimationFrame(() => {
      if (ref.current) ref.current.style.height = "auto";
    });
  };

  return (
    <div className="border-t bg-background pt-3">
      <div
        className={cn(
          "rounded-xl border bg-card p-2 shadow-xs transition-colors focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/50",
          tooLong && "border-destructive focus-within:border-destructive",
        )}
      >
        <textarea
          ref={ref}
          value={text}
          rows={1}
          data-testid="chat-input"
          aria-label="Your question"
          aria-invalid={tooLong}
          placeholder={disabledReason ?? "Ask about your documents…"}
          disabled={disabled}
          onChange={(event) => {
            setText(event.target.value);
            resize();
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              submit();
            }
          }}
          className="block max-h-[200px] w-full resize-none bg-transparent px-2 py-1.5 text-base outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed md:text-sm"
        />
        <div className="mt-1 flex items-center justify-between gap-2">
          <div className="min-w-0">{scope}</div>
          <div className="flex items-center gap-2">
            {text.length > MAX_QUESTION_CHARS * 0.8 ? (
              <span className={cn("text-xs tabular-nums", tooLong ? "text-destructive" : "text-muted-foreground")}>
                {text.length}/{MAX_QUESTION_CHARS}
              </span>
            ) : null}
            {busy ? (
              <Button type="button" size="icon" variant="outline" aria-label="Stop generating" onClick={onStop}>
                <Square className="fill-current" aria-hidden />
              </Button>
            ) : (
              <Button
                type="button"
                size="icon"
                data-testid="send-button"
                aria-label="Send question"
                disabled={!canSend}
                onClick={submit}
              >
                <ArrowUp aria-hidden />
              </Button>
            )}
          </div>
        </div>
      </div>
      {tooLong ? (
        <p role="alert" className="mt-1 text-xs text-destructive">
          Questions can be at most {MAX_QUESTION_CHARS} characters.
        </p>
      ) : null}
    </div>
  );
}
