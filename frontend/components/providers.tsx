"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { Toaster } from "sonner";

import { AuthProvider } from "@/components/auth-provider";
import { ThemeProvider, useTheme } from "@/components/theme-provider";
import { ApiError } from "@/lib/api/errors";

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        refetchOnWindowFocus: true,
        // Retrying a 4xx never helps (bad request, not found, forbidden); a flaky network might.
        retry: (failures, error) =>
          !(error instanceof ApiError && error.status >= 400 && error.status < 500) && failures < 2,
      },
    },
  });
}

function ThemedToaster() {
  const { resolvedTheme } = useTheme();
  return <Toaster theme={resolvedTheme} position="bottom-right" richColors closeButton />;
}

export function Providers({ children }: { children: React.ReactNode }) {
  // One client per browser tab; created in state so it survives re-renders but is never
  // shared between users on the server.
  const [queryClient] = useState(makeQueryClient);
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <AuthProvider>
          {children}
          <ThemedToaster />
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
