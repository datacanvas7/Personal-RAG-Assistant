"use client";

import { FileText, LayoutDashboard, LogOut, Settings, User as UserIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef } from "react";

import { useAuth } from "@/components/auth-provider";
import { Brand } from "@/components/brand";
import { useTheme } from "@/components/theme-provider";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useSettings } from "@/lib/queries";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/documents", label: "Documents", icon: FileText },
  { href: "/settings", label: "Settings", icon: Settings },
] as const;

function useActive(href: string): boolean {
  const pathname = usePathname();
  return pathname === href || pathname.startsWith(`${href}/`);
}

function SidebarLink({ href, label, icon: Icon }: (typeof NAV)[number]) {
  const active = useActive(href);
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
        active
          ? "bg-sidebar-accent text-sidebar-accent-foreground"
          : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground",
      )}
    >
      <Icon className="size-4" aria-hidden />
      {label}
    </Link>
  );
}

function TabLink({ href, label, icon: Icon }: (typeof NAV)[number]) {
  const active = useActive(href);
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex flex-1 flex-col items-center gap-1 py-2 text-xs font-medium",
        active ? "text-foreground" : "text-muted-foreground",
      )}
    >
      <Icon className="size-5" aria-hidden />
      {label}
    </Link>
  );
}

function UserMenu() {
  const { user, logout } = useAuth();
  const router = useRouter();

  const signOut = async () => {
    await logout();
    router.replace("/login");
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Account menu">
          <UserIcon aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuLabel className="truncate font-normal">
          <span className="block text-xs text-muted-foreground">Signed in as</span>
          <span className="block truncate font-medium">{user?.email}</span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void signOut()}>
          <LogOut aria-hidden />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** Adopt the theme saved on the account once per session, so it follows the user across devices. */
function useAccountTheme() {
  const { data } = useSettings();
  const { setTheme } = useTheme();
  const applied = useRef(false);
  useEffect(() => {
    if (data && !applied.current) {
      applied.current = true;
      setTheme(data.theme);
    }
  }, [data, setTheme]);
}

export function AppShell({ children }: { children: React.ReactNode }) {
  useAccountTheme();
  return (
    <div className="flex min-h-dvh">
      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col gap-6 border-r bg-sidebar px-3 py-4 md:flex">
        <Brand href="/dashboard" className="px-2" />
        <nav aria-label="Main" className="flex flex-col gap-1">
          {NAV.map((item) => (
            <SidebarLink key={item.href} {...item} />
          ))}
        </nav>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b bg-background/85 px-4 backdrop-blur sm:px-6">
          <Brand href="/dashboard" className="md:invisible" />
          <div className="flex items-center gap-1">
            <ThemeToggle />
            <UserMenu />
          </div>
        </header>
        <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6 pb-24 sm:px-6 md:pb-8">{children}</main>
      </div>

      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-30 flex border-t bg-background/95 backdrop-blur md:hidden"
      >
        {NAV.map((item) => (
          <TabLink key={item.href} {...item} />
        ))}
      </nav>
    </div>
  );
}
