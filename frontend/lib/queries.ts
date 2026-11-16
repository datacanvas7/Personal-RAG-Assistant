import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { analyticsApi, documentsApi, settingsApi } from "@/lib/api/endpoints";
import type { DocumentList, DocumentRead, SettingsUpdate } from "@/lib/api/types";

export const queryKeys = {
  documents: ["documents"] as const,
  settings: ["settings"] as const,
  overview: ["overview"] as const,
};

/** How often to ask the server about documents that are still being processed. */
export const POLL_INTERVAL_MS = 2_000;

/** The backend list endpoint caps a page at 100; the library shows the newest page. */
export const DOCUMENT_PAGE_SIZE = 100;

export function isInFlight(document: Pick<DocumentRead, "status">): boolean {
  return document.status === "pending" || document.status === "processing";
}

/** Poll only while something is actually being processed; an idle library costs no traffic. */
export function pollInterval(data: DocumentList | undefined): number | false {
  return data?.items.some(isInFlight) ? POLL_INTERVAL_MS : false;
}

export function useDocuments() {
  return useQuery({
    queryKey: queryKeys.documents,
    queryFn: ({ signal }) => documentsApi.list({ limit: DOCUMENT_PAGE_SIZE }, signal),
    refetchInterval: (query) => pollInterval(query.state.data),
  });
}

export function useOverview() {
  return useQuery({
    queryKey: queryKeys.overview,
    queryFn: () => analyticsApi.overview(),
    // Counts change as documents finish processing; follow the document poll loosely.
    refetchInterval: 10_000,
  });
}

export function useSettings() {
  return useQuery({
    queryKey: queryKeys.settings,
    queryFn: () => settingsApi.get(),
    staleTime: 60_000,
  });
}

export function useUpdateSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (changes: SettingsUpdate) => settingsApi.update(changes),
    onSuccess: (settings) => queryClient.setQueryData(queryKeys.settings, settings),
  });
}

/** Refresh everything that is derived from the document set. */
export function useInvalidateDocuments() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.documents }),
      queryClient.invalidateQueries({ queryKey: queryKeys.overview }),
    ]);
}

export function useDeleteDocument() {
  const invalidate = useInvalidateDocuments();
  return useMutation({
    mutationFn: (id: string) => documentsApi.remove(id),
    onSuccess: invalidate,
  });
}

export function useRetryDocument() {
  const invalidate = useInvalidateDocuments();
  return useMutation({
    mutationFn: (id: string) => documentsApi.retry(id),
    onSuccess: invalidate,
  });
}
