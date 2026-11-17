"use client";

import { Check, MessageSquare, Pencil, Plus, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api/errors";
import type { Conversation } from "@/lib/api/types";
import { useConversations, useDeleteConversation, useRenameConversation } from "@/lib/queries";
import { cn, timeAgo } from "@/lib/utils";

function Row({
  conversation,
  active,
  onAskDelete,
}: {
  conversation: Conversation;
  active: boolean;
  onAskDelete: (conversation: Conversation) => void;
}) {
  const rename = useRenameConversation();
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(conversation.title);

  const save = () => {
    const next = title.trim();
    if (!next || next === conversation.title) {
      setEditing(false);
      return;
    }
    rename.mutate(
      { id: conversation.id, title: next },
      {
        onSuccess: () => setEditing(false),
        onError: (error) => toast.error(errorMessage(error, "Couldn't rename the conversation.")),
      },
    );
  };

  if (editing) {
    return (
      <li className="flex items-center gap-1 px-1">
        <Input
          autoFocus
          value={title}
          maxLength={200}
          aria-label="Conversation title"
          className="h-8"
          onChange={(event) => setTitle(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") save();
            if (event.key === "Escape") setEditing(false);
          }}
        />
        <Button size="icon" variant="ghost" className="size-8" aria-label="Save title" loading={rename.isPending} onClick={save}>
          <Check aria-hidden />
        </Button>
        <Button size="icon" variant="ghost" className="size-8" aria-label="Cancel" onClick={() => setEditing(false)}>
          <X aria-hidden />
        </Button>
      </li>
    );
  }

  return (
    <li
      data-testid="conversation-item"
      data-active={active}
      className={cn(
        "group flex items-center rounded-md transition-colors",
        active ? "bg-sidebar-accent text-sidebar-accent-foreground" : "hover:bg-sidebar-accent/60",
      )}
    >
      <Link
        href={`/chat?c=${conversation.id}`}
        aria-current={active ? "page" : undefined}
        className="flex min-w-0 flex-1 flex-col px-3 py-2"
      >
        <span className="truncate text-sm font-medium" title={conversation.title}>
          {conversation.title}
        </span>
        <span className="text-xs text-muted-foreground">{timeAgo(conversation.updated_at)}</span>
      </Link>
      <div className="flex pr-1 opacity-100 md:opacity-0 md:group-focus-within:opacity-100 md:group-hover:opacity-100">
        <Button
          size="icon"
          variant="ghost"
          className="size-7"
          aria-label={`Rename ${conversation.title}`}
          onClick={() => {
            setTitle(conversation.title);
            setEditing(true);
          }}
        >
          <Pencil aria-hidden />
        </Button>
        <Button
          size="icon"
          variant="ghost"
          className="size-7"
          aria-label={`Delete ${conversation.title}`}
          onClick={() => onAskDelete(conversation)}
        >
          <Trash2 aria-hidden />
        </Button>
      </div>
    </li>
  );
}

export function ConversationList({
  activeId,
  onDeleted,
}: {
  activeId: string | null;
  /** Called after the open conversation has been deleted. */
  onDeleted: () => void;
}) {
  const { data, isPending, isError, refetch } = useConversations();
  const remove = useDeleteConversation();
  const [target, setTarget] = useState<Conversation | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const confirmDelete = () => {
    if (!target) return;
    const id = target.id;
    setConfirmOpen(false);
    remove.mutate(id, {
      onSuccess: () => {
        toast.success("Conversation deleted.");
        if (id === activeId) onDeleted();
      },
      onError: (error) => toast.error(errorMessage(error, "Couldn't delete the conversation.")),
    });
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <Button asChild variant="outline" className="w-full justify-start" data-testid="new-chat">
        <Link href="/chat">
          <Plus aria-hidden />
          New chat
        </Link>
      </Button>

      <nav aria-label="Conversations" className="min-h-0 flex-1 overflow-y-auto">
        {isPending ? (
          <div className="space-y-2 p-1" aria-busy="true">
            <Skeleton className="h-11" />
            <Skeleton className="h-11" />
            <Skeleton className="h-11" />
          </div>
        ) : isError ? (
          <div className="p-3 text-sm">
            <p className="text-destructive">Couldn&apos;t load your conversations.</p>
            <Button variant="link" className="h-auto p-0" onClick={() => void refetch()}>
              Try again
            </Button>
          </div>
        ) : data.items.length === 0 ? (
          <div className="flex flex-col items-center gap-2 px-4 py-8 text-center text-sm text-muted-foreground">
            <MessageSquare className="size-5" aria-hidden />
            No conversations yet. Ask your first question.
          </div>
        ) : (
          <ul className="space-y-0.5">
            {data.items.map((conversation) => (
              <Row
                key={conversation.id}
                conversation={conversation}
                active={conversation.id === activeId}
                onAskDelete={(value) => {
                  setTarget(value);
                  setConfirmOpen(true);
                }}
              />
            ))}
          </ul>
        )}
      </nav>

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this conversation?</AlertDialogTitle>
            <AlertDialogDescription>
              &ldquo;{target?.title}&rdquo; and all of its messages will be permanently removed. Your documents are
              not affected.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={confirmDelete}>Delete</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
