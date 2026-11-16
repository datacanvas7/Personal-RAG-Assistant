"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth-provider";
import { useTheme } from "@/components/theme-provider";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Theme } from "@/lib/api/types";
import { useUpdateSettings } from "@/lib/queries";

export const THEME_OPTIONS: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
];

/** Pick a theme: applies immediately and, when signed in, saves it to the account too. */
export function useThemeChoice() {
  const { theme, resolvedTheme, setTheme } = useTheme();
  const { status } = useAuth();
  const { mutate: saveTheme } = useUpdateSettings();

  const choose = (next: Theme) => {
    setTheme(next);
    if (status === "authenticated") {
      saveTheme(
        { theme: next },
        { onError: () => toast.error("Theme changed here, but couldn't be saved to your account.") },
      );
    }
  };
  return { theme, resolvedTheme, choose };
}

export function ThemeToggle() {
  const { theme, resolvedTheme, choose } = useThemeChoice();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Change theme">
          {resolvedTheme === "dark" ? <Moon aria-hidden /> : <Sun aria-hidden />}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {THEME_OPTIONS.map(({ value, label, icon: Icon }) => (
          <DropdownMenuItem key={value} onSelect={() => choose(value)} aria-current={theme === value}>
            <Icon aria-hidden />
            {label}
            {theme === value ? <span className="ml-auto text-xs text-muted-foreground">Current</span> : null}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
