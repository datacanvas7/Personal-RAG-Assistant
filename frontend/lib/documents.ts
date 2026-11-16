import type { DocumentRead, DocumentStatus } from "@/lib/api/types";

export type StatusFilter = "all" | DocumentStatus;

/** "In progress" covers both queued and processing. */
export function matchesFilter(document: Pick<DocumentRead, "status">, filter: StatusFilter): boolean {
  if (filter === "all") return true;
  if (filter === "processing") return document.status === "pending" || document.status === "processing";
  return document.status === filter;
}

export function filterDocuments(items: DocumentRead[], query: string, filter: StatusFilter): DocumentRead[] {
  const needle = query.trim().toLowerCase();
  return items.filter(
    (item) => matchesFilter(item, filter) && (needle === "" || item.filename.toLowerCase().includes(needle)),
  );
}
