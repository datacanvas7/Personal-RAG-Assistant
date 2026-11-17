"use client";

import { ChevronDown, FileText, FileX } from "lucide-react";
import Link from "next/link";

import type { Source } from "@/lib/api/types";
import { describeSource, formatScore, orderedSources } from "@/lib/chat";
import { cn } from "@/lib/utils";

/**
 * The passages an answer was built from. Collapsed by default; clicking a [n] chip in the
 * answer opens the list and highlights that entry.
 *
 * The API stores where a passage came from (file, page, relevance) but not its text, so the
 * entries show provenance rather than an excerpt.
 */
export function SourceList({
  sources,
  open,
  onOpenChange,
  highlighted,
}: {
  sources: readonly Source[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  highlighted: number | null;
}) {
  const items = orderedSources(sources);
  if (items.length === 0) return null;

  return (
    <div className="mt-3 border-t pt-2" data-testid="sources">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => onOpenChange(!open)}
        className="flex items-center gap-1 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
      >
        <ChevronDown className={cn("size-3.5 transition-transform", open ? "rotate-0" : "-rotate-90")} aria-hidden />
        {items.length} {items.length === 1 ? "source" : "sources"}
      </button>
      {open ? (
        <ol className="mt-2 space-y-1.5">
          {items.map((source) => {
            const available = source.document_id !== null;
            return (
              <li
                key={source.number}
                data-testid="source-item"
                data-highlighted={highlighted === source.number}
                className={cn(
                  "flex items-start gap-2 rounded-md border bg-background/60 px-2.5 py-2 text-xs",
                  highlighted === source.number && "border-primary ring-1 ring-primary/40",
                )}
              >
                <span className="mt-px flex size-5 shrink-0 items-center justify-center rounded bg-primary/15 font-semibold text-primary">
                  {source.number}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-1.5 font-medium">
                    {available ? (
                      <FileText className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                    ) : (
                      <FileX className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                    )}
                    <span className="truncate" title={source.filename}>
                      {describeSource(source)}
                    </span>
                  </p>
                  <p className="mt-0.5 text-muted-foreground">
                    Relevance {formatScore(source.score)}
                    {available ? (
                      <>
                        {" · "}
                        <Link href="/documents" className="underline underline-offset-2 hover:text-foreground">
                          Open library
                        </Link>
                      </>
                    ) : (
                      " · This document has since been deleted"
                    )}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>
      ) : null}
    </div>
  );
}
