"use client";

import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, FileText, MessageSquare, PanelLeft } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { AssistantBubble, StreamingBubble, UserBubble } from "@/components/chat/message-bubble";
import { Composer } from "@/components/chat/composer";
import { ConversationList } from "@/components/chat/conversation-list";
import { ScopeSelector } from "@/components/chat/scope-selector";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { chatApi } from "@/lib/api/endpoints";
import { ApiError, errorMessage } from "@/lib/api/errors";
import { queryKeys, useDocuments, useMessages, useSettings } from "@/lib/queries";
import { cn } from "@/lib/utils";

/** An exchange that is in flight, or that failed and can be retried. */
type Pending = {
  conversationId: string;
  question: string;
  answer: string;
  error: string | null;
  scope: string[] | null;
};

const SUGGESTIONS = [
  "Summarise the key points of my documents.",
  "What deadlines or dates are mentioned?",
  "Which document should I read first?",
];

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export function ChatView() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const conversationId = useSearchParams().get("c");

  const messages = useMessages(conversationId);
  const documents = useDocuments();
  const settings = useSettings();

  const [pending, setPending] = useState<Pending | null>(null);
  const [scope, setScope] = useState<string[] | null>(null);
  const [listOpen, setListOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

  // Stop a running answer if the page is left.
  useEffect(() => () => abortRef.current?.abort(), []);

  const visiblePending = pending && pending.conversationId === conversationId ? pending : null;
  const busy = pending !== null && pending.error === null;

  // Keep the newest text in view while it streams, unless the reader scrolled up.
  const savedCount = messages.data?.items.length ?? 0;
  const streamedLength = visiblePending?.answer.length ?? 0;
  useEffect(() => {
    const element = scroller.current;
    if (element && stickToBottom.current) element.scrollTop = element.scrollHeight;
  }, [savedCount, streamedLength, visiblePending?.error, conversationId]);

  const onScroll = () => {
    const element = scroller.current;
    if (!element) return;
    stickToBottom.current = element.scrollHeight - element.scrollTop - element.clientHeight < 80;
  };

  async function ask(question: string, restrictTo: string[] | null) {
    let id = conversationId;
    if (!id) {
      try {
        id = (await chatApi.createConversation()).id;
      } catch (error) {
        toast.error(errorMessage(error, "Couldn't start a conversation."));
        return;
      }
      router.replace(`/chat?c=${id}`);
      void queryClient.invalidateQueries({ queryKey: queryKeys.conversations });
    }

    const controller = new AbortController();
    abortRef.current = controller;
    stickToBottom.current = true;
    setPending({ conversationId: id, question, answer: "", error: null, scope: restrictTo });

    try {
      await chatApi.stream(
        id,
        { content: question, document_ids: restrictTo },
        {
          signal: controller.signal,
          onToken: (text) => setPending((current) => (current ? { ...current, answer: current.answer + text } : current)),
        },
      );
      // The server saved the exchange; show the saved copy (with sources) before dropping
      // the temporary one, so the page never flashes empty.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.messages(id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.conversations }),
        queryClient.invalidateQueries({ queryKey: queryKeys.overview }),
      ]);
      setPending(null);
    } catch (error) {
      const message = isAbort(error)
        ? "Stopped. This question wasn't saved."
        : error instanceof ApiError
          ? error.message
          : errorMessage(error, "The answer couldn't be completed.");
      setPending((current) => (current ? { ...current, error: message } : current));
      // A conversation that was deleted elsewhere: refresh the list so it disappears.
      if (error instanceof ApiError && error.status === 404) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.conversations });
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
    }
  }

  const items = messages.data?.items ?? [];
  const notFound = messages.error instanceof ApiError && messages.error.status === 404;
  const readyCount = documents.data?.items.filter((document) => document.status === "ready").length ?? 0;
  const llmMissing = settings.data ? !settings.data.server.llm_configured : false;
  const hasContent = items.length > 0 || visiblePending !== null;

  return (
    <div className="relative grid h-[calc(100dvh-11rem)] min-h-96 gap-4 md:h-[calc(100dvh-7rem)] md:grid-cols-[16rem_minmax(0,1fr)]">
      <aside
        className={cn(
          "min-h-0 rounded-lg border bg-sidebar p-2",
          listOpen ? "block max-md:absolute max-md:inset-x-4 max-md:top-11 max-md:z-30 max-md:h-[60dvh] max-md:shadow-xl" : "hidden md:block",
        )}
        onClick={(event) => {
          if ((event.target as HTMLElement).closest("a")) setListOpen(false);
        }}
      >
        <ConversationList activeId={conversationId} onDeleted={() => router.replace("/chat")} />
      </aside>

      <section className="flex min-h-0 min-w-0 flex-col" aria-label="Chat">
        <div className="mb-2 flex items-center gap-2 md:hidden">
          <Button variant="outline" size="sm" aria-expanded={listOpen} onClick={() => setListOpen((value) => !value)}>
            <PanelLeft aria-hidden />
            Conversations
          </Button>
        </div>

        {llmMissing ? (
          <div role="status" className="mb-3 flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
            <p>
              No language model is configured on the server, so questions can&apos;t be answered yet. Set{" "}
              <code className="rounded bg-muted px-1">LLM_API_KEY</code> in the backend environment.
            </p>
          </div>
        ) : null}

        <div
          ref={scroller}
          onScroll={onScroll}
          data-testid="message-list"
          className="min-h-0 flex-1 space-y-5 overflow-y-auto rounded-lg border bg-card/40 p-4"
        >
          {conversationId && messages.isPending ? (
            <div className="space-y-4" aria-busy="true" aria-label="Loading messages">
              <Skeleton className="ml-auto h-10 w-2/3" />
              <Skeleton className="h-24 w-full" />
            </div>
          ) : notFound ? (
            <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
              <MessageSquare className="size-8 text-muted-foreground" aria-hidden />
              <p className="font-medium">This conversation doesn&apos;t exist any more.</p>
              <Button asChild variant="outline">
                <Link href="/chat">Start a new chat</Link>
              </Button>
            </div>
          ) : messages.isError ? (
            <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
              <p className="text-destructive">{errorMessage(messages.error, "Couldn't load this conversation.")}</p>
              <Button variant="outline" onClick={() => void messages.refetch()}>
                Try again
              </Button>
            </div>
          ) : !hasContent ? (
            <EmptyState
              readyCount={readyCount}
              loadingDocuments={documents.isPending}
              onPick={(text) => void ask(text, scope)}
              disabled={busy || llmMissing || readyCount === 0}
            />
          ) : (
            <>
              {items.map((message) =>
                message.role === "user" ? (
                  <UserBubble key={message.id} text={message.content} />
                ) : (
                  <AssistantBubble key={message.id} message={message} />
                ),
              )}
              {visiblePending ? (
                <>
                  <UserBubble text={visiblePending.question} />
                  <StreamingBubble
                    text={visiblePending.answer}
                    error={visiblePending.error}
                    onRetry={() => void ask(visiblePending.question, visiblePending.scope)}
                    onDismiss={() => setPending(null)}
                  />
                </>
              ) : null}
            </>
          )}
        </div>

        <Composer
          busy={busy}
          disabled={llmMissing || notFound}
          disabledReason={llmMissing ? "Chat is unavailable until a language model is configured." : undefined}
          onSend={(text) => void ask(text, scope)}
          onStop={() => abortRef.current?.abort()}
          scope={
            <ScopeSelector
              documents={documents.data?.items ?? []}
              selected={scope}
              onChange={setScope}
              disabled={busy}
            />
          }
        />
      </section>
    </div>
  );
}

