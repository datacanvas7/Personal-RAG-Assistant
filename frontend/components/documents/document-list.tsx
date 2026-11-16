"use client";

import { FileText, RotateCcw, Search, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { StatusBadge } from "@/components/documents/status-badge";
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
import type { DocumentRead } from "@/lib/api/types";
import { filterDocuments, type StatusFilter as Filter } from "@/lib/documents";
import { DOCUMENT_PAGE_SIZE, useDeleteDocument, useDocuments, useRetryDocument } from "@/lib/queries";
import { cn, formatBytes, timeAgo } from "@/lib/utils";

const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "ready", label: "Ready" },
  { value: "processing", label: "In progress" },
  { value: "failed", label: "Failed" },
];

function details(document: DocumentRead): string {
  const parts = [formatBytes(document.size_bytes)];
  if (document.status === "ready") {
    if (document.total_pages) parts.push(`${document.total_pages} ${document.total_pages === 1 ? "page" : "pages"}`);
    if (document.total_chunks) parts.push(`${document.total_chunks} passages`);
  }
  parts.push(timeAgo(document.created_at));
  return parts.join(" · ");
}

function DocumentRow({
  document,
  onDelete,
}: {
  document: DocumentRead;
  onDelete: (document: DocumentRead) => void;
}) {
  const retry = useRetryDocument();
  return (
    <li className="flex items-start gap-3 rounded-lg border bg-card p-3 sm:items-center sm:p-4" data-testid="document-row">
      <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-md bg-accent text-accent-foreground sm:mt-0">
        <FileText className="size-4" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium" title={document.filename}>
          {document.filename}
        </p>
        <p className="text-xs text-muted-foreground">{details(document)}</p>
        {document.status === "failed" && document.error_message ? (
          <p className="mt-1 text-xs text-destructive">{document.error_message}</p>
        ) : null}
      </div>
      <div className="flex shrink-0 flex-col items-end gap-2 sm:flex-row sm:items-center">
        <StatusBadge status={document.status} />
        <div className="flex gap-1">
          {document.status === "failed" ? (
            <Button
              variant="ghost"
              size="icon"
              className="size-8"
              aria-label={`Retry ${document.filename}`}
              loading={retry.isPending}
              onClick={() =>
                retry.mutate(document.id, {
                  onSuccess: () => toast.success("Processing restarted."),
                  onError: (error) => toast.error(errorMessage(error, "Couldn't restart processing.")),
                })
              }
            >
              <RotateCcw aria-hidden />
            </Button>
          ) : null}
          <Button
            variant="ghost"
            size="icon"
            className="size-8 text-muted-foreground hover:text-destructive"
            aria-label={`Delete ${document.filename}`}
            onClick={() => onDelete(document)}
          >
            <Trash2 aria-hidden />
          </Button>
        </div>
      </div>
    </li>
  );
}

export function DocumentList() {
  const { data, isPending, isError, error, refetch } = useDocuments();
  const remove = useDeleteDocument();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  // The target outlives the dialog's close animation, so the file name doesn't blank out as it fades.
  const [toDelete, setToDelete] = useState<DocumentRead | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const askToDelete = (document: DocumentRead) => {
    setToDelete(document);
    setConfirmOpen(true);
  };

  const visible = useMemo(() => filterDocuments(data?.items ?? [], query, filter), [data, query, filter]);

  if (isPending) {
    return (
      <div className="space-y-2" aria-busy>
        {[0, 1, 2].map((key) => (
          <Skeleton key={key} className="h-16 w-full" />
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm">
        <p className="text-destructive">{errorMessage(error, "Couldn't load your documents.")}</p>
        <Button variant="outline" size="sm" className="mt-3" onClick={() => void refetch()}>
          Try again
        </Button>
      </div>
    );
  }

  if (data.items.length === 0) {
    return (
      <div className="rounded-xl border border-dashed p-8 text-center">
        <p className="font-medium">No documents yet</p>
        <p className="mt-1 text-sm text-muted-foreground">Upload a file above and it will appear here.</p>
      </div>
    );
  }

  const confirmDelete = () => {
    if (!toDelete) return;
    const target = toDelete;
    remove.mutate(target.id, {
      onSuccess: () => toast.success(`Deleted ${target.filename}.`),
      onError: (failure) => toast.error(errorMessage(failure, "Couldn't delete the document.")),
    });
    setConfirmOpen(false);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search by file name"
            aria-label="Search documents"
            className="pl-9"
          />
        </div>
        <div role="group" aria-label="Filter by status" className="flex gap-1 overflow-x-auto">
          {FILTERS.map(({ value, label }) => (
            <Button
              key={value}
              size="sm"
              variant={filter === value ? "secondary" : "ghost"}
              aria-pressed={filter === value}
              onClick={() => setFilter(value)}
            >
              {label}
            </Button>
          ))}
        </div>
      </div>

      {visible.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">No documents match your search.</p>
      ) : (
        <ul className={cn("space-y-2")} aria-label="Documents">
          {visible.map((document) => (
            <DocumentRow key={document.id} document={document} onDelete={askToDelete} />
          ))}
        </ul>
      )}

      {data.total > DOCUMENT_PAGE_SIZE ? (
        <p className="text-center text-xs text-muted-foreground">
          Showing the {DOCUMENT_PAGE_SIZE} most recent of {data.total} documents.
        </p>
      ) : null}

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this document?</AlertDialogTitle>
            <AlertDialogDescription>
              <span className="font-medium text-foreground">{toDelete?.filename}</span> and everything indexed from
              it will be removed permanently. This can&apos;t be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmDelete}
              className="bg-destructive text-white hover:bg-destructive/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
