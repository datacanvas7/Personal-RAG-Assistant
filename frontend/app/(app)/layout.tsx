import { AppShell } from "@/components/app-shell";
import { RequireAuth } from "@/components/auth/auth-gates";

// Everything under this group needs the signed-in user, which only the browser knows (the access
// token lives in memory), so the pages are rendered client-side behind <RequireAuth>. Navigations
// in are therefore not expected to be instant; the shell and a loading state show straight away.
export const instant = false;

export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <RequireAuth>
      <AppShell>{children}</AppShell>
    </RequireAuth>
  );
}