function EmptyState({
  readyCount,
  loadingDocuments,
  onPick,
  disabled,
}: {
  readyCount: number;
  loadingDocuments: boolean;
  onPick: (text: string) => void;
  disabled: boolean;
}) {
  if (!loadingDocuments && readyCount === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-center" data-testid="empty-no-documents">
        <FileText className="size-8 text-muted-foreground" aria-hidden />
        <div>
          <p className="font-medium">Add a document to start chatting</p>
          <p className="mt-1 max-w-sm text-sm text-muted-foreground">
            Answers come only from your own documents. Upload a file and wait for it to be marked Ready.
          </p>
        </div>
        <Button asChild>
          <Link href="/documents">Go to documents</Link>
        </Button>
      </div>
    );
  }
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 text-center" data-testid="empty-chat">
      <MessageSquare className="size-8 text-muted-foreground" aria-hidden />
      <div>
        <p className="font-medium">Ask anything about your documents</p>
        <p className="mt-1 text-sm text-muted-foreground">Every answer cites the passages it came from.</p>
      </div>
      <div className="flex max-w-xl flex-wrap justify-center gap-2">
        {SUGGESTIONS.map((suggestion) => (
          <Button key={suggestion} variant="outline" size="sm" disabled={disabled} onClick={() => onPick(suggestion)}>
            {suggestion}
          </Button>
        ))}
      </div>
    </div>
  );
}
