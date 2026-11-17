"use client";

import { ChevronDown, Library } from "lucide-react";
import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import type { DocumentRead } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * Choose which documents a question may draw on. `selected === null` means the whole
 * library (the API's default); otherwise only the ticked ready documents are searched.
 */
export function ScopeSelector({
  documents,
  selected,
  onChange,
  disabled,
}: {
  documents: readonly DocumentRead[];
  selected: readonly string[] | null;
  onChange: (selected: string[] | null) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const ready = documents.filter((document) => document.status === "ready");
  // Ignore ticked documents that no longer exist (deleted in another tab).
  const chosen = selected ? selected.filter((id) => ready.some((document) => document.id === id)) : null;

  const label =
    chosen === null
      ? "All documents"
      : chosen.length === 1
        ? (ready.find((document) => document.id === chosen[0])?.filename ?? "1 document")
        : `${chosen.length} documents`;

  const toggle = (id: string) => {
    const current = chosen ?? ready.map((document) => document.id);
    const next = current.includes(id) ? current.filter((value) => value !== id) : [...current, id];
    // Everything ticked is the same as no restriction; nothing ticked would ask about nothing.
    onChange(next.length === ready.length || next.length === 0 ? null : next);
  };

  return (
    <div className="relative">
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled}
        aria-expanded={open}
        aria-controls={panelId}
        data-testid="scope-button"
        onClick={() => setOpen((value) => !value)}
        className="max-w-56"
      >
        <Library aria-hidden />
        <span className="truncate">{label}</span>
        <ChevronDown className={cn("transition-transform", open && "rotate-180")} aria-hidden />
      </Button>
      {open ? (
        <div
          id={panelId}
          className="absolute bottom-full left-0 z-20 mb-2 w-72 max-w-[calc(100vw-2rem)] rounded-lg border bg-popover p-2 text-popover-foreground shadow-lg"
        >
          <p className="px-2 pt-1 pb-2 text-xs text-muted-foreground">Answer using only these documents:</p>
          {ready.length === 0 ? (
            <p className="px-2 py-3 text-sm text-muted-foreground">No documents are ready yet.</p>
          ) : (
            <ul className="max-h-60 space-y-0.5 overflow-y-auto">
              <li>
                <label className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent">
                  <input
                    type="checkbox"
                    className="size-4 accent-primary"
                    checked={chosen === null}
                    onChange={() => onChange(null)}
                  />
                  <span className="font-medium">All documents</span>
                </label>
              </li>
              {ready.map((document) => (
                <li key={document.id}>
                  <label className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent">
                    <input
                      type="checkbox"
                      className="size-4 accent-primary"
                      data-testid="scope-option"
                      // No restriction means every document is in scope, so all show ticked.
                      checked={chosen === null || chosen.includes(document.id)}
                      onChange={() => toggle(document.id)}
                    />
                    <span className="truncate" title={document.filename}>
                      {document.filename}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
