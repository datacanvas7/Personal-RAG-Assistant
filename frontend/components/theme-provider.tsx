"use client";

import { createContext, useCallback, useContext, useMemo, useSyncExternalStore } from "react";

import type { Theme } from "@/lib/api/types";

export const THEME_STORAGE_KEY = "theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

/** Runs in <head> before first paint (see app/layout.tsx) so there is no light→dark flash. */
export const THEME_INIT_SCRIPT = `(function(){try{var t=localStorage.getItem("${THEME_STORAGE_KEY}");var d=t==="dark"||((!t||t==="system")&&window.matchMedia("${DARK_QUERY}").matches);if(d)document.documentElement.classList.add("dark")}catch(e){}})()`;

type ThemeContextValue = {
  /** The user's choice: light, dark, or follow the system. */
  theme: Theme;
  /** What is actually showing. */
  resolvedTheme: "light" | "dark";
  setTheme: (theme: Theme) => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

/* The theme lives outside React (localStorage + the OS setting), so it is read through
   useSyncExternalStore: the server and the first client render both see "system"/light, which
   keeps hydration identical, and the real values arrive right after without an effect. */

const listeners = new Set<() => void>();

function readStoredTheme(): Theme {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "system") return stored;
  } catch {
    // Storage can be blocked (private mode); the choice then lasts for this visit only.
  }
  return "system";
}

let memoryTheme: Theme | null = null; // fallback when storage is unavailable

function currentTheme(): Theme {
  return memoryTheme ?? readStoredTheme();
}

function isDark(theme: Theme): boolean {
  return theme === "dark" || (theme === "system" && window.matchMedia(DARK_QUERY).matches);
}

function applyToDocument(): void {
  document.documentElement.classList.toggle("dark", isDark(currentTheme()));
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  const media = window.matchMedia(DARK_QUERY);
  const onSystemChange = () => {
    applyToDocument();
    listener();
  };
  media.addEventListener("change", onSystemChange);
  return () => {
    listeners.delete(listener);
    media.removeEventListener("change", onSystemChange);
  };
}

const getThemeSnapshot = (): Theme => currentTheme();
const getThemeServerSnapshot = (): Theme => "system";
const getDarkSnapshot = (): boolean => isDark(currentTheme());
const getDarkServerSnapshot = (): boolean => false;

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const theme = useSyncExternalStore(subscribe, getThemeSnapshot, getThemeServerSnapshot);
  const dark = useSyncExternalStore(subscribe, getDarkSnapshot, getDarkServerSnapshot);

  const setTheme = useCallback((next: Theme) => {
    memoryTheme = next;
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // see readStoredTheme
    }
    applyToDocument();
    for (const listener of listeners) listener();
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({ theme, resolvedTheme: dark ? "dark" : "light", setTheme }),
    [theme, dark, setTheme],
  );
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used inside <ThemeProvider>");
  return context;
}
