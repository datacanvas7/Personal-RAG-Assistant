"use client";

import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { onSessionExpired } from "@/lib/api/client";
import { authApi } from "@/lib/api/endpoints";
import type { User } from "@/lib/api/types";

type AuthState =
  | { status: "loading"; user: null }
  | { status: "authenticated"; user: User }
  | { status: "unauthenticated"; user: null };

type AuthContextValue = AuthState & {
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<AuthState>({ status: "loading", user: null });

  // Restore the session on every page load: the in-memory access token is gone after a
  // reload, so the first authenticated call silently trades the refresh cookie for a new one.
  useEffect(() => {
    let cancelled = false;
    onSessionExpired(() => {
      queryClient.clear();
      setState({ status: "unauthenticated", user: null });
    });
    authApi
      .me()
      .then((user) => {
        if (!cancelled) setState({ status: "authenticated", user });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "unauthenticated", user: null });
      });
    return () => {
      cancelled = true;
      onSessionExpired(null);
    };
  }, [queryClient]);

  const login = useCallback(
    async (email: string, password: string) => {
      await authApi.login(email, password);
      const user = await authApi.me();
      queryClient.clear(); // nothing from a previous account may linger in the cache
      setState({ status: "authenticated", user });
    },
    [queryClient],
  );

  const register = useCallback(
    async (email: string, password: string) => {
      await authApi.register(email, password);
      await login(email, password);
    },
    [login],
  );

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } finally {
      queryClient.clear();
      setState({ status: "unauthenticated", user: null });
    }
  }, [queryClient]);

  const value = useMemo(() => ({ ...state, login, register, logout }), [state, login, register, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>");
  return context;
}
